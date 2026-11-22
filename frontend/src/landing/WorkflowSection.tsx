import React from "react";
import { Search, Sparkles, SlidersHorizontal, Download } from "lucide-react";

export const WorkflowSection: React.FC = () => {
  const steps = [
    {
      num: "01",
      icon: Search,
      title: "Paste your URL",
      desc: "Add profile, album, or video links and start scanning.",
    },
    {
      num: "02",
      icon: Sparkles,
      title: "Review new items",
      desc: "See downloaded and skipped badges synced from your folder JSON.",
    },
    {
      num: "03",
      icon: SlidersHorizontal,
      title: "Select or skip",
      desc: "Pick new media to download or mark unwanted items as skipped.",
    },
    {
      num: "04",
      icon: Download,
      title: "Save to creator folders",
      desc: "Files download cleanly into Platform / Creator / Videos & Images.",
    },
  ];

  return (
    <section id="workflow" className="border-t border-hairline bg-page transition-colors duration-300">
      <div className="lc-container py-14 sm:py-20">
        <div className="max-w-xl">
          <h2 className="section-title">How it works</h2>
          <p className="section-lead">Four steps from URL to organized local media.</p>
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
