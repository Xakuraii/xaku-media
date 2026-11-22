import { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell } from "electron";
import crypto from "crypto";
import fs from "fs";
import http from "http";
import https from "https";
import netModule from "net";
import path from "path";
import { Readable } from "stream";
import { pathToFileURL } from "url";
import type {
  AppPreferences,
  AppUpdateCheckResult,
  DiscoveredMediaItem,
  MediaFormatInfoPayload,
  QuerySavedMediaParams,
  SystemInfo,
} from "../shared/types";
import { PythonBridge } from "./python-bridge";

// Register media-loader custom scheme before app is ready for local media streaming
protocol.registerSchemesAsPrivileged([
  {
    scheme: "media-loader",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      bypassCSP: false,
    },
  },
]);

let mainWindow: BrowserWindow | null = null;
const pythonBridge = new PythonBridge();
let isQuitting = false;
let libraryWatcher: fs.FSWatcher | null = null;
let watchedDownloadDir: string | null = null;
let libraryNotifyTimer: NodeJS.Timeout | null = null;

interface PreviewStreamEntry {
  url: string;
  headers: Record<string, string>;
  cookieHeader?: string | null;
}

const previewStreamRegistry = new Map<string, PreviewStreamEntry>();

function sameRegistrableSite(hostA: string, hostB: string): boolean {
  const a = hostA.toLowerCase();
  const b = hostB.toLowerCase();
  if (a === b) return true;
  const root = (h: string) => {
    const parts = h.split(".").filter(Boolean);
    return parts.length >= 2 ? parts.slice(-2).join(".") : h;
  };
  return root(a) === root(b);
}

async function fetchRemoteStreamViaNode(
  entry: PreviewStreamEntry,
  method: string,
  rangeHeader: string | null,
  signal?: AbortSignal
): Promise<Response> {
  const MAX_REDIRECTS = 5;
  const initialHost = new URL(entry.url).hostname;
  let currentUrl = entry.url;
  let currentMethod = method.toUpperCase() === "HEAD" ? "HEAD" : "GET";

  for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
    const targetUrl = isSafeRemotePreviewUrl(currentUrl);
    if (!targetUrl) {
      return new Response("Blocked unsafe remote preview URL", { status: 403 });
    }
    const parsedTarget = new URL(targetUrl);
    const outHeaders: Record<string, string> = { ...entry.headers };
    if (
      entry.cookieHeader &&
      sameRegistrableSite(initialHost, parsedTarget.hostname) &&
      !Object.keys(outHeaders).some((k) => k.toLowerCase() === "cookie")
    ) {
      outHeaders["Cookie"] = entry.cookieHeader;
    }
    if (rangeHeader) {
      outHeaders["Range"] = rangeHeader;
    }

    const result = await new Promise<
      | { kind: "redirect"; location: string }
      | { kind: "response"; response: Response }
    >((resolve, reject) => {
      const client = parsedTarget.protocol === "https:" ? https : http;
      const req = client.request(
        parsedTarget,
        {
          method: currentMethod,
          headers: outHeaders,
          timeout: 15000,
        },
        (incoming) => {
          const status = incoming.statusCode || 502;
          const location = incoming.headers.location;
          if (location && [301, 302, 303, 307, 308].includes(status)) {
            incoming.resume();
            resolve({ kind: "redirect", location: Array.isArray(location) ? location[0] : location });
            return;
          }

          const respHeaders = new Headers();
          const forwardKeys = [
            "content-type",
            "content-length",
            "content-range",
            "accept-ranges",
            "cache-control",
            "etag",
            "last-modified",
          ];
          for (const key of forwardKeys) {
            const val = incoming.headers[key];
            if (typeof val === "string" && val) {
              respHeaders.set(key, val);
            } else if (Array.isArray(val) && val.length > 0) {
              respHeaders.set(key, val.join(", "));
            }
          }

          if (currentMethod === "HEAD") {
            incoming.resume();
            resolve({ kind: "response", response: new Response(null, { status, headers: respHeaders }) });
            return;
          }

          const webStream = Readable.toWeb(incoming) as unknown as ReadableStream<Uint8Array>;
          resolve({
            kind: "response",
            response: new Response(webStream, { status, headers: respHeaders }),
          });
        }
      );

      const onAbort = () => {
        req.destroy(new Error("Preview request aborted"));
      };
      if (signal) {
        if (signal.aborted) {
          onAbort();
          reject(new Error("Preview request aborted"));
          return;
        }
        signal.addEventListener("abort", onAbort, { once: true });
      }

      req.on("timeout", () => {
        req.destroy(new Error("Preview request timed out"));
      });
      req.on("error", (err) => {
        if (signal) signal.removeEventListener("abort", onAbort);
        reject(err);
      });
      req.on("close", () => {
        if (signal) signal.removeEventListener("abort", onAbort);
      });
      req.end();
    });

    if (result.kind === "response") {
      return result.response;
    }

    currentUrl = new URL(result.location, parsedTarget).toString();
    if (currentMethod !== "HEAD") {
      currentMethod = "GET";
    }
  }

  return new Response("Too many redirects for preview stream", { status: 502 });
}

