import React, { useEffect, useRef, useState } from "react";
import {
  Folder,
  FolderOpen,
  HardDrive,
  Sliders,
  Cpu,
  Film,
  Image as ImageIcon,
  Sun,
  Moon,
  Monitor,
  RotateCcw,
  Check,
  AlertCircle,
  Settings as SettingsIcon,
  Sparkles,
  RefreshCw,
  ExternalLink,
  Gauge,
  KeyRound,
  Shield,
  Globe,
  Upload,
  Trash2,
  Plus,
  FileText,
  CheckCircle2,
} from "lucide-react";
import type {
  AppPreferences,
  CookieProfileRecord,
  FFmpegInfoResult,
  PythonBridgeStatus,
  SystemInfo,
} from "../../../desktop/shared/types";

interface SettingsViewProps {
  systemInfo: SystemInfo | null;
  pythonStatus: PythonBridgeStatus | null;
  ffmpegInfo: FFmpegInfoResult | null;
  /** Deep link from an error card: scroll to the cookie profiles section. */
  initialSection?: "cookies";
  onConcurrencyChange?: (val: number) => void;
  onSpeedLimitChange?: (val: number) => void;
  onThemeChange?: (theme: "dark" | "light" | "system") => void;
  theme?: "dark" | "light" | "system";
}

const COOKIE_EXPORT_EXTENSION_URL =
  "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc";

/** Derive a cookie profile domain from the first data line of a cookies.txt export. */
function detectCookieDomain(text: string): string | null {
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim().replace(/^#HttpOnly_/, "");
    if (!line || line.startsWith("#")) continue;
    const domain = line.split(/\s+/)[0]?.replace(/^\./, "").trim();
    if (domain && domain.includes(".")) return domain;
  }
  return null;
}

const DEFAULT_PREFERENCES: AppPreferences = {
  download_dir: "",
  image_download_dir: "",
  video_download_dir: "",
  max_concurrent_downloads: 4,
  max_download_speed_kbps: 0,
  max_retries: 3,
  request_timeout_seconds: 30,
  default_video_resolution: "1080p",
  default_video_container: "mp4",
  default_image_format: "original",
  theme: "dark",
  log_level: "INFO",
};

