"""Tests for output preferences: quality, container, image format, and retries."""

import threading
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from xakumedia.core.config import AppConfig, default_config
from xakumedia.db.repository import MediaRepository
from xakumedia.downloader.manager import DownloadManager
from xakumedia.exceptions import NetworkTimeoutError
from xakumedia.models.media import MediaFormatInfo, MediaItem, MediaType
from xakumedia.models.quality import ImageFormat, VideoContainer, VideoResolution
from xakumedia.models.queue import DownloadTask, TaskStatus


@pytest.fixture(autouse=True)
def reset_runtime_config() -> None:
    """Restore runtime defaults so one test's preferences never leak into another."""
    defaults = AppConfig()
    for field_name in AppConfig.model_fields:
        setattr(default_config, field_name, getattr(defaults, field_name))


@pytest.fixture
def temp_download_dir(tmp_path: Path) -> Path:
    """Point the download root at an isolated temp directory."""
    original = default_config.download_dir
    default_config.download_dir = tmp_path / "downloads"
    default_config.ensure_directories()
    try:
        yield default_config.download_dir
    finally:
        default_config.download_dir = original


def _video_item() -> MediaItem:
    return MediaItem(
        id=f"video-{uuid.uuid4()}",
        source_url="https://www.youtube.com/watch?v=abc",
        original_url="https://cdn.example.com/video.mp4",
        media_type=MediaType.VIDEO,
        author="xakuraii",
        available_formats=[
            MediaFormatInfo(
                format_id="1080",
                container="mp4",
                video_codec="avc1",
                audio_codec="mp4a",
                height=1080,
                url="https://cdn.example.com/1080.mp4",
            ),
            MediaFormatInfo(
                format_id="2160",
                container="mp4",
                video_codec="avc1",
                audio_codec="mp4a",
                height=2160,
                url="https://cdn.example.com/2160.mp4",
            ),
            MediaFormatInfo(
                format_id="480",
                container="mp4",
                video_codec="avc1",
                audio_codec="mp4a",
                height=480,
                url="https://cdn.example.com/480.mp4",
            ),
        ],
    )


def _manager(tmp_path: Path, name: str) -> DownloadManager:
    return DownloadManager(
        max_concurrent=1, repository=MediaRepository(tmp_path / f"{name}.db")
    )


def test_video_resolution_preference_caps_selection(tmp_path: Path) -> None:
    manager = _manager(tmp_path, "resolution")
    default_config.default_video_resolution = VideoResolution.RES_1080P

    selected, _, _ = manager._plan_streams(_video_item(), None)

    manager._executor.shutdown(wait=True)
    assert selected is not None
    assert selected.height == 1080


def test_video_container_preference_resolves_to_value(tmp_path: Path) -> None:
    manager = _manager(tmp_path, "container")
    item = _video_item()

    try:
        default_config.default_video_container = VideoContainer.ORIGINAL
        assert manager._desired_video_container(item) is None

        default_config.default_video_container = VideoContainer.WEBM
        assert manager._desired_video_container(item) == "webm"

        image = MediaItem(
            id="image-1",
            source_url="https://example.com/a.jpg",
            original_url="https://cdn.example.com/a.jpg",
            media_type=MediaType.IMAGE,
            author="xakuraii",
        )
        assert manager._desired_video_container(image) is None
    finally:
        manager._executor.shutdown(wait=True)


def test_image_format_preference_converts_finished_file(tmp_path: Path) -> None:
    from PIL import Image

    manager = _manager(tmp_path, "image")
    source = tmp_path / "xakuraii-img-1.png"
    Image.new("RGB", (8, 8), (200, 30, 40)).save(source)

    item = MediaItem(
        id="image-2",
        source_url="https://example.com/a.png",
        original_url="https://cdn.example.com/a.png",
        media_type=MediaType.IMAGE,
        author="xakuraii",
    )

    try:
        default_config.default_image_format = ImageFormat.ORIGINAL
        assert manager._apply_output_preferences(item, source, threading.Event()) == source

        default_config.default_image_format = ImageFormat.WEBP
        converted = manager._apply_output_preferences(item, source, threading.Event())
    finally:
        manager._executor.shutdown(wait=True)

    assert converted == source.with_suffix(".webp")
    assert converted.exists()
    assert not source.exists()


