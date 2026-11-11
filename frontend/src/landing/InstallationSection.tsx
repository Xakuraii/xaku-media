import React from "react";
import { Info } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";

export const InstallationSection: React.FC = () => {
  return (
    <section id="installation" className="border-t border-hairline bg-page transition-colors duration-300">
      <div className="lc-container py-16 sm:py-24">
        <div className="max-w-xl">
          <h2 className="section-title">Installation &amp; setup</h2>
          <p className="section-lead">
            Choose between a standard desktop installation or a portable
            single-binary run.
          </p>
        </div>

        {/* Two distribution options */}
        <div className="mt-10 sm:mt-14 grid grid-cols-1 md:grid-cols-2 gap-px rounded-2xl border border-hairline bg-hairline overflow-hidden">
          {/* Option 1: Installer */}
          <div className="bg-page p-6 sm:p-7">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-display text-lg font-semibold text-ink">
                Setup installer
              </h3>
              <span className="font-mono text-xs text-faint shrink-0">
                {RELEASE_CONFIG.installer.sizeFormatted}
              </span>
            </div>
            <p className="mt-2.5 text-sm text-muted leading-relaxed">
              Standard Windows setup wizard. Creates Start Menu and desktop
              shortcuts with an automated uninstaller.
            </p>
            <a
              href={RELEASE_CONFIG.installer.downloadUrl}
              className="mt-4 inline-block font-mono text-xs text-accent underline underline-offset-4 decoration-1 hover:decoration-2 transition-all"
            >
              Download {RELEASE_CONFIG.installer.filename}
            </a>
          </div>

          {/* Option 2: Portable */}
          <div className="bg-page p-6 sm:p-7">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-display text-lg font-semibold text-ink">
                Portable executable
              </h3>
              <span className="font-mono text-xs text-faint shrink-0">
                {RELEASE_CONFIG.portable.sizeFormatted}
              </span>
            </div>
            <p className="mt-2.5 text-sm text-muted leading-relaxed">
              Zero-install standalone binary. Run directly from any folder or USB
              flash drive without writing to the Windows registry.
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
        <div className="mt-4 rounded-2xl border border-hairline bg-band p-6 sm:p-7 flex gap-4">
          <Info className="w-5 h-5 text-accent shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <h3 className="font-display text-sm font-semibold text-ink">
              Windows Defender SmartScreen prompt
            </h3>
            <p className="mt-1.5 text-sm text-muted leading-relaxed">
              Because XakuMedia is an independent open-source project without a paid
              corporate code-signing certificate, Windows SmartScreen may show an
              unrecognized app banner. To start the application, click{" "}
              <strong className="text-ink font-semibold">More info</strong> and then
              select <strong className="text-accent font-semibold">Run anyway</strong>.
              You can inspect the entire source code openly on GitHub.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
};
