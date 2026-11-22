import React, { useState, useEffect } from "react";
import { Download, ExternalLink, Package } from "lucide-react";
import { AppShowcaseWindow } from "./AppShowcaseWindow";
import {
  RELEASE_CONFIG,
  checkGitHubReleaseStatus,
  GitHubReleaseStatus,
} from "./downloadConfig";

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
          <p className="mt-5 text-base sm:text-lg text-muted leading-relaxed max-w-xl">
            A local-first Windows app to scan profiles, albums, and links — skip what you
            don&apos;t want, download in full quality, and keep everything organized locally.
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

        {/* Real v1.0.0 Desktop App Showcase (Left/Right tab carousel) */}
        <AppShowcaseWindow />
      </div>
    </section>
  );
};
