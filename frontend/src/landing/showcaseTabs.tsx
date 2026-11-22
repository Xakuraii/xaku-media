import React from "react";
import {
  Bookmark,
  Check,
  CheckSquare,
  ChevronRight,
  Clock,
  Cookie,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Film,
  Folder,
  FolderOpen,
  Gauge,
  Globe,
  HardDrive,
  History,
  Image as ImageIcon,
  Layers,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
} from "lucide-react";

export type ShowcaseTabId = "scan" | "library" | "downloads" | "saved" | "history" | "settings";

export interface ShowcaseTabMeta {
  id: ShowcaseTabId;
  group: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}

export const SHOWCASE_TABS: ShowcaseTabMeta[] = [
  { id: "scan", group: "Workspace", label: "Scan Media", icon: Search },
  { id: "library", group: "Workspace", label: "Download Library", icon: HardDrive },
  { id: "downloads", group: "Workspace", label: "Downloads", icon: Download, badge: "2" },
  { id: "saved", group: "Sources", label: "Saved Sources", icon: Bookmark },
  { id: "history", group: "Sources", label: "Scan History", icon: History },
  { id: "settings", group: "System", label: "Settings", icon: Settings },
];

const CARD_WASH = [
  "from-accent/20 via-band to-surface",
  "from-band via-accent/15 to-raised",
  "from-raised via-band to-accent/15",
  "from-accent/15 via-raised to-band",
];

const VIDEO_MOCKS = [
  {
    title: "Tokyo night walk",
    spec: "1080P · 0:24",
    size: "4.8 MB",
    selected: true,
    avatar: true,
    status: null as "downloaded" | "skipped" | null,
  },
  {
    title: "Studio timelapse",
    spec: "1080P · 0:18",
    size: "3.1 MB",
    selected: true,
    avatar: false,
    status: null as "downloaded" | "skipped" | null,
  },
  {
    title: "Intro teaser",
    spec: "720P · 0:12",
    size: "1.9 MB",
    selected: false,
    avatar: false,
    status: "downloaded" as "downloaded" | "skipped" | null,
  },
  {
    title: "Draft clip #04",
    spec: "1080P · 0:15",
    size: "2.4 MB",
    selected: false,
    avatar: false,
    status: "skipped" as "downloaded" | "skipped" | null,
  },
];

