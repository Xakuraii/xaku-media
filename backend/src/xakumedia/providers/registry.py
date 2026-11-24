"""Provider registry: resolve a source URL to the provider that can handle it.

Resolution order is explicit and deterministic:

1. Direct media URLs (an actual image/video file).
2. The 5 focus platforms via dedicated adapters: TikTok, YouTube, X, Facebook, Instagram.
3. Other fallback platforms via ``OtherProvider`` (remaining yt-dlp & gallery-dl sites).
4. Unsupported.
"""

from __future__ import annotations

from ..exceptions.base import UnsupportedSourceError
from ..models.post import ProviderCapabilities
from ..models.url import ClassifiedUrl
from .base import BaseProvider
from .direct import DirectProvider
from .gallerydl import PROFILE_SUBCATEGORIES, GalleryDlProvider
from .platforms import (
    FacebookProvider,
    InstagramProvider,
    TikTokProvider,
    XProvider,
    YouTubeProvider,
    resolve_other_provider,
)

_DIRECT = DirectProvider()
_GALLERYDL = GalleryDlProvider()
_FOCUS_PROVIDERS: tuple[BaseProvider, ...] = (
    TikTokProvider(),
    YouTubeProvider(),
    XProvider(),
    FacebookProvider(),
    InstagramProvider(),
)


def _gallery_subcategory(url: str) -> str | None:
    category, subcategory = _GALLERYDL._extractor_info(url)
    del category
    return subcategory


def resolve_provider(url: str) -> BaseProvider:
    """Return the provider responsible for a URL, or raise UnsupportedSourceError."""
    if _DIRECT.match(url):
        return _DIRECT

    for provider in _FOCUS_PROVIDERS:
        if provider.match(url):
            return provider

    other = resolve_other_provider(url)
    if other is not None:
        return other

    raise UnsupportedSourceError(
        f"No provider supports this URL: {url}",
        details={"url": url},
    )


def provider_capabilities(url: str) -> ProviderCapabilities:
    """Describe what the resolved provider can do for a URL without scanning."""
    provider = resolve_provider(url)
    capabilities_for = getattr(provider, "capabilities_for", None)
    if callable(capabilities_for):
        return capabilities_for(url)
    return provider.capabilities


def is_profile_source(url: str) -> bool:
    """Return True when the URL resolves to a paginated profile-style source."""
    return _gallery_subcategory(url) in PROFILE_SUBCATEGORIES


def classify_url(url: str) -> ClassifiedUrl:
    """Classify a URL through the resolved provider."""
    return resolve_provider(url).classify(url)


__all__ = [
    "resolve_provider",
    "provider_capabilities",
    "is_profile_source",
    "classify_url",
]
