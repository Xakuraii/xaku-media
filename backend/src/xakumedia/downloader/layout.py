"""Destination folder layout for downloaded media.

Files are grouped by platform and media kind so a mixed library stays easy to
browse:

    <download_dir>/tiktok/videos/<post_id>/author_vdo_001.mp4
    <download_dir>/tiktok/images/<post_id>/author_img_001.jpg
    <download_dir>/facebook/videos/author_vdo_001.mp4
    <download_dir>/facebook/images/author_img_001.jpg
    <download_dir>/instagram/reels/author_vdo_001.mp4
    <download_dir>/instagram/images/author_img_001.jpg
    <download_dir>/x/videos/author_vdo_001.mp4
    <download_dir>/youtube/videos/author_vdo_001.mp4
    <download_dir>/youtube/shorts/author_vdo_001.mp4

TikTok is the only platform that also separates every post into its own folder,
because a slideshow's images and its video are distinct download groups.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from ..core.config import default_config
from ..models.media import MediaItem, MediaType
from ..utils.naming import sanitize_username

_PLATFORM_ALIASES = {
    "tiktok": "tiktok",
    "facebook": "facebook",
    "fb": "facebook",
    "instagram": "instagram",
    "insta": "instagram",
    "twitter": "x",
    "x": "x",
    "x.com": "x",
    "youtube": "youtube",
}

_HOST_ALIASES = {
    "tiktok.com": "tiktok",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
}

_GENERIC_PLATFORMS = {"", "gallery", "direct", "ytdlp", "gallerydl", "media", "unknown"}


def _normalize_platform(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in _PLATFORM_ALIASES:
        return _PLATFORM_ALIASES[cleaned]
    for marker, platform in _PLATFORM_ALIASES.items():
        if marker in cleaned:
            return platform
    if cleaned in _GENERIC_PLATFORMS:
        return None
    # A provider-specific category such as "artstation" is still a useful
    # browse folder. Keep it filesystem-safe and bounded.
    safe = sanitize_username(cleaned, fallback="")
    return safe or None


def _host_platform(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www.") or host.startswith("m."):
        host = host.split(".", 1)[1]
    for domain, platform in _HOST_ALIASES.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    # Unknown hosts still get their own folder so unlike sites never mix.
    return _normalize_platform(host.split(".", 1)[0])


def platform_folder(media_item: MediaItem) -> str:
    """Return the platform folder for a media item."""
    extra = media_item.metadata_extra or {}
    for candidate in (
        extra.get("extractor"),
        extra.get("platform"),
        extra.get("site"),
    ):
        normalized = _normalize_platform(str(candidate) if candidate else None)
        if normalized:
            return normalized

    for url in (
        media_item.post_url,
        media_item.source_url,
        media_item.original_url,
    ):
        normalized = _host_platform(url)
        if normalized:
            return normalized
    return "other"


def _is_short_video(media_item: MediaItem) -> bool:
    """Detect both a Shorts video URL and a channel's Shorts tab URL."""
    for url in (media_item.post_url, media_item.source_url):
        if not url:
            continue
        segments = [part for part in urlsplit(url).path.split("/") if part]
        if not segments:
            continue
        if segments[-1] == "shorts":
            return True
        if len(segments) >= 2 and segments[-2] == "shorts":
            return True
    return False


def media_kind_folder(media_item: MediaItem, platform: str | None = None) -> str:
    """Return the media-kind subfolder (videos, images, reels, shorts)."""
    platform = platform or platform_folder(media_item)
    if media_item.media_type == MediaType.IMAGE:
        return "images"
    if media_item.media_type == MediaType.AUDIO:
        return "audio"
    if platform == "instagram":
        return "reels"
    if platform == "youtube" and _is_short_video(media_item):
        return "shorts"
    return "videos"


def tiktok_post_folder(media_item: MediaItem) -> str | None:
    """Return the per-post folder key for a TikTok item, when available."""
    extra = media_item.metadata_extra or {}
    key = extra.get("post_id") or extra.get("post_key")
    if not key:
        provider_id = media_item.provider_media_id or ""
        # TikTok slides use "<video_id>:<slide_index>"; videos use the id as-is.
        key = provider_id.split(":", 1)[0]
    if not key:
        return None
    cleaned = str(key).strip()
    if cleaned.lower().startswith("tiktok:"):
        cleaned = cleaned.split(":", 1)[1]
    return sanitize_username(cleaned, fallback="") or None


def destination_directory(media_item: MediaItem, base_dir: Path | str | None = None) -> Path:
    """Build the destination directory for one media item.

    ``base_dir`` is treated as the download root, not the final folder, so an
    explicit target still receives the platform/media-type structure.
    """
    root = Path(base_dir) if base_dir else default_config.download_dir
    platform = platform_folder(media_item)
    folder = root / platform / media_kind_folder(media_item, platform)
    if platform == "tiktok":
        post_folder = tiktok_post_folder(media_item)
        if post_folder:
            folder = folder / post_folder
    return folder


__all__ = [
    "destination_directory",
    "media_kind_folder",
    "platform_folder",
    "tiktok_post_folder",
]
