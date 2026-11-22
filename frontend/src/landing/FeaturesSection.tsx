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
      title: "Bulk profile & link scans",
      description:
        "Paste profile, channel, gallery, or direct URLs and inspect discovered photos and videos in one view.",
    },
    {
      icon: Sparkles,
      title: "Select new & Skip",
      description:
        "Pick only new items or mark unwanted media as skipped — saved in portable per-folder xakumedia-library.json files.",
    },
    {
      icon: Film,
      title: "Quality-aware FFmpeg merge",
      description:
        "Matches your target resolution by short edge (1080p/4K) and muxes best video + audio losslessly.",
    },
    {
      icon: Gauge,
      title: "Creator folders & naming",
      description:
        "Saves into Platform / Creator / Videos & Images with sequential user-vdo-N and user-img-N numbering.",
    },
    {
      icon: Database,
      title: "JSON Download Library & PFPs",
      description:
        "Browse creator folders directly from your Settings download directory and bookmark sources with custom PFPs.",
    },
    {
      icon: Cookie,
      title: "Local cookie profiles",
      description:
        "Import your browser cookies.txt locally for signed-in sources, with clear diagnostics when access is restricted.",
    },
  ];

  return (
    <section id="features" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-14 sm:py-20">
        {/* Section heading */}
        <div className="max-w-xl">
          <h2 className="section-title">
            Built for bulk discovery, tuned for control
          </h2>
          <p className="section-lead">
            Scan, filter, skip, and organize media locally on Windows.
          </p>
        </div>

        {/* Spec-sheet grid: hairline dividers instead of stacked cards */}
        <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px rounded-2xl border border-hairline bg-hairline overflow-hidden">
          {features.map((feat) => {
            const Icon = feat.icon;
            return (
              <div
                key={feat.title}
                className="bg-page p-6 transition-colors duration-150 hover:bg-raised"
              >
                <div className="grid place-items-center w-10 h-10 rounded-lg border border-hairline bg-band text-accent">
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="mt-4 font-display text-base font-semibold text-ink">
                  {feat.title}
                </h3>
                <p className="mt-1.5 text-sm text-muted leading-relaxed">
                  {feat.description}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};
