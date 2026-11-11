import React, { useEffect, useState } from "react";
import { Navbar } from "./Navbar";
import { HeroSection } from "./HeroSection";
import { FeaturesSection } from "./FeaturesSection";
import { WorkflowSection } from "./WorkflowSection";
import { RequirementsSection } from "./RequirementsSection";
import { InstallationSection } from "./InstallationSection";
import { SecurityPrivacySection } from "./SecurityPrivacySection";
import { ReleaseChangelogSection } from "./ReleaseChangelogSection";
import { FaqSection } from "./FaqSection";
import { LandingFooter } from "./LandingFooter";
import { ChevronUp } from "lucide-react";

export const LandingPage: React.FC = () => {
  const [showScrollTop, setShowScrollTop] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setShowScrollTop(window.scrollY > 400);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="min-h-screen bg-page text-ink font-sans antialiased transition-colors duration-300">
      {/* Keyboard users can jump past the navigation */}
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:px-4 focus:py-2 focus:rounded-lg focus:bg-accent focus:text-on-accent focus:text-sm focus:font-semibold"
      >
        Skip to content
      </a>

      {/* Top navigation */}
      <Navbar />

      {/* Main sections */}
      <main id="content">
        {/* 1. Hero & download */}
        <HeroSection />

        {/* 2. Key features */}
        <FeaturesSection />

        {/* 3. Workflow - how it works */}
        <WorkflowSection />

        {/* 4. Windows system requirements */}
        <RequirementsSection />

        {/* 5. Installation & troubleshooting */}
        <InstallationSection />

        {/* 6. Security, privacy & limits */}
        <SecurityPrivacySection />

        {/* 7. Current version & changelog */}
        <ReleaseChangelogSection />

        {/* 8. Frequently asked questions */}
        <FaqSection />
      </main>

      {/* Footer */}
      <LandingFooter />

      {/* Floating scroll-to-top button */}
      {showScrollTop && (
        <button
          type="button"
          onClick={scrollToTop}
          className="fixed bottom-6 right-6 z-40 grid place-items-center w-11 h-11 rounded-full border border-hairline bg-surface/90 text-muted shadow-pop backdrop-blur-md transition-all duration-200 hover:text-ink hover:scale-105 active:scale-95"
          aria-label="Scroll to top"
        >
          <ChevronUp className="w-5 h-5" />
        </button>
      )}
    </div>
  );
};
