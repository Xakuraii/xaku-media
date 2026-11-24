"""Fallback provider adapters for all platforms outside the 5 focus platforms."""

from __future__ import annotations

from ..base import BaseProvider, host_of
from ..gallerydl import GalleryDlProvider
from ..ytdlp import VIDEO_HOSTS, YtDlpProvider


class OtherProvider:
    """Marker mixin shared by fallback providers for non-focus platforms."""

    platform_name = "other"


class OtherVideoProvider(OtherProvider, YtDlpProvider):
    """Handles other yt-dlp video hosts (Vimeo, Dailymotion, Twitch, etc.)."""

    label = "Other video platform (yt-dlp)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in VIDEO_HOSTS


class OtherGalleryProvider(OtherProvider, GalleryDlProvider):
    """Handles other gallery-dl supported sites (Pinterest, Wikimedia, Pixiv, etc.)."""

    label = "Other gallery / profile (gallery-dl)"


_OTHER_VIDEO = OtherVideoProvider()
_OTHER_GALLERY = OtherGalleryProvider()


def resolve_other_provider(url: str) -> BaseProvider | None:
    """Resolve a URL outside the 5 focus platforms, or return None."""
    if _OTHER_VIDEO.match(url):
        return _OTHER_VIDEO
    if _OTHER_GALLERY.match(url):
        return _OTHER_GALLERY
    return None
