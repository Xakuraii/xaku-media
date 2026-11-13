"""Shared provider contract for source detection and progressive discovery."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

from ..models.media import MediaItem, MediaType
from ..models.post import Post, ProviderCapabilities, ScanOptions
from ..models.url import ClassifiedUrl
from ..utils.stable_ids import stable_id, url_fingerprint

PageCallback = Callable[[int], None]
WarningCallback = Callable[[str], None]


def host_of(url: str) -> str:
    """Return a lowercase hostname for a URL, or an empty string."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


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
    ) -> Iterator[Post]:
        """Yield posts progressively until exhaustion, a limit, or cancellation."""
