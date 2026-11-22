import React from "react";
import {
  AlertTriangle,
  Cookie,
  ExternalLink,
  FileText,
  Globe,
  RefreshCw,
  Upload,
} from "lucide-react";

const COOKIE_EXTENSION_URL =
  "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc";

const STEPS = [
  {
    icon: Globe,
    title: "Sign in in your browser",
    body: "Open the site in Chrome/Edge while signed in to the account that can view the media.",
  },
  {
    icon: FileText,
    title: "Export Netscape cookies.txt",
    body: (
      <>
        Use{" "}
        <a
          href={COOKIE_EXTENSION_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline underline-offset-4 decoration-1 hover:decoration-2"
        >
          Get cookies.txt LOCALLY
        </a>{" "}
        to save as <span className="font-mono text-ink">.txt</span> (Netscape format, not JSON).
      </>
    ),
  },
  {
    icon: Upload,
    title: "Import in Settings",
    body: (
      <>
        Open <span className="font-mono text-ink">Settings → Session Credentials</span> and click{" "}
        <span className="font-mono text-ink">Import .txt File</span> or{" "}
        <span className="font-mono text-ink">Extract</span> (close browser first).
      </>
    ),
  },
  {
    icon: RefreshCw,
    title: "Rescan your URL",
    body: "Profiles stay local and auto-apply per domain. Re-export if a session expires.",
  },
];

const QUICK_FIXES = [
  {
    problem: "One-click browser extract fails",
    fix: "Close Chrome/Edge completely so Windows unlocks its cookie DB, or import cookies.txt.",
  },
  {
    problem: "Import reports 0 cookies",
    fix: "Make sure you exported Netscape .txt while viewing the logged-in tab.",
  },
  {
    problem: "Worked before, now blocked",
    fix: "Session expired — log in again and import a fresh cookies.txt.",
  },
  {
    problem: "Profile still fails with cookies",
    fix: "Some accounts disable embeds or block profile scraping — try a direct post/video link.",
  },
];

export const CookieGuideSection: React.FC = () => {
  return (
    <section id="cookies" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-14 sm:py-20">
        <div className="max-w-xl">
          <div className="flex items-center gap-2 text-xs font-mono text-faint">
            <Cookie className="w-4 h-4 text-accent" />
            <span>Session access</span>
          </div>
          <h2 className="section-title mt-3">Cookies for signed-in sites</h2>
          <p className="section-lead">
            For platforms like TikTok, Instagram, Facebook, or X, import your local{" "}
            <span className="font-mono text-ink">cookies.txt</span>. Never share cookie files.
          </p>
        </div>

        <div className="mt-10 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ol className="rounded-2xl border border-hairline bg-page divide-y divide-hairline overflow-hidden">
            {STEPS.map((step, index) => {
              const Icon = step.icon;
              return (
                <li key={step.title} className="flex gap-3.5 px-5 py-4">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-hairline bg-band font-mono text-[11px] font-semibold text-accent">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 text-faint" aria-hidden="true" />
                      <h3 className="font-display text-sm font-semibold text-ink">{step.title}</h3>
                    </div>
                    <p className="mt-1 text-sm text-muted leading-relaxed">{step.body}</p>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="space-y-4">
            <div className="rounded-2xl border border-hairline bg-page divide-y divide-hairline overflow-hidden">
              {QUICK_FIXES.map((item) => (
                <div key={item.problem} className="px-5 py-3.5">
                  <p className="flex items-center gap-2 text-sm font-medium text-ink">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                    <span>{item.problem}</span>
                  </p>
                  <p className="mt-1 pl-5 text-xs sm:text-sm text-muted leading-relaxed">
                    {item.fix}
                  </p>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 text-xs sm:text-sm text-muted">
              <span>Cookies stay local in your app data folder — never share or upload them.</span>
              <a
                href={COOKIE_EXTENSION_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 inline-flex items-center gap-1 font-mono text-xs text-accent underline underline-offset-4"
              >
                <span>Extension</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
