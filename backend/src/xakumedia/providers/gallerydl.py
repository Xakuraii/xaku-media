"""Gallery, album, and profile discovery backed by gallery-dl.

Unlike the legacy wrapper, this provider consumes gallery-dl's lazy item
iterator. Results are emitted per post as soon as the post boundary is known,
which keeps scans progressive, cancellable, and bounded.

Profiles and channels on some sites (Pinterest boards, Instagram tabs) are
returned by gallery-dl as ``Message.Queue`` entries instead of direct media.
Those queues are expanded recursively with a depth cap so a single profile URL
can still produce posts, while malicious or runaway queues stay bounded.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from gallery_dl import config as gdl_config
from gallery_dl import extractor as gdl_extractor
from gallery_dl.exception import (
    AuthenticationError,
    AuthorizationError,
    HttpError,
    NoExtractorError,
    NotFoundError,
)
from gallery_dl.extractor.message import Message

from ..core.logging import get_logger
from ..exceptions.base import (
    ExtractionError,
    MediaUnavailableError,
    PrivateMediaError,
    UnsupportedSourceError,
    XakuMediaError,
)
from ..extractors.gallery import parse_gallery_dl_error
from ..models.media import MediaFormatInfo, MediaItem, MediaType
from ..models.post import Post, ProviderCapabilities, ScanOptions
from ..models.url import ClassifiedUrl, UrlCategory
from ..utils.security import validate_url_security
from ..utils.stable_ids import url_fingerprint
from .base import (
    BaseProvider,
    PageCallback,
    WarningCallback,
    host_of,
    make_media_item,
    make_post,
)

logger = get_logger("providers.gallerydl")

PROFILE_SUBCATEGORIES = {"user", "channel", "profile", "artist", "board", "subreddit", "creator"}
AUTH_HEAVY_CATEGORIES = {"instagram", "twitter", "tiktok", "facebook", "threads", "patreon"}
MAX_QUEUE_DEPTH = 3
POST_KEYS = (
    "post_id",
    "shortcode",
    "tweet_id",
    "status_id",
    "submission_id",
    "gallery_id",
    "artwork_id",
    "pin_id",
    "illust_id",
    "work_id",
    "group",
)
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif", "bmp", "tiff", "svg"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mkv", "mov", "avi", "m4v", "ts"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "flac", "ogg", "wav", "opus"}
AUDIO_CODECS = {
    "mp3": "mp3",
    "m4a": "aac",
    "aac": "aac",
    "flac": "flac",
    "ogg": "vorbis",
    "opus": "opus",
    "wav": "pcm_s16le",
}
# Instagram returns DASH manifests by default. Its extractor can instead expose
# the progress video URL (``videos = "merged"``), which is a single MP4 with
# audio and needs no secondary manifest fetch during download.
MERGED_VIDEO_CATEGORIES = {"instagram"}
# Sites whose gallery-dl video entries are progressive MP4 files that already
# contain their audio track. Facebook is intentionally absent: its extractor
# emits a separate DASH audio item that must be muxed.
MUXED_VIDEO_CATEGORIES = {"instagram", "twitter", "threads"}
X_HOSTS = {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com"}
_X_TWEETS_PATH = re.compile(r"^/([^/]+)/tweets/?$")
# gallery-dl's Facebook profile extractor dispatches info/avatar/photos/albums
# but never the profile's video tabs. These patterns read the server-rendered
# video ids from those tabs so each reel can be handed to gallery-dl's own
# video extractor (which already knows how to pair DASH video and audio).
FACEBOOK_CATEGORY = "facebook"
FACEBOOK_VIDEO_TABS = ("videos", "reels")
FACEBOOK_VIDEO_ID_PATTERNS = (
    re.compile(r'"__typename":"Video","id":"(\d+)"'),
    re.compile(r'"video_id":"(\d+)"'),
    re.compile(r'\\"__typename\\":\\"Video\\",\\"id\\":\\"(\d+)\\"'),
    re.compile(r'\\"video_id\\":\\"(\d+)\\"'),
)


def _prefer_media_queue(url: str) -> str:
    """Point X profile queues at the media tab instead of the full timeline.

    gallery-dl's user extractor queues ``/<user>/tweets``. That walks every
    text-only tweet until media appears, which is slow and can hit rate limits.
    The media tab returns exactly the pictures and videos a scan wants.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    match = _X_TWEETS_PATH.match(parts.path)
    if host in X_HOSTS and match:
        return f"{parts.scheme or 'https'}://{parts.netloc}/{match.group(1)}/media"
    return url


