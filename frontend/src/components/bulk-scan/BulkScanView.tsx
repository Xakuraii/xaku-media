import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckSquare, Layers, RefreshCw, X } from "lucide-react";
import type {
  DiscoveredMediaItem,
  ScanOptionsPayload,
  ScanPost,
} from "../../../../desktop/shared/types";
import { JobStatusList } from "./JobStatusList";
import { PostBrowser } from "./PostBrowser";
import { ScanErrorPanel } from "./ScanErrorPanel";
import { ScanSourceForm } from "./ScanSourceForm";
import { explainDownloadFailure, explainStartFailure } from "./errors";
import type {
  BulkScanViewProps,
  JobEntry,
  MediaFilter,
  ScanErrorInfo,
} from "./types";
import { isItemSkipped, itemKeys } from "./types";
import { useScanJobs } from "./useScanJobs";
import { useScanSelection } from "./useScanSelection";
import {
  chooseFormat,
  countPosts,
  filterPosts,
  hostOf,
  orderItemsOldestFirst,
  parseUrls,
} from "./utils";

/**
 * Bulk-first discovery workspace.
 */
export function BulkScanView({
  prefillUrl,
  onPrefillConsumed,
  onDownloadStarted,
  onOpenSettings,
  onOpenExternal,
  onPreviewItem,
}: BulkScanViewProps) {
  const {
    allPosts,
    activeJobs,
    runningJobs,
    totalProgress,
    stats,
    starting,
    start,
    cancel,
    removeJob,
    refreshStats,
  } = useScanJobs();

  const [input, setInput] = useState<string>("");
  const [error, setError] = useState<ScanErrorInfo | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<MediaFilter>("all");
  const [search, setSearch] = useState<string>("");
  const [maxPosts, setMaxPosts] = useState<string>("");
  const [maxMedia, setMaxMedia] = useState<string>("");
  const [includeImages, setIncludeImages] = useState<boolean>(true);
  const [includeVideos, setIncludeVideos] = useState<boolean>(true);
  const [downloading, setDownloading] = useState<boolean>(false);
  const [showOptions, setShowOptions] = useState<boolean>(false);
  const [dragging, setDragging] = useState<boolean>(false);
  const [focusedJobId, setFocusedJobId] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState<Set<string>>(new Set());
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [skipping, setSkipping] = useState<boolean>(false);
  const [bookmarking, setBookmarking] = useState<boolean>(false);
  const [savedLinks, setSavedLinks] = useState<Set<string>>(new Set());
  const [savedAvatars, setSavedAvatars] = useState<Map<string, string>>(new Map());
  const [preferredResolution, setPreferredResolution] = useState<string>("1080p");
  const [hideSkipped, setHideSkipped] = useState<boolean>(false);
  const [refreshingStats, setRefreshingStats] = useState<boolean>(false);
  const [savingUrls, setSavingUrls] = useState<Set<string>>(new Set());
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    void (async () => {
      try {
        const prefs = await window.api?.getPreferences?.();
        if (prefs && typeof prefs.default_video_resolution === "string") {
          setPreferredResolution(prefs.default_video_resolution);
        }
      } catch {
        // keep default
      }
    })();
  }, []);

  useEffect(() => {
    if (!prefillUrl) return;
    setInput(prefillUrl);
    onPrefillConsumed?.();
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [prefillUrl, onPrefillConsumed]);

  const refreshDownloaded = async () => {
    try {
      const result = await window.api?.getDownloadTasks?.(undefined, 500);
      const next = new Set<string>();
      for (const task of result?.tasks || []) {
        if (task.status !== "completed") continue;
        const item = task.media_item;
        if (item?.id) next.add(item.id);
        if (item?.provider_media_id) next.add(item.provider_media_id);
        if (item?.original_url) next.add(item.original_url);
      }
      setDownloaded(next);
    } catch {
      // Non-fatal; "select new" will just be conservative.
    }
  };

  useEffect(() => {
    void refreshDownloaded();
    const off = window.api?.onDownloadCompleted?.(() => {
      void refreshDownloaded();
    });
    return () => off?.();
  }, []);

  const refreshSavedLinks = useCallback(async () => {
    try {
      const result = await window.api?.getSavedSources?.();
      if (result) {
        const links = new Set<string>();
        const avatars = new Map<string, string>();
        for (const source of result.sources || []) {
          links.add(source.url);
          if (source.thumbnail_url) avatars.set(source.url, source.thumbnail_url);
        }
        setSavedLinks(links);
        setSavedAvatars(avatars);
      }
    } catch {
      // Non-fatal; Save buttons simply start unset.
    }
  }, []);

  useEffect(() => {
    void refreshSavedLinks();
  }, [refreshSavedLinks]);

  // Scan payloads carry the folder-manifest status, so a rescan (or a scan from
  // another device) marks already downloaded/skipped items without a restart.
  useEffect(() => {
    const nextDownloaded = new Set<string>();
    const nextSkipped = new Set<string>();
    for (const post of allPosts) {
      for (const item of post.media_items) {
        if (item.library_status === "downloaded") itemKeys(item).forEach((key) => nextDownloaded.add(key));
        else if (item.library_status === "skipped") itemKeys(item).forEach((key) => nextSkipped.add(key));
      }
    }
    if (nextDownloaded.size > 0) {
      setDownloaded((prev) => {
        const merged = new Set(prev);
        nextDownloaded.forEach((key) => merged.add(key));
        return merged;
      });
    }
    if (nextSkipped.size > 0) {
      setSkipped((prev) => {
        const merged = new Set(prev);
        nextSkipped.forEach((key) => merged.add(key));
        return merged;
      });
    }
  }, [allPosts]);

  const saveScanLink = async (
    url: string,
    title: string,
    extra?: { author?: string | null; thumbnail_url?: string | null }
  ) => {
    if (!window.api?.saveSource) {
      setError({
        title: "Save link unavailable",
        summary: "The desktop bridge is not available.",
        steps: ["Run the desktop app instead of the browser preview."],
        actions: [],
      });
      return;
    }
    setError(null);
    try {
      const alreadySaved = savedLinks.has(url);
      await window.api.saveSource({
        url,
        title: title || url,
        author: extra?.author || undefined,
        thumbnail_url: extra?.thumbnail_url || undefined,
      });
      setSavedLinks((prev) => new Set(prev).add(url));
      if (extra?.thumbnail_url) {
        setSavedAvatars((prev) => new Map(prev).set(url, extra.thumbnail_url!));
      }
      setNotice(
        alreadySaved && extra?.thumbnail_url
          ? `Updated profile avatar for ${title || url} in Saved Sources.`
          : `Saved source link: ${url}`
      );
    } catch (err) {
      setError(explainStartFailure(err));
    }
  };

  const detectedUrls = useMemo(() => parseUrls(input), [input]);
  const filteredPosts = useMemo(
    () => filterPosts(allPosts, filter, search, focusedJobId),
    [allPosts, filter, search, focusedJobId]
  );
  const counts = useMemo(() => countPosts(filteredPosts), [filteredPosts]);
  const focusedScanLabel = useMemo(() => {
    if (!focusedJobId) return null;
    const job = activeJobs.find((entry) => entry.snapshot.job_id === focusedJobId);
    return job ? hostOf(job.snapshot.url) : null;
  }, [activeJobs, focusedJobId]);

  const {
    selected,
    selectedItems,
    toggleMedia,
    togglePost,
    selectAllVisible,
    selectOnlyNew,
    clearSelection,
    selectByType,
    invertSelection,
  } = useScanSelection(allPosts, filteredPosts, filter, downloaded, skipped);

  const isUsableAvatarCandidate = (candidate?: string | null): candidate is string => {
    if (!candidate) return false;
    const lower = candidate.trim().toLowerCase();
    if (!lower) return false;
    if (/\/(?:avatar|posts|photos|videos|reels|likes|reposts)\/?$/.test(lower)) return false;
    if (/tiktok\.com\/@[^/]+\/?$/.test(lower)) return false;
    return true;
  };

  const pickSourceDetailsFromPosts = (url: string, posts: ScanPost[]) => {
    const cleanAuthor = (raw?: string | null) => {
      const trimmed = (raw || "").trim().replace(/^@/, "");
      if (!trimmed || ["gallery", "unknown", "none", "user"].includes(trimmed.toLowerCase())) {
        return null;
      }
      return trimmed;
    };

    const inferredAuthor = (() => {
      for (const post of posts) {
        const a = cleanAuthor(post.author);
        if (a) return a;
        for (const item of post.media_items) {
          const ia = cleanAuthor(item.author);
          if (ia) return ia;
        }
      }
      try {
        const seg = new URL(url).pathname.split("/").filter(Boolean)[0];
        if (seg && !["watch", "playlist", "shorts", "reel", "reels", "p", "explore"].includes(seg)) {
          return seg.replace(/^@/, "");
        }
      } catch {
        // ignore invalid url
      }
      return null;
    })();

    let thumbnailUrl: string | undefined;
    // 1. Prefer image thumbnail_url
    for (const post of posts) {
      for (const item of post.media_items) {
        if (isUsableAvatarCandidate(item.thumbnail_url)) {
          thumbnailUrl = item.thumbnail_url;
          break;
        }
      }
      if (thumbnailUrl) break;
    }
    // 2. Fallback to image original_url (gallery-dl albums often omit thumbnail_url)
    if (!thumbnailUrl) {
      for (const post of posts) {
        for (const item of post.media_items) {
          if (item.media_type === "image" && isUsableAvatarCandidate(item.original_url)) {
            thumbnailUrl = item.original_url;
            break;
          }
        }
        if (thumbnailUrl) break;
      }
    }
    // 3. Fallback to first video's stream URL (SourceAvatar renders a <video> poster)
    if (!thumbnailUrl) {
      for (const post of posts) {
        for (const item of post.media_items) {
          if (item.media_type === "video" && isUsableAvatarCandidate(item.original_url)) {
            thumbnailUrl = item.original_url;
            break;
          }
        }
        if (thumbnailUrl) break;
      }
    }

    let host = url;
    try {
      host = new URL(url).hostname.replace(/^www\./, "");
    } catch {
      // keep raw url
    }
    const title = inferredAuthor ? `@${inferredAuthor}` : host;
    return {
      title,
      author: inferredAuthor || undefined,
      thumbnail_url: thumbnailUrl,
    };
  };

  const saveScanJobSource = async (entry: JobEntry) => {
    const url = entry.snapshot.url;
    if (!window.api?.saveSource) return;
    setSavingUrls((prev) => new Set(prev).add(url));
    try {
      const jobPosts =
        entry.posts.length > 0
          ? entry.posts
          : allPosts.filter((p) => p._job_id === entry.snapshot.job_id || p.source_url === url);
      const details = pickSourceDetailsFromPosts(url, jobPosts);
      await saveScanLink(url, details.title, {
        author: details.author,
        thumbnail_url: details.thumbnail_url,
      });
    } finally {
      setSavingUrls((prev) => {
        const next = new Set(prev);
        next.delete(url);
        return next;
      });
    }
  };

  const bookmarkInput = async () => {
    const urls = parseUrls(input);
    if (urls.length === 0) {
      setError({
        title: "Nothing to bookmark",
        summary: "Paste a valid http(s) URL first.",
        steps: ["Enter a profile, channel, playlist, gallery, or media URL."],
        actions: [],
      });
      return;
    }
    if (!window.api?.saveSource) {
      setError({
        title: "Bookmark unavailable",
        summary: "The desktop bridge is not available.",
        steps: [],
        actions: [],
      });
      return;
    }
    setBookmarking(true);
    setError(null);
    try {
      let saved = 0;
      for (const url of urls) {
        const matchingJob = activeJobs.find((j) => j.snapshot.url === url);
        const relatedPosts = matchingJob?.posts?.length
          ? matchingJob.posts
          : allPosts.filter((p) => p.source_url === url || p.post_url === url);
        const details = pickSourceDetailsFromPosts(url, relatedPosts);
        await window.api.saveSource({
          url,
          title: details.title,
          author: details.author,
          thumbnail_url: details.thumbnail_url,
        });
        setSavedLinks((prev) => new Set(prev).add(url));
        saved += 1;
      }
      setNotice(`Bookmarked ${saved} link${saved === 1 ? "" : "s"}.`);
    } catch (err) {
      setError(explainStartFailure(err));
    } finally {
      setBookmarking(false);
    }
  };

  const startScans = async () => {
    const urls = parseUrls(input);
    if (urls.length === 0) {
      setError({
        title: "Add at least one URL",
        summary: "Paste one http(s) link per line, or drop links into the box.",
        steps: [
          "Example: https://www.youtube.com/@channel/videos",
          "Direct image/video links must end with .jpg, .png, .mp4, and similar.",
        ],
        actions: [],
      });
      return;
    }

    const options: ScanOptionsPayload = {
      include_images: includeImages,
      include_videos: includeVideos,
    };
    const parsedMaxPosts = Number.parseInt(maxPosts, 10);
    const parsedMaxMedia = Number.parseInt(maxMedia, 10);
    if (!Number.isNaN(parsedMaxPosts) && parsedMaxPosts > 0) options.max_posts = parsedMaxPosts;
    if (!Number.isNaN(parsedMaxMedia) && parsedMaxMedia > 0) options.max_media = parsedMaxMedia;

    setError(null);
    setNotice(null);
    try {
      const { started, failures } = await start(urls, options);
      if (failures.length > 0) {
        const base = explainStartFailure(failures.join("\n"));
        setError({
          ...base,
          title: started > 0 ? "Some sources could not start" : base.title,
          summary: failures.join("\n"),
        });
      }
      if (started > 0) {
        setInput("");
        setNotice(
          `Started ${started} scan${started === 1 ? "" : "s"}. Results stream in as posts are found.`
        );
      }
    } catch (err) {
      setError(explainStartFailure(err));
    }
  };

  const cancelJob = async (jobId: string) => {
    try {
      await cancel(jobId);
    } catch (err) {
      setError(explainStartFailure(err));
    }
  };

  const deleteScan = async (job: JobEntry) => {
    const scanId = job.snapshot.scan_id;
    try {
      if (scanId && window.api?.clearScanHistory) {
        await window.api.clearScanHistory(scanId);
      }
      removeJob(job.snapshot.job_id);
      if (focusedJobId === job.snapshot.job_id) setFocusedJobId(null);
      refreshStats();
      setNotice("Scan deleted.");
    } catch (err) {
      setError(explainStartFailure(err));
    }
  };

  const queueDownloadItems = async (items: DiscoveredMediaItem[]): Promise<boolean> => {
    if (!window.api?.startBatchDownload) {
      setError({
        title: "Downloader unavailable",
        summary: "The desktop bridge is not available in this environment.",
        steps: ["Run the desktop app instead of the browser preview."],
        actions: [],
      });
      return false;
    }
    if (items.length === 0) return false;

    const downloadable = items.filter(
      (item) => (item.available_formats?.length ?? 0) > 0 || Boolean(item.original_url)
    );
    if (downloadable.length === 0) {
      setError({
        title: "Nothing to download",
        summary: "The selected items have no media URL or format information.",
        steps: ["Rescan the source to refresh media links."],
        actions: [],
      });
      return false;
    }

    const activeItems = downloadable.filter((item) => !isItemSkipped(item, skipped));
    const skippedExcluded = downloadable.length - activeItems.length;
    if (activeItems.length === 0) {
      setNotice(
        "Skipped items were excluded from download and remain recorded in the folder manifest. Unskip them first if you want to download them."
      );
      return false;
    }

    setDownloading(true);
    setError(null);
    setNotice(null);
    try {
      const orderedItems = orderItemsOldestFirst(activeItems);
      const payload = orderedItems.map((item) => ({
        media_item: item,
        selected_format: chooseFormat(item, preferredResolution),
      }));
      const result = await window.api.startBatchDownload(payload);
      setNotice(
        `Queued ${result.tasks.length} download${result.tasks.length === 1 ? "" : "s"}${
          skippedExcluded > 0 ? ` (${skippedExcluded} skipped excluded)` : ""
        }.`
      );
      onDownloadStarted?.();
      void refreshDownloaded();
      return true;
    } catch (err) {
      setError(explainDownloadFailure(err));
      return false;
    } finally {
      setDownloading(false);
    }
  };

  const downloadSelected = async () => {
    if (selectedItems.length === 0) return;
    const queued = await queueDownloadItems(selectedItems);
    if (queued) clearSelection();
  };

  const skipSelected = async () => {
    if (selectedItems.length === 0) return;
    if (!window.api?.skipMediaItems) {
      setError({
        title: "Skip unavailable",
        summary: "The desktop bridge is not available in this environment.",
        steps: ["Run the desktop app instead of the browser preview."],
        actions: [],
      });
      return;
    }
    setSkipping(true);
    setError(null);
    setNotice(null);
    try {
      const result = await window.api.skipMediaItems(selectedItems);
      setSkipped((prev) => {
        const next = new Set(prev);
        for (const item of selectedItems) itemKeys(item).forEach((key) => next.add(key));
        return next;
      });
      setNotice(
        `Skipped ${result.count} item${result.count === 1 ? "" : "s"}; they will not show as new again.`
      );
      clearSelection();
    } catch (err) {
      setError(explainDownloadFailure(err));
    } finally {
      setSkipping(false);
    }
  };

  const unskipSelected = async () => {
    const toUnskip = selectedItems.filter((item) =>
      itemKeys(item).some((key) => skipped.has(key))
    );
    if (toUnskip.length === 0) return;
    if (!window.api?.unskipMediaItems) return;
    setSkipping(true);
    setError(null);
    setNotice(null);
    try {
      const result = await window.api.unskipMediaItems(toUnskip);
      setSkipped((prev) => {
        const next = new Set(prev);
        for (const item of toUnskip) itemKeys(item).forEach((key) => next.delete(key));
        return next;
      });
      setNotice(
        `Restored ${result.count} item${result.count === 1 ? "" : "s"} as new.`
      );
      clearSelection();
    } catch (err) {
      setError(explainDownloadFailure(err));
    } finally {
      setSkipping(false);
    }
  };

  const toggleSingleSkip = async (item: DiscoveredMediaItem): Promise<boolean> => {
    const currentlySkipped = isItemSkipped(item, skipped);
    if (currentlySkipped) {
      if (!window.api?.unskipMediaItems) return false;
      await window.api.unskipMediaItems([item]);
      setSkipped((prev) => {
        const next = new Set(prev);
        itemKeys(item).forEach((key) => next.delete(key));
        return next;
      });
      setNotice("Restored item as new.");
      return false;
    }
    if (!window.api?.skipMediaItems) return false;
    await window.api.skipMediaItems([item]);
    setSkipped((prev) => {
      const next = new Set(prev);
      itemKeys(item).forEach((key) => next.add(key));
      return next;
    });
    setNotice("Marked item as skipped; it will not show as new again.");
    return true;
  };

  const handleRefreshScanView = async () => {
    setRefreshingStats(true);
    try {
      await Promise.all([refreshStats(), refreshDownloaded(), refreshSavedLinks()]);
    } finally {
      setRefreshingStats(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Scan Sources</h1>
          <p className="mt-1 text-sm text-muted">
            Paste a profile, channel, playlist, gallery, or direct media URL. Results appear as a
            gallery grid you can select and download in bulk.
          </p>
        </div>
        {stats && (
          <div
            className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted"
            title={stats.root_dir ? `Counted from xakumedia-library.json in ${stats.root_dir}` : undefined}
          >
            <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
              {stats.users ?? 0} {(stats.users ?? 0) === 1 ? "folder" : "folders"}
            </span>
            <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
              {stats.images} images
            </span>
            <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
              {stats.videos} videos
            </span>
            {(stats.skipped ?? 0) > 0 && (
              <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-amber-700 dark:text-amber-300">
                {stats.skipped} skipped
              </span>
            )}
            <button
              type="button"
              onClick={() => void handleRefreshScanView()}
              disabled={refreshingStats}
              title="Refresh image & video counts from Settings download folder"
              className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface px-2.5 py-1 text-muted transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${refreshingStats ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        )}
      </div>

      <ScanSourceForm
        input={input}
        onInputChange={setInput}
        inputRef={inputRef}
        detectedCount={detectedUrls.length}
        starting={starting}
        bookmarking={bookmarking}
        dragging={dragging}
        onDragStateChange={setDragging}
        onStart={() => void startScans()}
        onBookmark={() => void bookmarkInput()}
        showOptions={showOptions}
        onToggleOptions={() => setShowOptions((value) => !value)}
        maxPosts={maxPosts}
        maxMedia={maxMedia}
        includeImages={includeImages}
        includeVideos={includeVideos}
        onMaxPostsChange={setMaxPosts}
        onMaxMediaChange={setMaxMedia}
        onIncludeImagesChange={setIncludeImages}
        onIncludeVideosChange={setIncludeVideos}
      />

      {error && (
        <ScanErrorPanel
          info={error}
          onDismiss={() => setError(null)}
          onOpenSettings={onOpenSettings}
          onOpenExternal={onOpenExternal}
        />
      )}

      {notice && (
        <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-emerald-700 dark:text-emerald-300">
          <CheckSquare className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1 text-xs">{notice}</div>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss notice">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <JobStatusList
        jobs={activeJobs}
        focusedJobId={focusedJobId}
        savedLinks={savedLinks}
        savingUrls={savingUrls}
        onCancel={(jobId) => void cancelJob(jobId)}
        onFocus={(jobId) => setFocusedJobId((prev) => (prev === jobId ? null : jobId))}
        onShowAll={() => setFocusedJobId(null)}
        onSaveSource={(job) => void saveScanJobSource(job)}
        onDelete={(job) => void deleteScan(job)}
        onOpenSettings={onOpenSettings}
        onOpenExternal={onOpenExternal}
      />

      {(allPosts.length > 0 || runningJobs.length > 0) && (
        <PostBrowser
          filteredPosts={filteredPosts}
          counts={counts}
          selected={selected}
          downloaded={downloaded}
          skipped={skipped}
          savedLinks={savedLinks}
          savedAvatars={savedAvatars}
          runningCount={runningJobs.length}
          totalProgress={totalProgress}
          filter={filter}
          search={search}
          downloading={downloading}
          focusedScanLabel={focusedScanLabel}
          preferredResolution={preferredResolution}
          onFilterChange={setFilter}
          onSearchChange={setSearch}
          onToggleMedia={toggleMedia}
          onTogglePost={(post) => togglePost(post, filter)}
          onSaveLink={(url, title, extra) => void saveScanLink(url, title, extra)}
          onDownloadItems={(items) => void queueDownloadItems(items)}
          onSelectAllVisible={selectAllVisible}
          onSelectOnlyNew={selectOnlyNew}
          onSelectByType={selectByType}
          onInvertSelection={invertSelection}
          onClearSelection={clearSelection}
          onDownload={() => void downloadSelected()}
          onSkip={() => void skipSelected()}
          onUnskip={() => void unskipSelected()}
          skipping={skipping}
          hideSkipped={hideSkipped}
          onToggleHideSkipped={() => setHideSkipped((value) => !value)}
          onPreviewItem={(item) =>
            onPreviewItem?.(item, {
              isSkipped: isItemSkipped(item, skipped),
              onToggleSkip: () => toggleSingleSkip(item),
            })
          }
        />
      )}

      {allPosts.length === 0 && runningJobs.length === 0 && !starting && (
        <div className="rounded-xl border border-hairline bg-surface py-16 text-center">
          <Layers className="mx-auto h-10 w-10 stroke-1 text-muted" />
          <h3 className="mt-3 text-sm font-semibold text-ink">No media discovered yet</h3>
          <p className="mx-auto mt-1 max-w-md text-xs text-muted">
            Start with a channel, playlist, or profile URL. Results stream in and show as a gallery
            you can filter, select (all or only new), and download.
          </p>
          <p className="mx-auto mt-3 flex max-w-md items-center justify-center gap-1.5 text-[11px] text-muted">
            <AlertCircle className="h-3 w-3" />
            If a site returns nothing, the error card explains whether cookies are required.
          </p>
        </div>
      )}
    </div>
  );
}
