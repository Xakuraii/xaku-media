import React from "react";
import { ServerOff, EyeOff, ShieldCheck, Scale } from "lucide-react";

export const SecurityPrivacySection: React.FC = () => {
  const pillars = [
    {
      icon: ServerOff,
      title: "Local-first storage",
      desc: "History, queues, manifests, and cookies stay on your PC — no cloud backend or remote accounts.",
    },
    {
      icon: EyeOff,
      title: "Zero telemetry",
      desc: "No tracking pixels, analytics SDKs, or hidden uploads. Your downloads stay private.",
    },
    {
      icon: ShieldCheck,
      title: "Respects boundaries",
      desc: "Built-in SSRF and path guards. Does not crack DRM, bypass paywalls, or break access controls.",
    },
  ];

  return (
    // Inverted band: brand black in light mode, elevated surface in dark mode.
    <section
      id="security"
      className="border-t-2 border-brand-red bg-brand-black text-brand-white dark:bg-surface dark:border-t-2 dark:border-hairline transition-colors duration-300"
    >
      <div className="lc-container py-14 sm:py-20">
        <div className="max-w-xl">
          <h2 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight text-white">
            Privacy, trust &amp; responsibility
          </h2>
          <p className="mt-2.5 max-w-2xl text-sm sm:text-base text-white/65 leading-relaxed">
            Built to protect your system — use responsibly at your own discretion.
          </p>
        </div>

        {/* Pillars */}
        <div className="mt-10 grid grid-cols-1 sm:grid-cols-3 gap-8 sm:gap-0 sm:divide-x sm:divide-white/10">
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
                <p className="mt-1.5 text-sm text-white/65 leading-relaxed">{item.desc}</p>
              </div>
            );
          })}
        </div>

        {/* Use responsibly notice */}
        <div className="mt-10 flex items-start gap-3.5 rounded-2xl border border-white/15 bg-white/5 px-5 py-4">
          <Scale className="w-5 h-5 text-brand-accent shrink-0 mt-0.5" aria-hidden="true" />
          <p className="text-sm text-white/80 leading-relaxed">
            <strong className="text-white font-semibold">Use at your own responsibility:</strong>{" "}
            XakuMedia is for personal offline archiving only. Respect copyright, creator rights,
            and platform terms — you are solely responsible for the URLs you scan, the cookies you
            use, and how you store or share downloaded media.
          </p>
        </div>
      </div>
    </section>
  );
};
