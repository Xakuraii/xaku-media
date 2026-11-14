"""Video platform and channel discovery provider backed by yt-dlp.

Single video URLs produce one post. Channel, playlist, and other collection
URLs are enumerated (yt-dlp performs the platform pagination internally) and
each entry is hydrated lazily so results can be streamed to the UI and stopped
by the user without waiting for the whole collection.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from ..core.logging import get_logger
from ..exceptions.base import (
    ExtractionError,
    MediaUnavailableError,
)
from ..extractors.video import normalize_formats, parse_yt_dlp_error
from ..models.media import MediaType
from ..models.post import Post, ProviderCapabilities, ScanOptions
from ..models.url import ClassifiedUrl, UrlCategory
from ..utils.security import validate_url_security
from .base import BaseProvider, PageCallback, host_of, make_media_item, make_post

logger = get_logger("providers.ytdlp")

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
VIDEO_HOSTS = {
    "vimeo.com",
    "www.vimeo.com",
    "dailymotion.com",
    "www.dailymotion.com",
    "twitch.tv",
    "www.twitch.tv",
    "soundcloud.com",
    "www.soundcloud.com",
    "bilibili.com",
    "www.bilibili.com",
}
SAFETY_MAX_POSTS = 5000
HYDRATE_WORKERS = 6

_CHANNEL_PATH = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_CHANNEL_TABS = ("videos", "shorts", "streams")


def is_youtube(url: str) -> bool:
    return host_of(url) in YOUTUBE_HOSTS


def is_collection_url(url: str) -> bool:
    """Detect channel/playlist style URLs without network access."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in YOUTUBE_HOSTS and "list" in parse_qs(parts.query):
        return True
    if host in YOUTUBE_HOSTS:
        if _CHANNEL_PATH.match(parts.path):
            return True
        return bool(re.match(r"^/@[^/]+/(videos|shorts|streams|playlists)/?$", parts.path))
    if host in VIDEO_HOSTS:
        return "/playlist" in parts.path or "/channel" in parts.path or "/user" in parts.path
    return False


def enumerate_url(url: str) -> str:
    """Normalize a YouTube channel root to its Videos tab for enumeration."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return url
    match = _CHANNEL_PATH.match(parts.path)
    if match:
        base = url.split("?", 1)[0].rstrip("/")
        return f"{base}/videos"
    return url


def collection_urls(url: str) -> list[str]:
    """Return every tab/URL needed to enumerate a collection completely.

    A bare YouTube channel URL expands to Videos, Shorts, and Streams so a
    profile scan does not silently miss short-form or live uploads. Explicit
    tab URLs and playlists are enumerated exactly as given.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in YOUTUBE_HOSTS and _CHANNEL_PATH.match(parts.path):
        base = url.split("?", 1)[0].rstrip("/")
        return [f"{base}/{tab}" for tab in _CHANNEL_TABS]
    return [enumerate_url(url)]


def platform_label(url: str) -> str:
    host = host_of(url)
    if host in YOUTUBE_HOSTS:
        return "youtube"
    return "yt-dlp"


def author_hint(url: str) -> str | None:
    parts = urlsplit(url)
    match = re.match(r"^/@([^/]+)", parts.path)
    if match:
        return match.group(1)
    match = re.match(r"^/(?:channel|c|user)/([^/]+)", parts.path)
    if match:
        return match.group(1)
    return None


