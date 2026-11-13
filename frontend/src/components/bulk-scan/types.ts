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
