"""Models package for XakuMedia."""

from .media import MediaFormatInfo, MediaItem, MediaType
from .post import (
    Post,
    PostType,
    ProviderCapabilities,
    ScanJobSnapshot,
    ScanOptions,
    ScanProgress,
    ScanStatus,
)
from .quality import ImageFormat, ImageQualityPreset, VideoContainer, VideoResolution
from .queue import DownloadTask, ProgressUpdate, TaskStatus
from .source import IncrementalScanResult, RescanAllSummary, SavedSource
from .url import ClassifiedUrl, UrlCategory

__all__ = [
    "MediaType",
    "MediaFormatInfo",
    "MediaItem",
    "VideoResolution",
    "VideoContainer",
    "ImageFormat",
    "ImageQualityPreset",
    "UrlCategory",
    "ClassifiedUrl",
    "TaskStatus",
    "ProgressUpdate",
    "DownloadTask",
    "SavedSource",
    "IncrementalScanResult",
    "RescanAllSummary",
    "Post",
    "PostType",
    "ProviderCapabilities",
    "ScanOptions",
    "ScanProgress",
    "ScanJobSnapshot",
    "ScanStatus",
]
