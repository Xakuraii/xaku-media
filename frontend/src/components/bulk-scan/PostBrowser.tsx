import { useEffect, useMemo, useState } from "react";
import {
  Bookmark,
  CheckSquare,
  Download,
  EyeOff,
  Film,
  Image as ImageIcon,
  Layers,
  Link2,
  Loader2,
  Search,
  Square,
  Sparkles,
} from "lucide-react";
import type { DiscoveredMediaItem } from "../../../../desktop/shared/types";
import { isItemDownloaded, isItemSkipped, type MediaFilter, type PostWithScan } from "./types";
import { chooseFormat, formatBytes, visibleMedia } from "./utils";

/** Keep the DOM small while a large scan is still streaming in. */
const POST_PAGE_SIZE = 24;
const GROUP_MEDIA_PAGE_SIZE = 12;
const VIDEO_PAGE_SIZE = 120;

interface PostBrowserProps {
  filteredPosts: PostWithScan[];
  counts: { posts: number; media: number; images: number; videos: number; albums: number };
  selected: Set<string>;
  downloaded: Set<string>;
  skipped: Set<string>;
  bookmarked: Set<string>;
  bookmarkBusy: Set<string>;
  savedLinks: Set<string>;
  runningCount: number;
  totalProgress: { posts: number; media: number };
  filter: MediaFilter;
  search: string;
  downloading: boolean;
  focusedScanLabel?: string | null;
  preferredResolution?: string;
  onFilterChange: (filter: MediaFilter) => void;
  onSearchChange: (value: string) => void;
  onToggleMedia: (itemId: string) => void;
  onTogglePost: (post: PostWithScan) => void;
  onToggleBookmark: (item: DiscoveredMediaItem) => void;
  onTogglePostBookmark: (post: PostWithScan) => void;
  onSaveLink: (url: string, title: string) => void;
  onDownloadItems: (items: DiscoveredMediaItem[]) => void;
  onSelectAllVisible: () => void;
  onSelectOnlyNew: () => void;
  onSelectByType: (type: "image" | "video") => void;
  onInvertSelection: () => void;
  onClearSelection: () => void;
  onDownload: () => void;
  onSkip: () => void;
  skipping: boolean;
}

interface VideoEntry {
  item: DiscoveredMediaItem;
  post: PostWithScan;
}

