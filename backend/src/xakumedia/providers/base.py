"""Shared provider contract for source detection and progressive discovery."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ..models.media import MediaItem, MediaType
from ..models.post import Post, ProviderCapabilities, ScanOptions
from ..models.url import ClassifiedUrl
from ..utils.stable_ids import stable_id, url_fingerprint

PageCallback = Callable[..., None]
WarningCallback = Callable[[str], None]
TotalCallback = Callable[..., None]


def host_of(url: str) -> str:
    """Return a lowercase hostname for a URL, or an empty string."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def lookup_cookie_profile(candidate_urls: tuple[str, ...] | list[str]) -> Any | None:
    """Return the first matching cookie profile across candidate URLs/aliases."""
    try:
        from ..db import default_repository

        seen: set[str] = set()
        for url in candidate_urls:
            if not url or url in seen:
                continue
            seen.add(url)
            profile = default_repository.get_cookie_profile_for_domain(url)
            if profile and profile.cookie_file_path:
                return profile
    except Exception:
        return None
    return None


def media_identity(provider: str, provider_media_id: str | None, url: str) -> str:
    """Deterministic media row id from a provider identity or URL fingerprint."""
    return stable_id("media", provider, provider_media_id or url_fingerprint(url))


def make_media_item(
    *,
    provider: str,
    source_url: str,
    media_url: str,
    media_type: MediaType,
    post_id: str,
    title: str | None = None,
    author: str = "media",
    thumbnail_url: str | None = None,
    duration_seconds: float | None = None,
    width: int | None = None,
    height: int | None = None,
    filesize_bytes: int | None = None,
    extension: str | None = None,
    mime_type: str | None = None,
    format_info=None,
    provider_media_id: str | None = None,
    post_url: str | None = None,
    attachment_index: int = 0,
    metadata_extra: dict | None = None,
) -> MediaItem:
    """Build a fully-linked MediaItem with stable identity and post linkage."""
    identity = provider_media_id or url_fingerprint(media_url)
    return MediaItem(
        id=media_identity(provider, identity, media_url),
        source_url=source_url,
        media_type=media_type,
        title=title,
        author=author,
        thumbnail_url=thumbnail_url,
        original_url=media_url,
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        filesize_bytes=filesize_bytes,
        available_formats=[format_info] if format_info else [],
        provider=provider,
        provider_media_id=identity,
        post_id=post_id,
        post_url=post_url,
        attachment_index=attachment_index,
        extension=extension,
        mime_type=mime_type,
        metadata_extra=metadata_extra or {},
    )


def extract_published_timestamp(raw: dict[str, Any] | None) -> float | None:
    """Return a UTC Unix epoch timestamp in seconds from common extractor metadata."""
    if not isinstance(raw, dict):
        return None

    for key in ("timestamp", "release_timestamp", "createTime", "created_utc"):
        val = raw.get(key)
        if isinstance(val, bool) or val is None:
            continue
        if isinstance(val, (int, float)):
            num = float(val)
            if num > 0:
                return num / 1000.0 if num > 1e12 else num
        elif isinstance(val, str) and val.strip():
            try:
                num = float(val.strip())
                if num > 0:
                    return num / 1000.0 if num > 1e12 else num
            except ValueError:
                pass

    for key in ("date", "created_at", "published_at"):
        val = raw.get(key)
        if isinstance(val, datetime):
            dt = val if val.tzinfo is not None else val.replace(tzinfo=UTC)
            return dt.timestamp()
        if isinstance(val, str) and val.strip():
            text = val.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.timestamp()
            except ValueError:
                pass

    upload_date = raw.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
            return dt.timestamp()
        except ValueError:
            pass

    return None


def make_post(
    *,
    provider: str,
    source_url: str,
    post_key: str,
    author: str,
    title: str | None,
    media_items: list[MediaItem],
    post_url: str | None = None,
    provider_post_id: str | None = None,
    created_at: datetime | None = None,
    metadata_extra: dict | None = None,
) -> Post:
    """Build a post whose id is stable across scans."""
    post_id = stable_id("post", provider, post_key)
    for item in media_items:
        item.post_id = post_id
        item.post_url = post_url
    return Post(
        id=post_id,
        provider=provider,
        provider_post_id=provider_post_id or post_key,
        source_url=source_url,
        post_url=post_url,
        author=author,
        title=title,
        post_type=Post.infer_type(media_items),
        media_items=media_items,
        created_at=created_at,
        metadata_extra=metadata_extra or {},
    )


class BaseProvider(ABC):
    """Interface implemented by every source provider."""

    name: str = "base"
    label: str = "Base"
    capabilities: ProviderCapabilities

    @classmethod
    @abstractmethod
    def match(cls, url: str) -> bool:
        """Return True when this provider should handle the URL."""

    @abstractmethod
    def classify(self, url: str) -> ClassifiedUrl:
        """Describe the source without performing a full discovery scan."""

    @abstractmethod
    def iter_posts(
        self,
        url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        on_page: PageCallback | None = None,
        on_warning: WarningCallback | None = None,
        on_total: TotalCallback | None = None,
    ) -> Iterator[Post]:
        """Yield posts progressively until exhaustion, a limit, or cancellation."""