export const SettingsView: React.FC<SettingsViewProps> = ({
  systemInfo,
  pythonStatus,
  ffmpegInfo,
  initialSection,
  onConcurrencyChange,
  onSpeedLimitChange,
  onThemeChange,
  theme: activeTheme,
}) => {
  const [prefs, setPrefs] = useState<AppPreferences>(DEFAULT_PREFERENCES);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [saveNotice, setSaveNotice] = useState<{ message: string; ok: boolean } | null>(null);
  const [resetConfirmOpen, setResetConfirmOpen] = useState<boolean>(false);
  const credentialsRef = useRef<HTMLElement | null>(null);

  // Authentication, Cookies & Custom Request Headers State
  const [cookieProfiles, setCookieProfiles] = useState<CookieProfileRecord[]>([]);
  const [domainHeaders, setDomainHeaders] = useState<Record<string, Record<string, string>>>({});
  const [supportedBrowsers, setSupportedBrowsers] = useState<string[]>(["edge", "chrome", "firefox"]);
  const [selectedBrowser, setSelectedBrowser] = useState<string>("chrome");
  const [browserDomainFilter, setBrowserDomainFilter] = useState<string>("");
  const [importingBrowser, setImportingBrowser] = useState<boolean>(false);
  const [authActiveTab, setAuthActiveTab] = useState<"cookies" | "headers">("cookies");
  const [pasteModalOpen, setPasteModalOpen] = useState<boolean>(false);
  const [pasteDomain, setPasteDomain] = useState<string>("");
  const [pasteText, setPasteText] = useState<string>("");
  const [headerModalOpen, setHeaderModalOpen] = useState<boolean>(false);
  const [headerDomain, setHeaderDomain] = useState<string>("");
  const [headerUserAgent, setHeaderUserAgent] = useState<string>("");
  const [headerReferer, setHeaderReferer] = useState<string>("");
  const [headerAuth, setHeaderAuth] = useState<string>("");
  const [authFeedback, setAuthFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (initialSection !== "cookies") return;
    setAuthActiveTab("cookies");
    credentialsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [initialSection]);

  // Load preferences from SQLite on mount
  useEffect(() => {
    async function loadPreferences() {
      if (!window.api?.getPreferences) {
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        const data = await window.api.getPreferences();
        setPrefs(data);
        if (typeof data.cookie_browser === "string" && data.cookie_browser) {
          setSelectedBrowser(data.cookie_browser);
        }
      } catch (err) {
        console.error("Failed to load application preferences:", err);
      } finally {
        setLoading(false);
      }
    }

    loadPreferences();
    loadAuthData();
  }, []);

  const loadAuthData = async () => {
    try {
      if (window.api?.listCookieProfiles) {
        const res = await window.api.listCookieProfiles();
        setCookieProfiles(res.profiles || []);
      }
      if (window.api?.getDomainHeaders) {
        const res = await window.api.getDomainHeaders();
        setDomainHeaders(res.domain_headers || {});
      }
      if (window.api?.listSupportedBrowsers) {
        const res = await window.api.listSupportedBrowsers();
        if (res.browsers && res.browsers.length > 0) {
          setSupportedBrowsers(res.browsers);
          if (!res.browsers.includes(selectedBrowser)) {
            setSelectedBrowser(res.browsers[0]);
          }
        }
      }
    } catch (err) {
      console.warn("Failed to load auth credentials data:", err);
    }
  };

  const handleBrowserImport = async () => {
    if (!window.api?.importBrowserCookies) return;
    setImportingBrowser(true);
    setAuthFeedback(null);
    try {
      const res = await window.api.importBrowserCookies(
        selectedBrowser,
        browserDomainFilter.trim() || undefined
      );
      setAuthFeedback({
        type: "success",
        message: `Imported ${res.profile.cookie_count} cookies for '${res.profile.domain}' from ${selectedBrowser}.`,
      });
      await loadAuthData();
    } catch (err: any) {
      setAuthFeedback({
        type: "error",
        message: err?.message || `Failed to extract cookies from ${selectedBrowser}. Ensure the browser is closed.`,
      });
    } finally {
      setImportingBrowser(false);
    }
  };

  const handleFileImport = async () => {
    if (!window.api?.selectCookieFile || !window.api?.importCookiesFile) return;
    setAuthFeedback(null);
    try {
      const filePath = await window.api.selectCookieFile();
      if (!filePath) return;
      const res = await window.api.importCookiesFile(filePath);
      setAuthFeedback({
        type: "success",
        message: `Imported ${res.profile.cookie_count} cookies for '${res.profile.domain}' from file.`,
      });
      await loadAuthData();
    } catch (err: any) {
      setAuthFeedback({
        type: "error",
        message: err?.message || "Failed to import cookies file.",
      });
    }
  };

  const handleSavePasteCookies = async () => {
    if (!pasteDomain.trim() || !pasteText.trim()) {
      setAuthFeedback({ type: "error", message: "Domain and cookie text are required." });
      return;
    }
    if (!window.api?.saveCookiesText) return;
    try {
      const res = await window.api.saveCookiesText(pasteDomain.trim(), pasteText.trim());
      setAuthFeedback({
        type: "success",
        message: `Saved ${res.profile.cookie_count} cookies for '${res.profile.domain}'.`,
      });
      setPasteModalOpen(false);
      setPasteDomain("");
      setPasteText("");
      await loadAuthData();
    } catch (err: any) {
      setAuthFeedback({
        type: "error",
        message: err?.message || "Failed to parse or save Netscape cookies.",
      });
    }
  };

  const handleDeleteCookieProfile = async (id: string, domain: string) => {
    if (!window.api?.deleteCookieProfile) return;
    try {
      await window.api.deleteCookieProfile(id);
      setAuthFeedback({
        type: "success",
        message: `Deleted cookie profile for '${domain}'.`,
      });
      await loadAuthData();
    } catch (err: any) {
      setAuthFeedback({
        type: "error",
        message: err?.message || "Failed to delete cookie profile.",
      });
    }
  };

  const handleSaveDomainHeaders = async () => {
    if (!headerDomain.trim()) {
      setAuthFeedback({ type: "error", message: "Domain is required for custom headers." });
      return;
    }
    const headers: Record<string, string> = {};
    if (headerUserAgent.trim()) headers["User-Agent"] = headerUserAgent.trim();
    if (headerReferer.trim()) headers["Referer"] = headerReferer.trim();
    if (headerAuth.trim()) headers["Authorization"] = headerAuth.trim();

    if (Object.keys(headers).length === 0) {
      setAuthFeedback({ type: "error", message: "Provide at least one header value." });
      return;
    }

    if (!window.api?.setDomainHeaders) return;
    try {
      await window.api.setDomainHeaders(headerDomain.trim(), headers);
      setAuthFeedback({
        type: "success",
        message: `Saved custom request headers for '${headerDomain.trim()}'.`,
      });
      setHeaderModalOpen(false);
      setHeaderDomain("");
      setHeaderUserAgent("");
      setHeaderReferer("");
      setHeaderAuth("");
      await loadAuthData();
    } catch (err: any) {
      setAuthFeedback({
        type: "error",
        message: err?.message || "Failed to save domain headers.",
      });
    }
  };

  const handleDeleteDomainHeaders = async (domain: string) => {
    if (!window.api?.deleteDomainHeaders) return;
    try {
      await window.api.deleteDomainHeaders(domain);
      setAuthFeedback({
        type: "success",
        message: `Deleted custom headers for '${domain}'.`,
      });
      await loadAuthData();
    } catch (err: any) {
      setAuthFeedback({
        type: "error",
        message: err?.message || "Failed to delete custom headers.",
      });
    }
  };

  const showSaveNotice = (message: string = "Settings saved to local SQLite", ok: boolean = true) => {
    setSaveNotice({ message, ok });
    setTimeout(() => {
      setSaveNotice(null);
    }, 2800);
  };

  const handleUpdate = async (updates: Partial<AppPreferences>) => {
    const next = { ...prefs, ...updates };
    setPrefs(next);

    if (updates.max_concurrent_downloads && onConcurrencyChange) {
      onConcurrencyChange(updates.max_concurrent_downloads);
    }
    if (updates.max_download_speed_kbps !== undefined && onSpeedLimitChange) {
      onSpeedLimitChange(updates.max_download_speed_kbps);
    }
    if (updates.theme && onThemeChange) {
      onThemeChange(updates.theme);
    }

    if (!window.api?.updatePreferences) return;

    try {
      setSaving(true);
      const updated = await window.api.updatePreferences(updates);
      setPrefs(updated);
      showSaveNotice();
    } catch (err) {
      console.error("Failed to persist preferences:", err);
      showSaveNotice("Could not save settings — changes are only in memory", false);
    } finally {
      setSaving(false);
    }
  };

  const handleSelectFolder = async () => {
    if (!window.api?.selectFolder) return;
    try {
      const selected = await window.api.selectFolder(prefs.download_dir);
      if (selected && selected !== prefs.download_dir) {
        await handleUpdate({ download_dir: selected });
      }
    } catch (err) {
      console.error("Failed to select directory:", err);
    }
  };

  const handleOpenFolder = async () => {
    if (!prefs.download_dir || !window.api?.openPath) return;
    try {
      await window.api.openPath(prefs.download_dir);
    } catch (err) {
      console.error("Failed to open directory:", err);
    }
  };

  const handleResetToDefaults = async () => {
    if (!window.api?.resetPreferences) return;
    try {
      setSaving(true);
      const defaults = await window.api.resetPreferences();
      setPrefs(defaults);
      setResetConfirmOpen(false);
      if (onConcurrencyChange) {
        onConcurrencyChange(defaults.max_concurrent_downloads);
      }
      if (onSpeedLimitChange) {
        onSpeedLimitChange(defaults.max_download_speed_kbps ?? 0);
      }
      if (onThemeChange && defaults.theme) {
        onThemeChange(defaults.theme);
      }
      showSaveNotice("Preferences reset to factory defaults");
    } catch (err) {
      console.error("Failed to reset preferences:", err);
      showSaveNotice("Could not reset preferences", false);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-3">
        <RefreshCw className="h-8 w-8 text-accent animate-spin" />
        <p className="text-xs font-mono text-muted">Loading settings from local database...</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8 pb-16 animate-in fade-in duration-200">
      {/* Settings Header */}
      <div className="flex items-center justify-between border-b border-hairline pb-5">
        <div className="space-y-1">
          <div className="flex items-center space-x-2.5">
            <SettingsIcon className="h-6 w-6 text-accent" />
            <h1 className="text-2xl font-bold tracking-tight text-ink">Application Settings</h1>
          </div>
          <p className="text-sm text-muted mt-1">
            Configure local download paths, worker concurrency limits, format preferences, and theme styling.
          </p>
        </div>

        {/* Save indicator toast */}
        <div className="flex items-center space-x-3">
          {saveNotice && (
            <div
              className={`flex items-center space-x-2 px-3 py-1.5 border rounded-lg text-xs font-mono animate-in fade-in duration-150 ${
                saveNotice.ok
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
                  : "bg-red-500/10 border-red-500/30 text-red-700 dark:text-red-300"
              }`}
            >
              {saveNotice.ok ? (
                <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5 text-red-600 dark:text-red-400" />
              )}
              <span>{saveNotice.message}</span>
            </div>
          )}
          <button
            type="button"
            onClick={() => setResetConfirmOpen(true)}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-raised hover:bg-hairline/70 border border-hairline rounded-lg text-xs font-mono text-ink/80 transition-colors"
          >
            <RotateCcw className="h-3.5 w-3.5 text-muted" />
            <span>Reset Defaults</span>
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 1. Storage & Download Directories */}
      {/* ========================================================================= */}
      <section className="bg-surface border border-hairline rounded-2xl p-6 space-y-4 shadow-card">
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <HardDrive className="h-5 w-5 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Storage & Download Directory</h2>
              <p className="text-[11px] text-muted font-mono">
                Primary directory where images, videos, and multi-part files are saved.
              </p>
            </div>
          </div>
          <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-300">
            Local Disk Only
          </span>
        </div>

        <div className="space-y-3">
          <label className="text-xs font-medium text-ink/80">Default Download Location</label>
          <div className="flex items-center space-x-2">
            <div className="flex-1 bg-page border border-hairline rounded-xl px-4 py-2.5 flex items-center space-x-3 text-xs font-mono text-ink/90 overflow-hidden">
              <Folder className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
              <span className="truncate select-all" title={prefs.download_dir}>
                {prefs.download_dir || "Resolving system default..."}
              </span>
            </div>
            <button
              type="button"
              onClick={handleSelectFolder}
              className="px-4 py-2.5 bg-accent hover:bg-accent-vivid text-on-accent rounded-xl text-xs font-medium flex items-center space-x-2 transition-colors shrink-0 shadow-md shadow-accent/30"
            >
              <FolderOpen className="h-4 w-4" />
              <span>Change Folder...</span>
            </button>
            <button
              type="button"
              onClick={handleOpenFolder}
              className="p-2.5 bg-raised hover:bg-hairline/70 border border-hairline rounded-xl text-ink/80 hover:text-ink transition-colors shrink-0"
              title="Open folder in File Explorer"
            >
              <ExternalLink className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
            <div className="bg-raised border border-hairline rounded-xl p-3 flex items-center justify-between text-xs font-mono">
              <div className="flex items-center space-x-2 text-muted">
                <Film className="h-4 w-4 text-purple-600 dark:text-purple-400" />
                <span>Video Subdirectory:</span>
              </div>
              <span className="text-ink/90 font-bold">\videos</span>
            </div>
            <div className="bg-raised border border-hairline rounded-xl p-3 flex items-center justify-between text-xs font-mono">
              <div className="flex items-center space-x-2 text-muted">
                <ImageIcon className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                <span>Image Subdirectory:</span>
              </div>
              <span className="text-ink/90 font-bold">\images</span>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 2. Download Concurrency & Queue Scheduling */}
      {/* ========================================================================= */}
      <section className="bg-surface border border-hairline rounded-2xl p-6 space-y-5 shadow-card">
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <Sliders className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Concurrency & Queue Scheduling</h2>
              <p className="text-[11px] text-muted font-mono">
                Control active download slots, request timeouts, and automatic retry limits.
              </p>
            </div>
          </div>
          <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-purple-500/10 border border-purple-500/30 text-purple-700 dark:text-purple-300">
            {prefs.max_concurrent_downloads} Active Slots
          </span>
        </div>

        {/* Concurrency Slider & Stepper */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-ink/80">Simultaneous Active Downloads</span>
            <span className="font-mono text-purple-700 dark:text-purple-300 font-bold">{prefs.max_concurrent_downloads} slots</span>
          </div>

          <div className="flex items-center space-x-4">
            <input
              type="range"
              min="1"
              max="10"
              step="1"
              value={prefs.max_concurrent_downloads}
              onChange={(e) => handleUpdate({ max_concurrent_downloads: parseInt(e.target.value, 10) })}
              className="w-full h-2 bg-raised rounded-lg appearance-none cursor-pointer accent-accent"
            />
          </div>

          {/* Quick slot chips */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[1, 2, 3, 4, 5, 6, 8, 10].map((slot) => (
              <button
                key={slot}
                type="button"
                onClick={() => handleUpdate({ max_concurrent_downloads: slot })}
                className={`px-3 py-1 rounded-lg text-xs font-mono border transition-all ${
                  prefs.max_concurrent_downloads === slot
                    ? "bg-accent border-accent text-on-accent shadow-sm shadow-accent/40"
                    : "bg-raised border-hairline text-muted hover:text-ink hover:border-hairline-strong"
                }`}
              >
                {slot} {slot === 1 ? "Slot" : "Slots"}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-muted leading-relaxed font-mono">
            Tasks exceeding this limit stay safely queued in SQLite and start automatically as slots open up.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-hairline">
          {/* Timeout */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-ink/80">Network Timeout:</span>
              <span className="text-muted">{prefs.request_timeout_seconds} seconds</span>
            </div>
            <select
              value={prefs.request_timeout_seconds}
              onChange={(e) => handleUpdate({ request_timeout_seconds: parseFloat(e.target.value) })}
              className="w-full bg-page border border-hairline rounded-xl px-3 py-2 text-xs font-mono text-ink/90 focus:outline-none focus:border-accent"
            >
              <option value="15">15 seconds (Fast fail)</option>
              <option value="30">30 seconds (Recommended standard)</option>
              <option value="60">60 seconds (Large files)</option>
              <option value="120">120 seconds (Slow connections)</option>
            </select>
          </div>

          {/* Retries */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-ink/80">Max Auto-Retries:</span>
              <span className="text-muted">{prefs.max_retries} attempts</span>
            </div>
            <select
              value={prefs.max_retries}
              onChange={(e) => handleUpdate({ max_retries: parseInt(e.target.value, 10) })}
              className="w-full bg-page border border-hairline rounded-xl px-3 py-2 text-xs font-mono text-ink/90 focus:outline-none focus:border-accent"
            >
              <option value="0">0 (No retries)</option>
              <option value="1">1 attempt</option>
              <option value="3">3 attempts (Recommended)</option>
              <option value="5">5 attempts (Aggressive recovery)</option>
            </select>
          </div>
        </div>

        {/* Global Bandwidth Throttling & Speed Limit */}
        <div className="pt-4 border-t border-hairline space-y-3">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center space-x-2">
              <Gauge className="h-4 w-4 text-cyan-600 dark:text-cyan-400" />
              <span className="font-semibold text-ink/90">Global Bandwidth Speed Limit</span>
            </div>
            <span className="font-mono text-cyan-700 dark:text-cyan-300 font-bold">
              {prefs.max_download_speed_kbps && prefs.max_download_speed_kbps > 0
                ? prefs.max_download_speed_kbps >= 1024
                  ? `${(prefs.max_download_speed_kbps / 1024).toFixed(1)} MB/s`
                  : `${prefs.max_download_speed_kbps} KB/s`
                : "Unlimited (Full Speed)"}
            </span>
          </div>

          <div className="flex flex-wrap gap-1.5 pt-1">
            {[
              { label: "Unlimited", value: 0 },
              { label: "500 KB/s", value: 500 },
              { label: "1 MB/s", value: 1024 },
              { label: "2 MB/s", value: 2048 },
              { label: "5 MB/s", value: 5120 },
              { label: "10 MB/s", value: 10240 },
              { label: "20 MB/s", value: 20480 },
              { label: "50 MB/s", value: 51200 },
            ].map((preset) => {
              const active = (prefs.max_download_speed_kbps || 0) === preset.value;
              return (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => handleUpdate({ max_download_speed_kbps: preset.value })}
                  className={`px-3 py-1 rounded-lg text-xs font-mono border transition-all ${
                    active
                      ? "bg-cyan-700 border-cyan-400 text-white shadow-sm shadow-cyan-600/40"
                      : "bg-raised border-hairline text-muted hover:text-ink hover:border-hairline-strong"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>

          <div className="flex items-center space-x-3 pt-1">
            <span className="text-[11px] font-mono text-muted">Custom Limit (KB/s):</span>
            <input
              type="number"
              min="0"
              max="1000000"
              step="100"
              value={prefs.max_download_speed_kbps ?? 0}
              onChange={(e) => {
                const val = Math.max(0, parseInt(e.target.value, 10) || 0);
                handleUpdate({ max_download_speed_kbps: val });
              }}
              placeholder="0 = unlimited"
              className="w-36 bg-page border border-hairline rounded-xl px-3 py-1.5 text-xs font-mono text-ink/90 focus:outline-none focus:border-cyan-500"
            />
            <span className="text-[11px] text-faint font-mono">
              Applies globally across all active workers in real time.
            </span>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 3. Video Quality & Format Preferences */}
      {/* ========================================================================= */}
      <section className="bg-surface border border-hairline rounded-2xl p-6 space-y-5 shadow-card">
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <Film className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Default Video Pipeline Preferences</h2>
              <p className="text-[11px] text-muted font-mono">
                Preferred maximum resolution and container format for video downloads.
              </p>
            </div>
          </div>
          <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-page border border-hairline text-ink/80 uppercase">
            {prefs.default_video_resolution} · {prefs.default_video_container}
          </span>
        </div>

        {/* Video Resolution */}
        <div className="space-y-2.5">
          <label className="text-xs font-medium text-ink/80">Default Video Resolution</label>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
            {[
              { id: "best", label: "Best Available", desc: "Max Source" },
              { id: "2160p", label: "4K UHD", desc: "2160p" },
              { id: "1440p", label: "2K QHD", desc: "1440p" },
              { id: "1080p", label: "Full HD", desc: "1080p (Standard)" },
              { id: "720p", label: "HD", desc: "720p" },
              { id: "480p", label: "SD", desc: "480p" },
            ].map((res) => (
              <button
                key={res.id}
                type="button"
                onClick={() => handleUpdate({ default_video_resolution: res.id })}
                className={`p-2.5 rounded-xl border text-left flex flex-col transition-all ${
                  prefs.default_video_resolution === res.id
                    ? "bg-purple-500/10 border-purple-500/40 text-ink shadow-sm shadow-purple-900/50"
                    : "bg-raised border-hairline text-muted hover:text-ink hover:border-hairline-strong"
                }`}
              >
                <span className="text-xs font-bold text-ink">{res.label}</span>
                <span className="text-[11px] font-mono text-muted">{res.desc}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Video Container */}
        <div className="space-y-2.5">
          <label className="text-xs font-medium text-ink/80">Default Video Container</label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { id: "mp4", label: "MP4", desc: "Universal Compatibility" },
              { id: "mkv", label: "MKV", desc: "Multi-track & Subtitles" },
              { id: "webm", label: "WebM", desc: "VP9 / Opus Open Web" },
              { id: "original", label: "Original", desc: "Preserve Source Stream" },
            ].map((fmt) => (
              <button
                key={fmt.id}
                type="button"
                onClick={() => handleUpdate({ default_video_container: fmt.id })}
                className={`p-2.5 rounded-xl border text-left flex flex-col transition-all ${
                  prefs.default_video_container === fmt.id
                    ? "bg-purple-500/10 border-purple-500/40 text-ink shadow-sm shadow-purple-900/50"
                    : "bg-raised border-hairline text-muted hover:text-ink hover:border-hairline-strong"
                }`}
              >
                <span className="text-xs font-bold uppercase text-ink">{fmt.label}</span>
                <span className="text-[11px] font-mono text-muted">{fmt.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="text-[11px] font-mono text-muted bg-raised p-3 rounded-xl border border-hairline flex items-start space-x-2">
          <Sparkles className="h-4 w-4 text-purple-600 dark:text-purple-400 shrink-0 mt-0.5" />
          <span>
            Non-destructive multiplexing: Separate video and audio streams are muxed without lossy re-encoding whenever supported by FFmpeg.
          </span>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 4. Image Quality & Format Preferences */}
      {/* ========================================================================= */}
      <section className="bg-surface border border-hairline rounded-2xl p-6 space-y-4 shadow-card">
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <ImageIcon className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Default Image Pipeline Preferences</h2>
              <p className="text-[11px] text-muted font-mono">
                Preferred format for single image downloads and bulk gallery exports.
              </p>
            </div>
          </div>
          <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-page border border-hairline text-ink/80 uppercase">
            {prefs.default_image_format}
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { id: "original", label: "Original", desc: "Bit-for-bit Source Stream" },
            { id: "png", label: "PNG", desc: "Lossless Graphics" },
            { id: "jpg", label: "JPG", desc: "Universal Photo Standard" },
            { id: "webp", label: "WebP", desc: "Compact Modern Format" },
          ].map((fmt) => (
            <button
              key={fmt.id}
              type="button"
              onClick={() => handleUpdate({ default_image_format: fmt.id })}
              className={`p-2.5 rounded-xl border text-left flex flex-col transition-all ${
                prefs.default_image_format === fmt.id
                  ? "bg-emerald-500/10 border-emerald-500/40 text-ink shadow-sm shadow-emerald-900/50"
                  : "bg-raised border-hairline text-muted hover:text-ink hover:border-hairline-strong"
              }`}
            >
              <span className="text-xs font-bold uppercase text-ink">{fmt.label}</span>
              <span className="text-[11px] font-mono text-muted">{fmt.desc}</span>
            </button>
          ))}
        </div>

        <p className="text-[11px] text-muted font-mono">
          Original preserves original EXIF metadata, ICC color profiles, and native compression without alteration.
        </p>
      </section>

      {/* ========================================================================= */}
      {/* 5. Session Credentials, Cookies & Custom Request Headers */}
      {/* ========================================================================= */}
      <section
        ref={credentialsRef}
        className="bg-surface border border-hairline rounded-2xl p-6 space-y-4 shadow-card"
      >
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <KeyRound className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Session Credentials & Custom Headers</h2>
              <p className="text-[11px] text-muted font-mono">
                Manage authenticated sessions, browser cookies, and domain-level HTTP headers for restricted platforms.
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <div className="flex bg-page border border-hairline rounded-lg p-0.5 text-xs font-mono">
              <button
                type="button"
                onClick={() => setAuthActiveTab("cookies")}
                className={`px-3 py-1 rounded-md transition-colors ${
                  authActiveTab === "cookies"
                    ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 font-bold border border-amber-500/30"
                    : "text-muted hover:text-ink"
                }`}
              >
                Cookie Profiles ({cookieProfiles.length})
              </button>
              <button
                type="button"
                onClick={() => setAuthActiveTab("headers")}
                className={`px-3 py-1 rounded-md transition-colors ${
                  authActiveTab === "headers"
                    ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 font-bold border border-amber-500/30"
                    : "text-muted hover:text-ink"
                }`}
              >
                Domain Headers ({Object.keys(domainHeaders).length})
              </button>
            </div>
            <button
              type="button"
              onClick={loadAuthData}
              title="Refresh credentials and profiles"
              className="p-1.5 bg-page border border-hairline text-muted hover:text-ink rounded-lg transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Feedback alert */}
        {authFeedback && (
          <div
            className={`p-3 rounded-xl border text-xs font-mono flex items-center justify-between ${
              authFeedback.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
                : "bg-red-500/10 border-red-500/30 text-red-700 dark:text-red-300"
            }`}
          >
            <div className="flex items-center space-x-2">
              {authFeedback.type === "success" ? (
                <CheckCircle2 className="h-4 w-4 shrink-0" />
              ) : (
                <AlertCircle className="h-4 w-4 shrink-0" />
              )}
              <span>{authFeedback.message}</span>
            </div>
            <button
              type="button"
              onClick={() => setAuthFeedback(null)}
              className="text-muted hover:text-ink ml-2 text-xs"
            >
              ✕
            </button>
          </div>
        )}

        {authActiveTab === "cookies" ? (
          <div className="space-y-4">
            {/* Importers Toolbar */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-raised/70 border border-hairline rounded-xl p-4">
              {/* Browser Extractor */}
              <div className="space-y-2">
                <div className="flex items-center space-x-2 text-xs font-medium text-ink/80">
                  <Globe className="h-4 w-4 text-cyan-600 dark:text-cyan-400" />
                  <span>One-Click Browser Cookie Import</span>
                </div>
                <p className="text-[11px] text-muted font-mono">
                  Decrypts session cookies from local browser profiles (Edge, Chrome, Firefox, etc.).
                </p>
                <div className="flex items-center space-x-2 pt-1">
                  <select
                    value={selectedBrowser}
                    onChange={(e) => {
                      const browser = e.target.value;
                      setSelectedBrowser(browser);
                      void handleUpdate({ cookie_browser: browser });
                    }}
                    className="bg-page border border-hairline rounded-lg px-2.5 py-1.5 text-xs text-ink/90 font-mono focus:border-cyan-500 capitalize"
                  >
                    {supportedBrowsers.map((b) => (
                      <option key={b} value={b}>
                        {b.toUpperCase()}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="Domain filter (e.g. patreon.com)"
                    value={browserDomainFilter}
                    onChange={(e) => setBrowserDomainFilter(e.target.value)}
                    className="flex-1 bg-page border border-hairline rounded-lg px-2.5 py-1.5 text-xs text-ink/90 placeholder-faint font-mono focus:border-cyan-500"
                  />
                  <button
                    type="button"
                    onClick={handleBrowserImport}
                    disabled={importingBrowser}
                    className="px-3 py-1.5 bg-cyan-500/15 hover:bg-cyan-800/80 border border-cyan-500/30 text-cyan-700 dark:text-cyan-300 rounded-lg text-xs font-mono transition-colors flex items-center space-x-1.5 shrink-0"
                  >
                    {importingBrowser ? (
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Upload className="h-3.5 w-3.5" />
                    )}
                    <span>Extract</span>
                  </button>
                </div>
              </div>

              {/* File Import & Paste */}
              <div className="space-y-2 md:border-l md:border-hairline md:pl-4">
                <div className="flex items-center space-x-2 text-xs font-medium text-ink/80">
                  <FileText className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                  <span>Manual Netscape File & Text Import</span>
                </div>
                <p className="text-[11px] text-muted font-mono">
                  Import Netscape `.txt` cookies exported from browser extensions or paste raw headers.
                </p>
                <div className="flex items-center space-x-2 pt-1">
                  <button
                    type="button"
                    onClick={handleFileImport}
                    className="flex-1 px-3 py-1.5 bg-page hover:bg-raised border border-hairline text-ink/90 rounded-lg text-xs font-mono transition-colors flex items-center justify-center space-x-1.5"
                  >
                    <Upload className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
                    <span>Import .txt File</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setPasteModalOpen(true)}
                    className="flex-1 px-3 py-1.5 bg-page hover:bg-raised border border-hairline text-ink/90 rounded-lg text-xs font-mono transition-colors flex items-center justify-center space-x-1.5"
                  >
                    <Plus className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                    <span>Paste Text</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Active Profiles Table */}
            <div className="space-y-2">
              <span className="text-xs font-medium text-ink/80">Active Cookie Profiles</span>
              {cookieProfiles.length === 0 ? (
                <div className="p-6 text-center border border-dashed border-hairline rounded-xl bg-raised/50 text-xs font-mono text-faint">
                  No active session cookie profiles found. Import browser cookies or upload a Netscape .txt file above.
                </div>
              ) : (
                <div className="border border-hairline rounded-xl overflow-hidden bg-raised/60">
                  <table className="w-full text-left text-xs font-mono">
                    <thead className="bg-surface border-b border-hairline text-[11px] text-muted uppercase tracking-wider">
                      <tr>
                        <th className="py-2 px-3">Domain</th>
                        <th className="py-2 px-3">Source</th>
                        <th className="py-2 px-3">Cookies</th>
                        <th className="py-2 px-3">Storage Path</th>
                        <th className="py-2 px-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hairline text-ink/80">
                      {cookieProfiles.map((p) => (
                        <tr key={p.id} className="hover:bg-surface transition-colors">
                          <td className="py-2 px-3 font-bold text-amber-700 dark:text-amber-300">{p.domain}</td>
                          <td className="py-2 px-3">
                            <span className="px-1.5 py-0.5 rounded text-[11px] bg-page border border-hairline text-ink/80 uppercase">
                              {p.browser_source || "text"}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-cyan-700 dark:text-cyan-300">{p.cookie_count} entries</td>
                          <td className="py-2 px-3 text-[11px] text-faint truncate max-w-xs" title={p.cookie_file_path}>
                            {p.cookie_file_path}
                          </td>
                          <td className="py-2 px-3 text-right">
                            <button
                              type="button"
                              onClick={() => handleDeleteCookieProfile(p.id, p.domain)}
                              className="text-red-600 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 p-1 hover:bg-red-500/10 rounded transition-colors"
                              title="Delete cookie profile"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Headers Toolbar */}
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-ink/80">Configured Domain Request Headers</span>
              <button
                type="button"
                onClick={() => setHeaderModalOpen(true)}
                className="px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-700 dark:text-amber-300 rounded-lg text-xs font-mono transition-colors flex items-center space-x-1.5"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Add Domain Header</span>
              </button>
            </div>

            {Object.keys(domainHeaders).length === 0 ? (
              <div className="p-6 text-center border border-dashed border-hairline rounded-xl bg-raised/50 text-xs font-mono text-faint">
                No custom domain headers configured. Standard default User-Agent and CORS headers are used.
              </div>
            ) : (
              <div className="border border-hairline rounded-xl overflow-hidden bg-raised/60">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-surface border-b border-hairline text-[11px] text-muted uppercase tracking-wider">
                    <tr>
                      <th className="py-2 px-3">Domain</th>
                      <th className="py-2 px-3">User-Agent</th>
                      <th className="py-2 px-3">Referer</th>
                      <th className="py-2 px-3">Authorization</th>
                      <th className="py-2 px-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline text-ink/80">
                    {Object.entries(domainHeaders).map(([dom, h]) => (
                      <tr key={dom} className="hover:bg-surface transition-colors">
                        <td className="py-2 px-3 font-bold text-amber-700 dark:text-amber-300">{dom}</td>
                        <td className="py-2 px-3 text-[11px] text-muted truncate max-w-xs" title={h["User-Agent"] || "Default"}>
                          {h["User-Agent"] || "Default"}
                        </td>
                        <td className="py-2 px-3 text-[11px] text-muted truncate max-w-xs" title={h["Referer"] || "None"}>
                          {h["Referer"] || "None"}
                        </td>
                        <td className="py-2 px-3 text-[11px] text-muted">
                          {h["Authorization"] ? "Bearer ••••••••" : "None"}
                        </td>
                        <td className="py-2 px-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleDeleteDomainHeaders(dom)}
                            className="text-red-600 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 p-1 hover:bg-red-500/10 rounded transition-colors"
                            title="Delete custom headers"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ========================================================================= */}
      {/* 6. Appearance & Diagnostics */}
      {/* ========================================================================= */}
      <section className="bg-surface border border-hairline rounded-2xl p-6 space-y-4 shadow-card">
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <Moon className="h-5 w-5 text-accent" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Theme & Appearance</h2>
              <p className="text-[11px] text-muted font-mono">
                Select visual color palette and application interface theme.
              </p>
            </div>
          </div>
          <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-page border border-hairline text-ink/80 capitalize">
            {activeTheme ?? prefs.theme}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {[
            { id: "dark", label: "Dark Theme", desc: "XAKURAII Signature Black", icon: Moon },
            { id: "light", label: "Light Theme", desc: "Clean High Contrast", icon: Sun },
            { id: "system", label: "System Sync", desc: "Follow OS Settings", icon: Monitor },
          ].map((theme) => {
            const Icon = theme.icon;
            return (
              <button
                key={theme.id}
                type="button"
                onClick={() => handleUpdate({ theme: theme.id as any })}
                className={`p-3 rounded-xl border text-left flex flex-col space-y-1 transition-all ${
                  (activeTheme ?? prefs.theme) === theme.id
                    ? "bg-accent/10 border-accent/40 text-ink shadow-sm shadow-accent/10"
                    : "bg-raised border-hairline text-muted hover:text-ink hover:border-hairline-strong"
                }`}
              >
                <div className="flex items-center space-x-2">
                  <Icon className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                  <span className="text-xs font-bold text-ink">{theme.label}</span>
                </div>
                <span className="text-[11px] font-mono text-muted">{theme.desc}</span>
              </button>
            );
          })}
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 6. System Runtime Diagnostics */}
      {/* ========================================================================= */}
      <section className="bg-surface border border-hairline rounded-2xl p-6 space-y-4 shadow-card">
        <div className="flex items-center justify-between border-b border-hairline pb-3">
          <div className="flex items-center space-x-2.5">
            <Cpu className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Runtime System Diagnostics</h2>
              <p className="text-[11px] text-muted font-mono">
                Environment runtimes, tool detection, and local SQLite database path.
              </p>
            </div>
          </div>
          <span className="px-2.5 py-0.5 rounded text-xs font-mono bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-300">
            All Systems Active
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono">
          <div className="bg-raised border border-hairline rounded-xl p-3 space-y-1">
            <span className="text-muted text-[11px] uppercase">Python Engine</span>
            <div className="text-ink/90 font-bold">
              Python {pythonStatus?.info?.python_version || "3.12.x"} (PID: {pythonStatus?.pid || "Active"})
            </div>
            <div className="text-[11px] text-faint truncate" title={pythonStatus?.info?.python_executable}>
              {pythonStatus?.info?.python_executable}
            </div>
          </div>

          <div className="bg-raised border border-hairline rounded-xl p-3 space-y-1">
            <span className="text-muted text-[11px] uppercase">Media Processing (FFmpeg)</span>
            <div className="text-ink/90 font-bold">
              {ffmpegInfo?.installed ? `FFmpeg ${ffmpegInfo.version || "Installed"}` : "Not Detected"}
            </div>
            <div className="text-[11px] text-faint truncate" title={ffmpegInfo?.ffmpeg_path || "System PATH"}>
              {ffmpegInfo?.ffmpeg_path || "System PATH"}
            </div>
          </div>

          <div className="bg-raised border border-hairline rounded-xl p-3 space-y-1">
            <span className="text-muted text-[11px] uppercase">Electron Shell</span>
            <div className="text-ink/90 font-bold">
              Electron v{systemInfo?.version || "33.x"} ({systemInfo?.platform || "win32"} {systemInfo?.arch || "x64"})
            </div>
            <div className="text-[11px] text-faint">Local-First Desktop Architecture</div>
          </div>

          <div className="bg-raised border border-hairline rounded-xl p-3 space-y-1">
            <span className="text-muted text-[11px] uppercase">Local Data Directory</span>
            <div className="text-ink/90 font-bold truncate">
              {pythonStatus?.info?.data_dir || "%LOCALAPPDATA%\\XakuMedia"}
            </div>
            <div className="text-[11px] text-faint">Persistent SQLite Database</div>
          </div>
        </div>
      </section>

      {/* Confirmation Modal for Reset Defaults */}
      {resetConfirmOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setResetConfirmOpen(false)}
        >
          <div
            className="bg-page border border-hairline rounded-2xl w-full max-w-md p-6 shadow-2xl space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center space-x-3 text-amber-600 dark:text-amber-400">
              <AlertCircle className="h-6 w-6 shrink-0" />
              <h3 className="text-base font-bold text-ink">Reset Preferences to Factory Defaults?</h3>
            </div>
            <p className="text-xs text-muted leading-relaxed font-mono">
              This will restore the standard download folder, 4-worker concurrency limit, 1080p MP4 defaults, and dark theme. Your downloaded files and scan history will NOT be deleted.
            </p>
            <div className="flex items-center justify-end space-x-2 pt-2">
              <button
                type="button"
                onClick={() => setResetConfirmOpen(false)}
                className="px-4 py-2 bg-raised hover:bg-hairline/70 text-ink/80 hover:text-ink rounded-xl text-xs font-mono transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleResetToDefaults}
                disabled={saving}
                className="px-4 py-2 bg-accent hover:bg-accent-vivid text-on-accent rounded-xl text-xs font-medium transition-colors shadow-md shadow-accent/30 flex items-center space-x-1.5"
              >
                {saving && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                <span>Confirm Reset</span>
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Paste Cookies Modal */}
      {pasteModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setPasteModalOpen(false)}
        >
          <div
            className="bg-page border border-hairline rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center space-x-3 text-amber-600 dark:text-amber-400">
              <KeyRound className="h-5 w-5 shrink-0" />
              <h3 className="text-sm font-bold text-ink">Paste Netscape Cookies Text</h3>
            </div>
            <p className="text-xs text-muted font-mono">
              Paste standard Netscape HTTP cookie file text (tab-separated lines). Supports HttpOnly cookies.
            </p>
            <button
              type="button"
              onClick={() => {
                if (window.api?.openExternalUrl) {
                  void window.api.openExternalUrl(COOKIE_EXPORT_EXTENSION_URL);
                  return;
                }
                window.open(COOKIE_EXPORT_EXTENSION_URL, "_blank", "noopener,noreferrer");
              }}
              className="inline-flex w-fit items-center space-x-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[11px] font-mono text-amber-700 transition-colors hover:bg-amber-500/20 dark:text-amber-300"
            >
              <ExternalLink className="h-3 w-3" />
              <span>Get cookies.txt LOCALLY (Chrome/Edge extension)</span>
            </button>
            <div className="space-y-3 font-mono">
              <div>
                <label className="text-[11px] text-muted uppercase">Target Domain</label>
                <input
                  type="text"
                  placeholder="e.g. patreon.com or artstation.com"
                  value={pasteDomain}
                  onChange={(e) => setPasteDomain(e.target.value)}
                  className="w-full mt-1 bg-surface border border-hairline rounded-lg px-3 py-1.5 text-xs text-ink/90 placeholder-faint focus:border-amber-500"
                />
              </div>
              <div>
                <label className="text-[11px] text-muted uppercase">Cookie Text Content</label>
                <textarea
                  rows={6}
                  placeholder="# Netscape HTTP Cookie File&#10;.example.com	TRUE	/	TRUE	1893456000	session_id	xyz"
                  value={pasteText}
                  onChange={(e) => {
                    const value = e.target.value;
                    setPasteText(value);
                    if (!pasteDomain.trim()) {
                      const detected = detectCookieDomain(value);
                      if (detected) setPasteDomain(detected);
                    }
                  }}
                  className="w-full mt-1 bg-surface border border-hairline rounded-lg p-2.5 text-xs text-ink/90 placeholder-faint font-mono focus:border-amber-500 resize-none"
                />
              </div>
            </div>
            <div className="flex items-center justify-end space-x-2 pt-2">
              <button
                type="button"
                onClick={() => setPasteModalOpen(false)}
                className="px-4 py-2 bg-raised hover:bg-hairline/70 text-ink/80 hover:text-ink rounded-xl text-xs font-mono transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSavePasteCookies}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-black font-bold rounded-xl text-xs transition-colors flex items-center space-x-1.5"
              >
                <Check className="h-3.5 w-3.5" />
                <span>Save Cookies</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Domain Header Modal */}
      {headerModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setHeaderModalOpen(false)}
        >
          <div
            className="bg-page border border-hairline rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center space-x-3 text-cyan-600 dark:text-cyan-400">
              <Shield className="h-5 w-5 shrink-0" />
              <h3 className="text-sm font-bold text-ink">Configure Domain Request Headers</h3>
            </div>
            <p className="text-xs text-muted font-mono">
              Configure custom HTTP headers for requests to this domain and its subdomains.
            </p>
            <div className="space-y-3 font-mono">
              <div>
                <label className="text-[11px] text-muted uppercase">Target Domain</label>
                <input
                  type="text"
                  placeholder="e.g. reddit.com or deviantart.com"
                  value={headerDomain}
                  onChange={(e) => setHeaderDomain(e.target.value)}
                  className="w-full mt-1 bg-surface border border-hairline rounded-lg px-3 py-1.5 text-xs text-ink/90 placeholder-faint focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="text-[11px] text-muted uppercase">User-Agent Override (Optional)</label>
                <input
                  type="text"
                  placeholder="Custom User-Agent header..."
                  value={headerUserAgent}
                  onChange={(e) => setHeaderUserAgent(e.target.value)}
                  className="w-full mt-1 bg-surface border border-hairline rounded-lg px-3 py-1.5 text-xs text-ink/90 placeholder-faint focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="text-[11px] text-muted uppercase">Referer Header (Optional)</label>
                <input
                  type="text"
                  placeholder="https://www.example.com/"
                  value={headerReferer}
                  onChange={(e) => setHeaderReferer(e.target.value)}
                  className="w-full mt-1 bg-surface border border-hairline rounded-lg px-3 py-1.5 text-xs text-ink/90 placeholder-faint focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="text-[11px] text-muted uppercase">Authorization Header (Optional)</label>
                <input
                  type="password"
                  placeholder="Bearer token or API key..."
                  value={headerAuth}
                  onChange={(e) => setHeaderAuth(e.target.value)}
                  className="w-full mt-1 bg-surface border border-hairline rounded-lg px-3 py-1.5 text-xs text-ink/90 placeholder-faint focus:border-cyan-500"
                />
              </div>
            </div>
            <div className="flex items-center justify-end space-x-2 pt-2">
              <button
                type="button"
                onClick={() => setHeaderModalOpen(false)}
                className="px-4 py-2 bg-raised hover:bg-hairline/70 text-ink/80 hover:text-ink rounded-xl text-xs font-mono transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveDomainHeaders}
                className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-black font-bold rounded-xl text-xs transition-colors flex items-center space-x-1.5"
              >
                <Check className="h-3.5 w-3.5" />
                <span>Save Headers</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
