import {
  CheckSquare,
  Download,
  Film,
  Image as ImageIcon,
  Layers,
  Loader2,
  Search,
  Square,
  Sparkles,
} from "lucide-react";
import type { DiscoveredMediaItem } from "../../../../desktop/shared/types";
import { isItemDownloaded, type MediaFilter, type PostWithScan } from "./types";
import { chooseFormat, formatBytes, visibleMedia } from "./utils";

interface PostBrowserProps {
  filteredPosts: PostWithScan[];
  counts: { posts: number; media: number; images: number; videos: number; albums: number };
  selected: Set<string>;
  downloaded: Set<string>;
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
  onSelectAllVisible: () => void;
  onSelectOnlyNew: () => void;
  onSelectByType: (type: "image" | "video") => void;
  onInvertSelection: () => void;
  onClearSelection: () => void;
  onDownload: () => void;
}

export function PostBrowser({
  filteredPosts,
  counts,
  selected,
  downloaded,
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
  onSelectAllVisible,
  onSelectOnlyNew,
  onSelectByType,
  onInvertSelection,
  onClearSelection,
  onDownload,
}: PostBrowserProps) {
  const visibleItems = filteredPosts.flatMap((post) => visibleMedia(post, filter));
  const newCount = visibleItems.filter((item) => !isItemDownloaded(item, downloaded)).length;

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

      {visibleItems.length === 0 && runningCount === 0 ? (
        <div className="rounded-xl border border-hairline bg-surface py-16 text-center">
          <Layers className="mx-auto h-8 w-8 stroke-1 text-muted" />
          <p className="mt-2 text-xs text-muted">No media match this view yet.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {visibleItems.map((item, index) => {
            const isSelected = selected.has(item.id);
            const wasDownloaded = isItemDownloaded(item, downloaded);
            const chosen = chooseFormat(item, preferredResolution);
            return (
              <MediaCard
                key={item.id}
                item={item}
                index={index}
                isSelected={isSelected}
                wasDownloaded={wasDownloaded}
                chosenFormat={chosen}
                onToggle={() => onToggleMedia(item.id)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function MediaCard({
  item,
  index,
  isSelected,
  wasDownloaded,
  chosenFormat,
  onToggle,
}: {
  item: DiscoveredMediaItem;
  index: number;
  isSelected: boolean;
  wasDownloaded: boolean;
  chosenFormat: ReturnType<typeof chooseFormat>;
  onToggle: () => void;
}) {
  const displaySize = chosenFormat?.filesize_bytes ?? item.filesize_bytes;
  const displayRes = chosenFormat?.resolution || null;
  return (
    <div
      className={`group overflow-hidden rounded-lg border bg-surface transition-colors ${
        isSelected ? "border-accent ring-1 ring-accent/40" : "border-hairline"
      }`}
    >
      <div className="relative aspect-square bg-raised">
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
        >
          {isSelected ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
        </button>
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[9px] uppercase text-white/85">
          {item.media_type}{displayRes ? ` · ${displayRes}` : ""}
        </span>
        <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[9px] text-white/70">
          #{index + 1}
        </span>
        {wasDownloaded && (
          <span className="absolute bottom-1.5 left-1.5 rounded bg-emerald-600/90 px-1.5 py-0.5 font-mono text-[9px] text-white">
            downloaded
          </span>
        )}
      </div>
      <div className="space-y-1 px-2 py-1.5">
        <p className="truncate font-mono text-[10px] text-ink" title={item.title || item.original_url}>
          {item.title || item.extension?.toUpperCase() || `Item ${index + 1}`}
        </p>
        <div className="flex items-center justify-between font-mono text-[10px] text-muted">
          <span title={chosenFormat ? "Size for selected quality setting" : undefined}>
            {formatBytes(displaySize)}
          </span>
          <span className="truncate pl-1">
            {chosenFormat?.container || item.extension || item.mime_type?.split("/")[1] || ""}
          </span>
        </div>
      </div>
    </div>
  );
}
