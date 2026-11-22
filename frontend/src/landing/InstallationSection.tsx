import React from "react";
import { Info } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

export const InstallationSection: React.FC = () => {
  return (
    <section id="installation" className="border-t border-hairline bg-page transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-xl">
          <h2 className="section-title">Installation</h2>
          <p className="section-lead">Install with setup wizard or run portable directly.</p>
        </div>

        {/* Two distribution options */}
        <div className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-px rounded-2xl border border-hairline bg-hairline overflow-hidden">
          {/* Option 1: Installer */}
          <div className="bg-page p-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-display text-lg font-semibold text-ink">
                Setup installer
              </h3>
              <span className="font-mono text-xs text-faint shrink-0">
                {RELEASE_CONFIG.installer.sizeFormatted}
              </span>
            </div>
            <p className="mt-2 text-sm text-muted leading-relaxed">
              Standard Windows installer with Start Menu shortcut and uninstaller.
            </p>
            <a
              href={RELEASE_CONFIG.installer.downloadUrl}
              className="mt-4 inline-block font-mono text-xs text-accent underline underline-offset-4 decoration-1 hover:decoration-2 transition-all"
            >
              Download {RELEASE_CONFIG.installer.filename}
            </a>
          </div>

          {/* Option 2: Portable */}
          <div className="bg-page p-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-display text-lg font-semibold text-ink">
                Portable executable
              </h3>
              <span className="font-mono text-xs text-faint shrink-0">
                {RELEASE_CONFIG.portable.sizeFormatted}
              </span>
            </div>
            <p className="mt-2 text-sm text-muted leading-relaxed">
              Single standalone binary — run from any folder without installation.
            </p>
            <a
              href={RELEASE_CONFIG.portable.downloadUrl}
              className="mt-4 inline-block font-mono text-xs text-accent underline underline-offset-4 decoration-1 hover:decoration-2 transition-all"
            >
              Download {RELEASE_CONFIG.portable.filename}
            </a>
          </div>
        </div>

        {/* SmartScreen guidance */}
        <div className="mt-4 rounded-2xl border border-hairline bg-band p-5 sm:p-6 flex gap-4">
          <Info className="w-5 h-5 text-accent shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <h3 className="font-display text-sm font-semibold text-ink">
              Windows SmartScreen notice
            </h3>
            <p className="mt-1 text-sm text-muted leading-relaxed">
              Unsigned open-source binaries trigger SmartScreen on first launch. Click{" "}
              <strong className="text-ink font-semibold">More info</strong> →{" "}
              <strong className="text-accent font-semibold">Run anyway</strong>.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
};
