"""YouTube discovery provider adapter for videos, Shorts, live VODs, playlists, and channels."""

from __future__ import annotations

import shutil
import threading
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from ...extractors.video import strip_stale_waf_cookies
from ..base import host_of
from ..ytdlp import YOUTUBE_HOSTS, YtDlpProvider, _EntryHydrator, logger

_FORMAT_UNAVAILABLE_MARKERS = (
    "requested format is not available",
    "no video formats found",
)


def detect_js_runtimes() -> dict[str, dict[str, str]]:
    """Return available JS runtimes for yt-dlp's YouTube signature solver."""
    runtimes: dict[str, dict[str, str]] = {}
    deno_path = shutil.which("deno")
    if deno_path:
        runtimes["deno"] = {"path": deno_path}
    node_path = shutil.which("node")
    if node_path:
        runtimes["node"] = {"path": node_path}
    return runtimes


def is_youtube_format_error(exc: Exception | str) -> bool:
    """Return True when yt-dlp rejected formats due to session/player-client mismatch."""
    lower = str(exc).lower()
    return any(marker in lower for marker in _FORMAT_UNAVAILABLE_MARKERS)


class _YouTubeHydrator(_EntryHydrator):
    """Entry hydrator that retries without stale YouTube cookies on format errors."""

    def __init__(self, opts: dict[str, Any]) -> None:
        super().__init__(opts)
        self._cookieless_local = threading.local()

    def _cookieless_ydl(self) -> yt_dlp.YoutubeDL:
        ydl = getattr(self._cookieless_local, "ydl", None)
        if ydl is None:
            opts = {k: v for k, v in self._opts.items() if k != "cookiefile"}
            ydl = yt_dlp.YoutubeDL(opts)
            self._cookieless_local.ydl = ydl
            with self._lock:
                self._instances.append(ydl)
        return ydl

    def hydrate(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        info, error = super().hydrate(entry)
        if (
            info is not None
            or not self._opts.get("cookiefile")
            or not is_youtube_format_error(error)
        ):
            return info, error
        entry_url = entry.get("url") or entry.get("webpage_url")
        if not entry_url:
            return None, error
        try:
            retry_info = self._cookieless_ydl().extract_info(entry_url, download=False)
        except (DownloadError, ExtractorError) as exc:
            return None, str(exc)
        except Exception as exc:
            return None, str(exc)
        if not retry_info:
            return None, "no metadata returned"
        if retry_info.get("entries"):
            nested = [item for item in retry_info.get("entries") or [] if item]
            if not nested:
                return None, "empty nested collection"
            retry_info = nested[0]
        return retry_info, ""


class YouTubeProvider(YtDlpProvider):
    """Dedicated provider for YouTube videos, Shorts, playlists, and channels."""

    platform_name = "youtube"
    label = "YouTube (yt-dlp)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in YOUTUBE_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://www.youtube.com/")

    def _base_opts(self) -> dict[str, Any]:
        opts = super()._base_opts()
        js_runtimes = detect_js_runtimes()
        if js_runtimes:
            opts["js_runtimes"] = js_runtimes
        return opts

    def _build_hydrator(self, hydrate_opts: dict[str, Any]) -> _EntryHydrator:
        return _YouTubeHydrator(hydrate_opts)

    def _extract_single_info(self, opts: dict[str, Any], safe_url: str) -> Any:
        try:
            return super()._extract_single_info(opts, safe_url)
        except (DownloadError, ExtractorError) as exc:
            if not opts.get("cookiefile") or not is_youtube_format_error(exc):
                raise
            logger.debug(
                f"Retrying YouTube extraction without cookiefile for {safe_url}: {exc}"
            )
            retry_opts = {k: v for k, v in opts.items() if k != "cookiefile"}
            with yt_dlp.YoutubeDL(retry_opts) as ydl:
                strip_stale_waf_cookies(ydl, safe_url)
                return ydl.extract_info(safe_url, download=False)
