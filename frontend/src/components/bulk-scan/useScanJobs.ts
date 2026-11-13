import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  LibraryStats,
  ScanJobSnapshot,
  ScanOptionsPayload,
  ScanStartedPayload,
} from "../../../../desktop/shared/types";
import type { JobEntry } from "./types";
import { EMPTY_PROGRESS, dedupePosts } from "./utils";

export interface StartScanResult {
  started: number;
  failures: string[];
}

/**
 * Owns scan job snapshots, progressive event merging, and live stats.
 * The hook is deliberately independent of selection and rendering.
 */
export function useScanJobs() {
  const [jobs, setJobs] = useState<Record<string, JobEntry>>({});
  const [starting, setStarting] = useState<boolean>(false);
  const [stats, setStats] = useState<LibraryStats | null>(null);

  const refreshStats = useCallback(() => {
    window.api?.getLibraryStats?.().then(setStats).catch(() => undefined);
  }, []);

  const mergeSnapshot = useCallback((snapshot: ScanJobSnapshot) => {
    setJobs((prev) => {
      const existing = prev[snapshot.job_id];
      return {
        ...prev,
        [snapshot.job_id]: {
          snapshot,
          posts: dedupePosts([...(existing?.posts || []), ...(snapshot.posts || [])]),
        },
      };
    });
  }, []);

  const upsertStarted = useCallback((data: ScanStartedPayload) => {
    setJobs((prev) => {
      if (prev[data.job_id]) return prev;
      return {
        ...prev,
        [data.job_id]: {
          snapshot: {
            job_id: data.job_id,
            scan_id: data.scan_id,
            url: data.url,
            provider: data.provider,
            status: "queued",
            capabilities: data.capabilities,
            classified_url: data.classified_url,
            progress: { ...EMPTY_PROGRESS },
            posts: [],
            warnings: [],
          },
          posts: [],
        },
      };
    });
  }, []);

  useEffect(() => {
    const api = window.api;
    if (!api) return;
    const offs: Array<() => void> = [];

    offs.push(api.onScanStarted?.((data) => upsertStarted(data)) ?? (() => undefined));

    offs.push(
      api.onScanPost?.((data) => {
        setJobs((prev) => {
          const entry = prev[data.job_id];
          if (!entry) return prev;
          return {
            ...prev,
            [data.job_id]: {
              snapshot: { ...entry.snapshot, status: "running", progress: data.progress },
              posts: dedupePosts([...entry.posts, data.post]),
            },
          };
        });
      }) ?? (() => undefined)
    );

    offs.push(
      api.onScanProgress?.((data) => {
        setJobs((prev) => {
          const entry = prev[data.job_id];
          if (!entry) return prev;
          return {
            ...prev,
            [data.job_id]: {
              ...entry,
              snapshot: { ...entry.snapshot, status: data.status, progress: data.progress },
            },
          };
        });
      }) ?? (() => undefined)
    );

    offs.push(
      api.onScanWarning?.((data) => {
        setJobs((prev) => {
          const entry = prev[data.job_id];
          if (!entry || entry.snapshot.warnings.includes(data.message)) return prev;
          return {
            ...prev,
            [data.job_id]: {
              ...entry,
              snapshot: {
                ...entry.snapshot,
                warnings: [...entry.snapshot.warnings, data.message],
              },
            },
          };
        });
      }) ?? (() => undefined)
    );

    offs.push(
      api.onScanFinished?.((data) => {
        setJobs((prev) => {
          const entry = prev[data.job_id];
          if (!entry) return prev;
          return {
            ...prev,
            [data.job_id]: {
              ...entry,
              snapshot: {
                ...entry.snapshot,
                status: data.status,
                progress: data.progress,
                warnings: data.warnings?.length ? data.warnings : entry.snapshot.warnings,
                error: data.error ?? null,
                error_category: data.error_category ?? null,
                error_details: data.error_details ?? {},
                stop_reason: data.stop_reason ?? null,
              },
            },
          };
        });
        refreshStats();
      }) ?? (() => undefined)
    );

    void api
      .listScanJobs?.(20)
      .then((result) => {
        const restored: Record<string, JobEntry> = {};
        for (const snapshot of result.jobs || []) {
          restored[snapshot.job_id] = {
            snapshot,
            posts: dedupePosts(snapshot.posts || []),
          };
        }
        setJobs((prev) => ({ ...restored, ...prev }));
      })
      .catch(() => undefined);

    refreshStats();
    return () => offs.forEach((off) => off());
  }, [refreshStats, upsertStarted]);

  const start = useCallback(
    async (urls: string[], options: ScanOptionsPayload): Promise<StartScanResult> => {
      setStarting(true);
      const failures: string[] = [];
      let started = 0;
      try {
        const results = await Promise.allSettled(
          urls.map((url) => window.api!.startScan(url, options))
        );
        for (let index = 0; index < results.length; index += 1) {
          const result = results[index];
          if (result.status === "fulfilled") {
            started += 1;
            upsertStarted({
              job_id: result.value.job_id,
              scan_id: result.value.scan_id,
              url: result.value.url,
              provider: result.value.provider,
              capabilities: result.value.capabilities,
              classified_url: result.value.classified_url,
            });
            mergeSnapshot(result.value);
          } else {
            const reason =
              result.reason instanceof Error ? result.reason.message : String(result.reason);
            failures.push(`${urls[index]} — ${reason}`);
          }
        }
      } finally {
        setStarting(false);
        refreshStats();
      }
      return { started, failures };
    },
    [mergeSnapshot, refreshStats, upsertStarted]
  );

  const cancel = useCallback(async (jobId: string) => {
    await window.api?.cancelScan?.(jobId);
  }, []);

  const allPosts = useMemo(
    () => dedupePosts(Object.values(jobs).flatMap((entry) => entry.posts)),
    [jobs]
  );

  const activeJobs = useMemo(
    () => Object.values(jobs).sort((a, b) => (a.snapshot.started_at || "").localeCompare(b.snapshot.started_at || "")),
    [jobs]
  );

  const runningJobs = useMemo(
    () =>
      activeJobs.filter(
        (entry) =>
          entry.snapshot.status === "running" || entry.snapshot.status === "queued"
      ),
    [activeJobs]
  );

  const totalProgress = useMemo(
    () =>
      runningJobs.reduce(
        (acc, entry) => {
          acc.posts += entry.snapshot.progress.posts_discovered;
          acc.media += entry.snapshot.progress.media_discovered;
          return acc;
        },
        { posts: 0, media: 0 }
      ),
    [runningJobs]
  );

  return {
    jobs,
    allPosts,
    activeJobs,
    runningJobs,
    totalProgress,
    stats,
    starting,
    start,
    cancel,
    refreshStats,
  };
}
