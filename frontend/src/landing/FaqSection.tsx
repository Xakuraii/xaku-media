import React, { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

const COOKIE_EXTENSION_URL =
  "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc";

export const FaqSection: React.FC = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  const faqs: Array<{ q: string; a: React.ReactNode }> = [
    {
      q: "Is XakuMedia free?",
      a: "Yes — 100% free, local-first, and open-source with no subscriptions or ads.",
    },
    {
      q: "How do Skip and Download Library work across PCs?",
      a: "Each folder saves a small xakumedia-library.json file recording downloaded and skipped items. Copy your download folder to another PC and XakuMedia picks up right where you left off.",
    },
    {
      q: "Why do some sites need cookies?",
      a: (
        <>
          Signed-in platforms require your session cookies. Import Netscape{" "}
          <span className="font-mono text-ink">cookies.txt</span> in Settings → Session Credentials ({" "}
          <a href="#cookies" className="text-accent underline underline-offset-4">
            see guide
          </a>{" "}
          or{" "}
          <a
            href={COOKIE_EXTENSION_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline underline-offset-4"
          >
            get extension
          </a>
          ).
        </>
      ),
    },
    {
      q: "Why does Windows SmartScreen warn on first launch?",
      a: "The binary is not commercially code-signed yet. Click More info → Run anyway, or build directly from source on GitHub.",
    },
    {
      q: "Do I need to install Python or FFmpeg?",
      a: "No — Python 3.12 and FFmpeg are bundled inside both the installer and portable build.",
    },
    {
      q: "What are the rules for responsible use?",
      a: "Use XakuMedia strictly at your own responsibility for personal offline archiving. Respect creators, copyright laws, and site terms — never use it to redistribute content without permission or bypass paywalls.",
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
