import React from "react";
import { Monitor, Cpu, Box } from "lucide-react";

export const RequirementsSection: React.FC = () => {
  const specs = [
    {
      icon: Monitor,
      title: "OS",
      main: "Windows 10 / 11 (64-bit)",
      detail: "Standard x86_64 Windows desktop.",
    },
    {
      icon: Cpu,
      title: "Resources",
      main: "4 GB RAM · 350 MB disk",
      detail: "8 GB RAM recommended for 4K merges.",
    },
    {
      icon: Box,
      title: "Dependencies",
      main: "All bundled",
      detail: "Python 3.12 and FFmpeg are already inside.",
    },
  ];

  return (
    <section id="requirements" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-14 sm:py-20">
        <div className="max-w-xl">
          <h2 className="section-title">System requirements</h2>
          <p className="section-lead">Self-contained Windows app with zero external setup.</p>
        </div>

        {/* Single spec sheet */}
        <div className="mt-10 sm:mt-14 grid grid-cols-1 sm:grid-cols-3 gap-px rounded-2xl border border-hairline bg-hairline overflow-hidden">
          {specs.map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.title} className="bg-page p-6 sm:p-7">
                <div className="flex items-center gap-2.5">
                  <Icon className="w-5 h-5 text-accent" aria-hidden="true" />
                  <span className="text-xs font-medium text-faint">{item.title}</span>
                </div>
                <div className="mt-3 font-display text-lg font-semibold text-ink">
                  {item.main}
                </div>
                <p className="mt-2 text-sm text-muted leading-relaxed">{item.detail}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};
