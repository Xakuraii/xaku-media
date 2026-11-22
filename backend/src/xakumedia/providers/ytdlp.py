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
from urllib.parse import parse_qs, urlsplit, urlunsplit

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from ..core.config import default_config
from ..core.logging import get_logger
from ..exceptions.base import (
    ExtractionError,
    MediaUnavailableError,
    PrivateMediaError,
)
from ..extractors.video import (
    normalize_formats,
    parse_yt_dlp_error,
    strip_stale_waf_cookies,
)
from ..models.media import MediaFormatInfo, MediaType
from ..models.post import Post, ProviderCapabilities, ScanOptions
from ..models.url import ClassifiedUrl, UrlCategory
from ..utils.security import validate_url_security
from .base import BaseProvider, PageCallback, TotalCallback, host_of, make_media_item, make_post

logger = get_logger("providers.ytdlp")

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}
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
_TIKTOK_PROFILE_PATH = re.compile(r"^/@([^/]+)(?:/videos)?/?$")
_TIKTOK_PHOTO_PATH = re.compile(r"^/(@[^/]+)/photo/(\d+)")


def normalize_tiktok_photo_url(url: str) -> str:
    """Rewrite TikTok ``/photo/<id>`` links to the ``/video/<id>`` form.

    TikTok serves both forms for slideshows, but yt-dlp's TikTok extractor only
    matches ``/video/``. Users paste whichever form TikTok's share button gave
    them, so normalize before extraction instead of rejecting the link.
    """
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in TIKTOK_HOSTS:
        return url
    path = _TIKTOK_PHOTO_PATH.sub(r"/\1/video/\2", parts.path, count=1)
    if path == parts.path:
        return url
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

_IMPERSONATION_TARGET: Any | None = None
_IMPERSONATION_READY = False


def is_youtube(url: str) -> bool:
    return host_of(url) in YOUTUBE_HOSTS


def is_tiktok(url: str) -> bool:
    return host_of(url) in TIKTOK_HOSTS


def tiktok_impersonation_target() -> Any | None:
    """Return yt-dlp's Chrome impersonation target when its backend is usable.

    TikTok serves a JavaScript challenge to plain clients and returns 403. The
    impersonation target makes curl_cffi emulate Chrome's TLS fingerprint, which
    is the difference between "cookies saved but still forbidden" and a working
    scan. A missing or incompatible curl_cffi degrades to a normal request.
    """
    global _IMPERSONATION_TARGET, _IMPERSONATION_READY
    if _IMPERSONATION_READY:
        return _IMPERSONATION_TARGET
    _IMPERSONATION_READY = True
    try:
        import importlib

        importlib.import_module("yt_dlp.networking._curlcffi")
        from yt_dlp.networking.impersonate import ImpersonateTarget

        _IMPERSONATION_TARGET = ImpersonateTarget("chrome")
    except Exception as exc:
        logger.warning(
            f"TikTok browser impersonation unavailable; scans may be blocked: {exc}"
        )
        _IMPERSONATION_TARGET = None
    return _IMPERSONATION_TARGET


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
    if host in TIKTOK_HOSTS:
        return _TIKTOK_PROFILE_PATH.match(parts.path) is not None
    return False


