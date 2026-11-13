"""Provider registry: resolve a source URL to the provider that can handle it.

Resolution order is explicit and deterministic:

1. Direct media URLs (an actual image/video file).
2. Native yt-dlp video hosts, where yt-dlp offers real pagination and no auth.
3. gallery-dl profile-style sources (user/channel/board/subreddit).
4. Any other gallery-dl source (single post or gallery).
5. Unsupported.

A URL is only advertised as bulk-capable when a provider can actually paginate
it, which keeps the capability report honest for the UI.
"""

from __future__ import annotations

from ..exceptions.base import UnsupportedSourceError
from ..models.post import ProviderCapabilities
from ..models.url import ClassifiedUrl
from .base import BaseProvider, host_of
from .direct import DirectProvider
from .gallerydl import PROFILE_SUBCATEGORIES, GalleryDlProvider
from .ytdlp import VIDEO_HOSTS, YOUTUBE_HOSTS, YtDlpProvider

_DIRECT = DirectProvider()
_GALLERYDL = GalleryDlProvider()
_YTDLP = YtDlpProvider()


def _gallery_subcategory(url: str) -> str | None:
    category, subcategory = _GALLERYDL._extractor_info(url)
    del category
    return subcategory


def resolve_provider(url: str) -> BaseProvider:
    """Return the provider responsible for a URL, or raise UnsupportedSourceError."""
    if _DIRECT.match(url):
        return _DIRECT

    host = host_of(url)
    if host in YOUTUBE_HOSTS or host in VIDEO_HOSTS:
        return _YTDLP

    if _GALLERYDL.match(url):
        # Profile sources are preferred over generic gallery handling because
        # they are the bulk-first workflow this registry exists to serve.
        return _GALLERYDL

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
