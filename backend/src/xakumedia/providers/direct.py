"""Provider for direct image and video URLs."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import PurePosixPath

from ..exceptions.base import UnsupportedSourceError
from ..models.post import Post, ProviderCapabilities, ScanOptions
from ..models.url import ClassifiedUrl
from ..scanners.direct import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, classify_direct_url
from .base import (
    BaseProvider,
    PageCallback,
    WarningCallback,
    make_post,
    media_identity,
)

_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


class DirectProvider(BaseProvider):
    """Handles URLs that point straight at a media file."""

    name = "direct"
    label = "Direct media"
    capabilities = ProviderCapabilities(
        provider=name,
        label=label,
        source_type="direct_media",
        profile_bulk=False,
        individual_posts=True,
        albums=False,
        images=True,
        videos=True,
        pagination=False,
        notes="Single direct image, video, or audio URL.",
    )

    @classmethod
    def match(cls, url: str) -> bool:
        try:
            path = PurePosixPath(url.split("?", 1)[0].rstrip("/"))
        except ValueError:
            return False
        extension = path.suffix.lstrip(".").lower()
        return extension in _MEDIA_EXTENSIONS

    def classify(self, url: str) -> ClassifiedUrl:
        classified, _ = classify_direct_url(url)
        return classified

    def iter_posts(
        self,
        url: str,
        options: ScanOptions,
        cancel_event: threading.Event,
        on_page: PageCallback | None = None,
        on_warning: WarningCallback | None = None,
    ) -> Iterator[Post]:
        classified, item = classify_direct_url(url)
        if item is None or not classified.is_supported:
            raise UnsupportedSourceError(
                f"URL does not point to a direct media stream: {url}",
                details={"url": url},
            )

        if on_page is not None:
            on_page(1)

        item.provider = self.name
        item.provider_media_id = item.original_url
        # Direct probing creates a fresh UUID; replace it with the stable
        # identity so rescans and repeat downloads update one row instead of
        # colliding with the (provider, provider_media_id) unique index.
        item.id = media_identity(self.name, item.provider_media_id, item.original_url)
        item.post_url = classified.normalized_url
        item.attachment_index = 0

        yield make_post(
            provider=self.name,
            source_url=classified.normalized_url,
            post_key=classified.normalized_url,
            provider_post_id=classified.normalized_url,
            author=item.author,
            title=item.title,
            media_items=[item],
            post_url=classified.normalized_url,
            metadata_extra={"category": str(classified.category)},
        )
