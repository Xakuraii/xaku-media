import React from "react";
import { ServerOff, EyeOff, ShieldCheck } from "lucide-react";

export const SecurityPrivacySection: React.FC = () => {
  const pillars = [
    {
      icon: ServerOff,
      title: "100% local-first storage",
      desc: "All metadata, history, and queue records are stored exclusively in your local SQLite database. No external cloud backend or remote servers.",
    },
    {
      icon: EyeOff,
      title: "Zero cloud telemetry",
      desc: "XakuMedia has no tracking pixels, analytics SDKs, or remote diagnostic pings. Your media collection and activity remain strictly private.",
    },
    {
      icon: ShieldCheck,
      title: "Network defense & boundaries",
      desc: "Includes built-in SSRF protection against internal IP probing. Strictly respects content boundaries without cracking DRM or bypassing paywalls.",
    },
  ];

  return (
    // Inverted band: brand black in light mode, elevated surface in dark mode.
    <section
      id="security"
      className="border-t-2 border-brand-red bg-brand-black text-brand-white dark:bg-surface dark:border-t-2 dark:border-hairline transition-colors duration-300"
    >
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-xl">
          <h2 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight text-white">
            Privacy &amp; trust
          </h2>
          <p className="mt-3 max-w-2xl text-sm sm:text-base text-white/60 leading-relaxed">
            Engineered to respect your privacy and protect your local system.
          </p>
        </div>

        {/* Pillars */}
        <div className="mt-10 sm:mt-14 grid grid-cols-1 sm:grid-cols-3 gap-8 sm:gap-0 sm:divide-x sm:divide-white/10">
          {pillars.map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.title} className="sm:px-7 first:sm:pl-0 last:sm:pr-0">
                <div className="grid place-items-center w-10 h-10 rounded-lg bg-brand-red/15 text-brand-accent">
                  <Icon className="w-5 h-5" aria-hidden="true" />
                </div>
                <h3 className="mt-4 font-display text-base font-semibold text-white">
                  {item.title}
                </h3>
                <p className="mt-2 text-sm text-white/60 leading-relaxed">{item.desc}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};
