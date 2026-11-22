"""Normalized domain models for discovered and processed media items."""

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .quality import VideoResolution

_RESOLUTION_DIM_RE = re.compile(r"(\d{3,4})\s*[xX×]\s*(\d{3,4})")
_RESOLUTION_P_RE = re.compile(r"(\d{3,4})")
_MACROBLOCK_TOLERANCE = 16


class MediaType(StrEnum):
    """Primary media stream category."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class MediaFormatInfo(BaseModel):
    """Metadata describing a specific available media format/stream."""

    format_id: str
    container: str | None = None
    resolution: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    filesize_bytes: int | None = None
    is_direct_stream: bool = True
    url: str | None = None
    requires_merge: bool = False
    format_note: str | None = None
    # Per-stream request headers required by the CDN (for example TikTok's
    # Referer). Persisted with the task so retries after a restart still work.
    http_headers: dict[str, str] = Field(default_factory=dict)

    @property
    def quality_tier(self) -> int:
        """Effective resolution tier using the short edge for portrait/landscape video."""
        if self.width and self.height:
            return min(self.width, self.height)
        if self.height:
            return self.height
        if self.resolution:
            dim_match = _RESOLUTION_DIM_RE.search(self.resolution)
            if dim_match:
                return min(int(dim_match.group(1)), int(dim_match.group(2)))
            p_match = _RESOLUTION_P_RE.search(self.resolution)
            if p_match:
                return int(p_match.group(1))
        if self.width:
            return int(self.width * 9 / 16)
        return 0

    @property
    def resolution_sort_key(self) -> int:
        """Helper for sorting formats from lowest to highest resolution."""
        return self.quality_tier


class MediaItem(BaseModel):
    """Normalized media item discovered during scanning."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_url: str
    media_type: MediaType
    title: str | None = None
    author: str = "media"
    thumbnail_url: str | None = None
    original_url: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    filesize_bytes: int | None = None
    available_formats: list[MediaFormatInfo] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata_extra: dict[str, Any] = Field(default_factory=dict)

    # Source / post relationships and provider identity (added with the bulk
    # discovery model). These are optional so previously persisted payloads and
    # direct-URL flows still validate.
    provider: str | None = None
    provider_media_id: str | None = None
    post_id: str | None = None
    post_url: str | None = None
    attachment_index: int = 0
    mime_type: str | None = None
    extension: str | None = None
    is_thumbnail: bool = False
    # Transient status from the folder manifest (``downloaded``/``skipped``).
    # Not persisted in SQLite; set when scan results are serialized.
    library_status: str | None = None

    @property
    def dimensions_label(self) -> str | None:
        """Formatted human-readable dimensions (e.g., 1920x1080)."""
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None

    def find_best_format(
        self, max_resolution: VideoResolution | None = None
    ) -> MediaFormatInfo | None:
        """Find the highest quality playable format bounded by max_resolution."""
        if not self.available_formats:
            return None

        downloadable = [f for f in self.available_formats if f.url]
        pool = downloadable or list(self.available_formats)

        if self.media_type == MediaType.VIDEO:
            video_tracks = [
                f for f in pool if f.video_codec and f.video_codec.lower() != "none"
            ]
            if video_tracks:
                has_audio_partner = any(
                    f.audio_codec
                    and f.audio_codec.lower() != "none"
                    and (not f.video_codec or f.video_codec.lower() == "none")
                    for f in pool
                )
                playable = [
                    f
                    for f in video_tracks
                    if (f.audio_codec and f.audio_codec.lower() != "none")
                    or has_audio_partner
                ]
                pool = playable or video_tracks

        def score(fmt: MediaFormatInfo) -> tuple[int, int, float, int]:
            has_audio = int(
                bool(fmt.audio_codec and fmt.audio_codec.lower() != "none")
            )
            return (
                fmt.quality_tier,
                has_audio,
                fmt.fps or 0.0,
                fmt.filesize_bytes or 0,
            )

        threshold = max_resolution.height_threshold if max_resolution else None
        if threshold:
            known = [f for f in pool if f.quality_tier > 0]
            within = [f for f in known if f.quality_tier <= threshold + _MACROBLOCK_TOLERANCE]
            if within:
                return max(within, key=score)
            if known:
                return min(known, key=lambda f: f.quality_tier)

        return max(pool, key=score, default=None)
