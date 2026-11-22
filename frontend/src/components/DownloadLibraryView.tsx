import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Film,
  Folder,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  Loader2,
  Music,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  User,
  X,
} from "lucide-react";
import type {
  DiscoveredMediaItem,
  DownloadLibrarySnapshot,
  LibraryEntryItem,
  LibraryKindFolder,
  LibraryPlatformFolder,
  LibraryUserFolder,
} from "../../../desktop/shared/types";

interface DownloadLibraryViewProps {
  onPreviewItem: (item: DiscoveredMediaItem, localPath?: string | null) => void;
  onDownloadItem?: (item: DiscoveredMediaItem) => void;
  onOpenScan?: () => void;
  onOpenExternal?: (url: string) => void;
}

type StatusFilter = "all" | "downloaded" | "skipped" | "video" | "image";

function formatBytes(value?: number | null): string {
  if (!value || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function toDiscoveredItem(entry: LibraryEntryItem): DiscoveredMediaItem {
  return {
    id: entry.identity,
    source_url: entry.source_url || entry.original_url || entry.file_path || "",
    media_type: entry.media_type,
    title: entry.title || entry.filename || "Media Item",
    author: entry.author || "media",
    thumbnail_url:
      entry.file_path && entry.media_type === "image" && window.api?.toMediaLoaderUrl
        ? window.api.toMediaLoaderUrl(entry.file_path)
        : null,
    original_url: entry.original_url || entry.source_url || "",
    filesize_bytes: entry.size_bytes ?? null,
    available_formats: entry.extension
      ? [
          {
            format_id: "library",
            container: entry.extension,
            filesize_bytes: entry.size_bytes ?? null,
            is_direct_stream: true,
            url: entry.original_url || entry.source_url || null,
            requires_merge: false,
          },
        ]
      : [],
    created_at: entry.updated_at || new Date().toISOString(),
    provider: entry.provider ?? null,
    provider_media_id: entry.provider_media_id ?? null,
    post_url: entry.post_url ?? null,
    attachment_index: entry.attachment_index ?? 0,
    extension: entry.extension ?? null,
    library_status: entry.status,
  };
}

export const DownloadLibraryView: React.FC<DownloadLibraryViewProps> = ({
  onPreviewItem,
  onDownloadItem,
  onOpenScan,
  onOpenExternal,
}) => {
  const [snapshot, setSnapshot] = useState<DownloadLibrarySnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedPlatform, setSelectedPlatform] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState<string>("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LibraryEntryItem | null>(null);

  const loadLibrary = useCallback(async (silent = false) => {
    if (!window.api?.scanDownloadLibrary) {
      setLoading(false);
      return;
    }
    try {
      if (!silent) setLoading(true);
      else setRefreshing(true);
      setError(null);
      const data = await window.api.scanDownloadLibrary();
      setSnapshot(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadLibrary(false);
    const offLibrary = window.api?.onLibraryChanged?.(() => {
      void loadLibrary(true);
    });
    const offDownload = window.api?.onDownloadCompleted?.(() => {
      void loadLibrary(true);
    });
    return () => {
      offLibrary?.();
      offDownload?.();
    };
  }, [loadLibrary]);

  const currentPlatform: LibraryPlatformFolder | null = useMemo(() => {
    if (!snapshot || !selectedPlatform) return null;
    return snapshot.platforms.find((p) => p.name === selectedPlatform) ?? null;
  }, [snapshot, selectedPlatform]);

  const currentUser: LibraryUserFolder | null = useMemo(() => {
    if (!currentPlatform || !selectedUser) return null;
    return currentPlatform.users.find((u) => u.name === selectedUser) ?? null;
  }, [currentPlatform, selectedUser]);

  const currentFolder: LibraryKindFolder | null = useMemo(() => {
    if (!currentUser || !selectedFolder) return null;
    return currentUser.folders.find((f) => f.name === selectedFolder) ?? null;
  }, [currentUser, selectedFolder]);

  // Reset stale drill-down levels if a folder disappears after deletion.
  useEffect(() => {
    if (!snapshot) return;
    if (selectedPlatform && !currentPlatform) {
      setSelectedPlatform(null);
      setSelectedUser(null);
      setSelectedFolder(null);
    } else if (selectedUser && !currentUser) {
      setSelectedUser(null);
      setSelectedFolder(null);
    } else if (selectedFolder && !currentFolder) {
      setSelectedFolder(null);
    }
  }, [snapshot, selectedPlatform, selectedUser, selectedFolder, currentPlatform, currentUser, currentFolder]);

  const activeFolderItems = useMemo(() => {
    const entries: Array<{ item: LibraryEntryItem; folderPath: string }> = [];
    if (currentFolder) {
      for (const item of currentFolder.items) {
        entries.push({ item, folderPath: currentFolder.path });
      }
    } else if (currentUser) {
      for (const folder of currentUser.folders) {
        for (const item of folder.items) {
          entries.push({ item, folderPath: folder.path });
        }
      }
    }
    const query = searchQuery.trim().toLowerCase();
    return entries.filter(({ item }) => {
      if (filter === "downloaded" && item.status !== "downloaded") return false;
      if (filter === "skipped" && item.status !== "skipped") return false;
      if (filter === "video" && item.media_type !== "video") return false;
      if (filter === "image" && item.media_type !== "image") return false;
      if (!query) return true;
      const haystack = [item.title, item.filename, item.author, item.source_url, item.original_url]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [currentFolder, currentUser, filter, searchQuery]);

  const filteredPlatforms = useMemo(() => {
    if (!snapshot) return [];
    const query = searchQuery.trim().toLowerCase();
    if (!query) return snapshot.platforms;
    return snapshot.platforms.filter(
      (p) =>
        p.name.toLowerCase().includes(query) ||
        p.users.some((u) => u.name.toLowerCase().includes(query))
    );
  }, [snapshot, searchQuery]);

  const filteredUsers = useMemo(() => {
    if (!currentPlatform) return [];
    const query = searchQuery.trim().toLowerCase();
    if (!query) return currentPlatform.users;
    return currentPlatform.users.filter((u) => u.name.toLowerCase().includes(query));
  }, [currentPlatform, searchQuery]);

  const activePath =
    currentFolder?.path || currentUser?.path || currentPlatform?.path || snapshot?.root_dir;

  const handleGoUp = () => {
    if (selectedFolder) {
      setSelectedFolder(null);
      return;
    }
    if (selectedUser) {
      setSelectedUser(null);
      return;
    }
    if (selectedPlatform) {
      setSelectedPlatform(null);
    }
  };

  const handleUnskip = async (folderPath: string, entry: LibraryEntryItem) => {
    if (!window.api?.unskipLibraryEntry) return;
    setBusyKey(entry.identity);
    try {
      await window.api.unskipLibraryEntry(folderPath, entry.identity);
      await loadLibrary(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget?.file_path || !window.api?.deleteLibraryFile) return;
    setBusyKey(deleteTarget.identity);
    try {
      await window.api.deleteLibraryFile(deleteTarget.file_path);
      setDeleteTarget(null);
      await loadLibrary(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-hairline pb-5 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center space-x-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent shadow-card">
            <HardDrive className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">Download Library</h1>
            <p className="mt-0.5 font-mono text-xs text-muted">
              Live folder view synced from your download directory and{" "}
              <span className="text-ink/90">xakumedia-library.json</span> manifests.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {snapshot && (
            <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-muted">
              <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
                {snapshot.totals.downloaded} files
              </span>
              <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-amber-700 dark:text-amber-300">
                {snapshot.totals.skipped} skipped
              </span>
              <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
                {formatBytes(snapshot.totals.size_bytes)}
              </span>
            </div>
          )}
          {activePath && (
            <button
              type="button"
              onClick={() => window.api?.openPath?.(activePath)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-hairline bg-surface px-3 py-2 font-mono text-xs text-ink/80 transition-colors hover:bg-raised hover:text-ink"
              title="Open current folder in File Explorer"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              <span>Open Folder</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => void loadLibrary(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-xl border border-hairline bg-surface px-3 py-2 font-mono text-xs text-ink/80 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Breadcrumb & Search Bar */}
      <div className="flex flex-col gap-3 rounded-xl border border-hairline bg-surface p-3.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
          {selectedPlatform && (
            <button
              type="button"
              onClick={handleGoUp}
              className="mr-1 inline-flex items-center gap-1 rounded-lg border border-hairline bg-raised px-2 py-1 text-muted transition-colors hover:text-ink"
              title="Back one folder"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setSelectedPlatform(null);
              setSelectedUser(null);
              setSelectedFolder(null);
            }}
            className={`rounded-md px-2 py-1 transition-colors ${
              !selectedPlatform
                ? "bg-accent/10 font-semibold text-accent"
                : "text-muted hover:bg-raised hover:text-ink"
            }`}
          >
            Library
          </button>
          {currentPlatform && (
            <>
              <ChevronRight className="h-3.5 w-3.5 text-faint" />
              <button
                type="button"
                onClick={() => {
                  setSelectedUser(null);
                  setSelectedFolder(null);
                }}
                className={`rounded-md px-2 py-1 transition-colors ${
                  !selectedUser
                    ? "bg-accent/10 font-semibold text-accent"
                    : "text-muted hover:bg-raised hover:text-ink"
                }`}
              >
                {currentPlatform.name}
              </button>
            </>
          )}
          {currentUser && (
            <>
              <ChevronRight className="h-3.5 w-3.5 text-faint" />
              <button
                type="button"
                onClick={() => setSelectedFolder(null)}
                className={`rounded-md px-2 py-1 transition-colors ${
                  !selectedFolder
                    ? "bg-accent/10 font-semibold text-accent"
                    : "text-muted hover:bg-raised hover:text-ink"
                }`}
              >
                {currentUser.name}
              </button>
            </>
          )}
          {currentFolder && (
            <>
              <ChevronRight className="h-3.5 w-3.5 text-faint" />
              <span className="rounded-md bg-accent/10 px-2 py-1 font-semibold text-accent">
                {currentFolder.name}
              </span>
            </>
          )}
        </div>

        <div className="relative sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={
              currentUser
                ? "Filter files & skipped..."
                : currentPlatform
                ? "Filter users..."
                : "Search platform or user..."
            }
            className="w-full rounded-lg border border-hairline bg-page py-1.5 pl-8 pr-7 font-mono text-xs text-ink placeholder-faint focus:border-accent focus:outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 font-mono text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center space-y-3 py-24 text-muted">
          <Loader2 className="h-6 w-6 animate-spin text-accent" />
          <span className="font-mono text-xs">Scanning download folders and JSON manifests...</span>
        </div>
      ) : !snapshot || snapshot.platforms.length === 0 ? (
        <div className="flex flex-col items-center justify-center space-y-3 rounded-2xl border border-dashed border-hairline bg-surface p-12 text-center">
          <Folder className="h-10 w-10 stroke-1 text-faint" />
          <h3 className="text-sm font-semibold text-ink">Your Download Library is Empty</h3>
          <p className="max-w-md font-mono text-xs text-muted">
            Downloaded media and skipped items recorded in{" "}
            <span className="text-ink/80">xakumedia-library.json</span> inside{" "}
            <span className="text-ink/80">{snapshot?.root_dir || "your download folder"}</span>{" "}
            appear here automatically.
          </p>
          {onOpenScan && (
            <button
              type="button"
              onClick={onOpenScan}
              className="mt-2 rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-colors hover:bg-accent-vivid"
            >
              Scan Media Sources
            </button>
          )}
        </div>
      ) : !currentPlatform ? (
        /* LEVEL 0: PLATFORM FOLDERS */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredPlatforms.map((platform) => (
            <button
              key={platform.path}
              type="button"
              onClick={() => {
                setSelectedPlatform(platform.name);
                setSearchQuery("");
              }}
              className="group flex flex-col justify-between space-y-4 rounded-2xl border border-hairline bg-surface p-5 text-left shadow-card transition-all hover:border-accent/40 hover:bg-raised/40"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent transition-transform group-hover:scale-105">
                    <Folder className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-ink">{platform.name}</h3>
                    <span className="font-mono text-xs text-muted">
                      {platform.user_count} {platform.user_count === 1 ? "creator" : "creators"}
                    </span>
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-3 font-mono text-[11px] text-muted">
                <div className="flex flex-wrap items-center gap-2">
                  <span>{platform.video_count} videos</span>
                  <span>·</span>
                  <span>{platform.image_count} images</span>
                  {platform.skipped_count > 0 && (
                    <>
                      <span>·</span>
                      <span className="text-amber-700 dark:text-amber-300">
                        {platform.skipped_count} skipped
                      </span>
                    </>
                  )}
                </div>
                <span className="font-semibold text-ink/80">{formatBytes(platform.size_bytes)}</span>
              </div>
            </button>
          ))}
        </div>
      ) : !currentUser ? (
        /* LEVEL 1: USER FOLDERS INSIDE PLATFORM */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredUsers.map((user) => {
            const previewUrl =
              user.preview_path && window.api?.toMediaLoaderUrl
                ? window.api.toMediaLoaderUrl(user.preview_path)
                : null;
            return (
              <button
                key={user.path}
                type="button"
                onClick={() => {
                  setSelectedUser(user.name);
                  setSearchQuery("");
                  setFilter("all");
                }}
                className="group flex flex-col justify-between space-y-4 rounded-2xl border border-hairline bg-surface p-4 text-left shadow-card transition-all hover:border-accent/40 hover:bg-raised/40"
              >
                <div className="flex items-center gap-3">
                  {previewUrl ? (
                    <img
                      src={previewUrl}
                      alt={user.name}
                      className="h-12 w-12 shrink-0 rounded-xl border border-hairline object-cover"
                    />
                  ) : (
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-hairline bg-raised text-muted">
                      <User className="h-5 w-5" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-bold text-ink" title={user.name}>
                      {user.name}
                    </h3>
                    <p className="font-mono text-[11px] text-muted">
                      {user.folders.map((f) => f.name).join(" · ")}
                    </p>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-3 font-mono text-[11px] text-muted">
                  <div className="flex items-center gap-2">
                    <span>{user.video_count} vid</span>
                    <span>·</span>
                    <span>{user.image_count} img</span>
                    {user.skipped_count > 0 && (
                      <>
                        <span>·</span>
                        <span className="text-amber-700 dark:text-amber-300">
                          {user.skipped_count} skipped
                        </span>
                      </>
                    )}
                  </div>
                  <span className="font-semibold text-ink/80">{formatBytes(user.size_bytes)}</span>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        /* LEVEL 2 (USER PARENT) & LEVEL 3 (LEAF FOLDER) */
        <div className="space-y-5">
          {/* Child Subfolder Cards when viewing User Parent Folder */}
          {!currentFolder && currentUser.folders.length > 0 && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {currentUser.folders.map((folder) => {
                const Icon =
                  folder.media_type === "video"
                    ? Film
                    : folder.media_type === "audio"
                    ? Music
                    : ImageIcon;
                return (
                  <button
                    key={folder.path}
                    type="button"
                    onClick={() => {
                      setSelectedFolder(folder.name);
                      setFilter("all");
                    }}
                    className="group flex items-center justify-between rounded-xl border border-hairline bg-surface p-4 text-left transition-all hover:border-accent/40 hover:bg-raised/40"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-hairline bg-raised text-accent">
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="text-sm font-bold text-ink">{folder.name}/</p>
                        <p className="font-mono text-[11px] text-muted">
                          {folder.downloaded_count} files
                          {folder.skipped_count > 0 ? ` · ${folder.skipped_count} skipped` : ""}
                        </p>
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 text-faint group-hover:text-accent" />
                  </button>
                );
              })}
            </div>
          )}

          {/* Filter Pills */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              {(
                [
                  ["all", "All"],
                  ["downloaded", "Downloaded"],
                  ["skipped", "Skipped"],
                  ["video", "Videos"],
                  ["image", "Images"],
                ] as Array<[StatusFilter, string]>
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setFilter(id)}
                  className={`rounded-full border px-3 py-1 font-mono text-[11px] transition-colors ${
                    filter === id
                      ? "border-accent/40 bg-accent/10 font-semibold text-accent"
                      : "border-hairline text-muted hover:bg-raised hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="font-mono text-xs text-muted">
              {activeFolderItems.length} {activeFolderItems.length === 1 ? "item" : "items"}
            </span>
          </div>

          {activeFolderItems.length === 0 ? (
            <div className="rounded-xl border border-hairline bg-surface py-16 text-center font-mono text-xs text-muted">
              No items match this filter.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
              {activeFolderItems.map(({ item, folderPath }) => {
                const isSkipped = item.status === "skipped";
                const mediaUrl =
                  item.file_path && window.api?.toMediaLoaderUrl
                    ? window.api.toMediaLoaderUrl(item.file_path)
                    : null;
                const discovered = toDiscoveredItem(item);
                const busy = busyKey === item.identity;

                return (
                  <div
                    key={`${folderPath}:${item.identity}:${item.filename || ""}`}
                    className={`flex flex-col justify-between overflow-hidden rounded-xl border bg-surface transition-colors ${
                      isSkipped
                        ? "border-amber-500/35 bg-amber-500/[0.03]"
                        : "border-hairline hover:border-hairline-strong"
                    }`}
                  >
                    {/* Thumbnail / Preview Area */}
                    <div
                      onClick={() => {
                        if (!isSkipped && item.file_path) {
                          onPreviewItem(discovered, item.file_path);
                        }
                      }}
                      className={`relative aspect-video w-full overflow-hidden bg-band ${
                        !isSkipped && item.file_path ? "cursor-pointer group" : ""
                      }`}
                    >
                      {!isSkipped && mediaUrl && item.media_type === "image" ? (
                        <img
                          src={mediaUrl}
                          alt={item.title || item.filename || "Image"}
                          loading="lazy"
                          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                        />
                      ) : !isSkipped && mediaUrl && item.media_type === "video" ? (
                        <video
                          src={`${mediaUrl}#t=0.5`}
                          preload="metadata"
                          muted
                          playsInline
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 text-muted">
                          {isSkipped ? (
                            <EyeOff className="h-7 w-7 text-amber-600 dark:text-amber-400" />
                          ) : item.media_type === "video" ? (
                            <Film className="h-7 w-7" />
                          ) : item.media_type === "audio" ? (
                            <Music className="h-7 w-7" />
                          ) : (
                            <ImageIcon className="h-7 w-7" />
                          )}
                          <span className="font-mono text-[10px] uppercase">
                            {isSkipped ? "Skipped Item" : item.extension || item.media_type}
                          </span>
                        </div>
                      )}

                      {!isSkipped && item.file_path && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/45 opacity-0 transition-opacity group-hover:opacity-100">
                          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-on-accent shadow-lg">
                            {item.media_type === "image" ? (
                              <Eye className="h-4 w-4" />
                            ) : (
                              <Play className="ml-0.5 h-4 w-4 fill-current" />
                            )}
                          </span>
                        </div>
                      )}

                      <span
                        className={`absolute left-2 top-2 rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase text-white ${
                          isSkipped ? "bg-amber-600/90" : "bg-black/75"
                        }`}
                      >
                        {isSkipped ? "skipped" : item.extension || item.media_type}
                      </span>
                      {!isSkipped && item.size_bytes != null && (
                        <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[9px] text-white/90">
                          {formatBytes(item.size_bytes)}
                        </span>
                      )}
                    </div>

                    {/* Metadata + Actions */}
                    <div className="flex flex-1 flex-col justify-between space-y-2.5 p-3">
                      <div className="space-y-0.5">
                        <p
                          className="truncate font-mono text-xs font-semibold text-ink"
                          title={item.filename || item.title || ""}
                        >
                          {item.filename || item.title || "Untitled"}
                        </p>
                        {item.title && item.filename && item.title !== item.filename && (
                          <p className="truncate text-[11px] text-muted" title={item.title}>
                            {item.title}
                          </p>
                        )}
                      </div>

                      <div className="flex items-center justify-between gap-2 border-t border-hairline pt-2 font-mono text-[11px]">
                        {isSkipped ? (
                          <>
                            <button
                              type="button"
                              onClick={() => void handleUnskip(folderPath, item)}
                              disabled={busy}
                              className="inline-flex items-center gap-1 rounded-md border border-hairline bg-raised px-2 py-1 text-ink transition-colors hover:border-accent/40 hover:text-accent disabled:opacity-50"
                              title="Remove from skip list so future scans detect it as new"
                            >
                              {busy ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <RotateCcw className="h-3 w-3" />
                              )}
                              <span>Unskip</span>
                            </button>
                            <div className="flex items-center gap-1.5">
                              {onDownloadItem && item.original_url && (
                                <button
                                  type="button"
                                  onClick={() => onDownloadItem(discovered)}
                                  className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-2 py-1 text-accent transition-colors hover:bg-accent/20"
                                  title="Download this item now"
                                >
                                  <Download className="h-3 w-3" />
                                  <span>Get</span>
                                </button>
                              )}
                              {(item.post_url || item.source_url) && onOpenExternal && (
                                <button
                                  type="button"
                                  onClick={() => onOpenExternal((item.post_url || item.source_url)!)}
                                  className="p-1 text-muted hover:text-ink"
                                  title="Open source URL"
                                >
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </button>
                              )}
                            </div>
                          </>
                        ) : (
                          <>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => onPreviewItem(discovered, item.file_path)}
                                className="inline-flex items-center gap-1 text-ink/80 hover:text-accent"
                              >
                                <Eye className="h-3 w-3" />
                                <span>View</span>
                              </button>
                              {item.file_path && (
                                <button
                                  type="button"
                                  onClick={() => window.api?.openPath?.(item.file_path!)}
                                  className="inline-flex items-center gap-1 text-muted hover:text-ink"
                                  title="Show in File Explorer"
                                >
                                  <FolderOpen className="h-3 w-3" />
                                  <span>Folder</span>
                                </button>
                              )}
                            </div>
                            <button
                              type="button"
                              onClick={() => setDeleteTarget(item)}
                              className="p-1 text-red-600 transition-colors hover:text-red-500 dark:text-red-400"
                              title="Delete file from disk"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Delete File Confirmation Modal */}
      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
          onClick={() => setDeleteTarget(null)}
        >
          <div
            className="w-full max-w-md space-y-4 rounded-2xl border border-red-500/30 bg-page p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-bold text-ink">Delete Downloaded File?</h3>
            <p className="font-mono text-xs text-muted">
              This will permanently remove{" "}
              <span className="font-semibold text-ink">{deleteTarget.filename}</span> from disk and
              update <span className="text-ink">xakumedia-library.json</span>.
            </p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="rounded-xl bg-raised px-4 py-2 font-mono text-xs text-ink/80 hover:text-ink"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleConfirmDelete()}
                disabled={busyKey === deleteTarget.identity}
                className="inline-flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 font-mono text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
              >
                {busyKey === deleteTarget.identity && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                <span>Delete File</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
