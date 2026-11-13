import { flushSync } from "react-dom";

const DEFAULT_DURATION_MS = 400;

let isTransitioning = false;

function getCircleClipPaths(
  cx: number,
  cy: number,
  maxRadius: number,
  viewportWidth: number,
  viewportHeight: number
): [string, string] {
  const safeW = Math.max(1, viewportWidth);
  const safeH = Math.max(1, viewportHeight);
  const point = `${(cx / safeW) * 100}% ${(cy / safeH) * 100}%`;
  // circle() percentage radii resolve against hypot(w, h) / sqrt(2) of the snapshot box.
  const radiusPercent =
    (maxRadius / (Math.hypot(safeW, safeH) / Math.SQRT2)) * 100;

  return [`circle(0% at ${point})`, `circle(${radiusPercent}% at ${point})`];
}

/**
 * Runs a theme DOM/state update inside a circular View Transition expanding
 * from the center of `origin` (or the viewport center if omitted).
 */
export function runThemeCircleTransition(
  apply: () => void,
  origin?: HTMLElement | null,
  duration: number = DEFAULT_DURATION_MS
): void {
  if (
    typeof document === "undefined" ||
    typeof window === "undefined" ||
    typeof document.startViewTransition !== "function" ||
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  ) {
    apply();
    return;
  }

  if (isTransitioning) return;

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  let cx = viewportWidth / 2;
  let cy = viewportHeight / 2;

  if (origin && origin.isConnected) {
    const rect = origin.getBoundingClientRect();
    if (rect.width > 0 || rect.height > 0) {
      cx = rect.left + rect.width / 2;
      cy = rect.top + rect.height / 2;
    }
  }

  const maxRadius = Math.hypot(
    Math.max(cx, viewportWidth - cx),
    Math.max(cy, viewportHeight - cy)
  );

  const [startClip, endClip] = getCircleClipPaths(
    cx,
    cy,
    maxRadius,
    viewportWidth,
    viewportHeight
  );

  const root = document.documentElement;
  isTransitioning = true;
  root.dataset.magicuiThemeVt = "active";
  root.style.setProperty("--magicui-theme-toggle-vt-duration", `${duration}ms`);
  root.style.setProperty("--magicui-theme-vt-clip-from", startClip);

  const cleanup = () => {
    delete root.dataset.magicuiThemeVt;
    root.style.removeProperty("--magicui-theme-toggle-vt-duration");
    root.style.removeProperty("--magicui-theme-vt-clip-from");
    isTransitioning = false;
  };

  let transition: ViewTransition;
  try {
    transition = document.startViewTransition(() => {
      flushSync(() => {
        apply();
      });
    });
  } catch {
    cleanup();
    apply();
    return;
  }

  transition.finished.finally(cleanup);

  transition.ready
    .then(() => {
      root.animate(
        {
          clipPath: [startClip, endClip],
        },
        {
          duration,
          easing: "ease-in-out",
          fill: "forwards",
          pseudoElement: "::view-transition-new(root)",
        }
      );
    })
    .catch(() => {
      // Aborted or skipped transitions still trigger transition.finished -> cleanup.
    });
}

