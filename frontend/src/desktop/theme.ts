import { useEffect, useRef, useState } from "react";
import { runThemeCircleTransition } from "../lib/themeTransition";

export type ThemePreference = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

/** localStorage key mirrored from the SQLite preference for pre-paint use. */
const PREPAINT_KEY = "xakumedia_desktop_theme";

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "system") return systemPrefersDark() ? "dark" : "light";
  return preference;
}

/** Apply the resolved theme to <html> and keep the browser chrome in sync. */
export function applyTheme(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(preference);
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.classList.toggle("light", resolved === "light");
  root.dataset.theme = resolved;

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", resolved === "dark" ? "#0b0c10" : "#f4f5f7");
  }

  try {
    localStorage.setItem(PREPAINT_KEY, preference);
  } catch {
    // Ignore storage failures (private mode / locked profile).
  }

  return resolved;
}

/**
 * Desktop theme controller. The preference is persisted in SQLite by the
 * Python engine and mirrored to localStorage so the pre-paint script can
 * avoid a flash on the next launch.
 */
export function useDesktopTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>("dark");
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");
  const [ready, setReady] = useState(false);
  // If the user toggles before the stored preference resolves, their click wins.
  const interacted = useRef(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      let pref: ThemePreference = "dark";
      try {
        const prefs = await window.api?.getPreferences?.();
        const stored = prefs?.theme;
        if (stored === "dark" || stored === "light" || stored === "system") {
          pref = stored;
        }
      } catch (err) {
        console.error("Failed to load theme preference:", err);
      }
      if (cancelled || interacted.current) {
        setReady(true);
        return;
      }
      setPreferenceState(pref);
      setResolved(applyTheme(pref));
      setReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Follow OS changes live while the preference is "system".
  useEffect(() => {
    if (preference !== "system" || typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(applyTheme("system"));
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [preference]);

  /**
   * Apply a theme immediately and mirror it to localStorage. The caller may
   * opt out of persistence when it already writes preferences through its own
   * update call (e.g. the Settings form).
   */
  const setPreference = (
    next: ThemePreference,
    options?: { persist?: boolean; origin?: HTMLElement | null }
  ) => {
    interacted.current = true;
    const currentResolved: ResolvedTheme =
      typeof document !== "undefined" && document.documentElement.classList.contains("dark")
        ? "dark"
        : "light";
    const nextResolved = resolveTheme(next);

    const commit = () => {
      setPreferenceState(next);
      setResolved(applyTheme(next));
    };

    if (options?.origin && nextResolved !== currentResolved) {
      runThemeCircleTransition(commit, options.origin);
    } else {
      commit();
    }

    if (options?.persist === false) return;
    window.api?.updatePreferences?.({ theme: next }).catch((err) => {
      console.error("Failed to persist theme preference:", err);
    });
  };

  return { preference, resolved, ready, setPreference };
}
