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
from ..models.media import MediaFormatInfo, MediaType
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


def _find_extractor(url: str):
    try:
        return gdl_extractor.find(url)
    except Exception:
        return None


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
            if profile and profile.cookie_file_path:
                cookie_path = Path(profile.cookie_file_path)
                if cookie_path.exists() and cookie_path.is_file():
                    gdl_config.set(("extractor",), "cookies", str(cookie_path))
        except Exception:
            pass
        extractor.initialize()
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
        try:
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
                author=str(
                    group_meta.get("author")
                    or group_meta.get("user")
                    or group_meta.get("username")
                    or group_meta.get("artist")
                    or "media"
                ),
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
            return post

        for message, data, meta in extractor.items():
            if cancel_event.is_set():
                return
            if state.limit_reached():
                return

            if message == Message.Url:
                media_url = str(data)
                ext = _extension(meta, media_url)
                if ext in AUDIO_EXTENSIONS:
                    warn("Audio-only attachment skipped (not part of image/video scans).")
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
                    width=width,
                    height=height,
                    filesize_bytes=filesize,
                    is_direct_stream=True,
                    url=media_url,
                    requires_merge=False,
                    format_note=meta.get("format") or "original",
                )
                item = make_media_item(
                    provider=self.name,
                    source_url=safe_url,
                    media_url=media_url,
                    media_type=media_type,
                    post_id="",
                    title=meta.get("title") or meta.get("filename"),
                    author=str(
                        meta.get("author")
                        or meta.get("user")
                        or meta.get("username")
                        or group_meta.get("author")
                        or "media"
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
                state.media_count += 1
                if not state.page_reported and on_page:
                    on_page(1)
                    state.page_reported = True

                if state.media_limit_reached():
                    post = flush()
                    if post is not None:
                        yield post
                    return

            elif message == Message.Directory:
                group_meta.update({k: v for k, v in meta.items() if v not in (None, "")})

            elif message == Message.Queue:
                queue_url = str(data)
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