class _EntryHydrator:
    """Reuse one yt-dlp instance per worker thread while hydrating entries."""

    def __init__(self, opts: dict[str, Any]) -> None:
        self._opts = opts
        self._local = threading.local()
        self._instances: list[yt_dlp.YoutubeDL] = []
        self._lock = threading.Lock()

    def _ydl(self) -> yt_dlp.YoutubeDL:
        ydl = getattr(self._local, "ydl", None)
        if ydl is None:
            ydl = yt_dlp.YoutubeDL(self._opts)
            self._local.ydl = ydl
            with self._lock:
                self._instances.append(ydl)
        return ydl

    def hydrate(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry_url = entry.get("url") or entry.get("webpage_url")
        if not entry_url:
            return None, "entry has no URL"
        try:
            info = self._ydl().extract_info(entry_url, download=False)
        except (DownloadError, ExtractorError) as exc:
            return None, str(exc)
        except Exception as exc:  # a single bad entry must not abort the channel
            return None, str(exc)
        if not info:
            return None, "no metadata returned"
        if info.get("entries"):
            nested = [item for item in info.get("entries") or [] if item]
            if not nested:
                return None, "empty nested collection"
            info = nested[0]
        return info, ""

    def close(self) -> None:
        for ydl in self._instances:
            try:
                ydl.close()
            except Exception:
                pass
        self._instances.clear()


class YtDlpProvider(BaseProvider):
    """Discovers posts from video platforms supported by yt-dlp."""

    name = "ytdlp"
    label = "Video platform (yt-dlp)"

    @classmethod
    def match(cls, url: str) -> bool:
        host = host_of(url)
        if host in YOUTUBE_HOSTS or host in VIDEO_HOSTS:
            return True
        return False

    def capabilities_for(self, url: str) -> ProviderCapabilities:
        collection = is_collection_url(url)
        youtube = is_youtube(url)
        has_cookies = False
        try:
            from ..db import default_repository

            has_cookies = bool(default_repository.get_cookie_profile_for_domain(url))
        except Exception:
            pass
        return ProviderCapabilities(
            provider=self.name,
            label=self.label,
            source_type="channel" if collection else "video",
            profile_bulk=collection,
            individual_posts=True,
            albums=False,
            images=False,
            videos=True,
            pagination=collection,
            requires_auth=False,
            has_cookies=has_cookies,
            notes=(
                "YouTube channel Videos, Shorts, and Streams tabs are enumerated. "
                "Members-only and playlist-only content still require their direct URLs."
                if youtube
                else "Playlist/channel enumeration depends on the site extractor."
            ),
        )

    def classify(self, url: str) -> ClassifiedUrl:
        parts = urlsplit(url)
        collection = is_collection_url(url)
        handle = author_hint(url)
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=url,
            category=UrlCategory.CHANNEL if collection else UrlCategory.SOCIAL_POST,
            platform=platform_label(url),
            domain=parts.netloc,
            author_hint=handle,
            title_hint=handle or platform_label(url),
            is_supported=True,
            requires_auth=False,
            metadata_extra={"provider": self.name},
        )

    def _base_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "simulate": True,
            "socket_timeout": 20,
            "retries": 1,
            "noplaylist": False,
        }
        return opts

    def _apply_auth(self, url: str, opts: dict[str, Any]) -> None:
        try:
            from ..db import default_repository

            profile = default_repository.get_cookie_profile_for_domain(url)
            if profile and profile.cookie_file_path:
                cookie_path = Path(profile.cookie_file_path)
                if cookie_path.exists() and cookie_path.is_file():
                    opts["cookiefile"] = str(cookie_path)
            headers = default_repository.get_domain_headers(url)
            if headers:
                opts["http_headers"] = headers
        except Exception as exc:  # pragma: no cover - defensive auth wiring
            logger.debug(f"Cookie/header lookup skipped for {url}: {exc}")

    def _hydrate_entries(
        self,
        entries: list[dict[str, Any]],
        hydrate_opts: dict[str, Any],
        limit: int,
        cancel_event: threading.Event,
        warn: Callable[[str], None],
        source_url: str,
    ) -> Iterator[Post]:
        """Hydrate entries concurrently while streaming posts in completion order.

        yt-dlp's flat enumeration is fast; hydrating each video serially is the
        slow part of a channel scan. A bounded window keeps memory and request
        bursts under control and still allows prompt cancellation.
        """
        if not entries:
            return

        workers = min(HYDRATE_WORKERS, max(2, len(entries)))
        hydrator = _EntryHydrator(hydrate_opts)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="xaku-hydrate")
        pending: dict[Any, dict[str, Any]] = {}
        iterator = iter(entries)
        exhausted = False
        emitted = 0

        def submit_next() -> None:
            nonlocal exhausted
            while not exhausted:
                try:
                    entry = next(iterator)
                except StopIteration:
                    exhausted = True
                    return
                if entry.get("_type") in ("playlist", "multi_video"):
                    warn(
                        "Nested playlists are not expanded automatically. "
                        "Scan the playlist URL directly for its videos."
                    )
                    continue
                pending[executor.submit(hydrator.hydrate, entry)] = entry
                return

        for _ in range(workers * 2):
            submit_next()

        try:
            while pending:
                if cancel_event.is_set():
                    return
                done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                for future in done:
                    entry = pending.pop(future)
                    if cancel_event.is_set():
                        return
                    try:
                        info, error = future.result()
                    except Exception as exc:  # defensive: worker failures are per-entry
                        info, error = None, str(exc)
                    if not info:
                        label = (
                            entry.get("title")
                            or entry.get("id")
                            or entry.get("url")
                            or "unknown entry"
                        )
                        warn(f"Skipped an unavailable entry: {label}")
                        logger.debug(f"Hydration failed for {label}: {error}")
                        submit_next()
                        continue
                    emitted += 1
                    yield self._post_from_info(info, source_url)
                    if emitted >= limit:
                        return
                    submit_next()
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            # Closing while workers are still in flight would race with them.
            if not pending:
                hydrator.close()

    def _post_from_info(self, info: dict[str, Any], source_url: str) -> Post:
        formats = normalize_formats(info.get("formats", []))
        best = formats[0] if formats else None
        stream_url = (
            (best.url if best and best.url else None)
            or info.get("webpage_url")
            or source_url
        )
        video_id = str(info.get("id") or info.get("display_id") or stream_url)
        author = (
            info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or info.get("uploader_id")
            or "media"
        )
        page_url = info.get("webpage_url") or source_url
        post_key = f"{platform_label(source_url)}:{video_id}"
        post = make_post(
            provider=self.name,
            source_url=source_url,
            post_key=post_key,
            provider_post_id=video_id,
            author=str(author),
            title=info.get("title"),
            media_items=[],
            post_url=page_url,
            metadata_extra={
                "extractor": info.get("extractor_key") or info.get("extractor"),
                "view_count": info.get("view_count"),
            },
        )
        item = make_media_item(
            provider=self.name,
            source_url=source_url,
            media_url=stream_url,
            media_type=MediaType.VIDEO,
            post_id=post.id,
            title=info.get("title"),
            author=str(author),
            thumbnail_url=info.get("thumbnail"),
            duration_seconds=float(info["duration"]) if info.get("duration") else None,
            width=info.get("width") or (best.width if best else None),
            height=info.get("height") or (best.height if best else None),
            filesize_bytes=info.get("filesize")
            or info.get("filesize_approx")
            or (best.filesize_bytes if best else None),
            extension=(best.container if best else "mp4"),
            mime_type="video/mp4",
            format_info=best,
            provider_media_id=video_id,
            post_url=page_url,
            attachment_index=0,
            metadata_extra={"formats_available": len(formats)},
        )
        item.available_formats = formats
        post.media_items = [item]
        post.post_type = Post.infer_type(post.media_items)
        return post

    def iter_posts(
        self,
        url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        on_page: PageCallback | None = None,
        on_warning: Callable[[str], None] | None = None,
    ) -> Iterator[Post]:
        safe_url = validate_url_security(url)
        collection = is_collection_url(safe_url)
        warn = on_warning or (lambda _msg: None)

        if not options.include_videos:
            return

        if not collection:
            opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
            self._apply_auth(safe_url, opts)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(safe_url, download=False)
            except (DownloadError, ExtractorError) as exc:
                raise parse_yt_dlp_error(str(exc), safe_url) from exc
            if not info:
                raise MediaUnavailableError(f"Could not extract video metadata from: {url}")
            if on_page:
                on_page(1)
            yield self._post_from_info(info, safe_url)
            return

        limit = options.max_posts or SAFETY_MAX_POSTS
        enum_opts = self._base_opts() | {
            "extract_flat": "in_playlist",
            "playlistend": limit,
            "ignoreerrors": True,
        }
        hydrate_opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
        self._apply_auth(safe_url, enum_opts)
        self._apply_auth(safe_url, hydrate_opts)

        entries: list[dict[str, Any]] = []
        seen_entries: set[str] = set()
        failed_tabs: list[str] = []
        first_error: Exception | None = None

        try:
            for tab_index, enum_url in enumerate(collection_urls(safe_url)):
                if cancel_event.is_set():
                    return
                try:
                    with yt_dlp.YoutubeDL(enum_opts) as enum_ydl:
                        info = enum_ydl.extract_info(enum_url, download=False)
                except (DownloadError, ExtractorError) as exc:
                    failed_tabs.append(str(exc))
                    if first_error is None:
                        first_error = exc
                    continue
                if not info:
                    failed_tabs.append(f"No metadata returned for {enum_url}")
                    continue
                if on_page:
                    on_page(tab_index + 1)
                for entry in info.get("entries") or []:
                    if not entry:
                        continue
                    key = str(
                        entry.get("id")
                        or entry.get("url")
                        or entry.get("webpage_url")
                        or ""
                    )
                    if key and key in seen_entries:
                        continue
                    if key:
                        seen_entries.add(key)
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
                if len(entries) >= limit:
                    break

            if not entries:
                if first_error is not None:
                    raise parse_yt_dlp_error(str(first_error), safe_url) from first_error
                raise MediaUnavailableError(f"No posts found in collection: {url}")

            if failed_tabs:
                warn(
                    "Some collection tabs could not be enumerated: "
                    + " | ".join(message[:180] for message in failed_tabs[:3])
                )

            yield from self._hydrate_entries(
                entries,
                hydrate_opts,
                limit,
                cancel_event,
                warn,
                safe_url,
            )
        except (DownloadError, ExtractorError) as exc:
            raise parse_yt_dlp_error(str(exc), safe_url) from exc
        except ExtractionError:
            raise
