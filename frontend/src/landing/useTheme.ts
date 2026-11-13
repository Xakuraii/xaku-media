import { useEffect, useRef, useState } from "react";
import { runThemeCircleTransition } from "../lib/themeTransition";

export type Theme = "light" | "dark";

const STORAGE_KEY = "xakumedia_theme";

function readStoredTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  } catch {
    return null;
  }
}

function getInitialTheme(): Theme {
  const stored = readStoredTheme();
  if (stored) return stored;

  // The Electron desktop shell is authored dark; the public site follows
  // the visitor's OS preference until they make an explicit choice.
  if (typeof window !== "undefined" && Boolean(window.api)) return "dark";
  if (typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "dark";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", theme === "dark" ? "#0b0c10" : "#ffffff");
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const hasExplicitChoice = useRef<boolean>(readStoredTheme() !== null);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Track OS-level changes while the visitor has not picked a theme themselves.
  useEffect(() => {
    if (hasExplicitChoice.current || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => {
      if (!hasExplicitChoice.current) {
        setTheme(event.matches ? "dark" : "light");
      }
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const toggleTheme = (origin?: HTMLElement | null) => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    hasExplicitChoice.current = true;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore localStorage exceptions in private browsing.
    }
    runThemeCircleTransition(() => {
      applyTheme(next);
      setTheme(next);
    }, origin);
  };

  return { theme, toggleTheme };
}
