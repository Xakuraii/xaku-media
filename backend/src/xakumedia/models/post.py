"""Post, album, scan-job, and provider-capability domain models."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .media import MediaItem, MediaType
from .url import ClassifiedUrl


class PostType(StrEnum):
    """Shape of a discovered post or collection entry."""

    VIDEO = "video"
    IMAGE = "image"
    ALBUM = "album"
    SLIDESHOW = "slideshow"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Post(BaseModel):
    """A source post and the downloadable attachments it contains."""

    id: str
    provider: str
    provider_post_id: str | None = None
    source_url: str
    post_url: str | None = None
    author: str = "media"
    title: str | None = None
    post_type: PostType = PostType.UNKNOWN
    media_items: list[MediaItem] = Field(default_factory=list)
    created_at: datetime | None = None
    metadata_extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def image_count(self) -> int:
        return sum(1 for item in self.media_items if item.media_type == MediaType.IMAGE)

    @property
    def video_count(self) -> int:
        return sum(1 for item in self.media_items if item.media_type == MediaType.VIDEO)

    @classmethod
    def infer_type(cls, media_items: list[MediaItem]) -> PostType:
        """Infer a post type from its downloadable attachments."""
        images = sum(1 for item in media_items if item.media_type == MediaType.IMAGE)
        videos = sum(1 for item in media_items if item.media_type == MediaType.VIDEO)
        if videos and images:
            return PostType.MIXED
        if videos:
            return PostType.VIDEO if videos == 1 else PostType.MIXED
        if images > 1:
            return PostType.ALBUM
        if images == 1:
            return PostType.IMAGE
        return PostType.UNKNOWN


class ProviderCapabilities(BaseModel):
    """Honest declaration of what a provider can do for a given source URL."""

    provider: str
    label: str
    source_type: str = "unknown"
    profile_bulk: bool = False
    individual_posts: bool = False
    albums: bool = False
    images: bool = True
    videos: bool = True
    pagination: bool = False
    requires_auth: bool = False
    has_cookies: bool = False
    notes: str | None = None


class ScanOptions(BaseModel):
    """User-controlled scan bounds."""

    max_posts: int | None = Field(default=None, ge=1)
    max_media: int | None = Field(default=None, ge=1)
    include_images: bool = True
    include_videos: bool = True


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ScanProgress(BaseModel):
    posts_discovered: int = 0
    media_discovered: int = 0
    images_discovered: int = 0
    videos_discovered: int = 0
    pages_fetched: int = 0
    duplicates_skipped: int = 0
    current_page: int | None = None
    limit_applied: bool = False


class ScanJobSnapshot(BaseModel):
    """Serializable state of a running or finished scan job."""

    job_id: str
    scan_id: str | None = None
    url: str
    provider: str | None = None
    status: ScanStatus = ScanStatus.QUEUED
    classified_url: ClassifiedUrl | None = None
    capabilities: ProviderCapabilities | None = None
    progress: ScanProgress = Field(default_factory=ScanProgress)
    posts: list[Post] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    error_category: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
