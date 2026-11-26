"""Unit tests for chunked streaming downloader and download manager."""

import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from xakumedia.core.config import default_config
from xakumedia.db.repository import MediaRepository
from xakumedia.downloader.manager import DownloadManager
from xakumedia.downloader.stream import download_stream
from xakumedia.exceptions.base import (
    DownloadCancelledError,
    InvalidDestinationError,
    SSRFBlockedError,
)
from xakumedia.models.media import MediaFormatInfo, MediaItem, MediaType
from xakumedia.models.queue import ProgressUpdate, TaskStatus
from xakumedia.server.dispatcher import RpcDispatcher
from xakumedia.server.protocol import JsonRpcRequest


@pytest.fixture
def temp_dest_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a temporary directory authorized under default_config for download testing."""
    original_dl = default_config.download_dir
    default_config.download_dir = tmp_path / "downloads"
    default_config.ensure_directories()
    try:
        yield default_config.download_dir
    finally:
        default_config.download_dir = original_dl


@pytest.fixture
def test_media_item() -> MediaItem:
    """Fixture providing a sample MediaItem."""
    return MediaItem(
        id="item-test-123",
        source_url="https://example.com/art/neo_tokyo",
        original_url="https://cdn.example.com/images/neo_tokyo.jpg",
        media_type=MediaType.IMAGE,
        title="Neo Tokyo Night",
        author="artist_neo",
        thumbnail_url="https://cdn.example.com/thumbs/neo_tokyo.jpg",
        filesize_bytes=1024 * 128,
        available_formats=[
            MediaFormatInfo(
                format_id="orig",
                container="jpg",
                width=1920,
                height=1080,
                url="https://cdn.example.com/images/neo_tokyo.jpg",
            )
        ],
    )


def test_download_stream_success(temp_dest_dir: Path) -> None:
    """Verify streaming download creates target file, cleans up .part, and emits progress."""
    dest = temp_dest_dir / "images" / "neo_tokyo_001.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload_chunks = [b"A" * 32768, b"B" * 32768, b"C" * 32768]
    expected_content = b"".join(payload_chunks)

    progress_events: list[ProgressUpdate] = []

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_error = False
    mock_response.headers = {"content-length": str(len(expected_content))}
    mock_response.iter_bytes.return_value = payload_chunks
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_response
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client):
        final_path = download_stream(
            url="https://cdn.example.com/img.jpg",
            destination_path=dest,
            task_id="task-stream-1",
            progress_callback=lambda u: progress_events.append(u),
        )

    assert final_path == dest
    assert dest.exists()
    assert dest.read_bytes() == expected_content
    # Temporary part file must be removed after successful atomic move
    assert not dest.with_suffix(".jpg.part").exists()
    assert len(progress_events) >= 1
    assert progress_events[-1].status == TaskStatus.COMPLETED
    assert progress_events[-1].progress_percent == 100.0


def test_download_stream_cancellation(temp_dest_dir: Path) -> None:
    """Verify that cancellation stops writing, deletes .part file, and raises error."""
    dest = temp_dest_dir / "images" / "cancel_test.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)

    cancel_event = threading.Event()
    cancel_event.set()  # Signal cancellation immediately

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_error = False
    mock_response.headers = {"content-length": "100000"}
    mock_response.iter_bytes.return_value = [b"X" * 1024, b"Y" * 1024]
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_response
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(DownloadCancelledError):
            download_stream(
                url="https://cdn.example.com/img.jpg",
                destination_path=dest,
                task_id="task-stream-cancel",
                cancel_event=cancel_event,
            )

    assert not dest.exists()
    assert not dest.with_suffix(".jpg.part").exists()


def test_download_stream_ssrf_protection(temp_dest_dir: Path) -> None:
    """Verify that private IP addresses and metadata endpoints are blocked in downloader."""
    dest = temp_dest_dir / "images" / "ssrf_block.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SSRFBlockedError):
        download_stream(
            url="http://127.0.0.1/malicious.jpg",
            destination_path=dest,
            task_id="task-ssrf-1",
        )

    with pytest.raises(SSRFBlockedError):
        download_stream(
            url="http://169.254.169.254/latest/meta-data/",
            destination_path=dest,
            task_id="task-ssrf-2",
        )


def test_download_stream_invalid_destination(tmp_path: Path) -> None:
    """Verify path traversal outside authorized directories is rejected."""
    unauthorized_dest = tmp_path / "outside_allowed" / "secret.exe"

    with pytest.raises(InvalidDestinationError):
        download_stream(
            url="https://cdn.example.com/file.exe",
            destination_path=unauthorized_dest,
            task_id="task-path-1",
        )


def test_download_manager_start_and_complete(
    temp_dest_dir: Path, test_media_item: MediaItem, tmp_path: Path
) -> None:
    """Verify DownloadManager creates sequential filenames, persists tasks, and executes."""
    repo = MediaRepository(tmp_path / "test_dm.db")

    import xakumedia.downloader.manager as dm_mod

    with patch.object(dm_mod, "default_repository", repo):
        manager = DownloadManager(max_concurrent=2)

        # Mock stream download to succeed immediately
        with patch.object(dm_mod, "download_stream") as mock_stream:
            mock_stream.side_effect = lambda url, destination_path, **kwargs: destination_path

            task = manager.start_download(media_item=test_media_item)
            assert task is not None
            assert task.status in (TaskStatus.QUEUED, TaskStatus.DOWNLOADING, TaskStatus.COMPLETED)
            assert "artist_neo-img-" in task.destination_path.name

            # Wait briefly for worker thread to finish
            manager._executor.shutdown(wait=True)

            stored = repo.get_download_tasks(limit=10)
            assert len(stored) >= 1
            assert stored[0].status == TaskStatus.COMPLETED
            assert stored[0].media_item.title == "Neo Tokyo Night"


def test_download_manager_cancellation(
    temp_dest_dir: Path, test_media_item: MediaItem, tmp_path: Path
) -> None:
    """Verify DownloadManager can signal cancellation to active tasks."""
    repo = MediaRepository(tmp_path / "test_dm_cancel.db")

    import xakumedia.downloader.manager as dm_mod

    with patch.object(dm_mod, "default_repository", repo):
        manager = DownloadManager(max_concurrent=2)

        blocker_event = threading.Event()

        def slow_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
            cancel_ev = kwargs.get("cancel_event")
            while not (cancel_ev and cancel_ev.is_set()):
                if blocker_event.is_set():
                    break
                threading.Event().wait(0.05)
            if cancel_ev and cancel_ev.is_set():
                raise DownloadCancelledError("Cancelled")
            return destination_path

        with patch.object(dm_mod, "download_stream", side_effect=slow_stream):
            task = manager.start_download(media_item=test_media_item)

            # Signal cancellation
            cancelled = manager.cancel_download(task.id)
            assert cancelled is True

            manager._executor.shutdown(wait=True)
            stored = repo.get_download_tasks(limit=5)
            assert len(stored) == 1
            assert stored[0].status == TaskStatus.CANCELLED


def test_dispatcher_download_rpc(
    temp_dest_dir: Path, test_media_item: MediaItem, tmp_path: Path
) -> None:
    """Verify JSON-RPC endpoints for download task start, query, and cancellation."""
    repo = MediaRepository(tmp_path / "test_rpc_dm.db")
    dispatcher = RpcDispatcher(repository=repo)
    isolated_dm = DownloadManager(repository=repo)

    import xakumedia.db as db_mod
    import xakumedia.downloader as dl_pkg
    import xakumedia.downloader.manager as dm_mod

    try:
        with (
            patch.object(db_mod, "default_repository", repo),
            patch.object(dm_mod, "default_repository", repo),
            patch.object(dl_pkg, "default_download_manager", isolated_dm),
            patch.object(dm_mod, "default_download_manager", isolated_dm),
        ):
            with patch.object(dm_mod, "download_stream") as mock_stream:
                mock_stream.side_effect = (
                    lambda url, destination_path, **kwargs: destination_path
                )

                # 1. start_download RPC
                req_start = JsonRpcRequest(
                    id="rpc-dl-1",
                    method="start_download",
                    params={"media_item": test_media_item.model_dump()},
                )
                res_start = dispatcher.dispatch(req_start)
                assert res_start.error is None
                assert res_start.result is not None
                task_dict = res_start.result["task"]
                assert task_dict["media_item"]["title"] == "Neo Tokyo Night"
                task_id = task_dict["id"]

                # 2. get_download_tasks RPC
                req_tasks = JsonRpcRequest(
                    id="rpc-dl-2",
                    method="get_download_tasks",
                    params={},
                )
                res_tasks = dispatcher.dispatch(req_tasks)
                assert res_tasks.error is None
                assert res_tasks.result["count"] >= 1

                # 3. cancel_download RPC
                req_cancel = JsonRpcRequest(
                    id="rpc-dl-3",
                    method="cancel_download",
                    params={"task_id": task_id},
                )
                res_cancel = dispatcher.dispatch(req_cancel)
                assert res_cancel.error is None
                assert "cancelled" in res_cancel.result
    finally:
        isolated_dm._executor.shutdown(wait=True)


def _video_item_with(formats: list[MediaFormatInfo]) -> MediaItem:
    return MediaItem(
        id="item-video-merge",
        source_url="https://example.com/watch/merge",
        original_url=formats[0].url or "https://cdn.example.com/video.mp4",
        media_type=MediaType.VIDEO,
        title="Merge target",
        author="creator",
        available_formats=formats,
    )


def test_download_manager_merges_video_with_best_audio(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """A video-only selection downloads the best audio track and merges both."""
    repo = MediaRepository(tmp_path / "merge_test.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    video = MediaFormatInfo(
        format_id="v1080",
        container="mp4",
        height=1080,
        video_codec="h264",
        url="https://cdn.example.com/video-1080.mp4",
        requires_merge=True,
    )
    audio_low = MediaFormatInfo(
        format_id="a-low",
        container="m4a",
        audio_codec="aac",
        filesize_bytes=1000,
        url="https://cdn.example.com/audio-low.m4a",
    )
    audio_high = MediaFormatInfo(
        format_id="a-high",
        container="webm",
        audio_codec="opus",
        filesize_bytes=9000,
        url="https://cdn.example.com/audio-high.webm",
    )
    item = _video_item_with([video, audio_low, audio_high])

    streamed_urls: list[str] = []
    merge_calls: list[tuple[Path, Path, Path, str | None]] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        streamed_urls.append(url)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"stream:" + url.encode())
        return destination_path

    def fake_merge(
        *,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        output_container: str | None = None,
        **kwargs: Any,
    ) -> Path:
        merge_calls.append((video_path, audio_path, output_path, output_container))
        output_path.write_bytes(b"merged-output")
        return output_path

    with (
        patch.object(dm_mod, "download_stream", side_effect=fake_stream),
        patch("xakumedia.processor.ffmpeg.merge_video_audio", side_effect=fake_merge),
    ):
        task = manager.start_download(media_item=item, selected_format=video)
        assert task is not None
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_tasks(limit=5)[0]
    assert stored.status == TaskStatus.COMPLETED
    assert "https://cdn.example.com/video-1080.mp4" in streamed_urls
    # Highest-quality audio codec wins over the smaller AAC track.
    assert "https://cdn.example.com/audio-high.webm" in streamed_urls
    assert len(merge_calls) == 1

    video_part, audio_part, merged_temp, container = merge_calls[0]
    assert container == "mp4"
    # Output must carry the real container suffix, never a bare ``.part`` name.
    assert merged_temp.suffix == ".mp4"
    assert ".merged" in merged_temp.name
    assert not video_part.exists()
    assert not audio_part.exists()
    destination = stored.destination_path
    assert destination is not None and destination.is_file()
    assert destination.read_bytes() == b"merged-output"


def test_download_manager_passes_format_headers(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """CDN-specific headers (TikTok Referer) must reach the stream request."""
    repo = MediaRepository(tmp_path / "headers.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    fmt = MediaFormatInfo(
        format_id="h264",
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        url="https://cdn.example.com/headers.mp4",
        http_headers={"Referer": "https://www.tiktok.com/", "User-Agent": "Chrome"},
    )
    item = _video_item_with([fmt])
    captured: list[dict[str, str] | None] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        captured.append(kwargs.get("headers"))
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"video")
        return destination_path

    with patch.object(dm_mod, "download_stream", side_effect=fake_stream):
        manager.start_download(media_item=item, selected_format=fmt)
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_tasks(limit=5)[0]
    assert stored.status == TaskStatus.COMPLETED
    assert captured == [
        {"Referer": "https://www.tiktok.com/", "User-Agent": "Chrome"}
    ]


def test_download_manager_refreshes_expired_url_once(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """A 403/404-style failure re-extracts the post and retries with fresh URLs."""
    from xakumedia.exceptions.base import PrivateMediaError

    repo = MediaRepository(tmp_path / "refresh.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    stale = MediaFormatInfo(
        format_id="h264",
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        url="https://cdn.example.com/expired.mp4",
    )
    item = _video_item_with([stale])
    fresh_item = item.model_copy(deep=True)
    fresh_item.available_formats[0].url = "https://cdn.example.com/fresh.mp4"
    fresh_item.original_url = "https://cdn.example.com/fresh.mp4"

    streamed: list[str] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        streamed.append(url)
        if "expired" in url:
            raise PrivateMediaError("Signed URL expired")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"fresh")
        return destination_path

    with (
        patch.object(dm_mod, "download_stream", side_effect=fake_stream),
        patch.object(manager, "_refresh_media_item", return_value=fresh_item),
    ):
        manager.start_download(media_item=item, selected_format=stale)
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_tasks(limit=5)[0]
    assert stored.status == TaskStatus.COMPLETED
    assert streamed == [
        "https://cdn.example.com/expired.mp4",
        "https://cdn.example.com/fresh.mp4",
    ]


def test_download_manager_falls_back_to_muxed_when_no_audio_track(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """Without an audio-only stream, use the best complete stream instead of a silent file."""
    repo = MediaRepository(tmp_path / "muxed_fallback.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    video_only = MediaFormatInfo(
        format_id="v1080",
        container="mp4",
        height=1080,
        video_codec="h264",
        url="https://cdn.example.com/video-1080.mp4",
        requires_merge=True,
    )
    muxed = MediaFormatInfo(
        format_id="muxed720",
        container="webm",
        height=720,
        video_codec="vp9",
        audio_codec="opus",
        url="https://cdn.example.com/muxed-720.webm",
    )
    item = _video_item_with([video_only, muxed])

    streamed_urls: list[str] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        streamed_urls.append(url)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"muxed")
        return destination_path

    with (
        patch.object(dm_mod, "download_stream", side_effect=fake_stream),
        patch("xakumedia.processor.ffmpeg.merge_video_audio") as merge_mock,
    ):
        manager.start_download(media_item=item, selected_format=video_only)
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_tasks(limit=5)[0]
    assert stored.status == TaskStatus.COMPLETED
    assert streamed_urls == ["https://cdn.example.com/muxed-720.webm"]
    assert stored.selected_format is not None
    assert stored.selected_format.format_id == "muxed720"
    # The destination extension follows the fallback container, not the
    # originally requested MP4 quality.
    assert stored.destination_path is not None
    assert stored.destination_path.suffix == ".webm"
    merge_mock.assert_not_called()


def test_download_manager_fails_clearly_when_only_video_exists(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """A video-only source with no audio or muxed stream fails instead of saving silence."""
    repo = MediaRepository(tmp_path / "silent_video.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    video_only = MediaFormatInfo(
        format_id="v1080",
        container="mp4",
        height=1080,
        video_codec="h264",
        url="https://cdn.example.com/video-1080.mp4",
        requires_merge=True,
    )
    item = _video_item_with([video_only])

    import xakumedia.downloader.manager as dm_mod

    with (
        patch.object(dm_mod, "download_stream") as stream_mock,
        patch("xakumedia.processor.ffmpeg.merge_video_audio") as merge_mock,
    ):
        manager.start_download(media_item=item, selected_format=video_only)
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_tasks(limit=5)[0]
    assert stored.status == TaskStatus.FAILED
    assert stored.error_message is not None
    assert "silent video" in stored.error_message.lower()
    stream_mock.assert_not_called()
    merge_mock.assert_not_called()


def test_download_manager_allows_silent_gallerydl_facebook_video(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """Facebook reels without an audio track download instead of failing."""
    repo = MediaRepository(tmp_path / "facebook_silent.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    video_only = MediaFormatInfo(
        format_id="original",
        container="mp4",
        video_codec="h264",
        url="https://cdn.example.com/facebook-silent.mp4",
    )
    item = _video_item_with([video_only])
    item.provider = "gallerydl"
    item.metadata_extra = {"extractor": "facebook"}

    streamed: list[str] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        streamed.append(url)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"silent")
        return destination_path

    with patch.object(dm_mod, "download_stream", side_effect=fake_stream):
        manager.start_download(media_item=item, selected_format=video_only)
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_tasks(limit=5)[0]
    assert stored.status == TaskStatus.COMPLETED
    assert streamed == ["https://cdn.example.com/facebook-silent.mp4"]


def test_download_stream_uses_shared_client_without_closing_it(temp_dest_dir: Path) -> None:
    """A supplied client is reused and request options stay per download."""
    dest = temp_dest_dir / "images" / "pooled.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = b"pooled-bytes"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_error = False
    mock_response.headers = {"content-length": str(len(payload))}
    mock_response.iter_bytes.return_value = [payload]
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None

    shared_client = MagicMock()
    shared_client.is_closed = False
    shared_client.stream.return_value = mock_response

    download_stream(
        url="https://cdn.example.com/pooled.jpg",
        destination_path=dest,
        task_id="task-pooled",
        headers={"Referer": "https://example.com/post"},
        client=shared_client,
    )

    assert dest.read_bytes() == payload
    shared_client.close.assert_not_called()
    request = shared_client.stream.call_args
    assert request.args[:2] == ("GET", "https://cdn.example.com/pooled.jpg")
    assert request.kwargs["headers"]["Referer"] == "https://example.com/post"
    assert request.kwargs["timeout"] is not None


def test_download_manager_shares_one_stream_client(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """Bulk downloads reuse one connection pool instead of one client per file."""
    repo = MediaRepository(tmp_path / "pool.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)
    clients: list[object] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        clients.append(kwargs["client"])
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"x")
        return destination_path

    item = MediaItem(
        id="item-pool",
        source_url="https://example.com/post",
        original_url="https://cdn.example.com/pool.jpg",
        media_type=MediaType.IMAGE,
        title="Pool",
        author="creator",
        available_formats=[
            MediaFormatInfo(
                format_id="orig",
                container="jpg",
                url="https://cdn.example.com/pool.jpg",
            )
        ],
    )

    with patch.object(dm_mod, "download_stream", side_effect=fake_stream):
        first = manager.start_download(media_item=item)
        second = manager.start_download(media_item=item)

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            states = [repo.get_download_task(task.id).status for task in (first, second)]
            if all(state in (TaskStatus.COMPLETED, TaskStatus.FAILED) for state in states):
                break
            time.sleep(0.02)

    manager._executor.shutdown(wait=True)

    try:
        assert len(clients) == 2
        assert clients[0] is clients[1]
        assert repo.get_download_task(first.id).status == TaskStatus.COMPLETED
        assert repo.get_download_task(second.id).status == TaskStatus.COMPLETED
    finally:
        manager._stream_client().close()


def test_download_manager_refreshes_expired_facebook_url_on_download_error(
    temp_dest_dir: Path, tmp_path: Path
) -> None:
    """Transient HTTP 400 / DownloadError triggers URL refresh + retry for Facebook."""
    from xakumedia.exceptions import DownloadError

    repo = MediaRepository(tmp_path / "fb_retry.db")
    manager = DownloadManager(max_concurrent=1, repository=repo)

    stale_fmt = MediaFormatInfo(
        format_id="hd",
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        url="https://cdn.example.com/fb-stale.mp4",
    )
    fresh_fmt = MediaFormatInfo(
        format_id="hd",
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        url="https://cdn.example.com/fb-fresh.mp4",
    )
    item = _video_item_with([stale_fmt])
    item.provider = "gallerydl"
    item.provider_media_id = "99887766"
    item.source_url = "https://www.facebook.com/61580886670213"
    item.post_url = "https://www.facebook.com/61580886670213"
    item.metadata_extra = {"extractor": "facebook"}

    fresh_item = item.model_copy(deep=True)
    fresh_item.original_url = fresh_fmt.url
    fresh_item.available_formats = [fresh_fmt]

    attempted_urls: list[str] = []

    import xakumedia.downloader.manager as dm_mod

    def fake_stream(url: str, destination_path: Path, **kwargs: Any) -> Path:
        attempted_urls.append(url)
        if "fb-stale" in url:
            raise DownloadError("HTTP error 400: Bad Request")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"ok-fb-bytes")
        return destination_path

    with (
        patch.object(dm_mod, "download_stream", side_effect=fake_stream),
        patch.object(manager, "_refresh_media_item", return_value=fresh_item) as refresh_mock,
    ):
        task = manager.start_download(media_item=item, selected_format=stale_fmt)
        manager._executor.shutdown(wait=True)

    stored = repo.get_download_task(task.id)
    assert stored is not None
    assert stored.status == TaskStatus.COMPLETED
    assert attempted_urls == [
        "https://cdn.example.com/fb-stale.mp4",
        "https://cdn.example.com/fb-fresh.mp4",
    ]
    refresh_mock.assert_called_once()
