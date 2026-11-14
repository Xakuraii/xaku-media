import React from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Cookie,
  ExternalLink,
  FileText,
  Globe,
  KeyRound,
  ListChecks,
  Lock,
  MousePointerClick,
  RefreshCw,
  ShieldCheck,
  Upload,
} from "lucide-react";

const COOKIE_EXTENSION_URL =
  "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc";

interface CookieStep {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: React.ReactNode;
}

const STEPS: CookieStep[] = [
  {
    icon: Globe,
    title: "Sign in on the site in your browser",
    body: (
      <>
        Open the strict site in Chrome, Edge, Firefox, Brave, Opera, or Vivaldi and log in
        with the account that can already see the media. XakuMedia never asks for your
        password, and it cannot see content your account cannot access.
      </>
    ),
  },
  {
    icon: FileText,
    title: "Export a Netscape cookies.txt",
    body: (
      <>
        Recommended: install{" "}
        <a
          href={COOKIE_EXTENSION_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline underline-offset-4 decoration-1 hover:decoration-2"
        >
          Get cookies.txt LOCALLY
        </a>{" "}
        (Chrome / Edge), open the site while signed in, export, and save the file as{" "}
        <span className="font-mono text-ink">cookies.txt</span>. Export the Netscape{" "}
        <span className="font-mono text-ink">.txt</span> format — not JSON or HTML.
      </>
    ),
  },
  {
    icon: Upload,
    title: "Import it in Settings",
    body: (
      <>
        In the app open <span className="font-mono text-ink">Settings → Session Credentials
        → Cookie Profiles</span>, then choose <span className="font-mono text-ink">Import
        .txt File</span> or <span className="font-mono text-ink">Paste Text</span>. The
        domain is detected automatically; confirm the profile row and cookie count. Chrome
        is the default browser for one-click imports.
      </>
    ),
  },
  {
    icon: RefreshCw,
    title: "Return to Scan and rescan",
    body: (
      <>
        Paste the profile, channel, or post URL again and start the scan. If the site still
        refuses, the error panel names the cause. Session cookies expire — re-export from a
        freshly logged-in browser tab if a scan that used to work starts failing.
      </>
    ),
  },
];

const TROUBLESHOOTING = [
  {
    problem: "“This source requires a signed-in session”",
    fix: "Import cookies for that exact site, then rescan. The profile domain must cover the URL you scan; a parent-domain cookie applies to its subdomains.",
  },
  {
    problem: "Import reports 0 cookies",
    fix: "You probably exported JSON/HTML instead of Netscape .txt, or exported from the wrong site/tab. Re-export while the logged-in site is open.",
  },
  {
    problem: "One-click browser import fails",
    fix: "Close the browser completely (Windows can lock its cookie database), pick the correct browser profile, or use the .txt import instead.",
  },
  {
    problem: "It worked before, now it fails",
    fix: "The session expired or you signed out elsewhere. Log in again, export a fresh cookies.txt, and replace the old profile.",
  },
  {
    problem: "Cookies imported but the site still blocks",
    fix: "Some providers block automation, regions, or rate limits regardless of login. Try later, lower scan limits, or use a source that permits access.",
  },
];

export const CookieGuideSection: React.FC = () => {
  return (
    <section id="cookies" className="border-t border-hairline bg-band transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2.5">
            <span className="grid place-items-center w-9 h-9 rounded-lg border border-hairline bg-page text-accent">
              <Cookie className="w-5 h-5" />
            </span>
            <span className="font-mono text-xs text-faint">Session access for strict sites</span>
          </div>
          <h2 className="section-title mt-4">How to use cookies on strict sites</h2>
          <p className="section-lead">
            Most platforms treat an anonymous request as logged out, even when the page is
            public in your browser. XakuMedia can reuse your own signed-in browser session
            through a Netscape <span className="font-mono text-ink">cookies.txt</span>.
            No password sharing, no cloud account, no remote browser.
          </p>
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          {[
            { icon: Lock, label: "Stored locally" },
            { icon: FileText, label: "Netscape cookies.txt" },
            { icon: Globe, label: "Chrome is the default" },
            { icon: ShieldCheck, label: "Only sent to matching domains" },
          ].map(({ icon: Icon, label }) => (
            <span
              key={label}
              className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-page px-3 py-1 font-mono text-[11px] text-muted"
            >
              <Icon className="w-3.5 h-3.5 text-accent" />
              {label}
            </span>
          ))}
        </div>

        <div className="mt-10 sm:mt-14 grid grid-cols-1 lg:grid-cols-[1.35fr_1fr] gap-6">
          {/* Step-by-step */}
          <div className="rounded-2xl border border-hairline bg-page overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-hairline bg-band px-6 py-4">
              <div className="flex items-center gap-2.5">
                <MousePointerClick className="w-4 h-4 text-accent" />
                <h3 className="font-display text-sm font-semibold text-ink">
                  How to use cookies
                </h3>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-faint">
                4 steps
              </span>
            </div>

            <ol className="divide-y divide-hairline">
              {STEPS.map((step, index) => {
                const Icon = step.icon;
                return (
                  <li key={step.title} className="flex gap-4 px-6 py-5">
                    <div className="flex flex-col items-center">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-hairline bg-band font-mono text-[11px] font-semibold text-accent">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      {index < STEPS.length - 1 && (
                        <span className="mt-1 h-full w-px bg-hairline" aria-hidden="true" />
                      )}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Icon className="w-4 h-4 text-faint" aria-hidden="true" />
                        <h4 className="font-display text-sm font-semibold text-ink">
                          {step.title}
                        </h4>
                      </div>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted">{step.body}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>

          {/* Strict-site guidance */}
          <div className="space-y-4">
            <div className="rounded-2xl border border-hairline bg-page p-6">
              <div className="flex items-center gap-2.5">
                <ListChecks className="w-4 h-4 text-accent" />
                <h3 className="font-display text-sm font-semibold text-ink">
                  When you need this
                </h3>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                If media is visible only after signing in, cookies are usually the missing
                piece. Common examples include Instagram, X / Twitter, TikTok, Facebook,
                Reddit, Patreon, and private galleries or forums.
              </p>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                Coverage still depends on the provider. XakuMedia will not bypass DRM,
                paywalls, or account permissions.
              </p>

              <div className="mt-4 rounded-xl border border-hairline bg-band p-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-faint">
                  Netscape format
                </p>
                <pre className="mt-2 overflow-x-auto font-mono text-[10px] leading-relaxed text-muted">
{`# Netscape HTTP Cookie File
.instagram.com  TRUE  /  TRUE  1798761600  sessionid  <redacted>`}
                </pre>
                <p className="mt-2 text-[11px] text-faint">
                  <span className="font-mono text-ink">#HttpOnly_</span> lines are supported.
                </p>
              </div>
            </div>

            <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-6">
              <div className="flex items-center gap-2.5 text-amber-700 dark:text-amber-300">
                <AlertTriangle className="w-4 h-4" />
                <h3 className="font-display text-sm font-semibold">
                  Treat cookies like a password
                </h3>
              </div>
              <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-muted">
                <li>Anyone with the file can act as your session — never share it.</li>
                <li>Imported files stay under your local app data folder.</li>
                <li>Delete the profile when you are done; logging out invalidates it.</li>
                <li>Use only an account you own and content you are allowed to access.</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Troubleshooting */}
        <div className="mt-6 rounded-2xl border border-hairline bg-page overflow-hidden">
          <div className="flex items-center gap-2.5 border-b border-hairline bg-band px-6 py-4">
            <KeyRound className="w-4 h-4 text-accent" />
            <h3 className="font-display text-sm font-semibold text-ink">
              If cookies still do not work
            </h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-hairline">
            {TROUBLESHOOTING.map((item) => (
              <div key={item.problem} className="bg-page p-5">
                <p className="flex items-start gap-2 text-sm font-medium text-ink">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                  <span>{item.problem}</span>
                </p>
                <p className="mt-1.5 pl-5 text-sm leading-relaxed text-muted">{item.fix}</p>
              </div>
            ))}
            <div className="bg-page p-5 md:col-span-2">
              <p className="flex items-start gap-2 text-sm font-medium text-ink">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                <span>Quick checklist before you report a bug</span>
              </p>
              <p className="mt-1.5 pl-5 text-sm leading-relaxed text-muted">
                You exported after logging in · the file is Netscape .txt · the profile row
                shows the same domain you are scanning · the session still works in your
                browser · the site is not blocking your region or IP. Then rescan.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-2xl border border-hairline bg-page px-6 py-5">
          <p className="text-sm text-muted">
            Need a walkthrough? The Settings screen labels every importer, and scan errors
            link back to the exact remediation step.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={COOKIE_EXTENSION_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 font-mono text-xs text-accent underline underline-offset-4 decoration-1 hover:decoration-2"
            >
              <span>Get cookies.txt LOCALLY</span>
              <ExternalLink className="w-3 h-3" />
            </a>
            <a
              href="#download"
              className="inline-flex items-center gap-1.5 font-mono text-xs text-ink/80 hover:text-accent"
            >
              <span>Download XakuMedia</span>
              <ArrowRight className="w-3 h-3" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
};
