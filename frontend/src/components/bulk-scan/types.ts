import type {
  ScanJobSnapshot,
  ScanPost,
} from "../../../../desktop/shared/types";

export type MediaFilter = "all" | "image" | "video" | "album";

export interface JobEntry {
  snapshot: ScanJobSnapshot;
  posts: ScanPost[];
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
  onDownloadStarted?: () => void;
  onOpenSettings?: (section?: "cookies") => void;
  onOpenExternal?: (url: string) => void;
}
