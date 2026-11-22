import type {
  DiscoveredMediaItem,
  ScanJobSnapshot,
  ScanPost,
} from "../../../../desktop/shared/types";

export type MediaFilter = "all" | "image" | "video" | "album";

export interface JobEntry {
  snapshot: ScanJobSnapshot;
  posts: PostWithScan[];
}

export interface PostWithScan extends ScanPost {
  /** Client-side association used for scan filtering/deletion. */
  _job_id: string;
  _scan_id?: string | null;
}

export type ErrorAction =
  | { label: string; kind: "settings"; section: "cookies" }
  | { label: string; kind: "external"; url: string };

export interface ScanErrorInfo {
  title: string;
  summary: string;
  steps: string[];
  actions: ErrorAction[];
  code?: string | null;
}

export interface BulkScanViewProps {
  prefillUrl?: string;
  onPrefillConsumed?: () => void;
  onDownloadStarted?: () => void;
  onOpenSettings?: (section?: "cookies") => void;
  onOpenExternal?: (url: string) => void;
  onPreviewItem?: (
    item: DiscoveredMediaItem,
    options?: {
      isSkipped?: boolean;
      onToggleSkip?: () => Promise<boolean>;
    }
  ) => void;
}

export function isItemDownloaded(
  item: DiscoveredMediaItem,
  downloaded: Set<string>
): boolean {
  if (downloaded.has(item.id)) return true;
  if (item.provider_media_id && downloaded.has(item.provider_media_id)) return true;
  if (item.original_url && downloaded.has(item.original_url)) return true;
  return false;
}

export function isItemSkipped(item: DiscoveredMediaItem, skipped: Set<string>): boolean {
  if (skipped.has(item.id)) return true;
  if (item.provider_media_id && skipped.has(item.provider_media_id)) return true;
  if (item.original_url && skipped.has(item.original_url)) return true;
  return false;
}

/** True when a scan item was downloaded or explicitly skipped before. */
export function isItemHandled(
  item: DiscoveredMediaItem,
  downloaded: Set<string>,
  skipped: Set<string> = new Set()
): boolean {
  return isItemDownloaded(item, downloaded) || isItemSkipped(item, skipped);
}

/** Stable keys used to remember a handled item locally. */
export function itemKeys(item: DiscoveredMediaItem): string[] {
  return [item.id, item.provider_media_id ?? "", item.original_url ?? ""].filter(Boolean);
}
