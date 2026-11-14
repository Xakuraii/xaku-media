import React from "react";
import { Tag, Check, ExternalLink } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

export const ReleaseChangelogSection: React.FC = () => {
  const highlights = [
    "Bulk profile and channel scanning with paginated, cancellable background jobs",
    "Gallery workspace with Select all, Select only new, downloaded badges, and per-scan focus",
    "Scan History Rescan prefills the Scan tab; bookmark links are saved as sources",
    "Stable media identity and identity-aware upserts keep rescans duplicate-free",
    "Cookie import (Chrome default) plus actionable, cookie-aware scan errors",
    "Lossless FFmpeg video + audio merging with timeout, cancel, and best-audio fallback",
    "Local SQLite library, scan history, and settings with explicit Save persistence",
    "Backend regression suite and Electron desktop smoke tests cover the scan and download flows",
  ];

  return (
    <section id="changelog" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-xl">
          <h2 className="section-title">Release notes</h2>
          <p className="section-lead">
            Current version capabilities and architectural highlights.
          </p>
        </div>

        {/* Release document */}
        <div className="mt-10 sm:mt-14 max-w-4xl rounded-2xl border border-hairline bg-page overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 sm:px-8 py-5 border-b border-hairline bg-band">
            <div className="flex items-center gap-3.5">
              <span className="grid place-items-center w-9 h-9 rounded-lg bg-brand-red/10 text-accent">
                <Tag className="w-[18px] h-[18px]" aria-hidden="true" />
              </span>
              <div>
                <div className="flex items-center gap-2.5">
                  <h3 className="font-display text-base font-semibold text-ink">
                    XakuMedia {RELEASE_CONFIG.latestTag}
                  </h3>
                  <span className="rounded-full bg-brand-red/10 text-accent px-2.5 py-0.5 font-mono text-[10px] font-medium">
                    Latest
                  </span>
                </div>
                <p className="mt-1 font-mono text-xs text-faint">
                  Released {RELEASE_CONFIG.releaseDate} · Windows 64-bit
                </p>
              </div>
            </div>

            <a
              href={RELEASE_CONFIG.releasesUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-hairline bg-page text-xs font-medium text-muted hover:text-ink transition-colors duration-150"
            >
              <span>GitHub Releases</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>

          <ul className="px-6 sm:px-8 py-6 space-y-3.5">
            {highlights.map((item) => (
              <li key={item} className="flex items-start gap-3 text-sm text-muted">
                <Check className="w-4 h-4 text-accent shrink-0 mt-0.5" aria-hidden="true" />
                <span className="leading-relaxed">{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
};