export const ShowcaseTabContent: React.FC<{ tab: ShowcaseTabId }> = ({ tab }) => {
  if (tab === "scan") {
    return (
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-ink">Scan Sources</h2>
            <p className="text-[11px] text-muted">
              Paste a profile, channel, playlist, gallery, or direct media URL. Results appear as a
              gallery grid you can select and download in bulk.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 font-mono text-[9px] text-muted">
            <span className="rounded-full border border-hairline bg-surface px-2 py-0.5">
              2 folders
            </span>
            <span className="rounded-full border border-hairline bg-surface px-2 py-0.5">
              118 images
            </span>
            <span className="rounded-full border border-hairline bg-surface px-2 py-0.5">
              6 videos
            </span>
            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-300">
              5 skipped
            </span>
            <span className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface px-2 py-0.5">
              <RefreshCw className="h-2.5 w-2.5" />
              Refresh
            </span>
          </div>
        </div>

        {/* ScanSourceForm match */}
        <div className="space-y-2.5 rounded-xl border border-hairline bg-surface p-3.5 shadow-sm">
          <div className="rounded-lg border border-hairline bg-page px-3 py-2 font-mono text-[11px] text-ink">
            https://www.tiktok.com/@xakuraii
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-1.5 text-[11px] font-medium text-on-accent shadow-sm shadow-accent/25">
              <Search className="h-3 w-3" />
              Start scan
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline px-2.5 py-1.5 font-mono text-[10px] text-ink/80">
              <Bookmark className="h-3 w-3" />
              Bookmark link
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline px-2.5 py-1.5 font-mono text-[10px] text-muted">
              <SlidersHorizontal className="h-3 w-3" />
              Scan options
            </span>
            <span className="ml-auto font-mono text-[10px] text-muted">1 URL detected</span>
          </div>
        </div>

        {/* JobStatusList match */}
        <div className="space-y-1.5">
          <span className="font-mono text-[9px] uppercase tracking-wide text-muted">Scans</span>
          <div className="space-y-1.5 rounded-lg border border-hairline bg-surface px-3 py-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-mono text-[8px] uppercase text-emerald-700 dark:text-emerald-300">
                completed
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-ink/85">
                tiktok.com
                <span className="ml-1.5 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[8px] text-emerald-700 dark:text-emerald-300">
                  cookies saved
                </span>
              </span>
              <span className="font-mono text-[9px] text-muted">33 posts · 39 media</span>
              <span className="inline-flex items-center gap-1 rounded border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[9px] text-accent">
                <Check className="h-2.5 w-2.5" />
                Saved
              </span>
              <span className="inline-flex items-center gap-1 rounded border border-hairline px-1.5 py-0.5 font-mono text-[9px] text-ink/80">
                <Eye className="h-2.5 w-2.5" />
                Show only
              </span>
              <span className="inline-flex items-center gap-1 rounded border border-red-500/30 px-1.5 py-0.5 font-mono text-[9px] text-red-700 dark:text-red-300">
                <Trash2 className="h-2.5 w-2.5" />
                Delete
              </span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-raised">
              <div className="h-full w-full rounded-full bg-emerald-500" />
            </div>
          </div>
        </div>

        {/* Filter & batch bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-hairline bg-surface px-3 py-2">
          <div className="flex flex-wrap items-center gap-1">
            <span className="rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 font-mono text-[9px] text-accent">
              All 39
            </span>
            <span className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[9px] text-muted">
              Images 32
            </span>
            <span className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[9px] text-muted">
              Videos 7
            </span>
            <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-[9px] text-amber-700 dark:text-amber-300">
              <EyeOff className="mr-1 inline h-2.5 w-2.5" />
              Skipped 5
            </span>
          </div>
          <div className="flex items-center gap-2 font-mono text-[9px]">
            <span className="text-ink/80">Select all</span>
            <span className="inline-flex items-center gap-1 text-accent">
              <Sparkles className="h-2.5 w-2.5" />
              Select new (28)
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent/25 bg-accent/5 px-3 py-2">
          <span className="font-mono text-[10px] text-ink/85">
            <span className="font-semibold text-accent">2</span> selected · 33 posts · 39 media
          </span>
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[10px] font-medium text-amber-700 dark:text-amber-300">
              <EyeOff className="h-3 w-3" />
              Skip selected (2)
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-[10px] font-medium text-on-accent shadow-sm shadow-accent/25">
              <Download className="h-3 w-3" />
              Download selected (2)
            </span>
          </div>
        </div>

        {/* Shared Videos shelf */}
        <section className="overflow-hidden rounded-xl border border-hairline bg-surface">
          <div className="flex items-center gap-2 border-b border-hairline px-3 py-1.5">
            <Film className="h-3.5 w-3.5 text-accent" />
            <span className="text-[11px] font-semibold text-ink">Videos</span>
            <span className="font-mono text-[9px] text-muted">· 7 videos in one grid</span>
          </div>
          <div className="grid grid-cols-2 gap-2.5 p-2.5 sm:grid-cols-4">
            {VIDEO_MOCKS.map((vid, idx) => (
              <div
                key={vid.title}
                className={`overflow-hidden rounded-lg border bg-surface ${
                  vid.selected ? "border-accent ring-1 ring-accent/40" : "border-hairline"
                }`}
              >
                <div
                  className={`relative aspect-video bg-gradient-to-br ${CARD_WASH[idx % CARD_WASH.length]}`}
                >
                  <span className="absolute inset-0 grid place-items-center text-accent/65">
                    <Film className="h-5 w-5" />
                  </span>
                  <span
                    className={`absolute left-1 top-1 rounded p-0.5 ${
                      vid.selected
                        ? "bg-accent text-on-accent"
                        : "bg-black/60 text-white/85"
                    }`}
                  >
                    {vid.selected ? (
                      <CheckSquare className="h-3 w-3" />
                    ) : (
                      <Square className="h-3 w-3" />
                    )}
                  </span>
                  <span
                    className={`absolute right-1 top-1 rounded p-0.5 ${
                      vid.avatar ? "bg-accent text-on-accent" : "bg-black/60 text-white/80"
                    }`}
                  >
                    <Bookmark className={`h-3 w-3 ${vid.avatar ? "fill-current" : ""}`} />
                  </span>
                  {vid.status && (
                    <span
                      className={`absolute bottom-1 left-1 rounded px-1 py-0.5 font-mono text-[8px] text-white ${
                        vid.status === "skipped" ? "bg-amber-600/90" : "bg-emerald-600/90"
                      }`}
                    >
                      {vid.status}
                    </span>
                  )}
                  <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 py-0.5 font-mono text-[8px] text-white">
                    {vid.spec}
                  </span>
                </div>
                <div className="px-2 py-1">
                  <p className="truncate font-mono text-[9px] text-ink">{vid.title}</p>
                  <p className="flex justify-between font-mono text-[8px] text-muted">
                    <span>@xakuraii</span>
                    <span>{vid.size}</span>
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    );
  }

  if (tab === "library") {
    return (
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent">
              <HardDrive className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Download Library</h2>
              <p className="font-mono text-[10px] text-muted">
                Folders detected from <span className="text-ink/85">xakumedia-library.json</span> in{" "}
                <span className="text-ink/85">D:\Downloads</span>
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 font-mono text-[9px] text-muted">
            <span className="rounded-full border border-hairline bg-surface px-2 py-0.5">
              124 files
            </span>
            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-300">
              5 skipped
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2 py-1 text-ink/80">
              <FolderOpen className="h-3 w-3" />
              Open Folder
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2 py-1 text-ink/80">
              <RefreshCw className="h-3 w-3" />
              Refresh
            </span>
          </div>
        </div>

        {/* Breadcrumb */}
        <div className="flex items-center justify-between rounded-xl border border-hairline bg-surface px-3 py-2 font-mono text-[10px]">
          <div className="flex items-center gap-1">
            <span className="text-muted">Library</span>
            <ChevronRight className="h-3 w-3 text-faint" />
            <span className="text-muted">Tiktok</span>
            <ChevronRight className="h-3 w-3 text-faint" />
            <span className="rounded bg-accent/10 px-1.5 py-0.5 font-semibold text-accent">
              xakuraii
            </span>
          </div>
          <span className="font-mono text-[9px] text-faint">All · Downloaded · Skipped</span>
        </div>

        {/* Child Subfolder Containers */}
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          {[
            { name: "Images/", meta: "93 files", icon: ImageIcon },
            { name: "Videos/", meta: "6 files · 4 skipped", icon: Film },
            { name: "xakumedia-library.json", meta: "cross-device manifest", icon: Folder },
          ].map((sub) => {
            const Icon = sub.icon;
            return (
              <div
                key={sub.name}
                className="flex items-center justify-between rounded-xl border border-hairline bg-surface p-3"
              >
                <div className="flex items-center gap-2.5">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-hairline bg-raised text-accent">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-xs font-bold text-ink">{sub.name}</p>
                    <p className="font-mono text-[9px] text-muted">{sub.meta}</p>
                  </div>
                </div>
                <ChevronRight className="h-3.5 w-3.5 text-faint" />
              </div>
            );
          })}
        </div>

        {/* Files & Skipped items inside folder */}
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {[
            { name: "xakuraii-vdo-1.mp4", kind: "mp4", size: "18.4 MB", skipped: false },
            { name: "xakuraii-img-1.jpeg", kind: "jpeg", size: "640 KB", skipped: false },
            { name: "xakuraii-img-2.jpeg", kind: "jpeg", size: "820 KB", skipped: false },
            { name: "Skipped reel #09", kind: "skipped", size: "Manifest", skipped: true },
          ].map((entry, idx) => (
            <div
              key={entry.name}
              className={`overflow-hidden rounded-xl border bg-surface ${
                entry.skipped ? "border-amber-500/35 bg-amber-500/[0.03]" : "border-hairline"
              }`}
            >
              <div
                className={`relative aspect-video bg-gradient-to-br ${CARD_WASH[idx % CARD_WASH.length]}`}
              >
                <span className="absolute inset-0 grid place-items-center text-muted">
                  {entry.skipped ? (
                    <EyeOff className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  ) : entry.kind === "mp4" ? (
                    <Play className="h-5 w-5 text-accent" />
                  ) : (
                    <ImageIcon className="h-5 w-5 text-accent/70" />
                  )}
                </span>
                <span
                  className={`absolute left-1.5 top-1.5 rounded px-1 py-0.5 font-mono text-[8px] font-bold uppercase text-white ${
                    entry.skipped ? "bg-amber-600/90" : "bg-black/75"
                  }`}
                >
                  {entry.kind}
                </span>
                <span className="absolute bottom-1.5 right-1.5 rounded bg-black/75 px-1 py-0.5 font-mono text-[8px] text-white/90">
                  {entry.size}
                </span>
              </div>
              <div className="flex items-center justify-between px-2 py-1.5 font-mono text-[9px]">
                <span className="truncate font-semibold text-ink">{entry.name}</span>
                {entry.skipped ? (
                  <span className="inline-flex items-center gap-0.5 rounded border border-hairline bg-raised px-1.5 py-0.5 text-[8px] text-ink">
                    <RotateCcw className="h-2.5 w-2.5" />
                    Unskip
                  </span>
                ) : (
                  <span className="text-muted">View</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (tab === "downloads") {
    return (
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-ink">Download Manager</h2>
            <p className="text-[11px] text-muted">
              Concurrent streams with gap-free <span className="font-mono">user-vdo-N</span> naming
              and lossless FFmpeg merging.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 font-mono text-[9px]">
            <span className="rounded-lg border border-hairline bg-surface px-2 py-1 text-ink/80">
              Slots: 4
            </span>
            <span className="rounded-lg border border-hairline bg-surface px-2 py-1 text-ink/80">
              <Gauge className="mr-1 inline h-3 w-3 text-accent" />
              Unlimited
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2 py-1 text-ink/80">
              <Pause className="h-3 w-3" />
              Pause All
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2 py-1 text-ink/80">
              <RefreshCw className="h-3 w-3" />
              Refresh
            </span>
          </div>
        </div>

        <div className="space-y-2.5">
          <div className="space-y-2 rounded-xl border border-accent/30 bg-surface p-3.5">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-xs font-semibold text-ink">
                  xakuraii-vdo-5.mp4 · Studio session
                </p>
                <p className="font-mono text-[9px] text-muted">
                  D:\Downloads\Tiktok\xakuraii\Videos\xakuraii-vdo-5.mp4
                </p>
              </div>
              <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[9px] text-accent">
                1080p MP4 · 68%
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-raised">
              <div className="h-full w-2/3 rounded-full bg-accent" />
            </div>
            <div className="flex justify-between font-mono text-[9px] text-muted">
              <span>12.4 MB / 18.2 MB</span>
              <span>8.6 MB/s · ETA 0m 02s</span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 rounded-xl border border-purple-500/30 bg-surface p-3">
            <div>
              <p className="text-xs font-semibold text-ink">xakuraii-vdo-4.mp4 · City highlights</p>
              <p className="font-mono text-[9px] text-muted">
                FFmpeg lossless container muxing (video + AAC audio)
              </p>
            </div>
            <span className="rounded-full border border-purple-500/30 bg-purple-500/10 px-2.5 py-0.5 font-mono text-[9px] text-purple-700 dark:text-purple-300">
              merging
            </span>
          </div>

          <div className="flex items-center justify-between gap-2 rounded-xl border border-emerald-500/25 bg-surface p-3">
            <div>
              <p className="text-xs font-semibold text-ink">xakuraii-img-1.jpeg</p>
              <p className="font-mono text-[9px] text-muted">
                Saved to Tiktok/xakuraii/Images/ · manifest updated
              </p>
            </div>
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 font-mono text-[9px] text-emerald-700 dark:text-emerald-300">
              completed
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (tab === "saved") {
    return (
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent">
              <Bookmark className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold tracking-tight text-ink">Saved Sources</h2>
                <span className="rounded-full border border-hairline bg-raised px-2 py-0.5 font-mono text-[9px] text-accent">
                  3 Sources
                </span>
              </div>
              <p className="text-[11px] text-muted">
                Bookmark channels and galleries with creator PFPs for 1-click delta rescans.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[9px]">
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2.5 py-1.5 text-ink/80">
              <RefreshCw className="h-3 w-3" />
              Refresh
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2.5 py-1.5 text-ink/80">
              <RefreshCw className="h-3 w-3" />
              Rescan All
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 font-semibold text-on-accent">
              <Plus className="h-3 w-3" />
              Add Source
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            {
              platform: "Tiktok",
              title: "@xakuraii",
              handle: "@xakuraii",
              url: "https://www.tiktok.com/@xakuraii",
              items: "42 items",
              initials: "XA",
            },
            {
              platform: "Instagram",
              title: "@nasa",
              handle: "@nasa",
              url: "https://www.instagram.com/nasa/",
              items: "18 items",
              initials: "NA",
            },
            {
              platform: "Youtube",
              title: "@YouTube",
              handle: "@YouTube",
              url: "https://www.youtube.com/@YouTube",
              items: "12 items",
              initials: "YT",
            },
          ].map((src, idx) => (
            <div
              key={src.title}
              className="flex flex-col justify-between space-y-3 rounded-2xl border border-hairline bg-surface p-3.5 shadow-sm"
            >
              <div className="flex items-center justify-between font-mono text-[9px]">
                <span className="rounded bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-300">
                  {src.platform}
                </span>
                <span className="text-faint">Collection</span>
              </div>
              <div className="flex items-center gap-2.5">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-accent/30 bg-gradient-to-br ${CARD_WASH[idx % CARD_WASH.length]} font-mono text-[11px] font-bold text-accent`}
                >
                  {src.initials}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-xs font-bold text-ink">{src.title}</p>
                  <p className="truncate font-mono text-[9px] text-muted">{src.handle}</p>
                </div>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-hairline bg-page px-2 py-1 font-mono text-[9px] text-muted">
                <span className="truncate">{src.url}</span>
                <ExternalLink className="h-2.5 w-2.5 shrink-0 text-accent" />
              </div>
              <div className="flex items-center justify-between font-mono text-[9px] text-muted">
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-2.5 w-2.5" />
                  Today
                </span>
                <span className="font-semibold text-accent">{src.items}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="flex-1 rounded-lg border border-accent/30 bg-accent/10 py-1 text-center font-mono text-[9px] font-semibold text-accent">
                  Rescan Now
                </span>
                <span className="rounded-lg border border-hairline p-1 text-muted">
                  <Trash2 className="h-3 w-3" />
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (tab === "history") {
    return (
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-ink">Scan History</h2>
            <p className="text-[11px] text-muted">
              Local SQLite audit log of scanned profiles, galleries, and discovered media counts.
            </p>
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[9px]">
            <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-surface px-2.5 py-1 text-ink/80">
              <RefreshCw className="h-3 w-3" />
              Refresh
            </span>
            <span className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-red-700 dark:text-red-300">
              <Trash2 className="h-3 w-3" />
              Clear History
            </span>
          </div>
        </div>

        <div className="space-y-2">
          {[
            {
              url: "https://www.tiktok.com/@xakuraii",
              provider: "ytdlp · tiktok",
              counts: "33 posts · 39 media",
              time: "Just now",
            },
            {
              url: "https://www.facebook.com/zerm.mer",
              provider: "gallerydl · facebook",
              counts: "14 posts · 14 media",
              time: "Today, 9:12 PM",
            },
            {
              url: "https://www.youtube.com/@YouTube/videos",
              provider: "ytdlp · youtube",
              counts: "12 videos",
              time: "Today, 8:40 PM",
            },
          ].map((entry) => (
            <div
              key={entry.url}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-hairline bg-surface px-3.5 py-2.5"
            >
              <div className="min-w-0 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 font-mono text-[8px] uppercase text-emerald-700 dark:text-emerald-300">
                    completed
                  </span>
                  <span className="truncate font-mono text-[11px] font-medium text-ink">
                    {entry.url}
                  </span>
                </div>
                <p className="font-mono text-[9px] text-muted">
                  {entry.provider} · {entry.counts} · {entry.time}
                </p>
              </div>
              <span className="inline-flex items-center gap-1 rounded-lg border border-hairline bg-raised px-2.5 py-1 font-mono text-[9px] text-ink/85">
                <RefreshCw className="h-2.5 w-2.5" />
                Rescan
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">Settings &amp; Preferences</h2>
          <p className="text-[11px] text-muted">
            Download folders, short-edge video quality, image format, and cookie profiles.
          </p>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-[9px]">
          <span className="rounded-lg border border-hairline bg-surface px-2.5 py-1.5 text-muted">
            Reset Defaults
          </span>
          <span className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 font-semibold text-on-accent">
            <Check className="h-3 w-3" />
            Save Preferences
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-2 rounded-xl border border-hairline bg-surface p-3.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-ink">
            <Folder className="h-3.5 w-3.5 text-accent" />
            Download Location
          </div>
          <div className="rounded-lg border border-hairline bg-page px-2.5 py-1.5 font-mono text-[10px] text-ink">
            D:\Downloads
          </div>
          <p className="font-mono text-[9px] text-muted">
            Organizes files into Platform / Creator / Videos &amp; Images with{" "}
            <span className="text-ink/85">xakumedia-library.json</span>
          </p>
        </div>

        <div className="space-y-2 rounded-xl border border-hairline bg-surface p-3.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-ink">
            <Film className="h-3.5 w-3.5 text-accent" />
            Video &amp; Image Quality
          </div>
          <div className="grid grid-cols-3 gap-1.5 font-mono text-[9px]">
            <div className="rounded-lg border border-accent/40 bg-accent/10 px-2 py-1 text-center font-semibold text-accent">
              1080p HD
            </div>
            <div className="rounded-lg border border-hairline bg-page px-2 py-1 text-center text-ink">
              MP4 Container
            </div>
            <div className="rounded-lg border border-hairline bg-page px-2 py-1 text-center text-ink">
              Original Img
            </div>
          </div>
          <p className="font-mono text-[9px] text-muted">
            Portrait Reels/TikToks (1080×1920) match short-edge quality automatically.
          </p>
        </div>

        <div className="space-y-2 rounded-xl border border-hairline bg-surface p-3.5 sm:col-span-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold text-ink">
              <Cookie className="h-3.5 w-3.5 text-accent" />
              Session Credentials &amp; Cookies
            </div>
            <span className="inline-flex items-center gap-1 rounded border border-hairline px-2 py-0.5 font-mono text-[9px] text-muted">
              <RefreshCw className="h-2.5 w-2.5" />
              Refresh
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2 font-mono text-[9px]">
            <span className="inline-flex items-center gap-1 rounded-md border border-hairline bg-page px-2 py-1 text-ink">
              <Globe className="h-3 w-3 text-accent" />
              CHROME
            </span>
            <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-700 dark:text-emerald-300">
              tiktok.com · 35 cookies
            </span>
            <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-700 dark:text-emerald-300">
              instagram.com · 18 cookies
            </span>
            <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-700 dark:text-emerald-300">
              facebook.com · 24 cookies
            </span>
            <span className="ml-auto inline-flex items-center gap-1 text-muted">
              <Layers className="h-3 w-3" />
              Local-only storage
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
