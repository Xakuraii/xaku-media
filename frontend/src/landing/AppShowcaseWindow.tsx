import React, { useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  Minus,
  Moon,
  Sun,
  X,
} from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";
import { useTheme } from "./useTheme";
import { SHOWCASE_TABS, ShowcaseTabContent } from "./showcaseTabs";

export const AppShowcaseWindow: React.FC = () => {
  const [tabIndex, setTabIndex] = useState(0);
  const { theme } = useTheme();
  const currentTab = SHOWCASE_TABS[tabIndex];

  const handlePrev = () => {
    setTabIndex((prev) => (prev - 1 + SHOWCASE_TABS.length) % SHOWCASE_TABS.length);
  };

  const handleNext = () => {
    setTabIndex((prev) => (prev + 1) % SHOWCASE_TABS.length);
  };

  const groups = ["Workspace", "Sources", "System"];

  return (
    <div className="mt-14 sm:mt-16">
      {/* Carousel navigation controls */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handlePrev}
            aria-label="Previous app view"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-hairline bg-surface text-muted transition-colors hover:border-accent/40 hover:bg-raised hover:text-ink"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={handleNext}
            aria-label="Next app view"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-hairline bg-surface text-muted transition-colors hover:border-accent/40 hover:bg-raised hover:text-ink"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <span className="font-mono text-xs text-muted">
            <span className="font-semibold text-ink">{tabIndex + 1}</span> / {SHOWCASE_TABS.length}
            {" · "}
            <span className="text-ink">{currentTab.label}</span>
          </span>
        </div>

        <div className="flex items-center gap-1.5" role="tablist" aria-label="App interface tabs">
          {SHOWCASE_TABS.map((tab, idx) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={idx === tabIndex}
              aria-label={`Preview ${tab.label} UI`}
              onClick={() => setTabIndex(idx)}
              className={`h-2 rounded-full transition-all duration-150 ${
                idx === tabIndex
                  ? "w-6 bg-accent"
                  : "w-2 bg-hairline-strong hover:bg-muted"
              }`}
            />
          ))}
        </div>
      </div>

      {/* Desktop app window chrome matching v1.0.0 App.tsx */}
      <div className="overflow-hidden rounded-2xl border border-hairline bg-page shadow-pop">
        {/* Titlebar */}
        <div className="flex h-10 items-center justify-between border-b border-hairline bg-band pl-4 pr-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <img
              src="./XakuMedia.svg"
              alt=""
              className="h-4 w-4 shrink-0 object-contain"
              draggable={false}
            />
            <span className="truncate text-xs font-medium text-muted">
              XakuMedia v{RELEASE_CONFIG.version}
            </span>
          </div>
          <div className="flex items-center text-faint">
            <span className="grid h-7 w-7 place-items-center rounded-md">
              <Minus className="h-3 w-3" />
            </span>
            <span className="grid h-7 w-7 place-items-center rounded-md">
              <Maximize2 className="h-3 w-3" />
            </span>
            <span className="grid h-7 w-7 place-items-center rounded-md">
              <X className="h-3.5 w-3.5" />
            </span>
          </div>
        </div>

        {/* Non-interactive shell UI preview (use Left/Right controls above to browse) */}
        <div className="pointer-events-none flex min-h-[540px] select-none">
          {/* Persistent Sidebar matching App.tsx */}
          <aside className="hidden w-52 shrink-0 flex-col border-r border-hairline bg-band/70 p-2.5 lg:flex">
            <div className="mb-4 overflow-hidden rounded-xl border border-hairline bg-surface/85 px-2.5 py-2.5 shadow-sm">
              <div className="flex items-center gap-2.5">
                <img
                  src="./XakuMedia.svg"
                  alt=""
                  className="h-8 w-8 shrink-0 object-contain"
                  draggable={false}
                />
                <div className="min-w-0">
                  <span className="block truncate text-xs font-bold tracking-tight text-ink">
                    Xaku<span className="text-accent">Media</span>
                  </span>
                  <span className="block truncate font-mono text-[8px] uppercase tracking-[0.14em] text-faint">
                    Local media toolkit
                  </span>
                </div>
              </div>
            </div>

            <nav className="space-y-4">
              {groups.map((groupName) => (
                <div key={groupName} className="space-y-0.5">
                  <p className="px-2.5 pb-1 font-mono text-[9px] font-medium uppercase tracking-[0.16em] text-faint">
                    {groupName}
                  </p>
                  {SHOWCASE_TABS.filter((item) => item.group === groupName).map((item) => {
                    const Icon = item.icon;
                    const isActive = item.id === currentTab.id;
                    return (
                      <div
                        key={item.id}
                        className={`flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${
                          isActive
                            ? "border-hairline bg-surface text-ink shadow-sm"
                            : "border-transparent text-muted"
                        }`}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <Icon
                            className={`h-3.5 w-3.5 shrink-0 ${
                              isActive ? "text-accent" : "text-faint"
                            }`}
                          />
                          <span className="truncate">{item.label}</span>
                        </span>
                        {item.badge && (
                          <span className="rounded-full bg-accent px-1.5 py-0.5 font-mono text-[9px] font-bold text-on-accent">
                            {item.badge}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </nav>
          </aside>

          {/* Main Workspace Area */}
          <div className="flex min-w-0 flex-1 flex-col bg-page">
            {/* Header matching App.tsx (Workspace > CurrentTab + Theme icon) */}
            <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-hairline bg-band/70 px-5">
              <div className="flex min-w-0 items-center gap-1.5">
                <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-faint">
                  Workspace
                </span>
                <ChevronRight className="h-3 w-3 shrink-0 text-faint/60" />
                <span className="truncate text-xs font-semibold text-ink">{currentTab.label}</span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="grid h-7 w-7 place-items-center rounded-lg text-muted">
                  {theme === "dark" ? (
                    <Sun className="h-3.5 w-3.5" />
                  ) : (
                    <Moon className="h-3.5 w-3.5" />
                  )}
                </span>
              </div>
            </header>

            <div className="flex-1 p-5">
              <ShowcaseTabContent tab={currentTab.id} />
            </div>
          </div>
        </div>
      </div>

      <p className="mt-4 text-center font-mono text-xs text-faint">
        UI showcase of the {RELEASE_CONFIG.latestTag} desktop app — use the Left/Right arrows above
        to preview every tab.
      </p>
    </div>
  );
};
