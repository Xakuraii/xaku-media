import React, { useState, useEffect } from "react";
import {
  Download,
  Package,
  ExternalLink,
  Search,
  Film,
  Image as ImageIcon,
  Minus,
  Square,
  X,
  Check,
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
}

/** Illustrative contents of the desktop app's scan results grid. */
const MOCK_MEDIA: MockMediaItem[] = [
  { name: "landscape_001.jpg", kind: "image", spec: "3840×2160", selected: true },
  { name: "landscape_002.jpg", kind: "image", spec: "Original", selected: true },
  { name: "sunset_clip.mp4", kind: "video", spec: "1080p60 · H.264", selected: true },
  { name: "night_sky.mp4", kind: "video", spec: "4K · VP9", selected: false },
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
              {RELEASE_CONFIG.latestTag} — released {RELEASE_CONFIG.releaseDate}
            </span>
          </p>

          {/* Headline */}
          <h1 className="mt-6 font-display text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.06] text-ink text-balance">
            Bulk media downloading, made effortless.
          </h1>

          {/* Subtitle */}
          <p className="mt-6 text-base sm:text-lg text-muted leading-relaxed max-w-xl">
            A local-first Windows desktop app to discover, inspect, and batch-download
            videos and image galleries. No accounts, no cloud tracking, no subscriptions.
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

        {/* Desktop app window showcase (illustrative preview) */}
        <div className="mt-14 sm:mt-16">
          <div className="rounded-2xl border border-hairline bg-surface shadow-pop overflow-hidden">
            {/* Titlebar */}
            <div className="flex items-center justify-between pl-4 pr-3 h-11 bg-band border-b border-hairline">
              <div className="flex items-center gap-2 min-w-0">
                <span className="grid place-items-center w-4 h-4 rounded-sm bg-brand-white">
                  <img src="/XakuMedia.svg" alt="" className="w-full h-full" />
                </span>
                <span className="text-xs font-medium text-muted truncate">
                  XakuMedia — Desktop Media Downloader
                </span>
              </div>
              <div className="flex items-center text-faint">
                <span className="grid place-items-center w-8 h-8 rounded-md hover:bg-raised transition-colors">
                  <Minus className="w-3 h-3" />
                </span>
                <span className="grid place-items-center w-8 h-8 rounded-md hover:bg-raised transition-colors">
                  <Square className="w-3 h-3" />
                </span>
                <span className="grid place-items-center w-8 h-8 rounded-md hover:text-accent hover:bg-raised transition-colors">
                  <X className="w-3.5 h-3.5" />
                </span>
              </div>
            </div>

            {/* App body */}
            <div className="p-4 sm:p-6 space-y-4">
              {/* URL scan bar */}
              <div className="flex items-center gap-3 rounded-lg border border-hairline bg-band px-3.5 py-2.5">
                <Search className="w-4 h-4 text-faint shrink-0" />
                <span className="flex-1 truncate font-mono text-xs text-muted">
                  https://example.com/gallery/landscape-collection-2026
                </span>
                <span className="shrink-0 rounded-md bg-accent text-on-accent px-3 py-1.5 text-xs font-semibold">
                  Scan URL
                </span>
              </div>

              <div className="grid lg:grid-cols-[1.6fr_1fr] gap-4">
                {/* Discovered media grid */}
                <div className="rounded-lg border border-hairline overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-2.5 bg-band border-b border-hairline">
                    <span className="text-xs font-semibold text-ink">
                      Discovered collection
                    </span>
                    <span className="font-mono text-xs text-faint">24 items</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4 gap-px bg-hairline">
                    {MOCK_MEDIA.map((item) => (
                      <div key={item.name} className="bg-surface p-3 space-y-2.5">
                        <div className="relative aspect-[4/3] rounded-md bg-band grid place-items-center">
                          {item.kind === "video" ? (
                            <Film className="w-5 h-5 text-faint" />
                          ) : (
                            <ImageIcon className="w-5 h-5 text-faint" />
                          )}
                          <span
                            className={`absolute top-2 right-2 grid place-items-center w-[18px] h-[18px] rounded-[4px] border transition-colors ${
                              item.selected
                                ? "bg-accent border-accent text-on-accent"
                                : "border-hairline-strong bg-surface/60 text-transparent"
                            }`}
                            aria-hidden="true"
                          >
                            <Check className="w-3 h-3" />
                          </span>
                        </div>
                        <div>
                          <div className="font-mono text-[11px] text-ink truncate">
                            {item.name}
                          </div>
                          <div className="font-mono text-[11px] text-faint mt-0.5">
                            {item.spec}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Download queue */}
                <div className="rounded-lg border border-hairline overflow-hidden flex flex-col">
                  <div className="flex items-center justify-between px-4 py-2.5 bg-band border-b border-hairline">
                    <span className="text-xs font-semibold text-ink">Download queue</span>
                    <span className="font-mono text-xs text-faint">4 workers</span>
                  </div>

                  <div className="p-4 space-y-5 flex-1">
                    {/* Active item */}
                    <div>
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className="text-ink truncate">landscape_001.jpg</span>
                        <span className="text-accent shrink-0 ml-3">18.4 MB/s</span>
                      </div>
                      <div className="mt-2 h-1.5 rounded-full bg-raised overflow-hidden">
                        <div
                          className="h-full w-[76%] origin-left rounded-full bg-accent"
                          style={{ animation: "queue-progress 1.8s cubic-bezier(0.22, 0.61, 0.36, 1) both" }}
                        />
                      </div>
                    </div>

                    {/* Completed item */}
                    <div>
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className="text-muted truncate">landscape_002.jpg</span>
                        <span className="text-faint shrink-0 ml-3 flex items-center gap-1.5">
                          <Check className="w-3 h-3" />
                          Done
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 rounded-full bg-raised overflow-hidden">
                        <div className="h-full rounded-full bg-faint/50" style={{ width: "100%" }} />
                      </div>
                    </div>

                    {/* Queued item */}
                    <div>
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className="text-muted truncate">night_sky.mp4</span>
                        <span className="text-faint shrink-0 ml-3">Queued</span>
                      </div>
                      <div className="mt-2 h-1.5 rounded-full bg-raised overflow-hidden">
                        <div className="h-full w-0 rounded-full bg-accent" />
                      </div>
                    </div>
                  </div>

                  {/* Status bar */}
                  <div className="flex items-center justify-between px-4 py-2.5 bg-band border-t border-hairline font-mono text-[11px] text-faint">
                    <span>18 of 24 completed</span>
                    <span>Range resumption active</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <p className="mt-4 text-center font-mono text-xs text-faint">
            Illustrative preview of the desktop app
          </p>
        </div>
      </div>
    </section>
  );
};
