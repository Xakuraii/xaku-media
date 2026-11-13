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
  const found = text
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter((value) => /^https?:\/\//i.test(value));
  return Array.from(new Set(found));
}

function resolutionHeight(resolution?: string | null): number {
  if (!resolution) return 0;
  const match = resolution.match(/(\d{3,4})/);
  return match ? parseInt(match[1], 10) : 0;
}

export function chooseFormat(
  item: DiscoveredMediaItem,
  preferredResolution?: string | null
): MediaFormatInfoPayload | null {
  const formats = item.available_formats || [];
  if (formats.length === 0) return null;

  if (item.media_type === "video") {
    const pref = (preferredResolution || "").toLowerCase();
    const target = pref === "best" || pref === "original" ? Infinity : resolutionHeight(pref);

    const muxedWithAudio = formats.filter(
      (format) =>
        !format.requires_merge &&
        format.video_codec &&
        format.video_codec !== "none" &&
        format.audio_codec &&
        format.audio_codec !== "none"
    );
    const pickMuxed = () => {
      if (muxedWithAudio.length === 0) return null;
      if (Number.isFinite(target)) {
        const within = muxedWithAudio.filter((format) => (format.height || 0) <= target);
        if (within.length > 0) return within[0];
      }
      return muxedWithAudio[0];
    };
    const chosenMuxed = pickMuxed();
    if (chosenMuxed) return chosenMuxed;

    const videoTracks = formats.filter(
      (format) => format.video_codec && format.video_codec !== "none"
    );
    if (videoTracks.length > 0) {
      if (Number.isFinite(target)) {
        const within = videoTracks.filter((format) => (format.height || 0) <= target);
        if (within.length > 0) return within[0];
      }
      return videoTracks[0];
    }
  }

  const muxed = formats.find((format) => !format.requires_merge);
  return muxed || formats[0];
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