function isSafeRemotePreviewUrl(rawUrl: string): string | null {
  try {
    const parsed = new URL(rawUrl.trim());
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    if (!host || host === "localhost" || host.endsWith(".local")) return null;
    if (netModule.isIP(host)) {
      if (
        host === "::1" ||
        host.startsWith("127.") ||
        host.startsWith("10.") ||
        host.startsWith("192.168.") ||
        host.startsWith("169.254.") ||
        host.startsWith("fc") ||
        host.startsWith("fd") ||
        host.startsWith("fe80")
      ) {
        return null;
      }
      if (/^172\.(1[6-9]|2\d|3[01])\./.test(host)) return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

function notifyLibraryChanged(): void {
  if (libraryNotifyTimer) clearTimeout(libraryNotifyTimer);
  libraryNotifyTimer = setTimeout(() => {
    libraryNotifyTimer = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("library:changed");
    }
  }, 400);
}

function startLibraryWatcher(downloadDir: string | null | undefined): void {
  if (!downloadDir || typeof downloadDir !== "string") return;
  const resolved = path.resolve(downloadDir);
  if (watchedDownloadDir === resolved && libraryWatcher) return;

  if (libraryWatcher) {
    try {
      libraryWatcher.close();
    } catch {
      // Ignore close errors
    }
    libraryWatcher = null;
  }
  watchedDownloadDir = resolved;

  try {
    if (!fs.existsSync(resolved)) {
      fs.mkdirSync(resolved, { recursive: true });
    }
    libraryWatcher = fs.watch(resolved, { recursive: true }, (_eventType, filename) => {
      if (typeof filename === "string") {
        const lower = filename.toLowerCase();
        if (lower.endsWith(".part") || lower.endsWith(".tmp")) return;
      }
      notifyLibraryChanged();
    });
    libraryWatcher.on("error", (err) => {
      console.warn("[desktop] Library folder watcher error:", err);
    });
  } catch (err) {
    console.warn(`[desktop] Could not watch download directory '${resolved}':`, err);
  }
}

// Forward real-time Python notifications to the renderer window
pythonBridge.onNotification((method, params) => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(method, params);
  }
  if (method === "download:completed" || method === "download_completed") {
    notifyLibraryChanged();
  }
});

// Enforce single instance lock
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  // Without this message a second launch exits silently, which looks like
  // the app "shows nothing" while the first instance keeps the lock.
  console.error(
    "[desktop] Another XakuMedia instance is already running and holds the single-instance lock. " +
      "Close the existing XakuMedia window (check the taskbar) and start again."
  );
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function setupSecurityHeaders(): void {
  // Dev mode serves the renderer from the Vite dev server over http://, and
  // Vite injects inline scripts there (the @vitejs/plugin-react Fast Refresh
  // preamble and the pre-paint theme init). A strict "script-src 'self'"
  // blocks those and leaves the dev window blank, so allow inline scripts
  // only while developing; production keeps the strict policy.
  const isDevMode = !app.isPackaged && Boolean(process.env.VITE_DEV_SERVER_URL);
  const scriptSrcDirective = isDevMode
    ? "script-src 'self' 'unsafe-inline'; "
    : "script-src 'self'; ";
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [
          "default-src 'self'; " +
            scriptSrcDirective +
            "style-src 'self' 'unsafe-inline'; " +
            "img-src 'self' data: https: blob: media-loader:; " +
            "media-src 'self' data: https: blob: media-loader:; " +
            "font-src 'self' data:; " +
            "connect-src 'self' ws://localhost:5173 http://localhost:5173; " +
            "object-src 'none'; " +
            "base-uri 'self'; " +
            "form-action 'self'; " +
            "frame-ancestors 'none';",
        ],
        "X-Content-Type-Options": ["nosniff"],
        "X-Frame-Options": ["DENY"],
        "Referrer-Policy": ["no-referrer"],
      },
    });
  });
}

