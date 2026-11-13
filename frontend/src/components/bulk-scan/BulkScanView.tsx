import { useMemo, useRef, useState } from "react";
import { AlertCircle, CheckSquare, Layers, X } from "lucide-react";
import type { ScanOptionsPayload } from "../../../../desktop/shared/types";
import { JobStatusList } from "./JobStatusList";
import { PostBrowser } from "./PostBrowser";
import { ScanErrorPanel } from "./ScanErrorPanel";
import { ScanSourceForm } from "./ScanSourceForm";
import { explainDownloadFailure, explainStartFailure } from "./errors";
import type { BulkScanViewProps, MediaFilter, ScanErrorInfo } from "./types";
import { useScanJobs } from "./useScanJobs";
import { useScanSelection } from "./useScanSelection";
import {
  chooseFormat,
  countPosts,
  filterPosts,
  parseUrls,
} from "./utils";

/**
 * Bulk-first discovery workspace.
 *
 * One source URL expands into many posts. Results arrive progressively over
 * scan:* events, so the list stays usable and cancellable while pagination
 * continues in the background. Failures are explained with remediation
 * actions instead of raw extractor messages.
 */
export function BulkScanView({
  onDownloadStarted,
  onOpenSettings,
  onOpenExternal,
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
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const detectedUrls = useMemo(() => parseUrls(input), [input]);
  const counts = useMemo(() => countPosts(allPosts), [allPosts]);
  const filteredPosts = useMemo(
    () => filterPosts(allPosts, filter, search),
    [allPosts, filter, search]
  );

  const {
    selected,
    selectedItems,
    toggleMedia,
    togglePost,
    selectVisible,
    clearSelection,
    selectByType,
    selectAlbums,
    invertSelection,
  } = useScanSelection(allPosts, filteredPosts, filter);

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
    if (!Number.isNaN(parsedMaxPosts) && parsedMaxPosts > 0)
      options.max_posts = parsedMaxPosts;
    if (!Number.isNaN(parsedMaxMedia) && parsedMaxMedia > 0)
      options.max_media = parsedMaxMedia;

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

  const downloadSelected = async () => {
    if (!window.api?.startBatchDownload) {
      setError({
        title: "Downloader unavailable",
        summary: "The desktop bridge is not available in this environment.",
        steps: ["Run the desktop app instead of the browser preview."],
        actions: [],
      });
      return;
    }
    if (selectedItems.length === 0) return;

    const downloadable = selectedItems.filter(
      (item) => (item.available_formats?.length ?? 0) > 0 || Boolean(item.original_url)
    );
    if (downloadable.length === 0) {
      setError({
        title: "Nothing to download",
        summary: "The selected items have no media URL or format information.",
        steps: ["Rescan the source to refresh media links."],
        actions: [],
      });
      return;
    }

    setDownloading(true);
    setError(null);
    setNotice(null);
    try {
      const payload = downloadable.map((item) => ({
        media_item: item,
        selected_format: chooseFormat(item),
      }));
      const result = await window.api.startBatchDownload(payload);
      setNotice(
        `Queued ${result.tasks.length} download${result.tasks.length === 1 ? "" : "s"}.`
      );
      clearSelection();
      onDownloadStarted?.();
    } catch (err) {
      setError(explainDownloadFailure(err));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Scan Sources</h1>
          <p className="mt-1 text-sm text-muted">
            Paste a profile, channel, playlist, gallery, or direct media URL. Each source expands
            into posts and albums you can select in bulk.
          </p>
        </div>
        {stats && (
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
            <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
              {stats.posts} posts
            </span>
            <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
              {stats.images} images
            </span>
            <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
              {stats.videos} videos
            </span>
          </div>
        )}
      </div>

      <ScanSourceForm
        input={input}
        onInputChange={setInput}
        inputRef={inputRef}
        detectedCount={detectedUrls.length}
        starting={starting}
        dragging={dragging}
        onDragStateChange={setDragging}
        onStart={() => void startScans()}
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
        onCancel={(jobId) => void cancelJob(jobId)}
        onOpenSettings={onOpenSettings}
        onOpenExternal={onOpenExternal}
      />

      {(allPosts.length > 0 || runningJobs.length > 0) && (
        <PostBrowser
          filteredPosts={filteredPosts}
          counts={counts}
          selected={selected}
          runningCount={runningJobs.length}
          totalProgress={totalProgress}
          filter={filter}
          search={search}
          downloading={downloading}
          onFilterChange={setFilter}
          onSearchChange={setSearch}
          onTogglePost={togglePost}
          onToggleMedia={toggleMedia}
          onSelectVisible={selectVisible}
          onSelectByType={selectByType}
          onSelectAlbums={selectAlbums}
          onInvertSelection={invertSelection}
          onClearSelection={clearSelection}
          onDownload={() => void downloadSelected()}
        />
      )}

      {allPosts.length === 0 && runningJobs.length === 0 && !starting && (
        <div className="rounded-xl border border-hairline bg-surface py-16 text-center">
          <Layers className="mx-auto h-10 w-10 stroke-1 text-muted" />
          <h3 className="mt-3 text-sm font-semibold text-ink">No posts discovered yet</h3>
          <p className="mx-auto mt-1 max-w-md text-xs text-muted">
            Start with a channel, playlist, or profile URL. The scanner streams posts in as pages
            are fetched, so you can select and download before the whole source finishes.
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
