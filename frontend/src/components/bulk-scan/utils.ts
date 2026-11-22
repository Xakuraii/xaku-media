import type {
  DiscoveredMediaItem,
  MediaFormatInfoPayload,
  ScanProgressPayload,
} from "../../../../desktop/shared/types";
import type { MediaFilter, PostWithScan } from "./types";

export const EMPTY_PROGRESS: ScanProgressPayload = {
  posts_discovered: 0,
  media_discovered: 0,
  images_discovered: 0,
  videos_discovered: 0,
  pages_fetched: 0,
  duplicates_skipped: 0,
  current_page: null,
  limit_applied: false,
  total_posts: null,
  total_media: null,
  total_pages: null,
  phase: "discovering",
};

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function formatBytes(value?: number | null): string {
  if (!value || value <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function dedupePosts<T extends { id: string }>(posts: T[]): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const post of posts) {
    if (seen.has(post.id)) continue;
    seen.add(post.id);
    result.push(post);
  }
  return result;
}

export function parseUrls(text: string): string[] {
  const found: string[] = [];
  for (const token of text.split(/[\s,]+/)) {
    const cleaned = token.trim().replace(/^[("'<[]+/, "").replace(/[)"'>\],.;]+$/, "");
    if (!cleaned) continue;
    if (/^https?:\/\//i.test(cleaned)) {
      found.push(cleaned);
      continue;
    }
    // Accept scheme-less links such as "tiktok.com/@user" or "vm.tiktok.com/…".
    if (
      /^[a-z0-9-]+(\.[a-z0-9-]+)+(\/|\?|#|$)/i.test(cleaned) &&
      !/^[^/\s]+@[^/\s]+$/.test(cleaned)
    ) {
      found.push(`https://${cleaned}`);
    }
  }
  return Array.from(new Set(found));
}

const MACROBLOCK_TOLERANCE = 16;

function resolutionHeight(resolution?: string | null): number {
  if (!resolution) return 0;
  const dim = resolution.match(/(\d{3,4})\s*[xX×]\s*(\d{3,4})/);
  if (dim) return Math.min(parseInt(dim[1], 10), parseInt(dim[2], 10));
  const match = resolution.match(/(\d{3,4})/);
  return match ? parseInt(match[1], 10) : 0;
}

/**
 * Effective quality tier for a stream. Portrait 1080x1920 videos (TikTok,
 * Shorts, Reels) are 1080p Full HD — using the short edge prevents a 1080p
 * resolution cap from rejecting 1080x1920 and dropping to 480p/360p.
 */
function qualityTier(format: MediaFormatInfoPayload): number {
  if (format.width && format.height) {
    return Math.min(format.width, format.height);
  }
  if (format.height) return format.height;
  const parsed = resolutionHeight(format.resolution);
  if (parsed > 0) return parsed;
  if (format.width) return Math.round((format.width * 9) / 16);
  return 0;
}

function hasVideo(format: MediaFormatInfoPayload): boolean {
  return Boolean(format.video_codec && format.video_codec !== "none");
}

function hasAudio(format: MediaFormatInfoPayload): boolean {
  return Boolean(format.audio_codec && format.audio_codec !== "none");
}

function formatSize(format: MediaFormatInfoPayload): number {
  return format.filesize_bytes ?? 0;
}

/**
 * Rank candidate video tracks: highest quality tier first, then complete
 * streams (no FFmpeg merge), then higher fps, then largest file.
 * `targetHeight` is Infinity for "best".
 */
function pickVideoTrack(
  tracks: MediaFormatInfoPayload[],
  targetHeight: number
): MediaFormatInfoPayload | null {
  if (tracks.length === 0) return null;
  const ranked = [...tracks].sort(
    (a, b) =>
      qualityTier(b) - qualityTier(a) ||
      Number(hasAudio(b)) - Number(hasAudio(a)) ||
      (b.fps || 0) - (a.fps || 0) ||
      formatSize(b) - formatSize(a)
  );
  if (!Number.isFinite(targetHeight)) return ranked[0];
  const known = ranked.filter((format) => qualityTier(format) > 0);
  const within = known.filter(
    (format) => qualityTier(format) <= targetHeight + MACROBLOCK_TOLERANCE
  );
  if (within.length > 0) return within[0];
  if (known.length > 0) return known[known.length - 1];
  return ranked[0];
}

export function chooseFormat(
  item: DiscoveredMediaItem,
  preferredResolution?: string | null
): MediaFormatInfoPayload | null {
  const formats = item.available_formats || [];
  if (formats.length === 0) return null;

  // Only formats with a direct URL can be downloaded. Providers occasionally
  // omit URLs; fall back to the raw list so cards still show useful metadata.
  const downloadable = formats.filter((format) => Boolean(format.url));
  const pool = downloadable.length > 0 ? downloadable : formats;

  if (item.media_type === "video") {
    const pref = (preferredResolution || "").toLowerCase();
    // No preference means "best": an empty string must not collapse to a
    // 0px ceiling that would select the lowest-resolution track.
    const targetHeight =
      !pref || pref === "best" || pref === "original"
        ? Infinity
        : resolutionHeight(pref) || Infinity;

    const videoTracks = pool.filter(hasVideo);
    const hasAudioPartner = pool.some((format) => hasAudio(format) && !hasVideo(format));
    // A video-only track is usable only when a matching audio-only stream
    // exists; otherwise it would download as a silent file.
    const playable = videoTracks.filter((format) => hasAudio(format) || hasAudioPartner);
    const chosen = pickVideoTrack(playable, targetHeight);
    if (chosen) return chosen;
  }

  const direct = pool.find((format) => !format.requires_merge && Boolean(format.url));
  return direct ?? pool[0] ?? null;
}

export function postMatchesFilter(post: PostWithScan, filter: MediaFilter): boolean {
  if (filter === "all") return true;
  if (filter === "album") return post.media_items.length > 1;
  if (filter === "image") return post.media_items.some((item) => item.media_type === "image");
  return post.media_items.some((item) => item.media_type === "video");
}

export function visibleMedia(post: PostWithScan, filter: MediaFilter): DiscoveredMediaItem[] {
  if (filter === "image") return post.media_items.filter((item) => item.media_type === "image");
  if (filter === "video") return post.media_items.filter((item) => item.media_type === "video");
  return post.media_items;
}

export function filterPosts(
  posts: PostWithScan[],
  filter: MediaFilter,
  search: string,
  focusedJobId: string | null
): PostWithScan[] {
  const query = search.trim().toLowerCase();
  return posts.filter((post) => {
    if (focusedJobId && post._job_id !== focusedJobId) return false;
    if (!postMatchesFilter(post, filter)) return false;
    if (!query) return true;
    const haystack = [
      post.title,
      post.author,
      post.post_url,
      ...post.media_items.map((item) => item.title),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}

export function countPosts(posts: PostWithScan[]) {
  const media = posts.flatMap((post) => post.media_items);
  return {
    posts: posts.length,
    media: media.length,
    images: media.filter((item) => item.media_type === "image").length,
    videos: media.filter((item) => item.media_type === "video").length,
    albums: posts.filter((post) => post.media_items.length > 1).length,
  };
}

export function statusTone(status: string): string {
  if (status === "completed")
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (status === "running" || status === "queued")
    return "border-accent/30 bg-accent/10 text-accent";
  if (status === "cancelled")
    return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300";
}
