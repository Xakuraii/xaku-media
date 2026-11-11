import React from "react";
import { ExternalLink } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

export const LandingFooter: React.FC = () => {
  const links = [
    { label: "Features", href: "#features" },
    { label: "How it works", href: "#workflow" },
    { label: "Requirements", href: "#requirements" },
    { label: "Installation", href: "#installation" },
    { label: "Privacy", href: "#security" },
    { label: "FAQ", href: "#faq" },
  ];

  return (
    <footer className="border-t border-hairline bg-band text-muted transition-colors duration-300">
      <div className="lc-container py-12">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-8 pb-9 border-b border-hairline">
          {/* Brand info */}
          <div className="space-y-2">
            <div className="flex items-center gap-2.5">
              <span className="grid place-items-center w-6 h-6 rounded-md bg-brand-white">
                <img src="XakuMedia.svg" alt="XakuMedia" className="w-full h-full" />
              </span>
              <span className="font-display font-semibold text-ink text-sm tracking-tight">
                XakuMedia
              </span>
              <span className="font-mono text-xs text-faint">
                {RELEASE_CONFIG.latestTag}
              </span>
            </div>
            <p className="text-sm text-muted">
              Local-first Windows bulk media downloader by XAKURAII.
            </p>
          </div>

          {/* Quick links */}
          <nav className="flex flex-wrap items-center gap-x-7 gap-y-2 text-sm">
            {links.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="hover:text-ink transition-colors duration-150"
              >
                {link.label}
              </a>
            ))}
            <a
              href={`https://github.com/${RELEASE_CONFIG.githubOwner}/${RELEASE_CONFIG.githubRepo}`}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-ink transition-colors duration-150 inline-flex items-center gap-1"
            >
              <span>GitHub</span>
              <ExternalLink className="w-3 h-3 text-faint" />
            </a>
          </nav>
        </div>

        {/* Disclaimer */}
        <div className="pt-7 flex flex-col sm:flex-row items-center justify-between gap-2 font-mono text-xs text-faint">
          <span>Copyright © 2026 XAKURAII. Open source.</span>
          <span className="text-center sm:text-right">
            For personal media archiving. Not affiliated with third-party platforms.
          </span>
        </div>
      </div>
    </footer>
  );
};