export function PostBrowser({
  filteredPosts,
  counts,
  selected,
  downloaded,
  skipped,
  bookmarked,
  bookmarkBusy,
  savedLinks,
  runningCount,
  totalProgress,
  filter,
  search,
  downloading,
  focusedScanLabel,
  preferredResolution,
  onFilterChange,
  onSearchChange,
  onToggleMedia,
  onTogglePost,
  onToggleBookmark,
  onTogglePostBookmark,
  onSaveLink,
  onDownloadItems,
  onSelectAllVisible,
  onSelectOnlyNew,
  onSelectByType,
  onInvertSelection,
  onClearSelection,
  onDownload,
  onSkip,
  skipping,
}: PostBrowserProps) {
  const visibleItems = useMemo(
    () => filteredPosts.flatMap((post) => visibleMedia(post, filter)),
    [filteredPosts, filter]
  );
  const newCount = visibleItems.filter(
    (item) => !isItemDownloaded(item, downloaded) && !isItemSkipped(item, skipped)
  ).length;

  const [renderLimit, setRenderLimit] = useState(POST_PAGE_SIZE);
  const [videoLimit, setVideoLimit] = useState(VIDEO_PAGE_SIZE);
  useEffect(() => {
    setRenderLimit(POST_PAGE_SIZE);
    setVideoLimit(VIDEO_PAGE_SIZE);
  }, [filter, search, focusedScanLabel]);

  const displayedPosts = useMemo(
    () => filteredPosts.slice(0, renderLimit),
    [filteredPosts, renderLimit]
  );
  const remainingCount = Math.max(0, filteredPosts.length - displayedPosts.length);

  // Every video in the current result set lives in one shared shelf. A profile
  // with 50 video posts should read as a video grid, not 50 separate one-card
  // rows, and a run of image posts must not hide the videos behind page two.
  const allVideoEntries = useMemo<VideoEntry[]>(() => {
    if (filter === "image") return [];
    return filteredPosts.flatMap((post) =>
      post.media_items
        .filter((item) => item.media_type === "video")
        .map((item) => ({ item, post }))
    );
  }, [filteredPosts, filter]);
  const videoEntries = useMemo(
    () => allVideoEntries.slice(0, videoLimit),
    [allVideoEntries, videoLimit]
  );
  const remainingVideos = Math.max(0, allVideoEntries.length - videoEntries.length);

  // Image posts keep their own album grouping so a carousel stays together.
  const imageGroups = useMemo(() => {
    if (filter === "video") return [];
    return displayedPosts
      .map((post) => ({
        post,
        items: post.media_items.filter((item) => item.media_type === "image"),
      }))
      .filter((group) => group.items.length > 0);
  }, [displayedPosts, filter]);

  const hasResults = allVideoEntries.length > 0 || imageGroups.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-hairline bg-surface px-4 py-3">
        <div className="mr-auto flex flex-wrap items-center gap-2">
          {(
            [
              ["all", `All ${counts.media}`],
              ["image", `Images ${counts.images}`],
              ["video", `Videos ${counts.videos}`],
              ["album", `Albums ${counts.albums}`],
            ] as Array<[MediaFilter, string]>
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => onFilterChange(value)}
              className={`rounded-full border px-3 py-1 text-[11px] font-mono transition-colors ${
                filter === value
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-hairline text-muted hover:bg-raised hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Filter posts…"
              className="w-44 rounded-full border border-hairline bg-page py-1 pl-7 pr-3 font-mono text-[11px] text-ink placeholder-faint focus:border-accent focus:outline-none"
            />
          </div>
          {focusedScanLabel && (
            <span className="rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 font-mono text-[10px] text-accent">
              showing: {focusedScanLabel}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
          <button type="button" onClick={onSelectAllVisible} className="text-ink/80 hover:text-accent">
            Select all
          </button>
          <button type="button" onClick={onSelectOnlyNew} className="inline-flex items-center gap-1 text-ink/80 hover:text-accent">
            <Sparkles className="h-3 w-3" />
            Select new ({newCount})
          </button>
          <span className="text-hairline">|</span>
          <button type="button" onClick={() => onSelectByType("image")} className="text-ink/80 hover:text-accent">
            Images
          </button>
          <button type="button" onClick={() => onSelectByType("video")} className="text-ink/80 hover:text-accent">
            Videos
          </button>
          <button type="button" onClick={onInvertSelection} className="text-ink/80 hover:text-accent">
            Invert
          </button>
          <button type="button" onClick={onClearSelection} className="text-ink/80 hover:text-accent">
            Clear
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent/25 bg-accent/5 px-4 py-3">
        <div className="font-mono text-xs text-ink/80">
          <span className="text-accent font-semibold">{selected.size}</span> selected
          <span className="text-muted">
            {" "}
            · {counts.posts} posts · {counts.media} media · {newCount} new
          </span>
          {runningCount > 0 && (
            <span className="ml-3 text-muted">
              discovering… {totalProgress.posts} posts / {totalProgress.media} media
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onSkip}
            disabled={selected.size === 0 || skipping}
            title="Skip selected items and record them in the folder library manifest"
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
              selected.size > 0 && !skipping
                ? "cursor-pointer border-amber-500/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-300"
                : "cursor-not-allowed border-hairline bg-raised text-faint"
            }`}
          >
            {skipping ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <EyeOff className="h-4 w-4" />
            )}
            <span>{skipping ? "Skipping…" : `Skip selected (${selected.size})`}</span>
          </button>
          <button
            type="button"
            onClick={onDownload}
            disabled={selected.size === 0 || downloading}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all ${
              selected.size > 0 && !downloading
                ? "cursor-pointer bg-accent text-on-accent shadow-md shadow-accent/25 hover:bg-accent-vivid"
                : "cursor-not-allowed border border-hairline bg-raised text-faint"
            }`}
          >
            {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            <span>{downloading ? "Queueing…" : `Download selected (${selected.size})`}</span>
          </button>
        </div>
      </div>

      {!hasResults && runningCount === 0 ? (
        <div className="rounded-xl border border-hairline bg-surface py-16 text-center">
          <Layers className="mx-auto h-8 w-8 stroke-1 text-muted" />
          <p className="mt-2 text-xs text-muted">No media match this view yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {videoEntries.length > 0 && (
            <VideoShelf
              entries={videoEntries}
              totalCount={allVideoEntries.length}
              remainingCount={remainingVideos}
              onShowMore={() => setVideoLimit((limit) => limit + VIDEO_PAGE_SIZE)}
              selected={selected}
              downloaded={downloaded}
              skipped={skipped}
              bookmarked={bookmarked}
              bookmarkBusy={bookmarkBusy}
              savedLinks={savedLinks}
              preferredResolution={preferredResolution}
              downloading={downloading}
              onToggleMedia={onToggleMedia}
              onToggleBookmark={onToggleBookmark}
              onSaveLink={onSaveLink}
              onSelectVideos={() => onSelectByType("video")}
            />
          )}

          {imageGroups.map(({ post }) => (
            <PostGroup
              key={post.id}
              post={post}
              filter="image"
              selected={selected}
              downloaded={downloaded}
              skipped={skipped}
              bookmarked={bookmarked}
              bookmarkBusy={bookmarkBusy}
              savedLinks={savedLinks}
              preferredResolution={preferredResolution}
              downloading={downloading}
              onToggleMedia={onToggleMedia}
              onTogglePost={onTogglePost}
              onToggleBookmark={onToggleBookmark}
              onTogglePostBookmark={onTogglePostBookmark}
              onSaveLink={onSaveLink}
              onDownloadItems={onDownloadItems}
            />
          ))}
        </div>
      )}

      {remainingCount > 0 && (
        <div className="flex justify-center pt-2">
          <button
            type="button"
            onClick={() => setRenderLimit((limit) => limit + POST_PAGE_SIZE)}
            className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs font-medium text-muted transition-colors hover:border-accent/40 hover:text-ink"
          >
            Show {Math.min(POST_PAGE_SIZE, remainingCount)} more posts
            <span className="ml-1 text-faint">({remainingCount} remaining)</span>
          </button>
        </div>
      )}
    </div>
  );
}

function VideoShelf({
  entries,
  totalCount,
  remainingCount,
  onShowMore,
  selected,
  downloaded,
  skipped,
  bookmarked,
  bookmarkBusy,
  savedLinks,
  preferredResolution,
  downloading,
  onToggleMedia,
  onToggleBookmark,
  onSaveLink,
  onSelectVideos,
}: {
  entries: VideoEntry[];
  totalCount: number;
  remainingCount: number;
  onShowMore: () => void;
  selected: Set<string>;
  downloaded: Set<string>;
  skipped: Set<string>;
  bookmarked: Set<string>;
  bookmarkBusy: Set<string>;
  savedLinks: Set<string>;
  preferredResolution?: string;
  downloading: boolean;
  onToggleMedia: (itemId: string) => void;
  onToggleBookmark: (item: DiscoveredMediaItem) => void;
  onSaveLink: (url: string, title: string) => void;
  onSelectVideos: () => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-hairline bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-hairline px-3 py-2">
        <Film className="h-4 w-4 text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-ink">Videos</p>
          <p className="font-mono text-[10px] text-muted">
            {totalCount} video{totalCount === 1 ? "" : "s"} in one grid
            {remainingCount > 0 ? ` · showing ${entries.length}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onSelectVideos}
          className="rounded border border-hairline px-2 py-1 font-mono text-[10px] text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          Select all videos
        </button>
      </header>
      <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {entries.map(({ item, post }) => {
          const chosen = chooseFormat(item, preferredResolution);
          const linkUrl = item.post_url || item.original_url;
          return (
            <MediaCard
              key={item.id}
              item={item}
              index={0}
              variant="video"
              caption={post.author || post.title}
              isSelected={selected.has(item.id)}
              isBookmarked={bookmarked.has(item.id)}
              bookmarkBusy={bookmarkBusy.has(post.id) || bookmarkBusy.has(item.id)}
              wasDownloaded={isItemDownloaded(item, downloaded)}
              isSkipped={isItemSkipped(item, skipped)}
              chosenFormat={chosen}
              isLinkSaved={Boolean(linkUrl && savedLinks.has(linkUrl))}
              onToggle={() => onToggleMedia(item.id)}
              onToggleBookmark={() => onToggleBookmark(item)}
              onSaveLink={() =>
                linkUrl && onSaveLink(linkUrl, item.title || `${post.author} video`)
              }
            />
          );
        })}
      </div>
      {remainingCount > 0 && (
        <div className="border-t border-hairline px-3 py-2 text-center">
          <button
            type="button"
            onClick={onShowMore}
            className="font-mono text-[10px] text-muted transition-colors hover:text-accent"
          >
            Show {Math.min(VIDEO_PAGE_SIZE, remainingCount)} more videos
            <span className="ml-1 text-faint">({remainingCount} remaining)</span>
          </button>
        </div>
      )}
      {downloading && (
        <div className="border-t border-hairline px-3 py-1.5 text-center font-mono text-[10px] text-muted">
          Queueing downloads…
        </div>
      )}
    </section>
  );
}

