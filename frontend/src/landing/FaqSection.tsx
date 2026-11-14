import React, { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

const COOKIE_EXTENSION_URL =
  "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc";

export const FaqSection: React.FC = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  const faqs: Array<{ q: string; a: React.ReactNode }> = [
    {
      q: "Is XakuMedia completely free?",
      a: "Yes. XakuMedia is 100% free and open-source. There are no subscriptions, paid upgrades, or advertisements.",
    },
    {
      q: "Can I scan an entire profile or channel?",
      a: "Yes, for supported sources. Paste profile, channel, album, or post URLs into the bulk scan box (one per line) and set optional post/media limits. Jobs page through results and stream new posts into the gallery while the scan is still running. Coverage depends on the provider, and auth-heavy sites may need cookies.",
    },
    {
      q: "Why does a site say it needs cookies?",
      a: (
        <>
          Some sources only serve media to a signed-in session. Export a Netscape{" "}
          <span className="font-mono text-ink">cookies.txt</span> with the{" "}
          <a
            href={COOKIE_EXTENSION_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline underline-offset-4 decoration-1 hover:decoration-2"
          >
            Get cookies.txt LOCALLY
          </a>{" "}
          browser extension, then import it in Settings → Session Credentials (Chrome is
          the default browser choice). Cookie files stay on your machine. If a scan still
          fails, the error panel names the cause and the next step.{" "}
          <a
            href="#cookies"
            className="text-accent underline underline-offset-4 decoration-1 hover:decoration-2"
          >
            Read the full cookie guide
          </a>{" "}
          for export steps, format, and troubleshooting.
        </>
      ),
    },
    {
      q: "What does “Select new” do?",
      a: "It selects only the media the app has not downloaded before, so rescanning a profile or channel is a one-click incremental download. Already-downloaded cards are marked with a badge, and Select all still picks everything in the current view.",
    },
    {
      q: "Why does Windows SmartScreen show an unrecognized app prompt?",
      a: "XakuMedia is a community project distributed without a costly commercial Extended Validation (EV) certificate ($500+/year). Windows displays this default warning for any new unsigned binary. Simply click 'More info' and then 'Run anyway'. All code is fully open and auditable on GitHub.",
    },
    {
      q: "Do I need to install Python or FFmpeg separately?",
      a: "No. Python 3.12 embedded runtime and FFmpeg/FFprobe binaries are bundled directly inside the setup and portable executables. No configuration or PATH adjustments are needed.",
    },
    {
      q: "Can I limit the download speed?",
      a: "Yes. Set a global bandwidth limit (such as 500 KB/s, 2 MB/s, 10 MB/s, or Unlimited) in Settings or from the Downloads toolbar. The limiter is shared across all active workers and applies immediately.",
    },
    {
      q: "Can I download 4K video streams?",
      a: "Yes. When a source provides 4K or high-framerate streams, XakuMedia detects them and uses bundled FFmpeg to merge high-res video and audio tracks losslessly (-c copy) into MP4, MKV, or WebM. Choose the preferred resolution in Settings; the scan gallery previews the size for that quality.",
    },
    {
      q: "Where can I report bugs or suggest features?",
      a: "You can open an issue directly in our official GitHub repository. Feedback and community contributions are always welcome.",
    },
  ];

  return (
    <section id="faq" className="border-t border-hairline bg-page transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-xl">
          <h2 className="section-title">Frequently asked questions</h2>
          <p className="section-lead">
            Quick answers about bulk scanning, cookies, privacy, and downloads.
          </p>
        </div>

        {/* Document-style accordion list */}
        <div className="mt-10 sm:mt-14 max-w-3xl divide-y divide-hairline border-y border-hairline">
          {faqs.map((faq, idx) => {
            const isOpen = openIndex === idx;
            const panelId = `faq-panel-${idx}`;
            return (
              <div key={faq.q}>
                <button
                  type="button"
                  onClick={() => setOpenIndex(isOpen ? null : idx)}
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  className="group w-full flex items-center justify-between gap-4 py-5 text-left"
                >
                  <span
                    className={`text-sm sm:text-[15px] font-medium transition-colors duration-150 ${
                      isOpen ? "text-accent" : "text-ink group-hover:text-accent"
                    }`}
                  >
                    {faq.q}
                  </span>
                  <ChevronDown
                    className={`w-4 h-4 shrink-0 transition-transform duration-200 ${
                      isOpen ? "rotate-180 text-accent" : "text-faint"
                    }`}
                    aria-hidden="true"
                  />
                </button>
                {/* Height animation via grid-template-rows; falls back to an
                    instant toggle where that property is not animatable. */}
                <div
                  id={panelId}
                  className={`grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none ${
                    isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                  }`}
                >
                  <div className="overflow-hidden">
                    <div className="pb-5 pr-6 sm:pr-10 text-sm text-muted leading-relaxed">
                      {faq.a}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Support link */}
        <p className="mt-8 text-sm text-muted">
          Need more help?{" "}
          <a
            href={`https://github.com/${RELEASE_CONFIG.githubOwner}/${RELEASE_CONFIG.githubRepo}/issues`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline underline-offset-4 decoration-1 hover:decoration-2 transition-all inline-flex items-center gap-1"
          >
            <span>Ask a question on GitHub Issues</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </p>
      </div>
    </section>
  );
};
