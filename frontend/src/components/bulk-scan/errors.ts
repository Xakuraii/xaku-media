import type { ErrorAction, ScanErrorInfo } from "./types";

const COOKIE_SETTINGS: ErrorAction = {
  label: "Open cookie settings",
  kind: "settings",
  section: "cookies",
};

const COOKIE_DOCS: ErrorAction = {
  label: "Get cookies.txt (Chrome/Edge)",
  kind: "external",
  url: "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc",
};

const COOKIE_STEPS = [
  "Install “Get cookies.txt LOCALLY” in Chrome/Edge (or use the Firefox equivalent).",
  "Open the site in that browser while signed in, then export this site's cookies.txt.",
  "In XakuMedia open Settings → Cookies & Sessions and paste the text (or import the file).",
  "Scan the same URL again — the saved profile is applied automatically.",
];

function cookieHint(site?: string): string {
  return site ? ` ${site} usually requires a signed-in session.` : "";
}

function hasFlag(details: Record<string, unknown> | undefined, key: string): boolean {
  return Boolean(details && details[key]);
}

export function explainScanFailure(
  code?: string | null,
  message?: string | null,
  details?: Record<string, unknown>
): ScanErrorInfo {
  const site = typeof details?.site === "string" ? details.site : undefined;
  const requiresCookies =
    hasFlag(details, "requires_cookies") || details?.remediation === "add_cookies";
  const hasCookies = hasFlag(details, "has_cookies");
  const normalizedCode = (code || "").toUpperCase();
  const text = (message || "").toLowerCase();

  if (normalizedCode === "PRIVATE_MEDIA" || requiresCookies) {
    return {
      title: hasCookies ? "Cookies may have expired" : "This source needs cookies",
      summary:
        message ||
        `The site did not return public media.${cookieHint(site)}`,
      steps: hasCookies
        ? [
            "Open Settings → Cookies & Sessions.",
            "Re-import the cookie profile for this site (the saved session may have expired).",
            "Scan the URL again.",
          ]
        : COOKIE_STEPS,
      actions: [COOKIE_SETTINGS, COOKIE_DOCS],
      code,
    };
  }

  if (normalizedCode === "MEDIA_UNAVAILABLE") {
    return {
      title: "No media found",
      summary:
        message ||
        "The link returned no downloadable media. It may be empty, private, or removed.",
      steps: [
        "Check that the URL opens in a browser without signing in.",
        "Try a profile or channel URL instead of a single post.",
        "If the page needs a login, add a cookie profile and scan again.",
      ],
      actions: [COOKIE_SETTINGS, COOKIE_DOCS],
      code,
    };
  }

  if (normalizedCode === "UNSUPPORTED_SOURCE") {
    return {
      title: "This link is not supported",
      summary:
        message ||
        "No extractor recognises this URL. Use a profile, channel, playlist, gallery, or direct media URL.",
      steps: [
        "YouTube channels, playlists, and videos are verified to work.",
        "For other sites, open the profile page and copy that URL (not a search or home page).",
        "Direct image/video links must end with a file extension such as .jpg or .mp4.",
      ],
      actions: [],
      code,
    };
  }

  if (normalizedCode === "RATE_LIMITED" || text.includes("rate limit")) {
    return {
      title: "The site is rate limiting requests",
      summary: message || "Too many requests were sent in a short time.",
      steps: [
        "Wait a minute or two before scanning again.",
        "Lower the max posts/media limits for this source.",
        "Add a cookie profile if the limit applies to signed-out visitors.",
      ],
      actions: [COOKIE_SETTINGS],
      code,
    };
  }

  if (
    normalizedCode === "NETWORK_TIMEOUT" ||
    normalizedCode === "NETWORK_ERROR" ||
    text.includes("timed out") ||
    text.includes("connection")
  ) {
    return {
      title: "Network request failed",
      summary: message || "The host did not respond before the timeout.",
      steps: [
        "Check your internet connection and whether the site opens in a browser.",
        "Retry the scan; transient timeouts are common on large profiles.",
        "Disable a VPN/proxy if the site blocks it.",
      ],
      actions: [],
      code,
    };
  }

  if (normalizedCode === "SSRF_BLOCKED") {
    return {
      title: "Blocked for security",
      summary: message || "Localhost and private network addresses cannot be scanned.",
      steps: ["Use a public http(s) URL.", "This guard cannot be disabled."],
      actions: [],
      code,
    };
  }

  if (normalizedCode === "URL_CLASSIFICATION_ERROR") {
    return {
      title: "The URL could not be read",
      summary: message || "The URL is malformed or unreachable.",
      steps: ["Copy the full URL from the browser address bar.", "Make sure it starts with http:// or https://."],
      actions: [],
      code,
    };
  }

  return {
    title: "Scan failed",
    summary: message || "The scan stopped before it could discover media.",
    steps: [
      "Retry once; some sites fail intermittently.",
      "If it keeps failing, try a profile/channel URL instead of a single post.",
      "Auth-heavy sites may need a cookie profile.",
    ],
    actions: [COOKIE_SETTINGS],
    code,
  };
}

export function explainStartFailure(error: unknown): ScanErrorInfo {
  const message = error instanceof Error ? error.message : String(error);
  return explainScanFailure(null, message);
}

export function explainDownloadFailure(error: unknown): ScanErrorInfo {
  const message = error instanceof Error ? error.message : String(error);
  const text = message.toLowerCase();

  if (text.includes("outside the authorized download directory")) {
    return {
      title: "Download folder is not allowed",
      summary: message,
      steps: [
        "Downloads must be saved inside the app's authorized download folder.",
        "Clear the custom destination or pick a folder inside the default Downloads/XakuMedia folder.",
      ],
      actions: [],
    };
  }

  if (text.includes("no downloadable") || text.includes("no media")) {
    return {
      title: "Nothing to download",
      summary: message,
      steps: [
        "Select at least one item with an image or video attachment.",
        "If the item has no formats, rescan the source; the site may need cookies.",
      ],
      actions: [COOKIE_SETTINGS],
    };
  }

  if (text.includes("media not found") || text.includes("404")) {
    return {
      title: "The media file is no longer available",
      summary: message,
      steps: ["Rescan the source to refresh URLs.", "Expired CDN links need a fresh scan."],
      actions: [],
    };
  }

  if (text.includes("ffmpeg")) {
    return {
      title: "FFmpeg is required for this download",
      summary: message,
      steps: [
        "Install FFmpeg or point the app at an installed copy in Settings.",
        "Retry the download after FFmpeg is detected.",
      ],
      actions: [],
    };
  }

  return {
    title: "Download failed",
    summary: message,
    steps: ["Retry the download.", "Rescan the source if the link expired.", "Check free disk space."],
    actions: [],
  };
}
