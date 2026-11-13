"""Source providers for media discovery (direct, yt-dlp, gallery-dl)."""

from .base import BaseProvider, make_media_item, make_post
from .gallerydl import GalleryDlProvider
from .registry import (
    classify_url,
    is_profile_source,
    provider_capabilities,
    resolve_provider,
)
from .ytdlp import YtDlpProvider

__all__ = [
    "BaseProvider",
    "make_media_item",
    "make_post",
    "GalleryDlProvider",
    "YtDlpProvider",
    "resolve_provider",
    "provider_capabilities",
    "is_profile_source",
    "classify_url",
]
