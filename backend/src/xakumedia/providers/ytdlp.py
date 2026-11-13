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

_CHANNEL_PATH = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")


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
                "YouTube channel Videos tab and playlists are enumerated. "
                "Shorts/Live tabs and members-only content are not included."
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

    def _hydrate(self, ydl: yt_dlp.YoutubeDL, entry: dict[str, Any]) -> dict[str, Any] | None:
        entry_url = entry.get("url") or entry.get("webpage_url")
        if not entry_url:
            return None
        try:
            info = ydl.extract_info(entry_url, download=False)
        except (DownloadError, ExtractorError) as exc:
            logger.warning(f"Could not hydrate entry {entry_url}: {exc}")
            return None
        if not info:
            return None
        if info.get("entries"):
            entries = [item for item in info.get("entries") or [] if item]
            return entries[0] if entries else None
        return info

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

        enum_url = enumerate_url(safe_url)
        limit = options.max_posts or SAFETY_MAX_POSTS
        enum_opts = self._base_opts() | {
            "extract_flat": "in_playlist",
            "playlistend": limit,
            "ignoreerrors": True,
        }
        hydrate_opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
        self._apply_auth(safe_url, enum_opts)
        self._apply_auth(safe_url, hydrate_opts)

        try:
            with (
                yt_dlp.YoutubeDL(enum_opts) as enum_ydl,
                yt_dlp.YoutubeDL(hydrate_opts) as hydrate_ydl,
            ):
                info = enum_ydl.extract_info(enum_url, download=False)
                if not info:
                    raise MediaUnavailableError(
                        f"Collection could not be enumerated: {url}"
                    )
                entries = [entry for entry in (info.get("entries") or []) if entry]
                if on_page:
                    on_page(1)
                if not entries:
                    raise MediaUnavailableError(f"No posts found in collection: {url}")

                emitted = 0
                for entry in entries:
                    if cancel_event.is_set():
                        return
                    if emitted >= limit:
                        return
                    if entry.get("_type") in ("playlist", "multi_video"):
                        warn(
                            "Nested tabs are not expanded automatically. "
                            "Scan the channel Videos or a playlist URL directly."
                        )
                        continue
                    full = self._hydrate(hydrate_ydl, entry)
                    if not full:
                        warn(
                            f"Skipped an unavailable entry: {entry.get('title') or entry.get('id')}"
                        )
                        continue
                    emitted += 1
                    yield self._post_from_info(full, safe_url)
        except (DownloadError, ExtractorError) as exc:
            raise parse_yt_dlp_error(str(exc), safe_url) from exc
        except ExtractionError:
            raise
