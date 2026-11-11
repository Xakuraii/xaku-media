import React from "react";
import {
  Search,
  Film,
  Gauge,
  Layers,
  HardDrive,
  Cookie,
} from "lucide-react";

export const FeaturesSection: React.FC = () => {
  const features = [
    {
      icon: Search,
      title: "Smart URL scanner",
      description:
        "Automatically identifies direct video links, multi-item image galleries, and supported platform channels with zero manual configuration.",
    },
    {
      icon: Film,
      title: "Lossless stream merging",
      description:
        "Merges separate high-definition video and audio streams using bundled FFmpeg with copy mode (-c copy). No CPU re-encoding or quality loss.",
    },
    {
      icon: Gauge,
      title: "Bandwidth speed limiting",
      description:
        "Cap download speeds dynamically (512 KB/s to Unlimited) so large media batches don't saturate your home or office internet connection.",
    },
    {
      icon: Layers,
      title: "Concurrent queue & resumption",
      description:
        "Configurable worker slots (1 to 10 downloads). Interrupted transfers resume automatically where they left off using HTTP Range requests.",
    },
    {
      icon: HardDrive,
      title: "Local SQLite media library",
      description:
        "Every scan, task, and bookmark is cataloged locally in SQLite with WAL mode. Search, filter by file container, and sort offline in milliseconds.",
    },
    {
      icon: Cookie,
      title: "Browser cookie importer",
      description:
        "Import authenticated session cookies directly from Chrome, Edge, Firefox, Brave, Opera, or Vivaldi using secure Windows DPAPI decryption.",
    },
  ];

  return (
    <section id="features" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        {/* Section heading */}
        <div className="max-w-xl">
          <h2 className="section-title">
            Designed for speed, clarity, and control
          </h2>
          <p className="section-lead">
            Everything you need for bulk downloading — none of the bloat of
            web-based tools.
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
      </div>
    </section>
  );
};
