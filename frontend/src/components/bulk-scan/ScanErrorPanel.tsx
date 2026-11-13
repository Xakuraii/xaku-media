import { AlertCircle, Cookie, ExternalLink, X } from "lucide-react";
import type { ScanErrorInfo } from "./types";

interface ScanErrorPanelProps {
  info: ScanErrorInfo;
  onDismiss?: () => void;
  onOpenSettings?: (section?: "cookies") => void;
  onOpenExternal?: (url: string) => void;
}

export function ScanErrorPanel({
  info,
  onDismiss,
  onOpenSettings,
  onOpenExternal,
}: ScanErrorPanelProps) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-700 dark:text-red-300">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{info.title}</span>
          {info.code && (
            <span className="rounded border border-red-500/30 px-1.5 py-0.5 font-mono text-[10px] uppercase">
              {info.code}
            </span>
          )}
        </div>
        <p className="whitespace-pre-wrap break-words text-xs">{info.summary}</p>
        {info.steps.length > 0 && (
          <ol className="list-decimal space-y-0.5 pl-4 text-[11px] opacity-90">
            {info.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        )}
        {info.actions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {info.actions.map((action) => (
              <button
                key={action.label}
                type="button"
                onClick={() => {
                  if (action.kind === "settings") onOpenSettings?.(action.section);
                  else onOpenExternal?.(action.url);
                }}
                className="inline-flex items-center gap-1.5 rounded-md border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-[11px] font-medium transition-colors hover:bg-red-500/20"
              >
                {action.kind === "settings" ? (
                  <Cookie className="h-3 w-3" />
                ) : (
                  <ExternalLink className="h-3 w-3" />
                )}
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss error">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