def _find_extractor(url: str):
    try:
        return gdl_extractor.find(url)
    except Exception:
        return None


def _facebook_profile_base(url: str) -> str | None:
    """Return the canonical profile URL for a Facebook user/page root.

    Only profile roots are eligible: an explicit ``/photos`` or ``/reel`` URL
    should keep its exact requested scope.
    """
    extractor = _find_extractor(url)
    if extractor is None:
        return None
    if getattr(extractor, "category", None) != FACEBOOK_CATEGORY:
        return None
    if getattr(extractor, "subcategory", None) not in PROFILE_SUBCATEGORIES:
        return None
    groups = getattr(extractor, "groups", ()) or ()
    name = groups[0] if groups else None
    if not name:
        return None
    return f"https://www.facebook.com/{name}"


def _facebook_video_ids(pages: list[str]) -> list[str]:
    """Collect unique video ids from Facebook profile video/reel tab HTML."""
    seen: set[str] = set()
    ordered: list[str] = []
    for page in pages:
        for pattern in FACEBOOK_VIDEO_ID_PATTERNS:
            for video_id in pattern.findall(page):
                if video_id not in seen:
                    seen.add(video_id)
                    ordered.append(video_id)
    return ordered


def _post_key(meta: dict[str, Any]) -> str | None:
    for key in POST_KEYS:
        value = meta.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return None


def _extension(meta: dict[str, Any], media_url: str) -> str:
    ext = meta.get("extension")
    if ext:
        return str(ext).lstrip(".").lower()
    path = media_url.split("?", 1)[0]
    if "." in path.rsplit("/", 1)[-1]:
        return path.rsplit(".", 1)[-1].lower()
    return "jpg"


def _http_headers(meta: dict[str, Any]) -> dict[str, str]:
    """Copy gallery-dl's per-file request headers into a plain string map."""
    raw = meta.get("_http_headers") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if value is not None
    }


def _audio_codec(extension: str) -> str:
    return AUDIO_CODECS.get(extension.lower(), extension.lower() or "aac")


def _author_label(meta: dict[str, Any]) -> str:
    """Return a displayable author from the varied gallery-dl metadata."""
    value = (
        meta.get("author")
        or meta.get("user")
        or meta.get("username")
        or meta.get("artist")
        or "media"
    )
    if isinstance(value, dict):
        return str(
            value.get("username")
            or value.get("uniqueId")
            or value.get("name")
            or value.get("nickname")
            or value.get("nick")
            or "media"
        )
    return str(value)


@dataclass
class _DiscoveryState:
    """Shared limits and de-duplication across nested queue expansions."""

    options: ScanOptions
    media_count: int = 0
    posts_emitted: int = 0
    page_reported: bool = False
    visited: set[str] = field(default_factory=set)

    def post_limit_reached(self) -> bool:
        return self.options.max_posts is not None and self.posts_emitted >= self.options.max_posts

    def media_limit_reached(self) -> bool:
        return self.options.max_media is not None and self.media_count >= self.options.max_media

    def limit_reached(self) -> bool:
        return self.post_limit_reached() or self.media_limit_reached()


