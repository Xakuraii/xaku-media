import type {
  DiscoveredMediaItem,
  MediaFormatInfoPayload,
  ScanPost,
  ScanProgressPayload,
} from "../../../../desktop/shared/types";
import type { MediaFilter } from "./types";

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

export function dedupePosts(posts: ScanPost[]): ScanPost[] {
  const seen = new Set<string>();
  const result: ScanPost[] = [];
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

export function chooseFormat(item: DiscoveredMediaItem): MediaFormatInfoPayload | null {
  const formats = item.available_formats || [];
  if (formats.length === 0) return null;
  const muxed = formats.find((format) => !format.requires_merge);
  return muxed || formats[0];
}

export function postMatchesFilter(post: ScanPost, filter: MediaFilter): boolean {
  if (filter === "all") return true;
  if (filter === "album") return post.media_items.length > 1;
  if (filter === "image") return post.media_items.some((item) => item.media_type === "image");
  return post.media_items.some((item) => item.media_type === "video");
}

export function visibleMedia(post: ScanPost, filter: MediaFilter): DiscoveredMediaItem[] {
  if (filter === "image") return post.media_items.filter((item) => item.media_type === "image");
  if (filter === "video") return post.media_items.filter((item) => item.media_type === "video");
  return post.media_items;
}

export function filterPosts(posts: ScanPost[], filter: MediaFilter, search: string): ScanPost[] {
  const query = search.trim().toLowerCase();
  return posts.filter((post) => {
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

export function countPosts(posts: ScanPost[]) {
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
