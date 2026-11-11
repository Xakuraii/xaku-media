import React, { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

export const FaqSection: React.FC = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  const faqs = [
    {
      q: "Is XakuMedia completely free?",
      a: "Yes. XakuMedia is 100% free and open-source. There are no subscriptions, paid upgrades, or advertisements.",
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
      a: "Yes. You can configure global speed limits (such as 512 KB/s, 2 MB/s, 10 MB/s, or Unlimited) from Settings or the active Downloads toolbar to avoid saturating your bandwidth.",
    },
    {
      q: "Can I download 4K video streams?",
      a: "Yes. When a source provides 4K or high-framerate streams, XakuMedia detects them and uses bundled FFmpeg to merge high-res video and audio tracks losslessly (-c copy) into MP4, MKV, or WebM.",
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
            Quick answers about installation, privacy, and media downloading.
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
                    <p className="pb-5 pr-6 sm:pr-10 text-sm text-muted leading-relaxed">
                      {faq.a}
                    </p>
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