function registerIpcHandlers(): void {
  ipcMain.handle("app:ping", async (): Promise<string> => {
    return "pong";
  });

  ipcMain.handle("app:getSystemInfo", async (): Promise<SystemInfo> => {
    return {
      version: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
    };
  });

  // Python Engine IPC Handlers
  ipcMain.handle("python:ping", async () => {
    return pythonBridge.sendRequest("ping");
  });

  ipcMain.handle("python:getSystemInfo", async () => {
    return pythonBridge.sendRequest("get_system_info");
  });

  ipcMain.handle("python:getStatus", async () => {
    return pythonBridge.getStatus();
  });

  // Extraction calls hit remote sites through gallery-dl/yt-dlp and a page with
  // many items can legitimately take longer than the 15s request default.
  const EXTRACTION_TIMEOUT_MS = 120000;

  ipcMain.handle("python:classifyUrl", async (_event, url: string) => {
    return pythonBridge.sendRequest("classify_url", { url }, EXTRACTION_TIMEOUT_MS);
  });

  ipcMain.handle("python:extractVideo", async (_event, url: string) => {
    return pythonBridge.sendRequest("extract_video", { url }, EXTRACTION_TIMEOUT_MS);
  });

  ipcMain.handle("python:extractGallery", async (_event, url: string) => {
    return pythonBridge.sendRequest("extract_gallery", { url }, EXTRACTION_TIMEOUT_MS);
  });

  // Local SQLite Media Library & Scan History IPC Handlers
  ipcMain.handle("python:getScanHistory", async (_event, limit?: number, offset?: number) => {
    return pythonBridge.sendRequest("get_scan_history", { limit, offset });
  });

  ipcMain.handle("python:getScanItems", async (_event, scanId: string) => {
    return pythonBridge.sendRequest("get_scan_items", { scan_id: scanId });
  });

  ipcMain.handle("python:clearScanHistory", async (_event, scanId?: string) => {
    return pythonBridge.sendRequest("clear_scan_history", { scan_id: scanId });
  });

  // Bulk discovery scan jobs. Starting a job returns immediately; posts and
  // progress arrive as scan:* notifications forwarded by the bridge.
  ipcMain.handle(
    "python:startScan",
    async (_event, url: string, options?: Record<string, unknown>) => {
      return pythonBridge.sendRequest("start_scan", { url, options });
    }
  );

  ipcMain.handle("python:cancelScan", async (_event, jobId: string) => {
    return pythonBridge.sendRequest("cancel_scan", { job_id: jobId });
  });

  ipcMain.handle("python:getScanStatus", async (_event, jobId: string) => {
    return pythonBridge.sendRequest("get_scan_status", { job_id: jobId });
  });

  ipcMain.handle("python:listScanJobs", async (_event, limit?: number) => {
    return pythonBridge.sendRequest("list_scan_jobs", { limit });
  });

  ipcMain.handle("python:getScanPosts", async (_event, scanId: string) => {
    return pythonBridge.sendRequest("get_scan_posts", { scan_id: scanId });
  });

  ipcMain.handle("python:getLibraryStats", async () => {
    return pythonBridge.sendRequest("get_library_stats");
  });

  ipcMain.handle("python:getProviderCapabilities", async (_event, url: string) => {
    return pythonBridge.sendRequest("get_provider_capabilities", { url });
  });

  ipcMain.handle(
    "python:getSavedMedia",
    async (_event, mediaType?: string, limit?: number, offset?: number) => {
      return pythonBridge.sendRequest("get_saved_media", {
        media_type: mediaType,
        limit,
        offset,
      });
    }
  );

  ipcMain.handle("python:toggleSaveMedia", async (_event, mediaId: string) => {
    return pythonBridge.sendRequest("toggle_save_media", { media_id: mediaId });
  });

  ipcMain.handle("python:toggleSavePost", async (_event, postId: string) => {
    return pythonBridge.sendRequest("toggle_save_post", { post_id: postId });
  });

  ipcMain.handle("python:deleteMediaItem", async (_event, mediaId: string) => {
    return pythonBridge.sendRequest("delete_media_item", { media_id: mediaId });
  });

  ipcMain.handle("python:skipMediaItems", async (_event, items: DiscoveredMediaItem[]) => {
    const res = await pythonBridge.sendRequest("skip_media_items", { items });
    notifyLibraryChanged();
    return res;
  });

  ipcMain.handle("python:unskipMediaItems", async (_event, items: DiscoveredMediaItem[]) => {
    const res = await pythonBridge.sendRequest("unskip_media_items", { items });
    notifyLibraryChanged();
    return res;
  });

  ipcMain.handle("python:scanDownloadLibrary", async (_event, baseDir?: string) => {
    return pythonBridge.sendRequest("scan_download_library", baseDir ? { base_dir: baseDir } : {});
  });

  ipcMain.handle("python:deleteLibraryFile", async (_event, filePath: string) => {
    const res = await pythonBridge.sendRequest("delete_library_file", { file_path: filePath });
    notifyLibraryChanged();
    return res;
  });

  ipcMain.handle(
    "python:unskipLibraryEntry",
    async (_event, folderPath: string, identity: string) => {
      const res = await pythonBridge.sendRequest("unskip_library_entry", {
        folder_path: folderPath,
        identity,
      });
      notifyLibraryChanged();
      return res;
    }
  );

  // Download Manager IPC Handlers
  ipcMain.handle(
    "python:startDownload",
    async (
      _event,
      mediaItem: DiscoveredMediaItem,
      selectedFormat?: MediaFormatInfoPayload | null,
      destinationPath?: string
    ) => {
      return pythonBridge.sendRequest("start_download", {
        media_item: mediaItem,
        selected_format: selectedFormat,
        destination_path: destinationPath,
      });
    }
  );

  ipcMain.handle("python:cancelDownload", async (_event, taskId: string) => {
    return pythonBridge.sendRequest("cancel_download", { task_id: taskId });
  });

  ipcMain.handle("python:getDownloadTasks", async (_event, status?: string, limit?: number) => {
    return pythonBridge.sendRequest("get_download_tasks", { status, limit });
  });

  ipcMain.handle(
    "python:startBatchDownload",
    async (_event, items: any[], targetDir?: string) => {
      return pythonBridge.sendRequest("start_batch_download", {
        items,
        target_dir: targetDir,
      });
    }
  );

  ipcMain.handle("python:pauseDownload", async (_event, taskId: string) => {
    return pythonBridge.sendRequest("pause_download", { task_id: taskId });
  });

  ipcMain.handle("python:resumeDownload", async (_event, taskId: string) => {
    return pythonBridge.sendRequest("resume_download", { task_id: taskId });
  });

  ipcMain.handle("python:pauseAllDownloads", async () => {
    return pythonBridge.sendRequest("pause_all_downloads");
  });

  ipcMain.handle("python:resumeAllDownloads", async () => {
    return pythonBridge.sendRequest("resume_all_downloads");
  });

  ipcMain.handle("python:cancelAllDownloads", async () => {
    return pythonBridge.sendRequest("cancel_all_downloads");
  });

  ipcMain.handle("python:clearCompletedDownloads", async () => {
    return pythonBridge.sendRequest("clear_completed_downloads");
  });

  ipcMain.handle("python:setDownloadConcurrency", async (_event, concurrency: number) => {
    return pythonBridge.sendRequest("set_download_concurrency", { concurrency });
  });

  ipcMain.handle("python:setSpeedLimit", async (_event, speedLimitKbps: number) => {
    return pythonBridge.sendRequest("set_speed_limit", { speed_limit_kbps: speedLimitKbps });
  });

  ipcMain.handle("python:getSpeedLimit", async () => {
    return pythonBridge.sendRequest("get_speed_limit");
  });

  ipcMain.handle("python:getDownloadQueueState", async () => {
    return pythonBridge.sendRequest("get_download_queue_state");
  });

  ipcMain.handle("python:recoverInterruptedTasks", async (_event, autoResume?: boolean) => {
    return pythonBridge.sendRequest("recover_interrupted_tasks", {
      auto_resume: autoResume,
    });
  });

  // Media Processor & FFmpeg IPC Handlers
  ipcMain.handle("python:getFFmpegInfo", async () => {
    return pythonBridge.sendRequest("get_ffmpeg_info");
  });

  ipcMain.handle("python:inspectMedia", async (_event, filePath: string) => {
    return pythonBridge.sendRequest("inspect_media", { file_path: filePath });
  });

  ipcMain.handle(
    "python:mergeStreams",
    async (
      _event,
      videoPath: string,
      audioPath: string,
      outputPath: string,
      outputContainer?: string
    ) => {
      return pythonBridge.sendRequest("merge_streams", {
        video_path: videoPath,
        audio_path: audioPath,
        output_path: outputPath,
        output_container: outputContainer,
      });
    }
  );

  ipcMain.handle(
    "python:convertFormat",
    async (
      _event,
      inputPath: string,
      outputPath: string,
      targetFormat?: string
    ) => {
      return pythonBridge.sendRequest("convert_format", {
        input_path: inputPath,
        output_path: outputPath,
        target_format: targetFormat,
      });
    }
  );

  ipcMain.handle("python:querySavedMedia", async (_event, params?: QuerySavedMediaParams) => {
    return pythonBridge.sendRequest("query_saved_media", params || {});
  });

  ipcMain.handle(
    "python:generateThumbnail",
    async (
      _event,
      sourcePath: string,
      itemId: string,
      mediaType?: string,
      forceRegenerate?: boolean,
      timestampSec?: number
    ) => {
      return pythonBridge.sendRequest("generate_thumbnail", {
        source_path: sourcePath,
        item_id: itemId,
        media_type: mediaType,
        force_regenerate: forceRegenerate,
        timestamp_sec: timestampSec,
      });
    }
  );

  ipcMain.handle("python:exportMediaMetadata", async (_event, mediaId: string) => {
    return pythonBridge.sendRequest("export_media_metadata", { media_id: mediaId });
  });

  ipcMain.handle(
    "python:deleteDownloadedMedia",
    async (_event, taskId: string, deleteFileFromDisk?: boolean) => {
      return pythonBridge.sendRequest("delete_downloaded_media", {
        task_id: taskId,
        delete_file_from_disk: deleteFileFromDisk ?? true,
      });
    }
  );

  ipcMain.handle("app:openPath", async (_event, targetPath: string) => {
    if (!targetPath || typeof targetPath !== "string") return;
    const trimmed = targetPath.trim();
    // Reject UNC paths to prevent remote SMB credential leaks
    if (trimmed.startsWith("\\\\") || trimmed.startsWith("//")) {
      console.warn(`[desktop] Blocked UNC path in openPath: ${trimmed}`);
      return;
    }
    // Only accept absolute paths
    if (!path.isAbsolute(trimmed)) {
      console.warn(`[desktop] Blocked non-absolute path in openPath: ${trimmed}`);
      return;
    }

    try {
      const normalized = path.normalize(trimmed);
      if (fs.existsSync(normalized)) {
        const stat = fs.statSync(normalized);
        if (stat.isDirectory()) {
          await shell.openPath(normalized);
        } else {
          // Never execute non-directory files with shell.openPath (which could execute .exe/.bat);
          // showItemInFolder safely selects and reveals the media file in Windows Explorer.
          shell.showItemInFolder(normalized);
        }
      } else {
        const parentDir = path.dirname(normalized);
        if (fs.existsSync(parentDir) && fs.statSync(parentDir).isDirectory()) {
          await shell.openPath(parentDir);
        }
      }
    } catch (err) {
      console.warn(`[desktop] Failed to open path ${targetPath}:`, err);
    }
  });

const GITHUB_RELEASES_PAGE = "https://github.com/Xakuraii/xaku-media/releases";
const GITHUB_RELEASES_API = "https://api.github.com/repos/Xakuraii/xaku-media/releases/latest";

function compareSemver(current: string, candidate: string): number {
  const parse = (v: string) =>
    v
      .trim()
      .replace(/^v/i, "")
      .split("-", 1)[0]
      .split(".")
      .map((part) => Number.parseInt(part, 10) || 0);
  const a = parse(current);
  const b = parse(candidate);
  const len = Math.max(a.length, b.length, 3);
  for (let i = 0; i < len; i++) {
    const av = a[i] ?? 0;
    const bv = b[i] ?? 0;
    if (bv > av) return 1;
    if (bv < av) return -1;
  }
  return 0;
}

function safeHttpsUrl(raw: unknown): string | null {
  if (typeof raw !== "string" || !raw.trim()) return null;
  try {
    const parsed = new URL(raw.trim());
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

  ipcMain.handle("app:openExternal", async (_event, url: string): Promise<boolean> => {
    if (!url || typeof url !== "string") return false;
    try {
      const parsed = new URL(url.trim());
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        console.warn(`[desktop] Blocked non-web external URL: ${parsed.protocol}`);
        return false;
      }
      await shell.openExternal(parsed.toString());
      return true;
    } catch (err) {
      console.warn("[desktop] Failed to open external URL:", err);
      return false;
    }
  });

  ipcMain.handle(
    "app:registerPreviewStream",
    async (
      _event,
      url: string,
      headers?: Record<string, string>,
      sourceUrl?: string | null
    ): Promise<string | null> => {
      if (!url || typeof url !== "string") return null;
      const safeUrl = isSafeRemotePreviewUrl(url);
      if (!safeUrl) return null;

      const sanitizedHeaders: Record<string, string> = {};
      if (headers && typeof headers === "object") {
        for (const [key, value] of Object.entries(headers)) {
          if (typeof value !== "string" || !key.trim()) continue;
          const lower = key.toLowerCase();
          if (lower === "host" || lower === "content-length" || lower === "connection") continue;
          sanitizedHeaders[key] = value;
        }
      }

      let cookieHeader: string | null = null;
      try {
        const cookieResp = await pythonBridge.sendRequest<{ cookie_header?: string | null }>(
          "get_cookie_header",
          {
            url: safeUrl,
            source_url: typeof sourceUrl === "string" && sourceUrl.trim() ? sourceUrl.trim() : null,
          }
        );
        if (cookieResp && typeof cookieResp.cookie_header === "string" && cookieResp.cookie_header.trim()) {
          cookieHeader = cookieResp.cookie_header.trim();
        }
      } catch {
        // Preview still attempts unauthenticated streaming if cookie lookup fails
      }

      const token = crypto.randomUUID();
      if (previewStreamRegistry.size >= 40) {
        const oldestKey = previewStreamRegistry.keys().next().value;
        if (oldestKey) previewStreamRegistry.delete(oldestKey);
      }
      previewStreamRegistry.set(token, {
        url: safeUrl,
        headers: sanitizedHeaders,
        cookieHeader,
      });
      return `media-loader://remote/${token}`;
    }
  );

  ipcMain.handle("app:checkForUpdates", async (): Promise<AppUpdateCheckResult> => {
    const currentVersion = app.getVersion();
    try {
      const resp = await net.fetch(GITHUB_RELEASES_API, {
        headers: {
          Accept: "application/vnd.github+json",
          "User-Agent": `XakuMedia/${currentVersion}`,
        },
        signal: AbortSignal.timeout(6000),
      });
      if (resp.status === 404) {
        return {
          currentVersion,
          latestVersion: null,
          hasUpdate: false,
          status: "unpublished",
          releaseUrl: GITHUB_RELEASES_PAGE,
          downloadUrl: null,
          assetName: null,
        };
      }
      if (!resp.ok) {
        return {
          currentVersion,
          latestVersion: null,
          hasUpdate: false,
          status: "error",
          releaseUrl: GITHUB_RELEASES_PAGE,
          downloadUrl: null,
          assetName: null,
          error: `GitHub returned HTTP ${resp.status}`,
        };
      }

      const data = (await resp.json()) as {
        tag_name?: string;
        html_url?: string;
        published_at?: string;
        body?: string;
        assets?: Array<{ name?: string; browser_download_url?: string }>;
      };
      const tag = (data.tag_name || "").trim();
      const latestVersion = tag ? tag.replace(/^v/i, "") : null;
      const hasUpdate = Boolean(latestVersion && compareSemver(currentVersion, latestVersion) > 0);
      const assets = Array.isArray(data.assets) ? data.assets : [];
      const setupAsset =
        assets.find((a) => typeof a.name === "string" && /setup.*\.exe$/i.test(a.name)) ||
        assets.find((a) => typeof a.name === "string" && /\.exe$/i.test(a.name)) ||
        null;

      return {
        currentVersion,
        latestVersion: latestVersion ? `v${latestVersion}` : null,
        hasUpdate,
        status: hasUpdate ? "update_available" : "up_to_date",
        releaseUrl: safeHttpsUrl(data.html_url) || GITHUB_RELEASES_PAGE,
        downloadUrl: setupAsset ? safeHttpsUrl(setupAsset.browser_download_url) : null,
        assetName: setupAsset?.name || null,
        publishedAt: data.published_at || null,
        notes: typeof data.body === "string" ? data.body.slice(0, 600) : null,
      };
    } catch (err) {
      return {
        currentVersion,
        latestVersion: null,
        hasUpdate: false,
        status: "error",
        releaseUrl: GITHUB_RELEASES_PAGE,
        downloadUrl: null,
        assetName: null,
        error: err instanceof Error ? err.message : "Could not reach GitHub Releases.",
      };
    }
  });

  // Application Preferences & Native Folder Selector
  ipcMain.handle("dialog:selectFolder", async (_event, defaultPath?: string): Promise<string | null> => {
    const focusedWindow = BrowserWindow.getFocusedWindow() || mainWindow;
    const result = await dialog.showOpenDialog(focusedWindow || (undefined as any), {
      title: "Select Download Directory",
      defaultPath: defaultPath || undefined,
      properties: ["openDirectory", "createDirectory"],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0];
  });

  ipcMain.handle("preferences:get", async () => {
    return pythonBridge.sendRequest("get_preferences");
  });

  ipcMain.handle("preferences:update", async (_event, preferences: Partial<AppPreferences>) => {
    const updated = await pythonBridge.sendRequest<AppPreferences>("update_preferences", {
      preferences,
    });
    if (updated?.download_dir) {
      startLibraryWatcher(updated.download_dir);
      notifyLibraryChanged();
    }
    return updated;
  });

  ipcMain.handle("preferences:reset", async () => {
    const defaults = await pythonBridge.sendRequest<AppPreferences>("reset_preferences");
    if (defaults?.download_dir) {
      startLibraryWatcher(defaults.download_dir);
      notifyLibraryChanged();
    }
    return defaults;
  });

  // Authentication, Cookies & Custom Request Headers
  ipcMain.handle("python:listSupportedBrowsers", async () => {
    return pythonBridge.sendRequest("list_supported_browsers");
  });

  ipcMain.handle(
    "python:importBrowserCookies",
    async (_event, browser: string, domain?: string) => {
      return pythonBridge.sendRequest("import_browser_cookies", { browser, domain });
    }
  );

  ipcMain.handle(
    "python:saveCookiesText",
    async (_event, domain: string, content: string) => {
      return pythonBridge.sendRequest("save_cookies_text", { domain, content });
    }
  );

  ipcMain.handle(
    "python:importCookiesFile",
    async (_event, filePath: string, domain?: string) => {
      return pythonBridge.sendRequest("import_cookies_file", { file_path: filePath, domain });
    }
  );

  ipcMain.handle("python:listCookieProfiles", async () => {
    return pythonBridge.sendRequest("list_cookie_profiles");
  });

  ipcMain.handle("python:deleteCookieProfile", async (_event, profileId: string) => {
    return pythonBridge.sendRequest("delete_cookie_profile", { profile_id: profileId });
  });

  ipcMain.handle("python:getDomainHeaders", async (_event, domain?: string) => {
    return pythonBridge.sendRequest("get_domain_headers", domain ? { domain } : {});
  });

  ipcMain.handle(
    "python:setDomainHeaders",
    async (_event, domain: string, headers: Record<string, string>) => {
      return pythonBridge.sendRequest("set_domain_headers", { domain, headers });
    }
  );

  ipcMain.handle("python:deleteDomainHeaders", async (_event, domain: string) => {
    return pythonBridge.sendRequest("delete_domain_headers", { domain });
  });

  ipcMain.handle(
    "dialog:selectCookieFile",
    async (_event, defaultPath?: string): Promise<string | null> => {
      const focusedWindow = BrowserWindow.getFocusedWindow() || mainWindow;
      const result = await dialog.showOpenDialog(focusedWindow || (undefined as any), {
        title: "Select Netscape Cookie File",
        defaultPath: defaultPath || undefined,
        properties: ["openFile"],
        filters: [
          { name: "Cookie Files (*.txt)", extensions: ["txt"] },
          { name: "All Files (*.*)", extensions: ["*"] },
        ],
      });
      if (result.canceled || result.filePaths.length === 0) {
        return null;
      }
      return result.filePaths[0];
    }
  );

  // Saved Sources & Incremental Rescan
  ipcMain.handle("python:saveSource", async (_event, sourceData: any) => {
    return pythonBridge.sendRequest("save_source", sourceData);
  });

  ipcMain.handle("python:getSavedSources", async (_event, tag?: string) => {
    return pythonBridge.sendRequest("get_saved_sources", tag ? { tag } : {});
  });

  ipcMain.handle(
    "python:getSource",
    async (_event, params: { source_id?: string; url?: string }) => {
      return pythonBridge.sendRequest("get_source", params);
    }
  );

  ipcMain.handle("python:deleteSavedSource", async (_event, sourceId: string) => {
    return pythonBridge.sendRequest("delete_saved_source", { source_id: sourceId });
  });

  ipcMain.handle("python:rescanSource", async (_event, sourceId: string) => {
    return pythonBridge.sendRequest("rescan_source", { source_id: sourceId }, EXTRACTION_TIMEOUT_MS);
  });

  ipcMain.handle("python:rescanAllSources", async (_event, tag?: string) => {
    return pythonBridge.sendRequest(
      "rescan_all_sources",
      tag ? { tag } : {},
      EXTRACTION_TIMEOUT_MS
    );
  });
}

function createWindow(): void {
  const isDev = !app.isPackaged && Boolean(process.env.VITE_DEV_SERVER_URL);
  const preloadPath = path.join(__dirname, "preload.cjs");

  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, "icon.ico")
    : path.join(__dirname, "../../build/icon.ico");
  const fallbackIcon = app.isPackaged
    ? path.join(process.resourcesPath, "icon.png")
    : path.join(__dirname, "../../build/icon.png");
  const windowIcon = fs.existsSync(iconPath)
    ? iconPath
    : fs.existsSync(fallbackIcon)
    ? fallbackIcon
    : undefined;

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#0b0c10",
    title: "XakuMedia",
    icon: windowIcon,
    show: false, // Prevent white flash before ready-to-show
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  // Open maximized by default: the workspace is dense (sidebar + queue + previews)
  // and benefits from the full screen. The explicit width/height above are kept
  // as the restore bounds when the user un-maximizes the window.

  // Show window smoothly when initial frame is painted
  mainWindow.once("ready-to-show", async () => {
    // Maximize right before showing so the first painted frame fills the screen
    // and the window still has sensible restore bounds.
    mainWindow?.maximize();
    mainWindow?.show();
    console.log("[desktop] Main window maximized:", mainWindow?.isMaximized());
    if (process.env.ELECTRON_SMOKE_TEST === "1" || process.argv.includes("--smoke-test")) {
      console.log("[smoke-test] Electron window painted and ready-to-show event fired!");

      // Guard against a blank renderer: ready-to-show fires even when the
      // page painted empty (e.g., bundle 404s under file:// after a base-path
      // regression). Poll briefly until React mounts visible content.
      try {
        const startedAt = Date.now();
        let rendererState = { rootChildren: 0, textLength: 0 };
        for (;;) {
          rendererState = await mainWindow.webContents.executeJavaScript(`(() => {
            const root = document.getElementById("root");
            return {
              rootChildren: root ? root.childElementCount : -1,
              textLength: document.body.innerText.trim().length,
            };
          })()`);
          if (rendererState.rootChildren > 0 && rendererState.textLength > 20) break;
          if (Date.now() - startedAt > 5000) break;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        if (rendererState.rootChildren <= 0 || rendererState.textLength <= 20) {
          console.error(
            `[smoke-test] FAILED: renderer is blank (rootChildren=${rendererState.rootChildren}, textLength=${rendererState.textLength})`
          );
          process.exit(1);
        }
        console.log(
          `[smoke-test] Renderer content verified: rootChildren=${rendererState.rootChildren}, textLength=${rendererState.textLength}`
        );
      } catch (err) {
        console.error("[smoke-test] FAILED: renderer content check errored:", err);
        process.exit(1);
      }

      // Verify Python bridge during smoke test
      const pyStatus = pythonBridge.getStatus();
      console.log(
        `[smoke-test] Python engine status: connected=${pyStatus.connected}, pid=${pyStatus.pid}`
      );

      if (!pyStatus.connected) {
        console.error("[smoke-test] FAILED: Python engine bridge is not connected!");
        process.exit(1);
      }

      try {
        const pingResponse = await pythonBridge.sendRequest<{
          status: string;
          message: string;
          version: string;
        }>("ping");
        console.log(
          `[smoke-test] Python ping round-trip verified: ${pingResponse.status} / ${pingResponse.message} (v${pingResponse.version})`
        );

        // Verify SSRF defense over IPC
        try {
          await pythonBridge.sendRequest("classify_url", {
            url: "http://127.0.0.1/local_video.mp4",
          });
          console.error("[smoke-test] FAILED: SSRF check did not block loopback address!");
          process.exit(1);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          console.log(`[smoke-test] SSRF IPC defense verified: ${msg}`);
        }

        // Verify database query over IPC
        const historyResponse = await pythonBridge.sendRequest<{
          items: unknown[];
          count: number;
        }>("get_scan_history", { limit: 5 });
        console.log(
          `[smoke-test] Database scan history query verified over IPC: count=${historyResponse.count}`
        );

        // Verify download tasks query over IPC
        const tasksResponse = await pythonBridge.sendRequest<{
          tasks: unknown[];
          count: number;
        }>("get_download_tasks", { limit: 5 });
        console.log(
          `[smoke-test] Downloader tasks query verified over IPC: count=${tasksResponse.count}`
        );

        // Verify FFmpeg detection over IPC
        const ffmpegResponse = await pythonBridge.sendRequest<{
          installed: boolean;
          version?: string | null;
          ffmpeg_path?: string | null;
        }>("get_ffmpeg_info");
        console.log(
          `[smoke-test] FFmpeg detection verified over IPC: installed=${ffmpegResponse.installed}, version=${ffmpegResponse.version}`
        );

        // Verify preferences over IPC
        const prefsResponse = await pythonBridge.sendRequest<AppPreferences>("get_preferences");
        console.log(
          `[smoke-test] Preferences query verified over IPC: theme=${prefsResponse.theme}, max_concurrent=${prefsResponse.max_concurrent_downloads}`
        );

        // Verify task recovery over IPC
        const recoveryResponse = await pythonBridge.sendRequest<{
          recovered_count: number;
          resumed_count: number;
          message: string;
        }>("recover_interrupted_tasks", { auto_resume: false });
        console.log(
          `[smoke-test] Task recovery verified over IPC: recovered=${recoveryResponse.recovered_count}`
        );

        // Verify speed limit controls over IPC
        const speedSetResponse = await pythonBridge.sendRequest<{
          speed_limit_kbps: number;
        }>("set_speed_limit", { speed_limit_kbps: 512 });
        const speedGetResponse = await pythonBridge.sendRequest<{
          speed_limit_kbps: number;
        }>("get_speed_limit");
        await pythonBridge.sendRequest("set_speed_limit", { speed_limit_kbps: 0 });
        console.log(
          `[smoke-test] Speed limit verified over IPC: set=${speedSetResponse.speed_limit_kbps}, got=${speedGetResponse.speed_limit_kbps}`
        );

        // Verify Cookie Profile and Supported Browsers over IPC
        const browserResponse = await pythonBridge.sendRequest<{ browsers: string[] }>(
          "list_supported_browsers"
        );
        const cookieProfilesResponse = await pythonBridge.sendRequest<{
          profiles: unknown[];
          count: number;
        }>("list_cookie_profiles");
        console.log(
          `[smoke-test] Auth/cookies verified over IPC: browsers=${browserResponse.browsers.length}, profiles=${cookieProfilesResponse.count}`
        );

        // Verify Saved Sources and Incremental Rescan over IPC
        const savedSourcesResponse = await pythonBridge.sendRequest<{
          sources: unknown[];
          count: number;
        }>("get_saved_sources");
        console.log(
          `[smoke-test] Saved sources verified over IPC: count=${savedSourcesResponse.count}`
        );

        // Verify bulk discovery API surface over IPC (offline checks only)
        const statsResponse = await pythonBridge.sendRequest<{
          media_total: number;
          posts: number;
          scans: number;
        }>("get_library_stats");
        const capabilitiesResponse = await pythonBridge.sendRequest<{
          capabilities: { provider: string; profile_bulk: boolean; pagination: boolean };
        }>("get_provider_capabilities", {
          url: "https://www.youtube.com/@YouTube/videos",
        });
        const scanJobsResponse = await pythonBridge.sendRequest<{ count: number }>(
          "list_scan_jobs"
        );
        console.log(
          `[smoke-test] Bulk discovery verified over IPC: posts=${statsResponse.posts}, scans=${statsResponse.scans}, ` +
            `provider=${capabilitiesResponse.capabilities.provider}, ` +
            `bulk=${capabilitiesResponse.capabilities.profile_bulk}, ` +
            `jobs=${scanJobsResponse.count}`
        );
      } catch (err) {
        console.error("[smoke-test] FAILED: Python ping request failed:", err);
        process.exit(1);
      }

      console.log("[smoke-test] All smoke tests passed successfully!");
      setTimeout(() => {
        app.quit();
      }, 500);
    }
  });

  mainWindow.webContents.on("did-finish-load", () => {
    console.log("[desktop] Renderer loaded successfully.");
  });

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
    console.error(`[desktop] Failed to load renderer: ${errorCode} - ${errorDescription}`);
  });

  // Security: Deny opening new windows from renderer
  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: "deny" };
  });

  // Security: Block in-app navigation away from application origins
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const isLocal =
      url.startsWith("http://localhost:5173") ||
      url.startsWith("file://");
    if (!isLocal) {
      event.preventDefault();
    }
  });

  // Load the appropriate interface
  if (isDev) {
    const devUrl = process.env.VITE_DEV_SERVER_URL || "http://localhost:5173";
    mainWindow.loadURL(devUrl);
  } else {
    const candidates = [
      path.join(__dirname, "../../frontend/dist/index.html"),
      path.join(__dirname, "../frontend/dist/index.html"),
      path.join(app.getAppPath(), "frontend/dist/index.html"),
    ];
    const prodPath = candidates.find((p) => fs.existsSync(p)) || candidates[0];
    mainWindow.loadFile(prodPath);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  setupSecurityHeaders();
  registerIpcHandlers();

  // Allowed media file extensions for privileged streaming protocol
  const ALLOWED_MEDIA_EXTENSIONS = new Set([
    ".mp4",
    ".webm",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".ts",
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
    ".ogg",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".ico",
    ".bmp",
    ".avif",
    ".svg",
    ".part",
    ".tmp",
  ]);

  // Register protocol handler for streaming local & header-authenticated remote media
  protocol.handle("media-loader", async (request) => {
    try {
      const parsed = new URL(request.url);
      if (parsed.hostname === "remote") {
        const token = parsed.pathname.replace(/^\/+/, "");
        const entry = previewStreamRegistry.get(token);
        if (!entry) {
          return new Response("Preview stream expired", { status: 404 });
        }
        return await fetchRemoteStreamViaNode(
          entry,
          request.method,
          request.headers.get("range"),
          request.signal
        );
      }

      let filePath = "";
      if (parsed.searchParams.has("path")) {
        filePath = decodeURIComponent(parsed.searchParams.get("path") || "");
      } else {
        let p = decodeURIComponent(parsed.pathname);
        if (p.startsWith("/") && p.length > 2 && p[2] === ":") {
          p = p.slice(1);
        }
        filePath = p;
      }

      if (!filePath || typeof filePath !== "string") {
        return new Response("Invalid media path parameter", { status: 400 });
      }

      // Reject UNC paths to prevent remote network / SMB hash leaking
      if (filePath.startsWith("\\\\") || filePath.startsWith("//")) {
        console.warn(`[security] Blocked UNC path in media-loader: ${filePath}`);
        return new Response("Forbidden network path", { status: 403 });
      }

      // Reject null bytes and NTFS Alternate Data Streams (colons in filename)
      if (filePath.includes("\0") || path.basename(filePath).includes(":")) {
        console.warn(`[security] Blocked malformed / ADS path in media-loader: ${filePath}`);
        return new Response("Forbidden path syntax", { status: 403 });
      }

      const normalized = path.normalize(filePath);
      if (!path.isAbsolute(normalized)) {
        return new Response("Path must be absolute", { status: 400 });
      }

      // Enforce strict media extension whitelist
      const ext = path.extname(normalized).toLowerCase();
      if (!ALLOWED_MEDIA_EXTENSIONS.has(ext)) {
        console.warn(`[security] Blocked non-media file extension in media-loader: ${ext}`);
        return new Response("Forbidden file extension: only media files can be streamed", { status: 403 });
      }

      if (!fs.existsSync(normalized)) {
        return new Response("Not found", { status: 404 });
      }

      const stat = fs.statSync(normalized);
      if (!stat.isFile()) {
        return new Response("Resource is not a file", { status: 400 });
      }

      return net.fetch(pathToFileURL(normalized).toString());
    } catch (err) {
      console.warn("[desktop] media-loader request failed:", err);
      return new Response("Internal error", { status: 500 });
    }
  });

  try {
    await pythonBridge.start();
    try {
      const rec = await pythonBridge.sendRequest<any>("recover_interrupted_tasks", {});
      console.log(
        `[desktop] Interrupted task recovery check: ${rec.recovered_count} recovered, ` +
          `${rec.resumed_count} resumed, ${rec.paused_count} paused.`
      );
    } catch (recErr) {
      console.warn("[desktop] Interrupted task recovery startup check failed:", recErr);
    }
    try {
      const prefs = await pythonBridge.sendRequest<AppPreferences>("get_preferences", {});
      if (prefs?.download_dir) {
        startLibraryWatcher(prefs.download_dir);
      }
    } catch {
      // Watcher is best-effort
    }
  } catch (err) {
    console.error("[desktop] Failed to start Python bridge:", err);
  }

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", async (event) => {
  if (!isQuitting) {
    isQuitting = true;
    event.preventDefault();
    if (libraryNotifyTimer) {
      clearTimeout(libraryNotifyTimer);
      libraryNotifyTimer = null;
    }
    if (libraryWatcher) {
      try {
        libraryWatcher.close();
      } catch {
        // Ignore close errors
      }
      libraryWatcher = null;
    }
    console.log("[desktop] Shutting down Python engine before quitting...");
    try {
      await pythonBridge.stop();
    } catch (err) {
      console.warn("[desktop] Error stopping Python engine:", err);
    } finally {
      app.quit();
    }
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
