"""Instagram discovery provider adapter for images, carousels, videos, and reels."""

from __future__ import annotations

from ..base import host_of
from ..gallerydl import GalleryDlProvider

INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "instagr.am",
}


class InstagramProvider(GalleryDlProvider):
    """Dedicated provider for Instagram posts, carousels, profiles, and Reels."""

    platform_name = "instagram"
    label = "Instagram (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in INSTAGRAM_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://www.instagram.com/")
