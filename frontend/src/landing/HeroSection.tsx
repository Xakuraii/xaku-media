import React, { useState, useEffect } from "react";
import {
  Bookmark,
  Check,
  Download,
  ExternalLink,
  Film,
  History,
  Image as ImageIcon,
  LayoutGrid,
  Library,
  Maximize2,
  Minus,
  Package,
  Search,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import {
  RELEASE_CONFIG,
  checkGitHubReleaseStatus,
  GitHubReleaseStatus,
} from "./downloadConfig";

interface MockMediaItem {
  name: string;
  kind: "image" | "video";
  spec: string;
  selected: boolean;
  downloaded?: boolean;
}

/** Illustrative contents of the desktop app's bulk-scan gallery. */
const MOCK_MEDIA: MockMediaItem[] = [
  { name: "pin_4821.jpg", kind: "image", spec: "1080 × 1350 · JPG", selected: true },
  { name: "pin_4822.jpg", kind: "image", spec: "1080 × 1350 · JPG", selected: true },
  { name: "reel_118.mp4", kind: "video", spec: "1080p · H.264", selected: true },
  {
    name: "pin_4818.jpg",
    kind: "image",
    spec: "Original · JPG",
    selected: false,
    downloaded: true,
  },
  {
    name: "reel_104.mp4",
    kind: "video",
    spec: "720p · H.264",
    selected: false,
    downloaded: true,
  },
  { name: "pin_4823.jpg", kind: "image", spec: "1080 × 1350 · JPG", selected: true },
  { name: "pin_4824.jpg", kind: "image", spec: "1080 × 1350 · JPG", selected: false },
  { name: "clip_07.mp4", kind: "video", spec: "480p · H.264", selected: false },
];

interface SidebarItem {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  active?: boolean;
  badge?: string;
}

const SIDEBAR_GROUPS: Array<{ label: string; items: SidebarItem[] }> = [
  {
    label: "Workspace",
    items: [
      { label: "Scan", icon: Search, active: true },
      { label: "Library", icon: Library },
      { label: "Downloads", icon: Download, badge: "3" },
      { label: "History", icon: History },
    ],
  },
  {
    label: "Sources",
    items: [{ label: "Bookmarks", icon: Bookmark }],
  },
  {
    label: "System",
    items: [{ label: "Settings", icon: Settings }],
  },
];

const CARD_WASH = [
  "from-accent/15 via-band to-band",
  "from-band via-accent/10 to-band",
  "from-band to-accent/15",
  "from-accent/10 via-band to-raised",
  "from-band via-band to-accent/10",
  "from-accent/15 to-band",
  "from-band to-raised",
  "from-raised via-accent/10 to-band",
];

export const HeroSection: React.FC = () => {
  const [releaseStatus, setReleaseStatus] = useState<GitHubReleaseStatus>({
    isChecking: true,
    isPublished: false,
    assetsAvailable: false,
  });

  useEffect(() => {
    checkGitHubReleaseStatus().then((status) => {
      setReleaseStatus(status);
    });
  }, []);

  return (
    <section id="download" className="relative overflow-hidden">
      <div className="lc-container pt-14 pb-20 sm:pt-20 sm:pb-24">
        {/* Intro block */}
        <div className="max-w-3xl">
          {/* Version line */}
          <p className="flex items-center gap-2.5 font-mono text-xs text-faint">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent" />
            <span>
              {RELEASE_CONFIG.latestTag} · released {RELEASE_CONFIG.releaseDate}
            </span>
          </p>

          {/* Headline */}
          <h1 className="mt-6 font-display text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.06] text-ink text-balance">
            Bulk media downloading, made effortless.
          </h1>

          {/* Subtitle */}
          <p className="mt-6 text-base sm:text-lg text-muted leading-relaxed max-w-xl">
            A local-first Windows desktop app to scan profiles, channels, galleries, and
            direct links into one selectable gallery — then batch-download with
            quality-aware merging. No accounts, no cloud tracking, no subscriptions.
          </p>

          {/* Download actions */}
          <div className="mt-9 flex flex-col sm:flex-row sm:items-center gap-3">
            {releaseStatus.isPublished || releaseStatus.assetsAvailable ? (
              <>
                {/* Primary installer */}
                <a href={RELEASE_CONFIG.installer.downloadUrl} className="btn-accent w-full sm:w-auto">
                  <Download className="w-4 h-4" />
                  <span>Download for Windows</span>
                  <span className="font-mono font-normal text-xs opacity-75">
                    {RELEASE_CONFIG.installer.sizeFormatted}
                  </span>
                </a>

                {/* Secondary portable */}
                <a href={RELEASE_CONFIG.portable.downloadUrl} className="btn-ghost w-full sm:w-auto">
                  <Package className="w-4 h-4 text-muted" />
                  <span>Portable .exe</span>
                  <span className="font-mono font-normal text-xs text-faint">
                    {RELEASE_CONFIG.portable.sizeFormatted}
                  </span>
                </a>
              </>
            ) : (
              <a
                href={RELEASE_CONFIG.releasesUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-accent w-full sm:w-auto"
              >
                <Download className="w-4 h-4" />
                <span>Get {RELEASE_CONFIG.latestTag} on GitHub</span>
                <ExternalLink className="w-3.5 h-3.5 opacity-80" />
              </a>
            )}
          </div>

          {/* Trust row */}
          <ul className="mt-7 flex flex-wrap gap-x-5 gap-y-2 font-mono text-xs text-faint">
            <li>Windows 10 / 11 · 64-bit</li>
            <li>Python &amp; FFmpeg bundled</li>
            <li>100% local storage</li>
            <li>
              <a
                href="#installation"
                className="underline underline-offset-2 hover:text-accent transition-colors duration-150"
              >
                SmartScreen guide
              </a>
            </li>
          </ul>
        </div>

        {/* Desktop app window showcase (illustrative preview of the current shell) */}
        <div className="mt-14 sm:mt-16">
          <div className="rounded-2xl border border-hairline bg-surface shadow-pop overflow-hidden">
            {/* Titlebar */}
            <div className="flex items-center justify-between pl-4 pr-3 h-11 bg-band border-b border-hairline">
              <div className="flex items-center gap-2 min-w-0">
                <span className="grid place-items-center w-4 h-4 rounded-sm bg-brand-white">
                  <img src="XakuMedia.svg" alt="" className="w-full h-full" />
                </span>
                <span className="text-xs font-medium text-muted truncate">
                  XakuMedia — Local Media Toolkit
                </span>
              </div>
              <div className="flex items-center text-faint">
                <span className="grid place-items-center w-8 h-8 rounded-md hover:bg-raised transition-colors">
                  <Minus className="w-3 h-3" />
                </span>
                <span className="grid place-items-center w-8 h-8 rounded-md hover:bg-raised transition-colors">
                  <Maximize2 className="w-3 h-3" />
                </span>
                <span className="grid place-items-center w-8 h-8 rounded-md hover:text-accent hover:bg-raised transition-colors">
                  <X className="w-3.5 h-3.5" />
                </span>
              </div>
            </div>

            {/* App shell: persistent sidebar + workspace */}
            <div className="flex min-h-[520px]">
              {/* Sidebar (hidden on narrow preview widths) */}
              <aside className="hidden lg:flex w-44 shrink-0 flex-col justify-between border-r border-hairline bg-band/70 p-2.5">
                <div>
                  <div className="flex items-center gap-2.5 px-2 py-2.5">
                    <span className="grid h-7 w-7 place-items-center rounded-lg border border-hairline bg-surface">
                      <img src="XakuMedia.svg" alt="" className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <span className="block truncate text-[11px] font-semibold text-ink">
                        XakuMedia
                      </span>
                      <span className="block truncate font-mono text-[8px] uppercase tracking-[0.14em] text-faint">
                        Local media toolkit
                      </span>
                    </div>
                  </div>

                  <nav className="mt-2 space-y-3">
                    {SIDEBAR_GROUPS.map((group) => (
                      <div key={group.label}>
                        <p className="px-2 pb-1 font-mono text-[8px] font-medium uppercase tracking-[0.16em] text-faint">
                          {group.label}
                        </p>
                        <div className="space-y-0.5">
                          {group.items.map((item) => {
                            const Icon = item.icon;
                            return (
                              <div
                                key={item.label}
                                className={`flex items-center justify-between gap-2 rounded-lg border px-2 py-1.5 text-[11px] font-medium ${
                                  item.active
                                    ? "border-hairline bg-surface text-ink shadow-sm"
                                    : "border-transparent text-muted"
                                }`}
                              >
                                <span className="flex min-w-0 items-center gap-2">
                                  <Icon
                                    className={`h-3.5 w-3.5 shrink-0 ${
                                      item.active ? "text-accent" : "text-faint"
                                    }`}
                                  />
                                  <span className="truncate">{item.label}</span>
                                </span>
                                {item.badge && (
                                  <span className="rounded-full bg-accent px-1.5 py-0.5 font-mono text-[8px] font-bold text-on-accent">
                                    {item.badge}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </nav>
                </div>

                <div className="space-y-1.5 border-t border-hairline px-2 pt-2.5">
                  <span className="flex items-center gap-1.5 font-mono text-[8px] text-muted">
                    <span className="h-1 w-1 rounded-full bg-emerald-500" />
                    Python IPC
                  </span>
                  <span className="flex items-center gap-1.5 font-mono text-[8px] text-muted">
                    <span className="h-1 w-1 rounded-full bg-emerald-500" />
                    FFmpeg 7.1
                  </span>
                  <span className="block truncate font-mono text-[8px] text-faint">
                    win32 · v{RELEASE_CONFIG.version}
                  </span>
                </div>
              </aside>

              {/* Workspace */}
              <div className="flex min-w-0 flex-1 flex-col">
                {/* Header */}
                <div className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-hairline bg-band/50 px-4">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="font-mono text-[8px] uppercase tracking-[0.16em] text-faint">
                      Workspace
                    </span>
                    <span className="text-[9px] text-faint/60">/</span>
                    <span className="truncate text-[11px] font-semibold text-ink">Scan</span>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <span className="hidden sm:inline-flex items-center gap-1 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 font-mono text-[8px] text-red-700 dark:text-red-300">
                      <span className="h-1 w-1 rounded-full bg-accent" />
                      3 active
                    </span>
                    <span className="hidden md:inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-mono text-[8px] text-emerald-700 dark:text-emerald-300">
                      <span className="h-1 w-1 rounded-full bg-emerald-500" />
                      Python IPC
                    </span>
                    <span className="hidden xl:inline-flex items-center gap-1 rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 font-mono text-[8px] text-purple-700 dark:text-purple-300">
                      <Sparkles className="h-2.5 w-2.5" />
                      FFmpeg
                    </span>
                  </div>
                </div>

                {/* Scan workspace */}
                <div className="flex-1 space-y-3 p-4">
                  <div>
                    <h2 className="text-[15px] font-semibold tracking-tight text-ink">
                      Bulk scan
                    </h2>
                    <p className="mt-0.5 text-[10px] text-muted">
                      Paste profile, channel, album, or post URLs — one per line.
                    </p>
                  </div>

                  {/* Source input row */}
                  <div className="rounded-xl border border-hairline bg-surface p-3">
                    <div className="flex items-center gap-2 rounded-lg border border-hairline bg-page px-2.5 py-2">
                      <LayoutGrid className="h-3.5 w-3.5 shrink-0 text-faint" />
                      <span className="flex-1 truncate font-mono text-[10px] text-muted">
                        pinterest.com/pinterest · youtube.com/@creator · example.com/album
                      </span>
                      <span className="shrink-0 rounded-md bg-accent px-2.5 py-1 text-[10px] font-semibold text-on-accent">
                        Start scan
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[9px] text-faint">
                      <span className="inline-flex items-center gap-1">
                        <Bookmark className="h-2.5 w-2.5" />
                        Bookmark link
                      </span>
                      <span className="text-hairline">|</span>
                      <span>Scan options</span>
                      <span className="text-hairline">|</span>
                      <span className="text-accent">18 new since last scan</span>
                    </div>
                  </div>

                  {/* Scan job rows */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface px-3 py-2">
                      <span className="flex min-w-0 items-center gap-2 font-mono text-[10px]">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                        <span className="truncate text-ink/80">pinterest.com/pinterest</span>
                        <span className="shrink-0 text-faint">1 post · 5 images</span>
                      </span>
                      <span className="shrink-0 rounded-full border border-hairline px-2 py-0.5 font-mono text-[8px] text-muted">
                        completed
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-accent/25 bg-accent/5 px-3 py-2">
                      <span className="flex min-w-0 items-center gap-2 font-mono text-[10px]">
                        <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent" />
                        <span className="truncate text-ink/80">youtube.com/@creator</span>
                        <span className="shrink-0 text-faint">6 / 12 posts · 48 media</span>
                      </span>
                      <span className="h-1 w-20 shrink-0 overflow-hidden rounded-full bg-raised">
                        <span className="block h-full w-1/2 rounded-full bg-accent" />
                      </span>
                    </div>
                  </div>

                  {/* Selection toolbar */}
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-hairline bg-surface px-3 py-2">
                    <div className="flex flex-wrap items-center gap-1">
                      {[
                        ["All 48", true],
                        ["Images 36", false],
                        ["Videos 12", false],
                        ["Albums 4", false],
                      ].map(([label, active]) => (
                        <span
                          key={label as string}
                          className={`rounded-full border px-2 py-0.5 font-mono text-[9px] ${
                            active
                              ? "border-accent/40 bg-accent/10 text-accent"
                              : "border-hairline text-muted"
                          }`}
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center gap-2 font-mono text-[9px]">
                      <span className="text-ink/80">Select all</span>
                      <span className="inline-flex items-center gap-1 text-accent">
                        <Sparkles className="h-2.5 w-2.5" />
                        Select new (18)
                      </span>
                    </div>
                  </div>

                  {/* Batch bar */}
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent/25 bg-accent/5 px-3 py-2">
                    <span className="font-mono text-[10px]">
                      <span className="font-semibold text-accent">18</span>
                      <span className="text-ink/80"> selected</span>
                      <span className="text-muted"> · 6 posts · 48 media · 18 new</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1.5 text-[10px] font-medium text-on-accent shadow-sm shadow-accent/25">
                      <Download className="h-3 w-3" />
                      Download selected (18)
                    </span>
                  </div>

                  {/* Media gallery */}
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
                    {MOCK_MEDIA.map((item, index) => (
                      <div
                        key={item.name}
                        className={`overflow-hidden rounded-lg border bg-surface ${
                          item.selected ? "border-accent ring-1 ring-accent/40" : "border-hairline"
                        }`}
                      >
                        <div
                          className={`relative aspect-square bg-gradient-to-br ${CARD_WASH[index % CARD_WASH.length]}`}
                        >
                          <span className="absolute inset-0 grid place-items-center text-accent/70">
                            {item.kind === "video" ? (
                              <Film className="h-5 w-5" />
                            ) : (
                              <ImageIcon className="h-5 w-5" />
                            )}
                          </span>
                          <span
                            className={`absolute left-1 top-1 grid place-items-center rounded border p-0.5 ${
                              item.selected
                                ? "border-accent bg-accent text-on-accent"
                                : "border-hairline-strong bg-surface/70 text-transparent"
                            }`}
                            aria-hidden="true"
                          >
                            <Check className="h-2.5 w-2.5" />
                          </span>
                          <span className="absolute right-1 top-1 rounded bg-black/55 px-1 py-0.5 font-mono text-[7px] text-white/70">
                            #{index + 1}
                          </span>
                          {item.downloaded && (
                            <span className="absolute bottom-1 left-1 rounded bg-emerald-600/90 px-1 py-0.5 font-mono text-[7px] text-white">
                              downloaded
                            </span>
                          )}
                          <span className="absolute bottom-1 right-1 rounded bg-black/65 px-1 py-0.5 font-mono text-[7px] uppercase text-white/85">
                            {item.kind === "video" ? "video" : "image"}
                          </span>
                        </div>
                        <div className="space-y-0.5 px-1.5 py-1">
                          <p className="truncate font-mono text-[8px] text-ink">{item.name}</p>
                          <p className="truncate font-mono text-[8px] text-muted">{item.spec}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <p className="mt-4 text-center font-mono text-xs text-faint">
            Illustrative preview of the desktop app — this site shares the same theme
            tokens, typography, and bulk-scan workflow.
          </p>
        </div>
      </div>
    </section>
  );
};