def enumerate_url(url: str) -> str:
    """Normalize a channel/profile URL to the canonical form for enumeration."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in TIKTOK_HOSTS:
        match = _TIKTOK_PROFILE_PATH.match(parts.path)
        if match:
            return f"https://www.tiktok.com/@{match.group(1)}"
        return url
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
    if host in TIKTOK_HOSTS:
        return "tiktok"
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
            strip_stale_waf_cookies(ydl)
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
        if host in YOUTUBE_HOSTS or host in VIDEO_HOSTS or host in TIKTOK_HOSTS:
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
                else (
                    "TikTok profiles are enumerated through yt-dlp with Chrome "
                    "impersonation. A cookie profile makes private/follow-only "
                    "uploads available; photo posts are read through gallery-dl "
                    "so each slide is discovered as an image."
                    if is_tiktok(url)
                    else "Playlist/channel enumeration depends on the site extractor."
                )
            ),
        )

    def classify(self, url: str) -> ClassifiedUrl:
        parts = urlsplit(url)
        normalized = normalize_tiktok_photo_url(url)
        collection = is_collection_url(normalized)
        handle = author_hint(normalized)
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=normalized,
            category=UrlCategory.CHANNEL if collection else UrlCategory.SOCIAL_POST,
            platform=platform_label(normalized),
            domain=parts.netloc,
            author_hint=handle,
            title_hint=handle or platform_label(normalized),
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
            "socket_timeout": float(default_config.request_timeout_seconds),
            "retries": int(default_config.max_retries),
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
            if host_of(url) in TIKTOK_HOSTS:
                target = tiktok_impersonation_target()
                if target is not None:
                    opts["impersonate"] = target
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
        options: ScanOptions,
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
                    post = self._post_from_info(info, source_url, warn)
                    if post is None:
                        # TikTok photo post with no retrievable slides. The
                        # fallback already warned; never emit the audio track.
                        submit_next()
                        continue
                    if not options.include_videos and not any(
                        item.media_type == MediaType.IMAGE
                        for item in post.media_items
                    ):
                        submit_next()
                        continue
                    emitted += 1
                    yield post
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

    @staticmethod
    def _tiktok_video_id(page_url: str, info: dict[str, Any]) -> str:
        """Return the numeric TikTok post id from metadata or its page URL."""
        value = info.get("id") or info.get("display_id")
        if value:
            return str(value)
        match = re.search(r"/(?:video|photo)/(\d+)", page_url)
        if match:
            return match.group(1)
        return page_url.rstrip("/").rsplit("/", 1)[-1]

    def _tiktok_web_data(self, page_url: str, video_id: str) -> dict[str, Any]:
        """Return TikTok's embedded post data using yt-dlp's browser session.

        TikTok denies gallery-dl's plain requests with HTTP 403, while yt-dlp
        succeeds because it sends Chrome's TLS fingerprint and solves the JS
        challenge. Reusing that extractor is the difference between a photo
        post returning all slides and disappearing from the scan.
        """
        opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
        self._apply_auth(page_url, opts)
        with yt_dlp.YoutubeDL(opts) as ydl:
            strip_stale_waf_cookies(ydl, page_url)
            extractor = ydl.get_info_extractor("TikTok")
            fetch = getattr(extractor, "_extract_web_data_and_status", None)
            if not callable(fetch):
                return {}
            data, _status = fetch(page_url, video_id, fatal=False)
        return data if isinstance(data, dict) else {}

    def _resolve_tiktok_profile_via_waf(
        self,
        ydl: yt_dlp.YoutubeDL,
        profile_url: str,
    ) -> dict[str, Any] | None:
        """Resolve a TikTok @user profile by solving SlardarWAF when embed fallback fails.

        yt-dlp's single-video extractor solves SlardarWAF challenges automatically, but
        TikTokUserIE._real_extract only tries /embed/@user when the initial webpage is
        challenged. Creators with embeds disabled fail even with valid cookies unless we
        solve the WAF challenge on the profile page and extract via ``tiktokuser:<secUid>``.
        """
        parts = urlsplit(profile_url)
        match = re.match(r"^/@([^/?#]+)/?$", parts.path)
        if not match or not is_tiktok(profile_url):
            return None
        username = match.group(1)

        try:
            extractor = ydl.get_info_extractor("TikTokUser")
        except Exception:
            return None
        if not extractor:
            return None

        headers_fn = getattr(extractor, "_generate_blockbuster_headers", None)
        headers = headers_fn() if callable(headers_fn) else {}
        download_webpage = getattr(extractor, "_download_webpage", None)
        get_universal = getattr(extractor, "_get_universal_data", None)
        solve_waf = getattr(extractor, "_solve_challenge_and_set_cookies", None)
        if not callable(download_webpage) or not callable(get_universal):
            return None

        user_url = f"https://www.tiktok.com/@{username}"
        webpage = (
            download_webpage(
                user_url,
                username,
                note=False,
                errnote=False,
                fatal=False,
                impersonate=True,
                headers=headers,
            )
            or ""
        )
        universal_data = get_universal(webpage, username) if webpage else None
        if not universal_data and webpage and callable(solve_waf):
            cookie_names: tuple[str | None, ...] = ()
            try:
                cookie_names = solve_waf(webpage)
                webpage = (
                    download_webpage(
                        user_url,
                        username,
                        note=False,
                        errnote=False,
                        fatal=False,
                        impersonate=True,
                        headers=headers,
                    )
                    or ""
                )
            except ExtractorError as exc:
                logger.debug(f"TikTok WAF challenge solve skipped for @{username}: {exc}")
                return None
            finally:
                cookiejar = getattr(extractor, "cookiejar", None)
                if cookiejar is not None:
                    for cn in filter(None, cookie_names):
                        try:
                            cookiejar.clear(domain=".tiktok.com", path="/", name=cn)
                        except Exception:
                            pass
            universal_data = get_universal(webpage, username) if webpage else None

        detail = (
            universal_data.get("webapp.user-detail")
            if isinstance(universal_data, dict)
            else None
        )
        if not isinstance(detail, dict):
            return None

        status_code = detail.get("statusCode")
        user_info = detail.get("userInfo") if isinstance(detail.get("userInfo"), dict) else {}
        user = user_info.get("user") if isinstance(user_info.get("user"), dict) else {}
        stats = user_info.get("stats") or user_info.get("statsV2") or {}

        if status_code == 10222 or user.get("privateAccount") is True:
            raise PrivateMediaError(
                f"TikTok account '@{username}' is private. Log into a TikTok "
                "account that has access and import fresh cookies.",
                details={
                    "url": profile_url,
                    "site": "tiktok",
                    "requires_cookies": True,
                },
            )

        sec_uid = user.get("secUid")
        if not sec_uid or not isinstance(sec_uid, str):
            if status_code == 209002:
                raise PrivateMediaError(
                    f"TikTok restricted profile '@{username}' behind session "
                    "verification. Import fresh logged-in TikTok cookies in "
                    "Settings and retry.",
                    details={
                        "url": profile_url,
                        "site": "tiktok",
                        "requires_cookies": True,
                    },
                )
            return None

        video_count = stats.get("videoCount") if isinstance(stats, dict) else None
        if video_count == 0:
            raise MediaUnavailableError(
                f"TikTok account '@{username}' does not have any public videos posted.",
                details={"url": profile_url, "site": "tiktok"},
            )

        return ydl.extract_info(f"tiktokuser:{sec_uid}", download=False)

    @staticmethod
    def _tiktok_slideshow_items(
        data: dict[str, Any],
        author: str,
        title: str | None,
        video_id: str,
        page_url: str,
    ) -> list[Any]:
        """Build image items from TikTok's ``imagePost`` payload."""
        images = ((data.get("imagePost") or {}).get("images") or [])
        items: list[Any] = []
        seen: set[str] = set()
        for index, image in enumerate(images):
            if not isinstance(image, dict):
                continue
            image_url = image.get("imageURL") or {}
            urls = image_url.get("urlList") or []
            if not urls:
                urls = (image.get("displayImage") or {}).get("urlList") or []
            media_url = next(
                (str(url) for url in urls if isinstance(url, str) and url),
                "",
            )
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)
            path = media_url.split("?", 1)[0]
            extension = path.rsplit(".", 1)[-1].lower() if "." in path else "jpeg"
            if extension == "jpg":
                extension = "jpeg"
            width = image.get("imageWidth") or image_url.get("width")
            height = image.get("imageHeight") or image_url.get("height")
            format_info = MediaFormatInfo(
                format_id=f"image-{index}",
                container=extension,
                resolution=f"{width}x{height}" if width and height else None,
                width=width,
                height=height,
                is_direct_stream=True,
                url=media_url,
                requires_merge=False,
                format_note="original",
                http_headers={"Referer": "https://www.tiktok.com/"},
            )
            items.append(
                make_media_item(
                    provider=YtDlpProvider.name,
                    source_url=page_url,
                    media_url=media_url,
                    media_type=MediaType.IMAGE,
                    post_id="",
                    title=title,
                    author=author,
                    thumbnail_url=media_url,
                    width=width,
                    height=height,
                    extension=extension,
                    mime_type=f"image/{extension}",
                    format_info=format_info,
                    provider_media_id=f"{video_id}:{index}",
                    attachment_index=index,
                    metadata_extra={"post_id": video_id, "slideshow": True},
                )
            )
        return items

    def _tiktok_gallery_image_post(
        self,
        page_url: str,
        source_url: str,
        info: dict[str, Any],
        video_id: str,
        warn: Callable[[str], None] | None,
    ) -> Post | None:
        """Legacy slideshow fallback through gallery-dl (may be rate limited)."""
        from .gallerydl import GalleryDlProvider

        try:
            gallery = GalleryDlProvider()
            posts = list(
                gallery.iter_posts(
                    page_url,
                    ScanOptions(include_images=True, include_videos=False),
                    threading.Event(),
                )
            )
        except Exception as exc:
            if warn:
                warn(f"Could not load TikTok slideshow images: {exc}")
            logger.warning(f"TikTok slideshow fallback failed for {page_url}: {exc}")
            return None

        images = [
            item
            for post in posts
            for item in post.media_items
            if item.media_type == MediaType.IMAGE
        ]
        if not images:
            if warn:
                warn("A TikTok photo post did not return any slide images.")
            return None

        author = str(
            info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or next((post.author for post in posts if post.author), "media")
        )
        return make_post(
            provider=self.name,
            source_url=source_url,
            post_key=f"tiktok:{video_id}",
            provider_post_id=video_id,
            author=author,
            title=info.get("title") or next((post.title for post in posts if post.title), None),
            media_items=images,
            post_url=page_url,
            metadata_extra={
                "extractor": "TikTok",
                "slideshow": True,
                "media_provider": GalleryDlProvider.name,
            },
        )

    def _tiktok_image_post(
        self,
        page_url: str,
        source_url: str,
        info: dict[str, Any],
        warn: Callable[[str], None] | None = None,
    ) -> Post | None:
        """Build a TikTok slideshow post from the post's own slide images.

        yt-dlp only exposes the background audio track for photo-mode posts, so
        a normal video item would download as an MP3. yt-dlp's embedded post
        data (``imagePost.images``) contains the real slides and is fetched with
        the same impersonated session that enumerated the post. gallery-dl is
        kept as a fallback for unusual posts, but is unreliable here because
        TikTok blocks its plain HTTP client.
        """
        video_id = self._tiktok_video_id(page_url, info)
        data: dict[str, Any] = {}
        try:
            data = self._tiktok_web_data(page_url, video_id)
        except Exception as exc:  # fall back to gallery-dl below
            logger.debug(f"TikTok slide data unavailable for {page_url}: {exc}")

        author = str(
            (data.get("author") or {}).get("uniqueId")
            or info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or "media"
        )
        title = data.get("desc") or info.get("title")
        items = self._tiktok_slideshow_items(data, author, title, video_id, page_url)
        if items:
            return make_post(
                provider=self.name,
                source_url=source_url,
                post_key=f"tiktok:{video_id}",
                provider_post_id=video_id,
                author=author,
                title=title,
                media_items=items,
                post_url=page_url,
                metadata_extra={
                    "extractor": "TikTok",
                    "slideshow": True,
                    "media_provider": self.name,
                },
            )

        return self._tiktok_gallery_image_post(
            page_url, source_url, info, video_id, warn
        )

    def fetch_thumbnail(self, url: str) -> str | None:
        """Return the page's primary thumbnail URL, or None when unavailable."""
        opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
        self._apply_auth(url, opts)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            logger.debug(f"Thumbnail lookup failed for {url}: {exc}")
            return None
        if not isinstance(info, dict):
            return None
        thumbnail = info.get("thumbnail")
        if thumbnail:
            return str(thumbnail)
        for candidate in info.get("thumbnails") or []:
            if isinstance(candidate, dict) and candidate.get("url"):
                return str(candidate["url"])
        return None

    def _post_from_info(
        self,
        info: dict[str, Any],
        source_url: str,
        warn: Callable[[str], None] | None = None,
    ) -> Post | None:
        formats = normalize_formats(
            info.get("formats", []), info.get("http_headers")
        )
        page_url = info.get("webpage_url") or source_url
        video_formats = [fmt for fmt in formats if fmt.video_codec]

        if is_tiktok(source_url) and not video_formats:
            # Photo-mode posts only expose their background audio to yt-dlp.
            # Return the slide images when gallery-dl can provide them, and no
            # post at all when it cannot, so an MP3 is never presented as video.
            return self._tiktok_image_post(page_url, source_url, info, warn)

        best = video_formats[0] if video_formats else (formats[0] if formats else None)
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
        on_total: TotalCallback | None = None,
    ) -> Iterator[Post]:
        safe_url = normalize_tiktok_photo_url(validate_url_security(url))
        collection = is_collection_url(safe_url)
        warn = on_warning or (lambda _msg: None)

        if not options.include_videos and not (
            options.include_images and is_tiktok(safe_url)
        ):
            return

        if not collection:
            if on_total:
                on_total(1, None)
            opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
            self._apply_auth(safe_url, opts)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    strip_stale_waf_cookies(ydl, safe_url)
                    info = ydl.extract_info(safe_url, download=False)
            except (DownloadError, ExtractorError) as exc:
                if is_tiktok(safe_url) and options.include_images:
                    slideshow = self._tiktok_image_post(safe_url, safe_url, {}, warn)
                    if slideshow is not None:
                        if on_page:
                            on_page(1)
                        yield slideshow
                        return
                raise parse_yt_dlp_error(str(exc), safe_url) from exc
            if not info:
                raise MediaUnavailableError(f"Could not extract video metadata from: {url}")
            if on_page:
                on_page(1)
            post = self._post_from_info(info, safe_url, warn)
            if post is None or not post.media_items:
                raise MediaUnavailableError(
                    "TikTok returned no downloadable video or slide images for this post. "
                    "It may be region-restricted, deleted, or still processing."
                )
            yield post
            return

        limit = options.max_posts or SAFETY_MAX_POSTS
        enum_opts = self._base_opts() | {
            "extract_flat": "in_playlist",
            "playlistend": limit,
            "ignoreerrors": "only_download",
        }
        hydrate_opts = self._base_opts() | {"noplaylist": True, "extract_flat": False}
        self._apply_auth(safe_url, enum_opts)
        self._apply_auth(safe_url, hydrate_opts)

        entries: list[dict[str, Any]] = []
        seen_entries: set[str] = set()
        failed_tabs: list[str] = []
        first_error: Exception | None = None
        tab_urls = collection_urls(safe_url)

        try:
            for tab_index, enum_url in enumerate(tab_urls):
                if cancel_event.is_set():
                    return
                try:
                    with yt_dlp.YoutubeDL(enum_opts) as enum_ydl:
                        strip_stale_waf_cookies(enum_ydl, enum_url)
                        info = enum_ydl.extract_info(enum_url, download=False)
                        if not info and is_tiktok(enum_url):
                            info = self._resolve_tiktok_profile_via_waf(enum_ydl, enum_url)
                except (DownloadError, ExtractorError) as exc:
                    if is_tiktok(enum_url):
                        try:
                            with yt_dlp.YoutubeDL(enum_opts) as waf_ydl:
                                strip_stale_waf_cookies(waf_ydl, enum_url)
                                info = self._resolve_tiktok_profile_via_waf(waf_ydl, enum_url)
                        except ExtractionError:
                            raise
                        except (DownloadError, ExtractorError):
                            info = None
                    else:
                        info = None
                    if not info:
                        failed_tabs.append(str(exc))
                        if first_error is None:
                            first_error = exc
                        continue
                if not info:
                    failed_tabs.append(f"No metadata returned for {enum_url}")
                    continue
                if on_page:
                    on_page(tab_index + 1, len(tab_urls))
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
                    err_text = str(first_error)
                    if is_tiktok(safe_url) and "secondary user id" in err_text.lower():
                        user = author_hint(safe_url) or safe_url
                        raise MediaUnavailableError(
                            f"TikTok did not expose public profile posts for '@{user}' "
                            "(embeds may be disabled, the account may be private, or profile "
                            "listing is restricted even with saved cookies). Try scanning a "
                            "direct video or slideshow URL from this creator instead.",
                            details={
                                "url": safe_url,
                                "site": "tiktok",
                                "reason": "tiktok_secuid_unavailable",
                            },
                        ) from first_error
                    raise parse_yt_dlp_error(err_text, safe_url) from first_error
                raise MediaUnavailableError(f"No posts found in collection: {url}")

            if on_total:
                on_total(min(limit, len(entries)), None)

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
                options,
            )
        except (DownloadError, ExtractorError) as exc:
            raise parse_yt_dlp_error(str(exc), safe_url) from exc
        except ExtractionError:
            raise
