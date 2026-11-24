"""Per-platform provider modules for the 5 focus platforms and other fallback sites."""

from .facebook import FACEBOOK_HOSTS, FacebookProvider
from .instagram import INSTAGRAM_HOSTS, InstagramProvider
from .other import (
    OtherGalleryProvider,
    OtherProvider,
    OtherVideoProvider,
    resolve_other_provider,
)
from .tiktok import TikTokProvider
from .x import XProvider
from .youtube import YouTubeProvider

__all__ = [
    "FACEBOOK_HOSTS",
    "INSTAGRAM_HOSTS",
    "FacebookProvider",
    "InstagramProvider",
    "OtherGalleryProvider",
    "OtherProvider",
    "OtherVideoProvider",
    "TikTokProvider",
    "XProvider",
    "YouTubeProvider",
    "resolve_other_provider",
]
