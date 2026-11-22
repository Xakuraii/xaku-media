"""Destination folder layout for downloaded media.

Every download lands in a per-platform, per-user library so files from
different accounts never mix:

    <download_dir>/Youtube/<username>/Videos/<username>-vdo-1.mp4
    <download_dir>/Youtube/<username>/Images/<username>-img-1.jpg
    <download_dir>/Facebook/<username>/Videos/...
    <download_dir>/Instagram/<username>/Videos/...
    <download_dir>/Tiktok/<username>/Images/...
    <download_dir>/X/<username>/Videos/...

Platform folders use their public display names (``Youtube``, ``Tiktok``,
``X``). Every other site shares one mixed ``Others`` folder so unnamed sources
never scatter into one-off directories.
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
    "fb.watch": "facebook",
    "instagram.com": "instagram",
    "instagr.am": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
}

# Public folder names shown in the download library.
_PLATFORM_FOLDERS = {
    "tiktok": "Tiktok",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "x": "X",
    "youtube": "Youtube",
}

_KIND_FOLDERS = {
    MediaType.VIDEO: "Videos",
    MediaType.IMAGE: "Images",
    MediaType.AUDIO: "Audio",
}

_GENERIC_PLATFORMS = {"", "gallery", "direct", "ytdlp", "gallerydl", "media", "unknown"}


def _normalize_platform(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in _PLATFORM_ALIASES:
        return _PLATFORM_ALIASES[cleaned]
    # Only longer markers are matched inside a label (e.g. "TikTok - videos").
    # Short ones like "x" or "fb" would otherwise match any host ("example").
    for marker, platform in _PLATFORM_ALIASES.items():
        if len(marker) >= 4 and marker in cleaned:
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


def platform_key(media_item: MediaItem) -> str:
    """Return the normalized platform key (``youtube``, ``x``, ``tiktok``...)."""
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


def platform_folder(media_item: MediaItem) -> str:
    """Return the display folder for the media item's platform."""
    key = platform_key(media_item)
    if key in _PLATFORM_FOLDERS:
        return _PLATFORM_FOLDERS[key]
    # Every unlisted site shares one mixed library instead of a per-site folder.
    return "Others"


def user_folder(media_item: MediaItem) -> str:
    """Return the sanitized author folder name for the media item."""
    return sanitize_username(media_item.author or "media")


def media_kind_folder(media_item: MediaItem) -> str:
    """Return the media-kind subfolder (``Videos``, ``Images``, ``Audio``)."""
    return _KIND_FOLDERS.get(media_item.media_type, "Images")


def destination_directory(media_item: MediaItem, base_dir: Path | str | None = None) -> Path:
    """Build the destination directory for one media item.

    ``base_dir`` is treated as the download root, not the final folder, so an
    explicit target still receives the platform/user/media-type structure.
    """
    root = Path(base_dir) if base_dir else default_config.download_dir
    return (
        root
        / platform_folder(media_item)
        / user_folder(media_item)
        / media_kind_folder(media_item)
    )


__all__ = [
    "destination_directory",
    "media_kind_folder",
    "platform_folder",
    "platform_key",
    "user_folder",
]
