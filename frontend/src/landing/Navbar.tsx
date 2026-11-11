import React, { useState } from "react";
import { Download, Github, Menu, X, Sun, Moon } from "lucide-react";
import { RELEASE_CONFIG } from "./downloadConfig";
import { useTheme } from "./useTheme";

export const Navbar: React.FC = () => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();

  const navLinks = [
    { label: "Features", href: "#features" },
    { label: "How it works", href: "#workflow" },
    { label: "Requirements", href: "#requirements" },
    { label: "Installation", href: "#installation" },
    { label: "FAQ", href: "#faq" },
  ];

  const githubUrl = `https://github.com/${RELEASE_CONFIG.githubOwner}/${RELEASE_CONFIG.githubRepo}`;

  return (
    <header className="sticky top-0 z-50 border-b border-hairline bg-page/80 backdrop-blur-md transition-colors duration-200">
      <div className="lc-container h-16 flex items-center justify-between">
        {/* Brand logo & name */}
        <a href="#" className="flex items-center space-x-2.5">
          <span className="grid place-items-center w-7 h-7 rounded-md bg-brand-white">
            <img
              src="XakuMedia.svg"
              alt="XakuMedia logo"
              className="w-full h-full"
            />
          </span>
          <span className="font-display font-semibold text-base tracking-tight text-ink">
            Xaku<span className="text-accent">Media</span>
          </span>
        </a>

        {/* Desktop navigation links */}
        <nav className="hidden md:flex items-center space-x-7 text-sm font-medium text-muted">
          {navLinks.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="hover:text-ink transition-colors duration-150 py-1"
            >
              {item.label}
            </a>
          ))}
        </nav>

        {/* Right action buttons */}
        <div className="hidden md:flex items-center space-x-1.5">
          {/* Light / dark mode toggle */}
          <button
            type="button"
            onClick={toggleTheme}
            className="grid place-items-center w-9 h-9 rounded-lg text-muted hover:text-ink hover:bg-raised transition-colors duration-150"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? (
              <Sun className="w-[18px] h-[18px]" />
            ) : (
              <Moon className="w-[18px] h-[18px]" />
            )}
          </button>

          {/* GitHub repository link */}
          <a
            href={githubUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="grid place-items-center w-9 h-9 rounded-lg text-muted hover:text-ink hover:bg-raised transition-colors duration-150"
            title="GitHub repository"
          >
            <Github className="w-[18px] h-[18px]" />
          </a>

          {/* Download CTA */}
          <a
            href="#download"
            className="flex items-center space-x-1.5 ml-2 px-3.5 py-2 rounded-lg bg-accent text-on-accent hover:bg-accent-vivid font-semibold text-xs transition-colors duration-150"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download</span>
          </a>
        </div>

        {/* Mobile actions */}
        <div className="flex md:hidden items-center space-x-1">
          <button
            type="button"
            onClick={toggleTheme}
            className="grid place-items-center w-9 h-9 rounded-lg text-muted hover:text-ink transition-colors duration-150"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? (
              <Sun className="w-[18px] h-[18px]" />
            ) : (
              <Moon className="w-[18px] h-[18px]" />
            )}
          </button>
          <a
            href="#download"
            className="grid place-items-center w-9 h-9 rounded-lg bg-accent text-on-accent"
            title="Download"
          >
            <Download className="w-4 h-4" />
          </a>
          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="grid place-items-center w-9 h-9 rounded-lg border border-hairline bg-surface text-muted hover:text-ink transition-colors duration-150"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileMenuOpen}
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden border-b border-hairline bg-page px-4 pt-2 pb-5 space-y-3">
          <nav className="flex flex-col space-y-1">
            {navLinks.map((item) => (
              <a
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className="px-3 py-2.5 rounded-lg text-sm font-medium text-muted hover:text-ink hover:bg-raised transition-colors duration-150"
              >
                {item.label}
              </a>
            ))}
          </nav>
          <div className="pt-3 border-t border-hairline flex items-center justify-between px-3">
            <a
              href={githubUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-muted hover:text-ink transition-colors duration-150 flex items-center space-x-1.5"
            >
              <Github className="w-4 h-4" />
              <span>GitHub</span>
            </a>
            <a
              href="#download"
              onClick={() => setMobileMenuOpen(false)}
              className="px-3.5 py-2 rounded-lg bg-accent text-on-accent text-xs font-semibold"
            >
              Download {RELEASE_CONFIG.latestTag}
            </a>
          </div>
        </div>
      )}
    </header>
  );
};
