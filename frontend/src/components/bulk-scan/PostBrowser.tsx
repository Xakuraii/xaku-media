import {
  CheckSquare,
  Download,
  Film,
  FolderOpen,
  Image as ImageIcon,
  Layers,
  Loader2,
  Search,
  Square,
} from "lucide-react";
import type { ScanPost } from "../../../../desktop/shared/types";
import type { MediaFilter } from "./types";
import { formatBytes, hostOf, visibleMedia } from "./utils";

interface PostBrowserProps {
  filteredPosts: ScanPost[];
  counts: { posts: number; media: number; images: number; videos: number; albums: number };
  selected: Set<string>;
  runningCount: number;
  totalProgress: { posts: number; media: number };
  filter: MediaFilter;
  search: string;
  downloading: boolean;
  onFilterChange: (filter: MediaFilter) => void;
  onSearchChange: (value: string) => void;
  onTogglePost: (post: ScanPost) => void;
  onToggleMedia: (itemId: string) => void;
  onSelectVisible: () => void;
  onSelectByType: (type: "image" | "video") => void;
  onSelectAlbums: () => void;
  onInvertSelection: () => void;
  onClearSelection: () => void;
  onDownload: () => void;
}

export function PostBrowser({
  filteredPosts,
  counts,
  selected,
  runningCount,
  totalProgress,
  filter,
  search,
  downloading,
  onFilterChange,
  onSearchChange,
  onTogglePost,
  onToggleMedia,
  onSelectVisible,
  onSelectByType,
  onSelectAlbums,
  onInvertSelection,
  onClearSelection,
  onDownload,
}: PostBrowserProps) {
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
        </div>
        <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
          <button type="button" onClick={onSelectVisible} className="text-ink/80 hover:text-accent">
            Select view
          </button>
          <span className="text-hairline">|</span>
          <button type="button" onClick={() => onSelectByType("image")} className="text-ink/80 hover:text-accent">
            Images
          </button>
          <button type="button" onClick={() => onSelectByType("video")} className="text-ink/80 hover:text-accent">
            Videos
          </button>
          <button type="button" onClick={onSelectAlbums} className="text-ink/80 hover:text-accent">
            Albums
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
            · {counts.posts} posts · {counts.media} media
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
          {downloading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          <span>{downloading ? "Queueing…" : `Download selected (${selected.size})`}</span>
        </button>
      </div>

      {filteredPosts.length === 0 && runningCount === 0 ? (
        <div className="rounded-xl border border-hairline bg-surface py-16 text-center">
          <FolderOpen className="mx-auto h-8 w-8 stroke-1 text-muted" />
          <p className="mt-2 text-xs text-muted">No posts match this filter yet.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredPosts.map((post) => {
            const media = visibleMedia(post, filter);
            const allSelected =
              post.media_items.length > 0 &&
              post.media_items.every((item) => selected.has(item.id));
            const someSelected = post.media_items.some((item) => selected.has(item.id));
            return (
              <div
                key={post.id}
                className="overflow-hidden rounded-xl border border-hairline bg-surface shadow-sm"
              >
                <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-4 py-3">
                  <button
                    type="button"
                    onClick={() => onTogglePost(post)}
                    className="text-ink/70 transition-colors hover:text-accent"
                    aria-label={allSelected ? "Deselect post" : "Select post"}
                  >
                    {allSelected ? (
                      <CheckSquare className="h-4 w-4 text-accent" />
                    ) : someSelected ? (
                      <CheckSquare className="h-4 w-4 text-muted" />
                    ) : (
                      <Square className="h-4 w-4" />
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {post.title || post.media_items[0]?.title || "Untitled post"}
                    </p>
                    <p className="truncate font-mono text-[11px] text-muted">
                      {post.author} · {post.provider}
                      {post.post_url ? ` · ${hostOf(post.post_url)}` : ""}
                    </p>
                  </div>
                  <span className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[10px] uppercase text-muted">
                    {post.post_type}
                  </span>
                  <span className="font-mono text-[11px] text-muted">
                    {post.media_items.length} item{post.media_items.length === 1 ? "" : "s"}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-4">
                  {media.map((item, index) => {
                    const isSelected = selected.has(item.id);
                    return (
                      <div
                        key={item.id}
                        className={`group overflow-hidden rounded-lg border bg-page transition-colors ${
                          isSelected ? "border-accent ring-1 ring-accent/40" : "border-hairline"
                        }`}
                      >
                        <div className="relative aspect-[4/3] bg-raised">
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
                            onClick={() => onToggleMedia(item.id)}
                            className="absolute left-1.5 top-1.5 rounded bg-black/65 p-1 text-white/90 backdrop-blur transition-colors hover:bg-accent hover:text-on-accent"
                            aria-label={isSelected ? "Deselect item" : "Select item"}
                          >
                            {isSelected ? (
                              <CheckSquare className="h-3.5 w-3.5" />
                            ) : (
                              <Square className="h-3.5 w-3.5" />
                            )}
                          </button>
                          <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[9px] uppercase text-white/85">
                            {item.media_type}
                          </span>
                          <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[9px] text-white/70">
                            #{index + 1}
                          </span>
                        </div>
                        <div className="space-y-1 px-2.5 py-2">
                          <p
                            className="truncate font-mono text-[11px] text-ink"
                            title={item.title || item.original_url}
                          >
                            {item.title || item.extension?.toUpperCase() || `Item ${index + 1}`}
                          </p>
                          <div className="flex items-center justify-between font-mono text-[10px] text-muted">
                            <span>{formatBytes(item.filesize_bytes)}</span>
                            <span className="truncate pl-2">
                              {item.extension || item.mime_type?.split("/")[1] || ""}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
