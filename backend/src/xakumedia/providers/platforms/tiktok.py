"""TikTok discovery provider adapter.

Preserves XakuMedia's verified TikTok extraction pipeline: Chrome TLS
impersonation, stale ``_waftokenid`` cookie cleanup, SlardarWAF profile
challenge solving, ``tiktokuser:<secUid>`` pagination, and embedded
``imagePost`` / gallery-dl slideshow discovery.
"""

from __future__ import annotations

from ..base import host_of
from ..ytdlp import TIKTOK_HOSTS, YtDlpProvider


class TikTokProvider(YtDlpProvider):
    """Dedicated provider entry point for TikTok profiles, videos, slideshows, and short links."""

    platform_name = "tiktok"
    label = "TikTok (yt-dlp)"

    @classmethod
    def match(cls, url: str) -> bool:
        return host_of(url) in TIKTOK_HOSTS