function PostGroup({
  post,
  filter,
  selected,
  downloaded,
  skipped,
  bookmarked,
  bookmarkBusy,
  savedLinks,
  preferredResolution,
  downloading,
  onToggleMedia,
  onTogglePost,
  onToggleBookmark,
  onTogglePostBookmark,
  onSaveLink,
  onDownloadItems,
}: {
  post: PostWithScan;
  filter: MediaFilter;
  selected: Set<string>;
  downloaded: Set<string>;
  skipped: Set<string>;
  bookmarked: Set<string>;
  bookmarkBusy: Set<string>;
  savedLinks: Set<string>;
  preferredResolution?: string;
  downloading: boolean;
  onToggleMedia: (itemId: string) => void;
  onTogglePost: (post: PostWithScan) => void;
  onToggleBookmark: (item: DiscoveredMediaItem) => void;
  onTogglePostBookmark: (post: PostWithScan) => void;
  onSaveLink: (url: string, title: string) => void;
  onDownloadItems: (items: DiscoveredMediaItem[]) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const items = useMemo(() => visibleMedia(post, filter), [post, filter]);
  if (items.length === 0) return null;

  const shownItems = expanded ? items : items.slice(0, GROUP_MEDIA_PAGE_SIZE);
  const hiddenCount = Math.max(0, items.length - shownItems.length);
  const allSelected = items.every((item) => selected.has(item.id));
  const savedCount = items.filter((item) => bookmarked.has(item.id)).length;
  const allSaved = savedCount === items.length;
  const postBusy = bookmarkBusy.has(post.id);
  const images = items.filter((item) => item.media_type === "image").length;
  const videos = items.filter((item) => item.media_type === "video").length;
  const label = items.length > 1 ? "album" : "post";
  const heading = post.title || post.provider_post_id || `Untitled ${label}`;
  const linkUrl = post.post_url || post.source_url;
  const linkSaved = Boolean(linkUrl && savedLinks.has(linkUrl));

  return (
    <section className="overflow-hidden rounded-xl border border-hairline bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-hairline px-3 py-2">
        <button
          type="button"
          onClick={() => onTogglePost(post)}
          aria-pressed={allSelected}
          aria-label={allSelected ? `Deselect this ${label}` : `Select this ${label}`}
          className={`rounded p-1 transition-colors ${
            allSelected ? "text-accent" : "text-muted hover:text-ink"
          }`}
        >
          {allSelected ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-ink" title={heading}>
            {heading}
          </p>
          <p className="truncate font-mono text-[10px] text-muted">
            {post.author || "unknown"}
            {post.post_url ? ` · ${post.post_url}` : ""}
          </p>
        </div>
        <span className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[10px] text-muted">
          {label} · {items.length}
          {images > 0 ? ` · ${images} img` : ""}
          {videos > 0 ? ` · ${videos} vid` : ""}
        </span>
        {linkUrl && (
          <button
            type="button"
            onClick={() => onSaveLink(linkUrl, heading)}
            title={linkSaved ? "This source link is already saved" : "Save this source link"}
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 font-mono text-[10px] transition-colors ${
              linkSaved
                ? "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300"
                : "border-hairline text-muted hover:bg-raised hover:text-ink"
            }`}
          >
            <Link2 className="h-3 w-3" />
            {linkSaved ? "Link saved" : "Save link"}
          </button>
        )}
        <button
          type="button"
          onClick={() => onTogglePostBookmark(post)}
          disabled={postBusy}
          title={allSaved ? "Remove this post from favorites" : "Save this post to favorites"}
          aria-pressed={allSaved}
          className={`inline-flex items-center gap-1 rounded border px-2 py-1 font-mono text-[10px] transition-colors ${
            allSaved
              ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300"
              : "border-hairline text-muted hover:bg-raised hover:text-ink"
          } ${postBusy ? "opacity-60" : ""}`}
        >
          <Bookmark className={`h-3 w-3 ${allSaved ? "fill-current" : ""}`} />
          {allSaved ? `Saved ${savedCount}/${items.length}` : "Save post"}
        </button>
        <button
          type="button"
          onClick={() => onDownloadItems(items)}
          disabled={downloading || items.length === 0}
          className="inline-flex items-center gap-1 rounded border border-accent/30 bg-accent/10 px-2 py-1 font-mono text-[10px] text-accent transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-3 w-3" />
          {items.length > 1 ? `Download ${label} (${items.length})` : "Download"}
        </button>
      </header>

      <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
        {shownItems.map((item, index) => {
          const chosen = chooseFormat(item, preferredResolution);
          return (
            <MediaCard
              key={item.id}
              item={item}
              index={index}
              isSelected={selected.has(item.id)}
              isBookmarked={bookmarked.has(item.id)}
              bookmarkBusy={postBusy || bookmarkBusy.has(item.id)}
              wasDownloaded={isItemDownloaded(item, downloaded)}
              isSkipped={isItemSkipped(item, skipped)}
              chosenFormat={chosen}
              onToggle={() => onToggleMedia(item.id)}
              onToggleBookmark={() => onToggleBookmark(item)}
            />
          );
        })}
      </div>

      {hiddenCount > 0 && (
        <div className="border-t border-hairline px-3 py-2 text-center">
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="font-mono text-[10px] text-muted hover:text-accent"
          >
            Show {hiddenCount} more in this {label}
          </button>
        </div>
      )}
      {expanded && items.length > GROUP_MEDIA_PAGE_SIZE && (
        <div className="border-t border-hairline px-3 py-2 text-center">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="font-mono text-[10px] text-muted hover:text-accent"
          >
            Collapse to {GROUP_MEDIA_PAGE_SIZE}
          </button>
        </div>
      )}
    </section>
  );
}

function formatDuration(seconds?: number | null): string | null {
  if (!seconds || seconds <= 0) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes}:${String(rest).padStart(2, "0")}` : `0:${String(rest).padStart(2, "0")}`;
}

function MediaCard({
  item,
  index,
  variant = "image",
  caption,
  isSelected,
  isBookmarked,
  bookmarkBusy,
  wasDownloaded,
  isSkipped,
  chosenFormat,
  isLinkSaved = false,
  onToggle,
  onToggleBookmark,
  onSaveLink,
}: {
  item: DiscoveredMediaItem;
  index: number;
  variant?: "video" | "image";
  caption?: string | null;
  isSelected: boolean;
  isBookmarked: boolean;
  bookmarkBusy: boolean;
  wasDownloaded: boolean;
  isSkipped: boolean;
  chosenFormat: ReturnType<typeof chooseFormat>;
  isLinkSaved?: boolean;
  onToggle: () => void;
  onToggleBookmark: () => void;
  onSaveLink?: () => void;
}) {
  const displaySize = chosenFormat?.filesize_bytes ?? item.filesize_bytes;
  const displayRes = chosenFormat?.resolution || null;
  const duration = formatDuration(item.duration_seconds);
  return (
    <div
      className={`group overflow-hidden rounded-lg border bg-surface transition-colors ${
        isSelected ? "border-accent ring-1 ring-accent/40" : "border-hairline"
      }`}
    >
      <div
        className={`relative bg-raised ${variant === "video" ? "aspect-video" : "aspect-square"}`}
      >
        {item.thumbnail_url ? (
          <img
            src={item.thumbnail_url}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-muted">
            {item.media_type === "video" ? (
              <Film className="h-8 w-8 stroke-1" />
            ) : item.media_type === "image" ? (
              <ImageIcon className="h-8 w-8 stroke-1" />
            ) : (
              <Layers className="h-8 w-8 stroke-1" />
            )}
          </div>
        )}
        <button
          type="button"
          onClick={onToggle}
          className="absolute left-1.5 top-1.5 rounded bg-black/65 p-1 text-white/90 backdrop-blur transition-colors hover:bg-accent hover:text-on-accent"
          aria-label={isSelected ? "Deselect item" : "Select item"}
          aria-pressed={isSelected}
        >
          {isSelected ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
        </button>
        <button
          type="button"
          onClick={onToggleBookmark}
          disabled={bookmarkBusy}
          className={`absolute right-1.5 top-1.5 rounded p-1 backdrop-blur transition-colors ${
            isBookmarked
              ? "bg-amber-500/90 text-white"
              : "bg-black/60 text-white/75 hover:bg-amber-500/80 hover:text-white"
          } ${bookmarkBusy ? "opacity-60" : ""}`}
          aria-label={isBookmarked ? "Remove from favorites" : "Save to favorites"}
          aria-pressed={isBookmarked}
        >
          <Bookmark className={`h-3.5 w-3.5 ${isBookmarked ? "fill-current" : ""}`} />
        </button>
        {onSaveLink && (
          <button
            type="button"
            onClick={onSaveLink}
            className={`absolute right-1.5 top-9 rounded p-1 backdrop-blur transition-colors ${
              isLinkSaved
                ? "bg-sky-600/90 text-white"
                : "bg-black/60 text-white/75 hover:bg-sky-600/85 hover:text-white"
            }`}
            aria-label={isLinkSaved ? "Source link saved" : "Save source link"}
            title={isLinkSaved ? "Source link saved" : "Save source link"}
          >
            <Link2 className="h-3.5 w-3.5" />
          </button>
        )}
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[9px] uppercase text-white/85">
          {item.media_type}
          {displayRes ? ` · ${displayRes}` : ""}
          {duration ? ` · ${duration}` : ""}
        </span>
        {(wasDownloaded || isSkipped) && (
          <span
            className={`absolute bottom-1.5 left-1.5 rounded px-1.5 py-0.5 font-mono text-[9px] text-white ${
              isSkipped ? "bg-amber-600/90" : "bg-emerald-600/90"
            }`}
          >
            {isSkipped ? "skipped" : "downloaded"}
          </span>
        )}
      </div>
      <div className="space-y-1 px-2 py-1.5">
        <p className="truncate font-mono text-[10px] text-ink" title={item.title || item.original_url}>
          {variant === "video" ? "" : `#${index + 1} `}
          {item.title || item.extension?.toUpperCase() || `Item ${index + 1}`}
        </p>
        <div className="flex items-center justify-between font-mono text-[10px] text-muted">
          <span className="truncate pr-1">{caption || ""}</span>
          <span className="shrink-0" title={chosenFormat ? "Size for selected quality setting" : undefined}>
            {formatBytes(displaySize)}
          </span>
        </div>
      </div>
    </div>
  );
}