class GalleryDlProvider(BaseProvider):
    """Discovers posts and albums from sites supported by gallery-dl."""

    name = "gallerydl"
    label = "Gallery / profile (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return _find_extractor(url) is not None

    def _extractor_info(self, url: str) -> tuple[str | None, str | None]:
        extractor = _find_extractor(url)
        if extractor is None:
            return None, None
        return getattr(extractor, "category", None), getattr(extractor, "subcategory", None)

    def capabilities_for(self, url: str) -> ProviderCapabilities:
        category, subcategory = self._extractor_info(url)
        profile = subcategory in PROFILE_SUBCATEGORIES
        requires_auth = category in AUTH_HEAVY_CATEGORIES
        has_cookies = False
        try:
            from ..db import default_repository

            has_cookies = bool(default_repository.get_cookie_profile_for_domain(url))
            requires_auth = requires_auth and not has_cookies
        except Exception:
            pass
        if category is None:
            return ProviderCapabilities(
                provider=self.name,
                label=self.label,
                source_type="gallery",
                profile_bulk=False,
                individual_posts=True,
                albums=True,
                pagination=False,
                images=True,
                videos=True,
                notes="No gallery-dl extractor matched this URL.",
            )
        return ProviderCapabilities(
            provider=self.name,
            label=self.label,
            source_type="profile" if profile else "gallery",
            profile_bulk=profile,
            individual_posts=True,
            albums=True,
            images=True,
            videos=True,
            pagination=profile,
            requires_auth=requires_auth,
            has_cookies=has_cookies,
            notes=(
                f"gallery-dl extractor: {category}/{subcategory or '-'}."
                + (
                    " This site usually requires authorized session cookies."
                    if requires_auth
                    else ""
                )
            ),
        )

    def classify(self, url: str) -> ClassifiedUrl:
        parts = urlsplit(url)
        category, subcategory = self._extractor_info(url)
        profile = subcategory in PROFILE_SUBCATEGORIES
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=url,
            category=UrlCategory.CHANNEL if profile else UrlCategory.GALLERY,
            platform=category or parts.netloc,
            domain=parts.netloc,
            author_hint=None,
            title_hint=(
                parts.path.strip("/").split("/")[-1]
                if parts.path.strip("/")
                else parts.netloc
            ),
            is_supported=category is not None,
            requires_auth=category in AUTH_HEAVY_CATEGORIES,
            metadata_extra={
                "provider": self.name,
                "extractor_category": category or "",
                "extractor_subcategory": subcategory or "",
            },
        )

    def _prepare_extractor(self, safe_url: str):
        extractor = _find_extractor(safe_url)
        if extractor is None:
            raise UnsupportedSourceError(
                f"No gallery extractor supports this URL: {safe_url}",
                details={"url": safe_url},
            )
        gdl_config.set(("extractor",), "timeout", 20)
        try:
            from ..db import default_repository

            profile = default_repository.get_cookie_profile_for_domain(safe_url)
            category = getattr(extractor, "category", None)
            if category and profile and profile.cookie_file_path:
                cookie_path = Path(profile.cookie_file_path)
                if cookie_path.exists() and cookie_path.is_file():
                    # Scope cookies to this site's extractor instead of leaking
                    # one site's session to every gallery-dl request.
                    gdl_config.set(("extractor", category), "cookies", str(cookie_path))
            if category in MERGED_VIDEO_CATEGORIES:
                gdl_config.set(("extractor", category), "videos", "merged")
            if category in AUTH_HEAVY_CATEGORIES:
                # These sites reject gallery-dl's default non-browser UA on the
                # media endpoints even with valid cookies. The ``+`` prefix asks
                # gallery-dl for its built-in Chrome UA string; without it the
                # literal value "chrome" would be sent as the User-Agent.
                gdl_config.set(("extractor", category), "user-agent", "+chrome")
        except Exception:
            pass
        extractor.initialize()
        log = getattr(extractor, "log", None)
        if log is not None and not hasattr(log, "traceback"):
            # gallery-dl's error paths call log.traceback, which only exists on
            # its own logger adapter. Without this shim a failed extractor raises
            # "AttributeError: 'Logger' object has no attribute 'traceback'" and
            # hides the real site error.
            log.traceback = log.exception
        return extractor

    def _no_media_error(self, safe_url: str) -> ExtractionError:
        """Explain an empty result in terms the user can act on."""
        capabilities = self.capabilities_for(safe_url)
        category, _ = self._extractor_info(safe_url)
        site = category or host_of(safe_url) or "This site"
        details: dict[str, Any] = {
            "url": safe_url,
            "site": site,
            "requires_cookies": capabilities.requires_auth,
            "has_cookies": capabilities.has_cookies,
            "settings": "cookies",
        }
        if capabilities.requires_auth:
            return PrivateMediaError(
                f"{site} returned no downloadable media. This site usually requires a "
                "signed-in session. Add a cookie profile for this domain in "
                "Settings → Cookies & Sessions, then scan again.",
                details={**details, "remediation": "add_cookies"},
            )
        if capabilities.has_cookies:
            return MediaUnavailableError(
                f"{site} returned no downloadable media even with the stored cookies. "
                "The cookie profile may be expired, or the collection may be empty or "
                "private. Re-import cookies or check the URL.",
                details={**details, "remediation": "refresh_cookies"},
            )
        return MediaUnavailableError(
            "No downloadable media was found. The URL may be empty, private, or the "
            "site may need a signed-in session. Check the link, or add a cookie profile "
            "in Settings → Cookies & Sessions and try again.",
            details={**details, "remediation": "check_url_or_cookies"},
        )

    def _explain(self, error: ExtractionError, safe_url: str) -> ExtractionError:
        """Attach actionable cookie context to errors from auth-heavy sites."""
        category, _ = self._extractor_info(safe_url)
        if category not in AUTH_HEAVY_CATEGORIES:
            return error
        capabilities = self.capabilities_for(safe_url)
        error.details = {
            **error.details,
            "site": category,
            "requires_cookies": capabilities.requires_auth,
            "has_cookies": capabilities.has_cookies,
            "settings": "cookies",
            "remediation": "add_cookies" if capabilities.requires_auth else "refresh_cookies",
        }
        if capabilities.requires_auth and error.code == "MEDIA_UNAVAILABLE":
            error.message = (
                f"{error.message} — {category} usually needs a signed-in session. "
                "Add a cookie profile for this domain in Settings → Cookies & Sessions, "
                "then scan again."
            )
        return error

    def iter_posts(
        self,
        url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        on_page: PageCallback | None = None,
        on_warning: WarningCallback | None = None,
    ) -> Iterator[Post]:
        safe_url = validate_url_security(url)
        warn = on_warning or (lambda _msg: None)
        state = _DiscoveryState(options=options)
        facebook_profile = (
            _facebook_profile_base(safe_url) if options.include_videos else None
        )
        try:
            # Facebook's profile extractor only lists photos/albums. Discover
            # profile videos first so a media cap still leaves room for both
            # kinds instead of letting a large photo set consume every slot.
            if facebook_profile is not None and not cancel_event.is_set():
                yield from self._facebook_profile_videos(
                    facebook_profile,
                    cancel_event,
                    warn,
                    on_page,
                    state,
                )
            if not state.limit_reached():
                yield from self._discover(
                    safe_url,
                    cancel_event,
                    warn,
                    on_page,
                    state,
                    depth=0,
                )
        except (AuthenticationError, AuthorizationError) as exc:
            raise self._explain(parse_gallery_dl_error(exc, safe_url), safe_url) from exc
        except (NotFoundError, HttpError, NoExtractorError) as exc:
            raise self._explain(parse_gallery_dl_error(exc, safe_url), safe_url) from exc
        except ExtractionError:
            raise
        except Exception as exc:
            raise parse_gallery_dl_error(exc, safe_url) from exc

        if state.posts_emitted == 0:
            raise self._no_media_error(safe_url)

    def _facebook_video_pages(
        self,
        profile_url: str,
        cancel_event: threading.Event,
        warn: WarningCallback,
    ) -> list[str]:
        """Fetch a Facebook profile's server-rendered video and reel tabs.

        The session has to be warmed on a normal page first; Facebook answers
        cold requests with HTTP 400. gallery-dl's own extractor supplies the
        browser headers, cookies, and rate-limit handling used here.
        """
        try:
            extractor = self._prepare_extractor(f"{profile_url}/photos")
            extractor.request(f"{profile_url}/photos_by", fatal=False)
        except Exception as exc:
            warn(f"Skipped Facebook video discovery (session unavailable): {exc}")
            return []

        pages: list[str] = []
        for tab in FACEBOOK_VIDEO_TABS:
            if cancel_event.is_set():
                break
            try:
                response = extractor.request(f"{profile_url}/{tab}", fatal=False)
            except Exception as exc:
                warn(f"Could not list Facebook {tab}: {exc}")
                continue
            status = getattr(response, "status_code", 200)
            if status >= 400:
                warn(f"Facebook {tab} page returned HTTP {status}.")
                continue
            pages.append(getattr(response, "text", ""))
        return pages

    def _facebook_profile_videos(
        self,
        profile_url: str,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
    ) -> Iterator[Post]:
        """Discover each Facebook profile reel through gallery-dl's video extractor."""
        pages = self._facebook_video_pages(profile_url, cancel_event, warn)
        video_ids = _facebook_video_ids(pages)
        if video_ids:
            logger.info(
                "Facebook profile %s listed %d video(s)", profile_url, len(video_ids)
            )
        for video_id in video_ids:
            if cancel_event.is_set() or state.limit_reached():
                return
            reel_url = f"https://www.facebook.com/reel/{video_id}"
            try:
                yield from self._discover(
                    reel_url,
                    cancel_event,
                    warn,
                    on_page,
                    state,
                    depth=1,
                )
            except Exception as exc:
                # One broken/deleted reel must not discard the rest of the scan.
                warn(f"Skipped Facebook video {video_id}: {exc}")

    def _discover(
        self,
        safe_url: str,
        cancel_event: threading.Event,
        warn: WarningCallback,
        on_page: PageCallback | None,
        state: _DiscoveryState,
        depth: int,
    ) -> Iterator[Post]:
        """Yield posts for one extractor, expanding nested queues in place."""
        if safe_url in state.visited:
            return
        state.visited.add(safe_url)

        extractor = self._prepare_extractor(safe_url)
        category = getattr(extractor, "category", None) or "gallery"

        group_key: str | None = None
        group_meta: dict[str, Any] = {}
        group_items: list = []
        group_ids: set[str] = set()
        pending_audio: list[tuple[str, dict[str, Any], str]] = []
        # A media cap can land exactly on a video entry, with its companion
        # audio entry still queued in gallery-dl's iterator. Let that one audio
        # item attach before closing the post, or the result would be a silent
        # video that the downloader refuses.
        allow_audio_after_limit = False

        def attach_audio_track(
            item: MediaItem, audio_url: str, meta: dict[str, Any], ext: str
        ) -> None:
            """Attach a separate audio stream so the downloader can mux it."""
            format_id = "audio"
            existing = {fmt.format_id for fmt in item.available_formats}
            if format_id in existing:
                format_id = f"audio-{len(item.available_formats)}"
            item.available_formats.append(
                MediaFormatInfo(
                    format_id=format_id,
                    container=ext,
                    audio_codec=_audio_codec(ext),
                    filesize_bytes=meta.get("filesize") or meta.get("size"),
                    is_direct_stream=True,
                    url=audio_url,
                    requires_merge=False,
                    format_note="audio",
                    http_headers=_http_headers(meta),
                )
            )

        def attach_pending_audio(item: MediaItem) -> None:
            while pending_audio:
                audio_url, meta, ext = pending_audio.pop(0)
                attach_audio_track(item, audio_url, meta, ext)

        def attach_audio_item(meta: dict[str, Any], media_url: str) -> None:
            """Attach an audio entry to the current video, or queue it for one."""
            ext = _extension(meta, media_url)
            target = next(
                (
                    item
                    for item in reversed(group_items)
                    if item.media_type == MediaType.VIDEO
                ),
                None,
            )
            if target is None:
                pending_audio.append((media_url, meta, ext))
            else:
                attach_audio_track(target, media_url, meta, ext)

        def flush() -> Post | None:
            nonlocal group_key, group_meta, group_items, group_ids
            if not group_items:
                return None
            if state.post_limit_reached():
                group_items = []
                return None
            post = make_post(
                provider=self.name,
                source_url=safe_url,
                post_key=group_key or safe_url,
                provider_post_id=_post_key(group_meta) or (group_key or safe_url),
                author=_author_label(group_meta),
                title=group_meta.get("title") or group_meta.get("description"),
                media_items=list(group_items),
                post_url=group_meta.get("post_url")
                or group_meta.get("webpage_url")
                or safe_url,
                metadata_extra={
                    "extractor": category,
                    "group_key": group_key or safe_url,
                },
            )
            state.posts_emitted += 1
            group_items = []
            group_ids = set()
            group_meta = {}
            pending_audio.clear()
            return post

        for message, data, meta in extractor.items():
            if cancel_event.is_set():
                return
            if state.limit_reached():
                if (
                    allow_audio_after_limit
                    and message == Message.Url
                    and _extension(meta, str(data)) in AUDIO_EXTENSIONS
                ):
                    attach_audio_item(meta, str(data))
                    continue
                post = flush()
                if post is not None:
                    yield post
                return

            if message == Message.Url:
                media_url = str(data)

                # gallery-dl hands DASH manifest entries to yt-dlp as
                # ``ytdl:<page><n>.mp4``. The extractor also records the
                # progressive fallback URL, which is directly downloadable and
                # already contains audio. Prefer it so a scan result is always
                # a real CDN stream.
                if media_url.startswith("ytdl:"):
                    fallback = meta.get("_fallback") or ()
                    fallback_url = str(fallback[0]) if fallback else ""
                    if not fallback_url:
                        warn(
                            "Skipped a DASH-only video stream that has no direct "
                            "download URL."
                        )
                        continue
                    media_url = fallback_url

                ext = _extension(meta, media_url)
                if ext in AUDIO_EXTENSIONS:
                    # Facebook (and other DASH sources) emit video and audio as
                    # separate items. Keep the audio as a format of the current
                    # video so the download manager can merge them instead of
                    # saving a silent video.
                    attach_audio_item(meta, media_url)
                    continue
                is_video = ext in VIDEO_EXTENSIONS
                if is_video and not state.options.include_videos:
                    continue
                if not is_video and not state.options.include_images:
                    continue

                key = _post_key(meta) or f"gallery:{safe_url}"
                if group_key is not None and key != group_key:
                    post = flush()
                    if post is not None:
                        yield post
                if group_key != key:
                    group_key = key

                meta_keys = (
                    "author",
                    "user",
                    "username",
                    "artist",
                    "title",
                    "description",
                    "post_url",
                )
                for candidate in meta_keys:
                    if not group_meta.get(candidate) and meta.get(candidate):
                        group_meta[candidate] = meta.get(candidate)

                hint = str(
                    meta.get("id") or meta.get("filename") or url_fingerprint(media_url)
                )
                # Multi-file posts (TikTok slideshows, carousels) repeat the post
                # id on every file. gallery-dl's file counter keeps them distinct.
                num = meta.get("num")
                if num not in (None, ""):
                    hint = f"{hint}:{num}"
                if hint in group_ids:
                    continue
                group_ids.add(hint)

                media_type = MediaType.VIDEO if is_video else MediaType.IMAGE
                width = meta.get("width")
                height = meta.get("height")
                filesize = meta.get("filesize") or meta.get("size")
                resolution = f"{width}x{height}" if width and height else None
                format_info = MediaFormatInfo(
                    format_id="original",
                    container=ext,
                    resolution=resolution,
                    video_codec=(
                        str(meta.get("video_codec") or meta.get("vcodec") or "h264")
                        if is_video
                        else None
                    ),
                    audio_codec=(
                        str(meta.get("audio_codec") or "aac")
                        if is_video and category in MUXED_VIDEO_CATEGORIES
                        else None
                    ),
                    width=width,
                    height=height,
                    filesize_bytes=filesize,
                    is_direct_stream=True,
                    url=media_url,
                    requires_merge=False,
                    format_note=meta.get("format") or "original",
                    http_headers=_http_headers(meta),
                )
                item = make_media_item(
                    provider=self.name,
                    source_url=safe_url,
                    media_url=media_url,
                    media_type=media_type,
                    post_id="",
                    title=meta.get("title") or meta.get("filename"),
                    author=(
                        _author_label(meta)
                        if meta.get("author")
                        or meta.get("user")
                        or meta.get("username")
                        else _author_label(group_meta)
                    ),
                    thumbnail_url=meta.get("thumbnail")
                    or (media_url if media_type == MediaType.IMAGE else None),
                    duration_seconds=float(meta["duration"])
                    if meta.get("duration")
                    else None,
                    width=width,
                    height=height,
                    filesize_bytes=filesize,
                    extension=ext,
                    mime_type=f"{media_type.value}/{ext}",
                    format_info=format_info,
                    provider_media_id=hint,
                    attachment_index=len(group_items),
                    metadata_extra={
                        "post_key": key,
                        "extractor": category,
                    },
                )
                group_items.append(item)
                if is_video:
                    attach_pending_audio(item)
                state.media_count += 1
                if not state.page_reported and on_page:
                    on_page(1)
                    state.page_reported = True

                if state.media_limit_reached():
                    allow_audio_after_limit = is_video

            elif message == Message.Directory:
                group_meta.update({k: v for k, v in meta.items() if v not in (None, "")})

            elif message == Message.Queue:
                queue_url = _prefer_media_queue(str(data))
                if depth >= MAX_QUEUE_DEPTH:
                    warn(
                        f"Skipped nested collection beyond depth {MAX_QUEUE_DEPTH}: "
                        f"{queue_url[:120]}"
                    )
                    continue
                try:
                    nested_url = validate_url_security(queue_url)
                except XakuMediaError as exc:
                    warn(f"Skipped queue URL blocked by security policy: {exc.message}")
                    continue
                if not nested_url.lower().startswith(("http://", "https://")):
                    warn(f"Skipped non-web queue URL: {nested_url[:120]}")
                    continue
                try:
                    yield from self._discover(
                        nested_url,
                        cancel_event,
                        warn,
                        on_page,
                        state,
                        depth + 1,
                    )
                except XakuMediaError as exc:
                    warn(
                        f"Skipped nested collection on {host_of(nested_url) or 'unknown host'}: "
                        f"{exc.message}"
                    )
                if state.limit_reached():
                    return

        post = flush()
        if post is not None:
            yield post
