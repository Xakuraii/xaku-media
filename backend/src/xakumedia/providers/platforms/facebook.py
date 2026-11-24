"""Facebook discovery provider adapter for photos, albums, videos, and reels."""

from __future__ import annotations

from ..base import host_of
from ..gallerydl import GalleryDlProvider

FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.com",
    "www.fb.com",
    "fb.watch",
}


class FacebookProvider(GalleryDlProvider):
    """Dedicated provider for Facebook profiles, photos, videos, and reels."""

    platform_name = "facebook"
    label = "Facebook (gallery-dl)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in FACEBOOK_HOSTS

    def _cookie_candidate_urls(self, url: str) -> tuple[str, ...]:
        return (url, "https://www.facebook.com/")
