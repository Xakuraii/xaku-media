import { Loader2, Search } from "lucide-react";
import type { RefObject } from "react";

interface ScanSourceFormProps {
  input: string;
  onInputChange: (value: string) => void;
  inputRef: RefObject<HTMLTextAreaElement>;
  detectedCount: number;
  starting: boolean;
  dragging: boolean;
  onDragStateChange: (dragging: boolean) => void;
  onStart: () => void;
  showOptions: boolean;
  onToggleOptions: () => void;
  maxPosts: string;
  maxMedia: string;
  includeImages: boolean;
  includeVideos: boolean;
  onMaxPostsChange: (value: string) => void;
  onMaxMediaChange: (value: string) => void;
  onIncludeImagesChange: (value: boolean) => void;
  onIncludeVideosChange: (value: boolean) => void;
}

export function ScanSourceForm({
  input,
  onInputChange,
  inputRef,
  detectedCount,
  starting,
  dragging,
  onDragStateChange,
  onStart,
  showOptions,
  onToggleOptions,
  maxPosts,
  maxMedia,
  includeImages,
  includeVideos,
  onMaxPostsChange,
  onMaxMediaChange,
  onIncludeImagesChange,
  onIncludeVideosChange,
}: ScanSourceFormProps) {
  return (
    <div className="space-y-4 rounded-xl border border-hairline bg-surface p-5 shadow-lg">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          onDragStateChange(true);
        }}
        onDragLeave={() => onDragStateChange(false)}
        onDrop={(event) => {
          event.preventDefault();
          onDragStateChange(false);
          const text = event.dataTransfer.getData("text/plain");
          if (text) onInputChange(input ? `${input}\n${text}` : text);
        }}
        className={`relative rounded-lg border ${dragging ? "border-accent bg-accent/5" : "border-hairline bg-page"} transition-colors`}
      >
        <textarea
          ref={inputRef}
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
              event.preventDefault();
              onStart();
            }
          }}
          rows={input.split("\n").length > 2 ? 4 : 3}
          placeholder={
            "https://www.youtube.com/@channel/videos\nhttps://www.youtube.com/playlist?list=...\nhttps://site.example/profile\n\nOne URL per line. Drag and drop links here."
          }
          className="w-full resize-y bg-transparent px-4 py-3 font-mono text-sm text-ink placeholder-faint focus:outline-none"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onStart}
          disabled={starting || !input.trim()}
          className={`flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all ${
            input.trim() && !starting
              ? "cursor-pointer bg-accent text-on-accent shadow-md shadow-accent/25 hover:bg-accent-vivid"
              : "cursor-not-allowed border border-hairline bg-raised text-faint"
          }`}
        >
          {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          <span>{starting ? "Starting…" : "Start scan"}</span>
        </button>
        <button
          type="button"
          onClick={onToggleOptions}
          className="rounded-lg border border-hairline px-3 py-2.5 text-xs font-mono text-ink/80 transition-colors hover:bg-raised"
        >
          {showOptions ? "Hide options" : "Scan options"}
        </button>
        <span className="ml-auto font-mono text-[11px] text-muted">
          {detectedCount} URL{detectedCount === 1 ? "" : "s"} detected
        </span>
      </div>

      {showOptions && (
        <div className="grid gap-3 rounded-lg border border-hairline bg-page p-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="space-y-1 text-[11px] font-mono text-muted">
            <span>Max posts per source</span>
            <input
              type="number"
              min={1}
              value={maxPosts}
              onChange={(event) => onMaxPostsChange(event.target.value)}
              placeholder="No limit"
              className="w-full rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-ink focus:border-accent focus:outline-none"
            />
          </label>
          <label className="space-y-1 text-[11px] font-mono text-muted">
            <span>Max media per source</span>
            <input
              type="number"
              min={1}
              value={maxMedia}
              onChange={(event) => onMaxMediaChange(event.target.value)}
              placeholder="No limit"
              className="w-full rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-ink focus:border-accent focus:outline-none"
            />
          </label>
          <label className="flex items-center gap-2 pt-5 text-xs text-ink/80">
            <input
              type="checkbox"
              checked={includeImages}
              onChange={(event) => onIncludeImagesChange(event.target.checked)}
              className="h-3.5 w-3.5 accent-current"
            />
            <span>Include images</span>
          </label>
          <label className="flex items-center gap-2 pt-5 text-xs text-ink/80">
            <input
              type="checkbox"
              checked={includeVideos}
              onChange={(event) => onIncludeVideosChange(event.target.checked)}
              className="h-3.5 w-3.5 accent-current"
            />
            <span>Include videos</span>
          </label>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-3 text-[11px] text-muted">
        <span>
          Verified: YouTube channels, playlists, and single videos (yt-dlp). Other sites depend on
          gallery-dl coverage and may require session cookies.
        </span>
        <span className="font-mono">SSRF &amp; path guards active</span>
      </div>
    </div>
  );
}
