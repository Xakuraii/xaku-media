import React from "react";
import {
  Search,
  Sparkles,
  Film,
  Gauge,
  Database,
  Cookie,
} from "lucide-react";

export const FeaturesSection: React.FC = () => {
  const features = [
    {
      icon: Search,
      title: "Bulk profile & channel scans",
      description:
        "Paste multiple profile, channel, album, or post URLs at once. Background scan jobs page through supported sources and stream posts and media into one gallery as they are discovered.",
    },
    {
      icon: Sparkles,
      title: "Select all, select only new",
      description:
        "Filter by images, videos, or albums, then pick everything or only the items you have never downloaded. Downloaded badges and per-scan focus keep large rescans quick to review.",
    },
    {
      icon: Film,
      title: "Lossless stream merging",
      description:
        "Prefers a muxed stream when one exists; otherwise it downloads the best video track plus the best audio track and merges them with bundled FFmpeg in copy mode — with cancellation and timeout safeguards.",
    },
    {
      icon: Gauge,
      title: "Speed & concurrency control",
      description:
        "A global token-bucket limiter (Unlimited to custom KB/s) and configurable download worker slots keep large batches inside your bandwidth budget without throttling unrelated traffic.",
    },
    {
      icon: Database,
      title: "Local library & scan history",
      description:
        "Every scan, post, media item, and task lives in local SQLite. Bookmark links, rescan a history entry with its URL prefilled, and search or sort your collection entirely offline.",
    },
    {
      icon: Cookie,
      title: "Cookie-aware sign-in help",
      description:
        "Import a Netscape cookies.txt (Chrome by default) for sources that require a session. When a site still fails, the error names the cause and the exact next step instead of a generic failure.",
    },
  ];

  return (
    <section id="features" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        {/* Section heading */}
        <div className="max-w-xl">
          <h2 className="section-title">
            Built for bulk discovery, tuned for control
          </h2>
          <p className="section-lead">
            The same workspace you see in the desktop preview — profile scanning,
            gallery selection, and downloads that stay on your machine.
          </p>
        </div>

        {/* Spec-sheet grid: hairline dividers instead of stacked cards */}
        <div className="mt-10 sm:mt-14 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px rounded-2xl border border-hairline bg-hairline overflow-hidden">
          {features.map((feat) => {
            const Icon = feat.icon;
            return (
              <div
                key={feat.title}
                className="bg-page p-6 sm:p-7 transition-colors duration-150 hover:bg-raised"
              >
                <div className="grid place-items-center w-10 h-10 rounded-lg border border-hairline bg-band text-accent">
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="mt-4 font-display text-base font-semibold text-ink">
                  {feat.title}
                </h3>
                <p className="mt-2 text-sm text-muted leading-relaxed">
                  {feat.description}
                </p>
              </div>
            );
          })}
        </div>

        <p className="mt-4 font-mono text-xs text-faint">
          Provider coverage is honest by design: verified direct URLs, native video hosts,
          and gallery-dl platforms work out of the box; auth-heavy sites need your own
          cookies.
        </p>
      </div>
    </section>
  );
};