def test_retry_preference_controls_attempts(
    temp_download_dir: Path, tmp_path: Path
) -> None:
    repo = MediaRepository(tmp_path / "retry.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)
    default_config.max_retries = 2

    item = _video_item()
    attempts = {"count": 0}

    def flaky_stream(url: str, destination_path: Path, **kwargs: object) -> Path:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise NetworkTimeoutError("signed URL expired")
        return destination_path

    import xakumedia.downloader.manager as dm_mod

    try:
        with (
            patch.object(dm_mod, "download_stream", side_effect=flaky_stream),
            patch.object(manager, "_refresh_media_item", return_value=item),
        ):
            task = manager.start_download(media_item=item)
            manager._executor.shutdown(wait=True)
    finally:
        manager._executor.shutdown(wait=True)

    assert attempts["count"] == 3
    stored = repo.get_download_tasks(limit=1)
    assert stored and stored[0].status == TaskStatus.COMPLETED
    assert task is not None


def test_sequence_compaction_renames_files_and_db_rows(
    temp_download_dir: Path, tmp_path: Path
) -> None:
    repo = MediaRepository(tmp_path / "compact.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)
    folder = temp_download_dir / "Example" / "artist" / "Videos"
    folder.mkdir(parents=True)

    first = folder / "artist-vdo-1.mp4"
    third = folder / "artist-vdo-3.mp4"
    first.touch()
    third.touch()

    tasks = []
    for index, path in enumerate((first, third), start=1):
        item = MediaItem(
            id=f"compact-{index}",
            source_url=f"https://example.com/{index}",
            original_url=f"https://cdn.example.com/{index}.mp4",
            media_type=MediaType.VIDEO,
            author="artist",
        )
        tasks.append(
            DownloadTask(
                id=str(uuid.uuid4()),
                media_item=item,
                status=TaskStatus.QUEUED,
                destination_path=path,
                temp_path=path.with_suffix(".mp4.part"),
            )
        )
    repo.save_download_tasks(tasks)

    try:
        manager._prepare_sequence_folder(folder, "artist", MediaType.VIDEO)
    finally:
        manager._executor.shutdown(wait=True)

    assert sorted(p.name for p in folder.iterdir()) == [
        "artist-vdo-1.mp4",
        "artist-vdo-2.mp4",
    ]

    stored_paths = {
        task.destination_path.name
        for task in repo.get_download_tasks(limit=10)
        if task.destination_path
    }
    assert stored_paths == {"artist-vdo-1.mp4", "artist-vdo-2.mp4"}


def test_portrait_1080p_video_selected_under_1080p_ceiling(tmp_path: Path) -> None:
    manager = _manager(tmp_path, "portrait")
    default_config.default_video_resolution = VideoResolution.RES_1080P
    portrait_item = MediaItem(
        id="portrait-1",
        source_url="https://www.tiktok.com/@xakuraii/video/123",
        original_url="https://cdn.example.com/123.mp4",
        media_type=MediaType.VIDEO,
        author="xakuraii",
        available_formats=[
            MediaFormatInfo(
                format_id="2160p",
                container="mp4",
                video_codec="h264",
                audio_codec="aac",
                width=2160,
                height=3840,
                url="https://cdn.example.com/2160.mp4",
            ),
            MediaFormatInfo(
                format_id="1080p",
                container="mp4",
                video_codec="h264",
                audio_codec="aac",
                width=1080,
                height=1920,
                url="https://cdn.example.com/1080.mp4",
            ),
            MediaFormatInfo(
                format_id="540p",
                container="mp4",
                video_codec="h264",
                audio_codec="aac",
                width=540,
                height=960,
                url="https://cdn.example.com/540.mp4",
            ),
        ],
    )

    try:
        selected, _, _ = manager._plan_streams(portrait_item, None)
    finally:
        manager._executor.shutdown(wait=True)

    assert selected is not None
    assert selected.format_id == "1080p"


def test_find_best_format_skips_audio_only_when_video_exceeds_ceiling() -> None:
    item = MediaItem(
        id="video-audio-only",
        source_url="https://www.youtube.com/watch?v=xyz",
        original_url="https://cdn.example.com/xyz.mp4",
        media_type=MediaType.VIDEO,
        author="xakuraii",
        available_formats=[
            MediaFormatInfo(
                format_id="1440p",
                container="mp4",
                video_codec="avc1",
                audio_codec="mp4a",
                width=2560,
                height=1440,
                url="https://cdn.example.com/1440.mp4",
            ),
            MediaFormatInfo(
                format_id="audio",
                container="m4a",
                audio_codec="mp4a",
                url="https://cdn.example.com/audio.m4a",
            ),
        ],
    )

    selected = item.find_best_format(VideoResolution.RES_1080P)
    assert selected is not None
    assert selected.format_id == "1440p"


def test_timeout_and_retry_preferences_apply_to_providers() -> None:
    from xakumedia.providers.ytdlp import YtDlpProvider

    default_config.request_timeout_seconds = 75.0
    default_config.max_retries = 6

    opts = YtDlpProvider()._base_opts()
    assert opts["socket_timeout"] == 75.0
    assert opts["retries"] == 6


def test_sequence_reservation_avoids_collisions_across_rapid_batches(
    temp_download_dir: Path, tmp_path: Path
) -> None:
    repo = MediaRepository(tmp_path / "rapid.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)
    gate = threading.Event()

    def slow_stream(url: str, destination_path: Path, **kwargs: object) -> Path:
        gate.wait(timeout=2.0)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"ok")
        return destination_path

    def make_items(prefix: str) -> list[dict[str, object]]:
        return [
            {
                "media_item": MediaItem(
                    id=f"{prefix}-{i}",
                    source_url=f"https://www.tiktok.com/@xakuraii/video/{prefix}{i}",
                    original_url=f"https://cdn.example.com/{prefix}{i}.mp4",
                    media_type=MediaType.VIDEO,
                    author="xakuraii",
                    metadata_extra={"extractor": "TikTok"},
                )
            }
            for i in range(2)
        ]

    import xakumedia.downloader.manager as dm_mod

    try:
        with patch.object(dm_mod, "download_stream", side_effect=slow_stream):
            batch_one = manager.start_batch_download(make_items("a"))
            batch_two = manager.start_batch_download(make_items("b"))
            gate.set()
            manager._executor.shutdown(wait=True)
    finally:
        gate.set()
        manager._executor.shutdown(wait=True)

    names = sorted(
        t.destination_path.name
        for t in (batch_one + batch_two)
        if t.destination_path is not None
    )
    assert names == [
        "xakuraii-vdo-1.mp4",
        "xakuraii-vdo-2.mp4",
        "xakuraii-vdo-3.mp4",
        "xakuraii-vdo-4.mp4",
    ]
