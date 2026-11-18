import { useEffect, useState } from "react";
import { AlertTriangle, Eye, Trash2, X } from "lucide-react";
import { explainScanFailure } from "./errors";
import type { JobEntry } from "./types";
import { hostOf, statusTone } from "./utils";

function formatElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  const total = Math.floor(seconds);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes < 60) return `${minutes}m ${secs}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function progressFor(entry: JobEntry, now: number) {
  const { snapshot } = entry;
  const running = snapshot.status === "running" || snapshot.status === "queued";
  const started = snapshot.started_at ? Date.parse(snapshot.started_at) : null;
  const finished = snapshot.finished_at ? Date.parse(snapshot.finished_at) : null;
  const elapsed = started ? Math.max(0, ((finished ?? now) - started) / 1000) : 0;
  const maxMedia = snapshot.options?.max_media ?? null;
  const maxPosts = snapshot.options?.max_posts ?? null;

  let percent: number | null = null;
  if (!running) percent = 100;
  else if (maxMedia && maxMedia > 0) {
    percent = Math.min(99, Math.round((snapshot.progress.media_discovered / maxMedia) * 100));
  } else if (maxPosts && maxPosts > 0) {
    percent = Math.min(99, Math.round((snapshot.progress.posts_discovered / maxPosts) * 100));
  }

  const target =
    maxMedia && maxMedia > 0
      ? `limit ${maxMedia} media`
      : maxPosts && maxPosts > 0
        ? `limit ${maxPosts} posts`
        : null;
  return { running, elapsed, percent, target };
}

interface JobStatusListProps {
  jobs: JobEntry[];
  focusedJobId: string | null;
  onCancel: (jobId: string) => void;
  onFocus: (jobId: string) => void;
  onShowAll: () => void;
  onDelete: (job: JobEntry) => void;
  onOpenSettings?: (section?: "cookies") => void;
  onOpenExternal?: (url: string) => void;
}

export function JobStatusList({
  jobs,
  focusedJobId,
  onCancel,
  onFocus,
  onShowAll,
  onDelete,
  onOpenSettings,
  onOpenExternal,
}: JobStatusListProps) {
  const anyRunning = jobs.some(
    (entry) => entry.snapshot.status === "running" || entry.snapshot.status === "queued"
  );
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [anyRunning]);

  if (jobs.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wide text-muted">Scans</span>
        {focusedJobId && (
          <button
            type="button"
            onClick={onShowAll}
            className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] font-mono text-ink/80 hover:bg-raised"
          >
            <X className="h-3 w-3" />
            Show all scans
          </button>
        )}
      </div>
      {jobs.map((entry) => {
        const { snapshot } = entry;
        const running = snapshot.status === "running" || snapshot.status === "queued";
        const focused = focusedJobId === snapshot.job_id;
        const failure =
          snapshot.status === "failed"
            ? explainScanFailure(snapshot.error_category, snapshot.error, snapshot.error_details)
            : null;
        const progress = progressFor(entry, now);
        const barTone =
          snapshot.status === "completed"
            ? "bg-emerald-500"
            : snapshot.status === "failed"
              ? "bg-red-500"
              : snapshot.status === "cancelled"
                ? "bg-amber-500"
                : "bg-accent";
        return (
          <div
            key={snapshot.job_id}
            className={`space-y-2 rounded-lg border px-4 py-2.5 transition-colors ${
              focused ? "border-accent/50 bg-accent/5" : "border-hairline bg-surface"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${statusTone(snapshot.status)}`}
              >
                {snapshot.status}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink/80">
                {hostOf(snapshot.url)}
                {snapshot.capabilities?.has_cookies && (
                  <span className="ml-2 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-300">
                    cookies saved
                  </span>
                )}
                {snapshot.capabilities?.requires_auth && (
                  <span className="ml-2 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-300">
                    may need cookies
                  </span>
                )}
              </span>
              <span className="font-mono text-[11px] text-muted">
                {snapshot.progress.posts_discovered} posts · {snapshot.progress.media_discovered} media
              </span>
              {running ? (
                <button
                  type="button"
                  onClick={() => onCancel(snapshot.job_id)}
                  className="rounded-md border border-hairline px-2.5 py-1 font-mono text-[11px] text-ink/80 hover:bg-raised"
                >
                  Stop
                </button>
              ) : (
                <span className="font-mono text-[10px] text-muted">
                  {snapshot.stop_reason || snapshot.status}
                </span>
              )}
              <button
                type="button"
                onClick={() => onFocus(snapshot.job_id)}
                title="Show only this scan"
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-mono transition-colors ${
                  focused
                    ? "border-accent/40 bg-accent/10 text-accent"
                    : "border-hairline text-ink/80 hover:bg-raised"
                }`}
              >
                <Eye className="h-3 w-3" />
                {focused ? "Viewing" : "Show only"}
              </button>
              <button
                type="button"
                onClick={() => onDelete(entry)}
                title="Delete this scan"
                className="inline-flex items-center gap-1 rounded-md border border-red-500/30 px-2 py-1 text-[11px] font-mono text-red-700 transition-colors hover:bg-red-500/10 dark:text-red-300"
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </button>
            </div>

            <div className="space-y-1">
              <div
                className="relative h-1.5 overflow-hidden rounded-full bg-raised"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress.percent ?? undefined}
                aria-label={`Scan progress for ${hostOf(snapshot.url)}`}
              >
                {progress.percent === null ? (
                  <div
                    className={`absolute inset-y-0 left-0 w-1/3 animate-pulse rounded-full ${barTone}`}
                  />
                ) : (
                  <div
                    className={`h-full rounded-full transition-[width] duration-300 ${barTone}`}
                    style={{ width: `${progress.percent}%` }}
                  />
                )}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[10px] text-muted">
                <span>
                  {progress.running
                    ? progress.percent === null
                      ? "scanning…"
                      : `${progress.percent}%${progress.target ? ` of ${progress.target}` : ""}`
                    : `${snapshot.stop_reason || snapshot.status}${progress.target ? ` · ${progress.target}` : ""}`}
                </span>
                <span>
                  {formatElapsed(progress.elapsed)} elapsed
                  {progress.running && snapshot.progress.pages_fetched > 0
                    ? ` · page ${snapshot.progress.pages_fetched}`
                    : ""}
                </span>
              </div>
            </div>

            {failure && (
              <div className="flex flex-wrap items-start gap-2 rounded-md border border-red-500/25 bg-red-500/5 px-3 py-2 text-red-700 dark:text-red-300">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] font-semibold">
                    {failure.title}
                    {failure.code ? ` (${failure.code})` : ""}
                  </p>
                  <p className="whitespace-pre-wrap break-words text-[11px] opacity-90">{failure.summary}</p>
                  {failure.steps[0] && (
                    <p className="mt-1 text-[10px] opacity-80">
                      Next: {failure.steps.slice(0, 2).join(" ")}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {failure.actions.map((action) => (
                    <button
                      key={action.label}
                      type="button"
                      onClick={() => {
                        if (action.kind === "settings") onOpenSettings?.(action.section);
                        else onOpenExternal?.(action.url);
                      }}
                      className="rounded border border-red-500/40 px-2 py-0.5 text-[10px] font-medium transition-colors hover:bg-red-500/15"
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {snapshot.warnings.length > 0 && (
              <span className="block font-mono text-[10px] text-amber-700 dark:text-amber-300">
                {snapshot.warnings.length} warning{snapshot.warnings.length === 1 ? "" : "s"}:{" "}
                {snapshot.warnings[snapshot.warnings.length - 1]}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
