"""X / Twitter discovery provider adapter for images, videos, and media timelines."""

from __future__ import annotations

from ..base import host_of
from ..gallerydl import X_HOSTS, GalleryDlProvider


class XProvider(GalleryDlProvider):
    """Dedicated provider for X (x.com) and Twitter (twitter.com) media."""

    platform_name = "x"
    label = "X / Twitter (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in X_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://x.com/", "https://twitter.com/")
