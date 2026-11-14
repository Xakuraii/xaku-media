import React from "react";
import { Search, Sparkles, SlidersHorizontal, Download } from "lucide-react";

export const WorkflowSection: React.FC = () => {
  const steps = [
    {
      num: "01",
      icon: Search,
      title: "Paste your sources",
      desc: "Drop in one or many profile, channel, album, or media URLs. Bookmark a link in the same step if you want to rescan it later.",
    },
    {
      num: "02",
      icon: Sparkles,
      title: "Watch the gallery fill",
      desc: "Background jobs page through supported sources and stream posts and media into a live gallery, so you can start reviewing before the scan finishes.",
    },
    {
      num: "03",
      icon: SlidersHorizontal,
      title: "Select only what's new",
      desc: "Filter images, videos, or albums, then use Select all or Select new. Preview the quality and expected size chosen by your saved settings.",
    },
    {
      num: "04",
      icon: Download,
      title: "Download, merge, done",
      desc: "Files download with concurrent workers and Range resumption, merged losslessly when needed, and cataloged in your local library and scan history.",
    },
  ];

  return (
    <section id="workflow" className="border-t border-hairline bg-page transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-xl">
          <h2 className="section-title">How it works</h2>
          <p className="section-lead">
            From a list of links to a reviewed, downloaded collection — bulk first.
          </p>
        </div>

        {/* Step rail */}
        <ol className="mt-10 sm:mt-14 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-10 list-none">
          {steps.map((s) => {
            const Icon = s.icon;
            return (
              <li key={s.num} className="border-t-2 border-hairline pt-5">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-semibold text-accent">
                    {s.num}
                  </span>
                  <Icon className="w-5 h-5 text-faint" aria-hidden="true" />
                </div>
                <h3 className="mt-4 font-display text-base font-semibold text-ink">
                  {s.title}
                </h3>
                <p className="mt-2 text-sm text-muted leading-relaxed">{s.desc}</p>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
};
