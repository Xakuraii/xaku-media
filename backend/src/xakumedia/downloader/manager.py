"""Background download queue and worker thread orchestration manager."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from ..core.config import default_config
from ..core.logging import get_logger
from ..db import default_repository
from ..exceptions import (
    DownloadError,
    DownloadPausedError,
    MediaUnavailableError,
    NetworkTimeoutError,
    PrivateMediaError,
)
from ..models.media import MediaFormatInfo, MediaItem, MediaType
from ..models.post import ScanOptions
from ..models.queue import DownloadTask, ProgressUpdate, TaskStatus
from ..server.loop import send_notification
from ..server.protocol import JsonRpcNotification
from ..utils.naming import (
    compact_sequence_numbers,
    format_sequential_filename,
    get_next_sequence_number,
)
from .layout import destination_directory, user_folder
from .library import apply_renames, record_download
from .stream import download_stream

logger = get_logger("downloader.manager")


def _broadcast(name: str, payload: dict[str, Any]) -> None:
    """Send dual-format JSON-RPC notifications (colon and underscore syntax)."""
    for method_name in (f"download:{name}", f"download_{name}"):
        try:
            send_notification(JsonRpcNotification(method=method_name, params=payload))
        except Exception:
            pass


class DownloadManager:
    """Orchestrates background download execution, progress broadcasting, and queue state."""

    def __init__(
        self,
        max_concurrent: int | None = None,
        repository: Any = None,
        throttler: Any = None,
    ) -> None:
        self.max_concurrent = max(
            1, min(10, max_concurrent or default_config.max_concurrent_downloads)
        )
        self.repository = repository or default_repository
        from .throttler import default_throttler

        self.throttler = throttler or default_throttler
        self._executor = ThreadPoolExecutor(max_workers=30, thread_name_prefix="xaku-worker")
        self._lock = threading.Lock()
        self._sequence_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._pause_events: dict[str, threading.Event] = {}
        self._active_tasks: dict[str, DownloadTask] = {}
        self._pending_queue: list[tuple[DownloadTask, str]] = []
        self._stream_http_client: httpx.Client | None = None
        self._stream_client_lock = threading.Lock()

    def _stream_client(self) -> httpx.Client:
        """Return the pooled HTTP client shared by every stream download.

        Reusing one connection pool removes a TCP+TLS handshake per file, which
        dominates bulk photo downloads. Headers and cookies stay per request.
        """
        client = self._stream_http_client
        if client is None or client.is_closed:
            with self._stream_client_lock:
                client = self._stream_http_client
                if client is None or client.is_closed:
                    client = httpx.Client(
                        follow_redirects=True,
                        timeout=None,
                        limits=httpx.Limits(
                            max_connections=64,
                            max_keepalive_connections=32,
                            keepalive_expiry=10.0,
                        ),
                    )
                    self._stream_http_client = client
        return client

    def set_speed_limit(self, kbps: int) -> int:
        """Update maximum bandwidth limit in KB/s (0 = unlimited)."""
        return self.throttler.set_speed_limit(kbps)

    def get_speed_limit(self) -> int:
        """Return the current bandwidth limit in KB/s (0 = unlimited)."""
        return self.throttler.get_speed_limit()

    def set_concurrency(self, concurrency: int) -> int:
        """Update maximum concurrent active download workers (clamped between 1 and 10)."""
        clamped = max(1, min(10, concurrency))
        self.max_concurrent = clamped
        self._schedule_next()
        logger.info(f"Concurrency set to {self.max_concurrent}")
        return self.max_concurrent

    def _enqueue(self, task: DownloadTask, url: str) -> None:
        """Add a task to the pending FIFO queue and schedule available workers."""
        with self._lock:
            self._pending_queue.append((task, url))
        self._schedule_next()

    def _schedule_next(self) -> None:
        """Launch waiting tasks from the pending queue if worker capacity is available."""
        # Build the shared client on the scheduling thread so the first worker
        # does not stall on TLS setup, which would delay pause/cancel response.
        self._stream_client()
        with self._lock:
            while len(self._active_tasks) < self.max_concurrent and self._pending_queue:
                task, url = self._pending_queue.pop(0)
                cancel_event = threading.Event()
                pause_event = threading.Event()
                self._cancel_events[task.id] = cancel_event
                self._pause_events[task.id] = pause_event
                self._active_tasks[task.id] = task
                self._executor.submit(
                    self._run_task, task, url, cancel_event, pause_event
                )

    def _prepare_sequence_folder(
        self,
        directory: Path,
        username: str,
        media_type: MediaType,
    ) -> None:
        """Renumber this user's files to 1..N before a new file is added.

        Gaps appear when the user deletes a downloaded file; the next download
        closes them so the folder always reads 1, 2, 3, ... with no holes.
        Renamed files keep their download-task rows in sync.
        """
        with self._sequence_lock:
            renamed = compact_sequence_numbers(directory, username, media_type)
            if not renamed:
                return

            mapping = {str(old): str(new) for old, new in renamed}
            try:
                apply_renames(renamed)
            except Exception as exc:  # manifest bookkeeping is best effort
                logger.warning(f"Could not update library manifest after renumbering: {exc}")
            try:
                self.repository.remap_download_paths(mapping)
            except Exception as exc:  # never block a download on a path remap
                logger.warning(f"Could not remap download paths after renumbering: {exc}")

    def start_download(
        self,
        media_item: MediaItem,
        selected_format: MediaFormatInfo | None = None,
        destination_path: Path | str | None = None,
    ) -> DownloadTask:
        """Enqueue and launch a background download task."""
        # 1. Resolve source stream URL
        url = (
            selected_format.url
            if (selected_format and selected_format.url)
            else media_item.original_url
        )

        # 2. Resolve destination path if not provided
        if destination_path:
            dest = Path(destination_path)
        else:
            username = user_folder(media_item)
            is_image = media_item.media_type == MediaType.IMAGE

            ext = "jpg" if is_image else "mp4"
            if selected_format and selected_format.container:
                ext = selected_format.container.lstrip(".")
            elif media_item.available_formats and media_item.available_formats[0].container:
                ext = media_item.available_formats[0].container.lstrip(".")
            else:
                parsed_ext = Path(url.split("?")[0]).suffix.lstrip(".")
                if parsed_ext and len(parsed_ext) <= 5:
                    ext = parsed_ext

            target_dir = destination_directory(media_item)
            target_dir.mkdir(parents=True, exist_ok=True)
            self._prepare_sequence_folder(target_dir, username, media_item.media_type)
            seq = get_next_sequence_number(target_dir, username, media_item.media_type)
            filename = format_sequential_filename(username, media_item.media_type, seq, ext)
            dest = target_dir / filename

        dest.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest.with_suffix(dest.suffix + ".part")

        task = DownloadTask(
            id=str(uuid.uuid4()),
            media_item=media_item,
            status=TaskStatus.QUEUED,
            selected_format=selected_format,
            destination_path=dest,
            temp_path=temp_path,
        )

        # Persist task in SQLite
        self.repository.save_download_task(task)

        # Enqueue task and attempt scheduling
        self._enqueue(task, url)
        logger.info(f"Queued download task {task.id} for {dest.name}")
        return task

    def start_batch_download(
        self,
        items: list[dict[str, Any] | tuple[Any, ...]],
        target_dir: Path | str | None = None,
    ) -> list[DownloadTask]:
        """Enqueue multiple download tasks with sequential naming and slot scheduling."""
        created_tasks: list[DownloadTask] = []
        seq_tracker: dict[tuple[Path, str, MediaType], int] = {}
        pending_items: list[tuple[DownloadTask, str]] = []
        created_dirs: set[Path] = set()
        prepared_dirs: set[tuple[Path, str, MediaType]] = set()

        for entry in items:
            media_item: MediaItem
            selected_format: MediaFormatInfo | None = None
            dest_override: Path | str | None = None

            if isinstance(entry, dict):
                m_raw = entry.get("media_item")
                if isinstance(m_raw, MediaItem):
                    media_item = m_raw
                else:
                    media_item = MediaItem.model_validate(m_raw)

                f_raw = entry.get("selected_format")
                if isinstance(f_raw, MediaFormatInfo):
                    selected_format = f_raw
                elif f_raw:
                    selected_format = MediaFormatInfo.model_validate(f_raw)

                dest_override = entry.get("destination_path")
            elif isinstance(entry, (tuple, list)):
                m_raw = entry[0]
                media_item = (
                    m_raw if isinstance(m_raw, MediaItem) else MediaItem.model_validate(m_raw)
                )
                if len(entry) > 1 and entry[1] is not None:
                    f_raw = entry[1]
                    selected_format = (
                        f_raw
                        if isinstance(f_raw, MediaFormatInfo)
                        else MediaFormatInfo.model_validate(f_raw)
                    )
                if len(entry) > 2 and entry[2] is not None:
                    dest_override = entry[2]
            else:
                continue

            url = (
                selected_format.url
                if (selected_format and selected_format.url)
                else media_item.original_url
            )

            if dest_override:
                dest = Path(dest_override)
            else:
                username = user_folder(media_item)
                is_image = media_item.media_type == MediaType.IMAGE

                ext = "jpg" if is_image else "mp4"
                if selected_format and selected_format.container:
                    ext = selected_format.container.lstrip(".")
                elif media_item.available_formats and media_item.available_formats[0].container:
                    ext = media_item.available_formats[0].container.lstrip(".")
                else:
                    parsed_ext = Path(url.split("?")[0]).suffix.lstrip(".")
                    if parsed_ext and len(parsed_ext) <= 5:
                        ext = parsed_ext

                item_dir = destination_directory(
                    media_item, Path(target_dir) if target_dir else None
                )
                if item_dir not in created_dirs:
                    item_dir.mkdir(parents=True, exist_ok=True)
                    created_dirs.add(item_dir)

                prep_key = (item_dir, username, media_item.media_type)
                if prep_key not in prepared_dirs:
                    self._prepare_sequence_folder(
                        item_dir, username, media_item.media_type
                    )
                    prepared_dirs.add(prep_key)

                key = (item_dir, username, media_item.media_type)
                if key not in seq_tracker:
                    seq = get_next_sequence_number(item_dir, username, media_item.media_type)
                    seq_tracker[key] = seq
                else:
                    seq_tracker[key] += 1
                    seq = seq_tracker[key]

                filename = format_sequential_filename(username, media_item.media_type, seq, ext)
                dest = item_dir / filename

            if dest.parent not in created_dirs:
                dest.parent.mkdir(parents=True, exist_ok=True)
                created_dirs.add(dest.parent)
            temp_path = dest.with_suffix(dest.suffix + ".part")

            task = DownloadTask(
                id=str(uuid.uuid4()),
                media_item=media_item,
                status=TaskStatus.QUEUED,
                selected_format=selected_format,
                destination_path=dest,
                temp_path=temp_path,
            )
            created_tasks.append(task)
            pending_items.append((task, url))

        # Persist all batch tasks in a single high-performance database transaction
        if hasattr(self.repository, "save_download_tasks"):
            self.repository.save_download_tasks(created_tasks)
        else:
            for task in created_tasks:
                self.repository.save_download_task(task)

        with self._lock:
            self._pending_queue.extend(pending_items)

        self._schedule_next()
        logger.info(f"Queued batch of {len(created_tasks)} tasks.")
        return created_tasks

    def cancel_download(self, task_id: str) -> bool:
        """Signal cancellation for an active or queued download task."""
        with self._lock:
            event = self._cancel_events.get(task_id)
            if event:
                event.set()
                logger.info(f"Cancellation signaled for active download task {task_id}")
                return True

            for i, (task, _) in enumerate(self._pending_queue):
                if task.id == task_id:
                    self._pending_queue.pop(i)
                    task.status = TaskStatus.CANCELLED
                    self.repository.save_download_task(task)
                    _broadcast("cancelled", {"task_id": task_id})
                    logger.info(f"Cancelled pending task {task_id}")
                    return True

        task = self.repository.get_download_task(task_id)
        if task and not task.status.is_terminal:
            task.status = TaskStatus.CANCELLED
            self.repository.save_download_task(task)
            _broadcast("cancelled", {"task_id": task_id})
            return True
        return False

    def pause_download(self, task_id: str) -> bool:
        """Signal pause for an active download or mark a queued task paused."""
        with self._lock:
            event = self._pause_events.get(task_id)
            if event:
                event.set()
                logger.info(f"Pause signaled for active download task {task_id}")
                return True

            for i, (task, _) in enumerate(self._pending_queue):
                if task.id == task_id:
                    self._pending_queue.pop(i)
                    task.status = TaskStatus.PAUSED
                    self.repository.save_download_task(task)
                    _broadcast(
                        "paused",
                        {"task_id": task_id, "task": task.model_dump(mode="json")},
                    )
                    logger.info(f"Paused pending task {task_id}")
                    return True

        task = self.repository.get_download_task(task_id)
        if task and task.status in (TaskStatus.QUEUED, TaskStatus.DOWNLOADING):
            task.status = TaskStatus.PAUSED
            self.repository.save_download_task(task)
            _broadcast(
                "paused",
                {"task_id": task_id, "task": task.model_dump(mode="json")},
            )
            return True

        return False

    def resume_download(self, task_id: str) -> bool:
        """Resume a paused download task."""
        with self._lock:
            if task_id in self._active_tasks or any(
                t.id == task_id for t, _ in self._pending_queue
            ):
                return True

        task = self.repository.get_download_task(task_id)
        if not task or task.status not in (TaskStatus.PAUSED, TaskStatus.QUEUED):
            return False

        task.status = TaskStatus.QUEUED
        self.repository.save_download_task(task)

        url = (
            task.selected_format.url
            if (task.selected_format and task.selected_format.url)
            else task.media_item.original_url
        )
        self._enqueue(task, url)
        _broadcast(
            "resumed",
            {"task_id": task_id, "task": task.model_dump(mode="json")},
        )
        logger.info(f"Resumed task {task_id}")
        return True

    def pause_all(self) -> int:
        """Pause all active and pending download tasks."""
        count = 0
        with self._lock:
            for event in self._pause_events.values():
                event.set()
                count += 1

            for task, _ in self._pending_queue:
                task.status = TaskStatus.PAUSED
                self.repository.save_download_task(task)
                _broadcast(
                    "paused",
                    {"task_id": task.id, "task": task.model_dump(mode="json")},
                )
                count += 1
            self._pending_queue.clear()

        logger.info(f"pause_all signaled for {count} tasks.")
        return count

    def resume_all(self) -> int:
        """Resume all paused download tasks in the database."""
        paused_tasks = self.repository.get_download_tasks(
            status=TaskStatus.PAUSED, limit=200
        )
        resumed_count = 0
        for task in paused_tasks:
            if self.resume_download(task.id):
                resumed_count += 1
        logger.info(f"resume_all re-enqueued {resumed_count} tasks.")
        return resumed_count

    def cancel_all(self) -> int:
        """Cancel all active and pending download tasks."""
        count = 0
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
                count += 1

            for task, _ in self._pending_queue:
                task.status = TaskStatus.CANCELLED
                self.repository.save_download_task(task)
                _broadcast("cancelled", {"task_id": task.id})
                count += 1
            self._pending_queue.clear()

        logger.info(f"cancel_all cancelled {count} tasks.")
        return count

    def clear_completed(self) -> int:
        """Remove completed, failed, and cancelled tasks from database."""
        deleted = self.repository.clear_completed_tasks()
        _broadcast("queue_cleared", {"cleared_count": deleted})
        return deleted

    def get_queue_state(self) -> dict[str, Any]:
        """Get aggregate counts and worker slot metrics for the download queue."""
        with self._lock:
            active_count = len(self._active_tasks)
            pending_count = len(self._pending_queue)

        return {
            "max_concurrent": self.max_concurrent,
            "active_count": active_count,
            "pending_count": pending_count,
            "counts": self.repository.get_queue_counts(),
        }

    def get_tasks(
        self, status: TaskStatus | None = None, limit: int = 50
    ) -> list[DownloadTask]:
        """Query download tasks from the database."""
        return self.repository.get_download_tasks(status=status, limit=limit)

    def recover_interrupted_tasks(
        self, auto_resume: bool | None = None
    ) -> dict[str, Any]:
        """Audit and recover uncompleted or crashed download tasks."""
        from .recovery import TaskRecoveryService

        service = TaskRecoveryService(manager=self)
        summary = service.recover_interrupted_tasks(auto_resume=auto_resume)
        return summary.to_dict()

    @staticmethod
    def _format_has_video(fmt: MediaFormatInfo | None) -> bool:
        if not fmt:
            return False
        codec = (fmt.video_codec or "").lower()
        return bool(codec and codec != "none")

    @staticmethod
    def _format_has_audio(fmt: MediaFormatInfo | None) -> bool:
        if not fmt:
            return False
        codec = (fmt.audio_codec or "").lower()
        return bool(codec and codec != "none")

    def _best_audio_format(self, media_item: MediaItem) -> MediaFormatInfo | None:
        """Pick the highest-quality audio-only stream with a direct URL."""
        codec_rank = {
            "flac": 7,
            "alac": 7,
            "wav": 6,
            "opus": 5,
            "vorbis": 4,
            "aac": 4,
            "mp4a": 4,
            "mp3": 3,
            "ac3": 2,
            "eac3": 2,
        }
        candidates = [
            fmt
            for fmt in media_item.available_formats
            if fmt.url
            and self._format_has_audio(fmt)
            and not self._format_has_video(fmt)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda fmt: (
                codec_rank.get((fmt.audio_codec or "").lower(), 1),
                fmt.filesize_bytes or 0,
            ),
            reverse=True,
        )
        return candidates[0]

    def _best_muxed_format(
        self, media_item: MediaItem, preferred_height: int | None = None
    ) -> MediaFormatInfo | None:
        """Fallback to a complete video+audio stream when no audio track exists."""
        candidates = [
            fmt
            for fmt in media_item.available_formats
            if fmt.url
            and self._format_has_video(fmt)
            and self._format_has_audio(fmt)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda fmt: (fmt.height or 0, fmt.filesize_bytes or 0), reverse=True)
        if preferred_height:
            within = [fmt for fmt in candidates if (fmt.height or 0) <= preferred_height]
            if within:
                return within[0]
        return candidates[0]

    @staticmethod
    def _destination_for_container(dest: Path, container: str | None) -> Path:
        """Keep the destination extension in sync with the stream being written."""
        ext = (container or "").lower().lstrip(".")
        if not ext or dest.suffix.lower() == f".{ext}":
            return dest
        return dest.with_suffix(f".{ext}")

    def _plan_streams(
        self,
        media_item: MediaItem,
        selected: MediaFormatInfo | None,
    ) -> tuple[MediaFormatInfo | None, MediaFormatInfo | None, str]:
        """Resolve a complete plan: direct/muxed stream, or video plus audio.

        Never returns a video-only plan when a separate audio track exists.
        """
        if selected is None and media_item.available_formats:
            # Respect the configured quality ceiling; "best" has no threshold.
            selected = media_item.find_best_format(
                default_config.default_video_resolution
            )

        if (
            selected
            and self._format_has_video(selected)
            and not self._format_has_audio(selected)
        ):
            audio_format = self._best_audio_format(media_item)
            if audio_format and audio_format.url:
                return (
                    selected,
                    audio_format,
                    selected.url or media_item.original_url,
                )

            muxed = self._best_muxed_format(media_item, selected.height)
            if muxed and muxed.url:
                logger.warning(
                    f"No audio-only track for {selected.format_id}; "
                    f"falling back to muxed format {muxed.format_id} "
                    f"({muxed.height or '?'}p)"
                )
                return muxed, None, muxed.url

            # Facebook reels sometimes have no audio stream at all (silent
            # clips, or the page exposes only a video-only DASH rendition).
            # gallery-dl reports that honestly; failing the download would leave
            # the user with nothing to play. Other providers keep the strict
            # check because a missing audio partner there usually means a bad
            # extraction, not a silent source.
            if (
                (media_item.provider or "").lower() == "gallerydl"
                and media_item.metadata_extra.get("extractor") == "facebook"
            ):
                logger.info(
                    f"Facebook video {selected.format_id} has no audio track; "
                    "downloading the silent stream."
                )
                return selected, None, selected.url or media_item.original_url

            raise DownloadError(
                "The selected quality is a video-only stream, and this source "
                "did not expose a matching audio track. XakuMedia will not save "
                "a silent video. Rescan the source or choose another quality."
            )

        url = (
            selected.url
            if selected and selected.url
            else media_item.original_url
        )
        return selected, None, url

    def _match_format(
        self,
        media_item: MediaItem,
        old: MediaFormatInfo | None,
    ) -> MediaFormatInfo | None:
        """Map a previously selected format onto a freshly extracted item."""
        if old is None:
            return None

        for candidate in media_item.available_formats:
            if candidate.format_id == old.format_id:
                return candidate

        if self._format_has_audio(old) and not self._format_has_video(old):
            return self._best_audio_format(media_item)

        if self._format_has_video(old):
            videos = [
                candidate
                for candidate in media_item.available_formats
                if self._format_has_video(candidate) and candidate.url
            ]
            if not videos:
                return None
            target_height = old.height or 0
            return min(
                videos,
                key=lambda candidate: abs((candidate.height or 0) - target_height),
            )

        return media_item.available_formats[0] if media_item.available_formats else None

    def _refresh_media_item(self, media_item: MediaItem) -> MediaItem | None:
        """Re-extract the owning post to replace expired or signed CDN URLs.

        yt-dlp and gallery-dl URLs can expire while a task waits in the queue.
        Re-running the provider for the same post returns a fresh stream URL and
        the headers needed to fetch it.
        """
        provider_name = (media_item.provider or "").lower()
        if provider_name == "gallerydl":
            from ..providers.gallerydl import GalleryDlProvider

            provider = GalleryDlProvider()
        elif provider_name == "ytdlp":
            from ..providers.ytdlp import YtDlpProvider

            provider = YtDlpProvider()
        else:
            return None

        page_url = (
            media_item.post_url
            or media_item.original_url
            or media_item.source_url
        )
        if not page_url.lower().startswith(("http://", "https://")):
            return None

        try:
            posts = list(
                provider.iter_posts(
                    page_url,
                    ScanOptions(
                        include_images=True,
                        include_videos=True,
                        max_posts=25,
                    ),
                    threading.Event(),
                )
            )
        except Exception as exc:
            logger.warning(
                f"Could not refresh media URLs for {page_url}: {exc}"
            )
            return None

        candidates = [item for post in posts for item in post.media_items if item]
        if not candidates:
            return None

        if media_item.provider_media_id:
            for candidate in candidates:
                if candidate.provider_media_id == media_item.provider_media_id:
                    logger.info(
                        f"Refreshed media URL for {media_item.provider_media_id} "
                        f"via {provider_name}."
                    )
                    return candidate

        same_type = [
            candidate
            for candidate in candidates
            if candidate.media_type == media_item.media_type
        ]
        if len(same_type) == 1:
            return same_type[0]

        for candidate in same_type:
            if candidate.attachment_index == media_item.attachment_index:
                return candidate

        return None

    def _align_destination(
        self,
        task: DownloadTask,
        dest: Path,
        selected: MediaFormatInfo | None,
        container: str | None = None,
    ) -> Path:
        """Match the destination suffix to the selected container."""
        target = container or (selected.container if selected else None)
        if not target:
            return dest
        aligned = self._destination_for_container(dest, target)
        if aligned == dest:
            return dest
        logger.info(
            f"Task {task.id}: destination extension adjusted "
            f"{dest.name} -> {aligned.name}"
        )
        task.destination_path = aligned
        task.temp_path = aligned.with_suffix(aligned.suffix + ".part")
        self.repository.save_download_task(task)
        return aligned

    @staticmethod
    def _desired_video_container(media_item: MediaItem) -> str | None:
        """Return the configured output container, or None for "original"."""
        if media_item.media_type != MediaType.VIDEO:
            return None
        container = default_config.default_video_container
        value = getattr(container, "value", container)
        value = str(value).lower()
        if value in ("", "original"):
            return None
        return value

    @staticmethod
    def _convert_container(
        source: Path,
        target: Path,
        cancel_event: threading.Event,
    ) -> Path:
        """Remux ``source`` into the configured container.

        A conversion failure keeps the already-downloaded source file instead of
        failing the whole task; the log records why the preference was skipped.
        """
        from ..processor.ffmpeg import convert_container

        try:
            return convert_container(
                source,
                target,
                is_cancelled=cancel_event.is_set,
            )
        except Exception as exc:
            logger.warning(
                f"Could not convert {source.name} to {target.suffix}: {exc}. "
                "Keeping the original container."
            )
            return source

    @staticmethod
    def _apply_output_preferences(
        media_item: MediaItem,
        final_path: Path,
        cancel_event: threading.Event,
    ) -> Path:
        """Apply the configured image format to a finished download."""
        if media_item.media_type != MediaType.IMAGE:
            return final_path

        target_format = default_config.default_image_format
        value = str(getattr(target_format, "value", target_format)).lower()
        if value in ("", "original"):
            return final_path
        if cancel_event.is_set():
            return final_path

        from ..processor.images import ImageConversionError, convert_image_format

        try:
            return convert_image_format(final_path, value)
        except ImageConversionError as exc:
            logger.warning(f"Image format preference skipped: {exc}")
            return final_path

    def _run_task(
        self,
        task: DownloadTask,
        url: str,
        cancel_event: threading.Event,
        pause_event: threading.Event,
    ) -> None:
        """Worker thread executing the stream download and optional FFmpeg stream merge."""
        task.status = TaskStatus.DOWNLOADING
        self.repository.save_download_task(task)

        # Broadcast download started
        _broadcast("started", {"task": task.model_dump(mode="json")})

        last_db_persist = time.monotonic()

        def progress_callback(update: ProgressUpdate) -> None:
            nonlocal last_db_persist
            task.bytes_downloaded = update.bytes_downloaded
            task.total_bytes = update.total_bytes
            task.progress_percent = update.progress_percent
            task.speed_bytes_sec = update.speed_bytes_sec

            # Broadcast live progress notification
            _broadcast("progress", update.model_dump(mode="json"))

            now = time.monotonic()
            if now - last_db_persist >= 1.0:
                self.repository.save_download_task(task)
                last_db_persist = now

        # Pick a complete download plan: a muxed stream when possible, or a
        # video track plus the best audio track. Never fall through to a silent
        # video-only file.
        selected = task.selected_format
        media_item = task.media_item
        dest = task.destination_path
        audio_format: MediaFormatInfo | None = None
        video_part: Path | None = None
        audio_part: Path | None = None
        merged_temp: Path | None = None
        video_bytes = 0
        desired_container = self._desired_video_container(media_item)

        def cleanup_parts() -> None:
            """Drop partial merge inputs so a retry starts from clean bytes."""
            nonlocal video_part, audio_part, merged_temp
            for part in (video_part, audio_part, merged_temp):
                if part is not None:
                    try:
                        part.unlink(missing_ok=True)
                    except OSError:
                        pass
            video_part = None
            audio_part = None
            merged_temp = None

        try:
            if not dest:
                raise DownloadError(
                    "Download destination path is missing; the task cannot be started."
                )

            selected, audio_format, url = self._plan_streams(media_item, selected)
            task.selected_format = selected
            # Sync the file extension with the actual stream container. A muxed
            # fallback or caller-supplied path can otherwise yield WebM bytes in
            # a ``.mp4`` file, which players may refuse to open. An explicit
            # container preference wins and the bytes are remuxed to match.
            dest = self._align_destination(
                task, dest, selected, container=desired_container
            )
            source_container = (selected.container if selected else "") or ""
            source_container = source_container.lower().lstrip(".")

            def run_plan() -> Path:
                """Execute the current stream plan once."""
                nonlocal selected, audio_format, url, media_item, dest
                nonlocal video_part, audio_part, merged_temp, video_bytes

                if audio_format and audio_format.url:
                    v_fmt_id = selected.format_id if selected else "unknown"
                    a_fmt_id = audio_format.format_id
                    logger.info(
                        f"Task {task.id} requires FFmpeg merge "
                        f"(video: {v_fmt_id}, audio: {a_fmt_id})"
                    )
                    video_part = dest.with_name(f"{dest.name}.video")
                    audio_part = dest.with_name(f"{dest.name}.audio")
                    merged_temp = dest.with_name(f"{dest.stem}.merged{dest.suffix}")
                    try:
                        merged_temp.unlink(missing_ok=True)
                    except OSError:
                        pass

                    video_bytes = 0

                    # 1. Download video track (0-85% of the task)
                    def video_progress(up: ProgressUpdate) -> None:
                        nonlocal video_bytes
                        video_bytes = up.bytes_downloaded
                        progress_callback(
                            ProgressUpdate(
                                task_id=task.id,
                                status=TaskStatus.DOWNLOADING,
                                bytes_downloaded=up.bytes_downloaded,
                                total_bytes=up.total_bytes,
                                progress_percent=round(up.progress_percent * 0.85, 1),
                                speed_bytes_sec=up.speed_bytes_sec,
                                eta_seconds=up.eta_seconds,
                                detail_message="Downloading video track...",
                            )
                        )

                    download_stream(
                        url=url,
                        destination_path=video_part,
                        task_id=task.id,
                        progress_callback=video_progress,
                        cancel_event=cancel_event,
                        pause_event=pause_event,
                        headers=selected.http_headers if selected else None,
                        throttler=self.throttler,
                        client=self._stream_client(),
                    )
                    try:
                        video_bytes = video_part.stat().st_size
                    except OSError:
                        pass

                    # 2. Download audio track (85-97% of the task)
                    def audio_progress(up: ProgressUpdate) -> None:
                        total = (
                            video_bytes + up.total_bytes
                            if up.total_bytes
                            else up.total_bytes
                        )
                        progress_callback(
                            ProgressUpdate(
                                task_id=task.id,
                                status=TaskStatus.DOWNLOADING,
                                bytes_downloaded=video_bytes + up.bytes_downloaded,
                                total_bytes=total,
                                progress_percent=round(
                                    85.0 + (up.progress_percent * 0.12), 1
                                ),
                                speed_bytes_sec=up.speed_bytes_sec,
                                eta_seconds=up.eta_seconds,
                                detail_message="Downloading audio track...",
                            )
                        )

                    download_stream(
                        url=audio_format.url,
                        destination_path=audio_part,
                        task_id=task.id,
                        progress_callback=audio_progress,
                        cancel_event=cancel_event,
                        pause_event=pause_event,
                        headers=audio_format.http_headers or None,
                        throttler=self.throttler,
                        client=self._stream_client(),
                    )

                    # 3. Transition to MERGING state
                    task.status = TaskStatus.MERGING
                    task.progress_percent = 97.0
                    self.repository.save_download_task(task)
                    _broadcast(
                        "progress",
                        ProgressUpdate(
                            task_id=task.id,
                            status=TaskStatus.MERGING,
                            bytes_downloaded=task.bytes_downloaded,
                            total_bytes=task.total_bytes,
                            progress_percent=97.0,
                            detail_message="Merging audio and video tracks with FFmpeg...",
                        ).model_dump(mode="json"),
                    )

                    # 4. Perform FFmpeg multiplexing into a correctly suffixed temp file
                    from ..processor.ffmpeg import merge_video_audio

                    container = (
                        desired_container
                        or (
                            selected.container
                            if selected and selected.container
                            else dest.suffix.lstrip(".")
                        )
                    )
                    merge_video_audio(
                        video_path=video_part,
                        audio_path=audio_part,
                        output_path=merged_temp,
                        output_container=container,
                        is_cancelled=cancel_event.is_set,
                    )

                    # 5. Clean up temporary parts and atomically finalize
                    video_part.unlink(missing_ok=True)
                    audio_part.unlink(missing_ok=True)
                    video_part = None
                    audio_part = None

                    import os

                    os.replace(str(merged_temp), str(dest))
                    merged_temp = None
                    return dest

                # Direct single-stream download. When the configured container
                # differs from the source stream, fetch the source first and
                # remux afterwards so the extension always matches the bytes.
                download_target = dest
                if (
                    desired_container
                    and source_container
                    and source_container != desired_container
                ):
                    download_target = dest.with_suffix(f".{source_container}")

                final = download_stream(
                    url=url,
                    destination_path=download_target,
                    task_id=task.id,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                    headers=selected.http_headers if selected else None,
                    throttler=self.throttler,
                    client=self._stream_client(),
                )

                if download_target != dest:
                    return self._convert_container(download_target, dest, cancel_event)
                return final

            attempts = max(1, int(default_config.max_retries) + 1)
            final_path: Path | None = None
            for attempt in range(1, attempts + 1):
                try:
                    final_path = run_plan()
                    break
                except (
                    PrivateMediaError,
                    MediaUnavailableError,
                    NetworkTimeoutError,
                    httpx.TransportError,
                ) as exc:
                    if attempt >= attempts:
                        raise
                    # Signed CDN URLs expire while a task waits in the queue.
                    # Ask the owning provider for fresh URLs and try again.
                    logger.warning(
                        f"Task {task.id}: attempt {attempt}/{attempts} failed "
                        f"({exc}); refreshing media URLs from the source provider."
                    )
                    cleanup_parts()
                    refreshed_item = self._refresh_media_item(media_item)
                    if refreshed_item is not None:
                        fresh_selected = self._match_format(refreshed_item, selected)
                        fresh_audio = (
                            self._match_format(refreshed_item, audio_format)
                            if audio_format
                            else None
                        )
                        media_item = refreshed_item
                        task.media_item = media_item
                        selected = fresh_selected
                        audio_format = fresh_audio
                        selected, audio_format, url = self._plan_streams(
                            media_item, selected
                        )
                        task.selected_format = selected
                        dest = self._align_destination(
                            task, dest, selected, container=desired_container
                        )
                        source_container = (
                            (selected.container if selected else "") or ""
                        ).lower().lstrip(".")
                        self.repository.save_download_task(task)
                    time.sleep(min(0.5 * attempt, 2.0))

            if final_path is None:
                raise DownloadError(
                    "The download did not complete after the configured retries."
                )

            final_path = self._apply_output_preferences(
                media_item, final_path, cancel_event
            )

            task.mark_completed(final_path)
            self.repository.save_download_task(task)
            record_download(media_item, final_path)
            logger.info(f"Task {task.id} completed successfully: {final_path}")
            _broadcast("completed", {"task": task.model_dump(mode="json")})

        except DownloadPausedError:
            task.status = TaskStatus.PAUSED
            self.repository.save_download_task(task)
            logger.info(f"Task {task.id} paused by user.")
            _broadcast(
                "paused",
                {"task_id": task.id, "task": task.model_dump(mode="json")},
            )

        except Exception as exc:
            if video_part and video_part.exists():
                video_part.unlink(missing_ok=True)
            if audio_part and audio_part.exists():
                audio_part.unlink(missing_ok=True)
            if merged_temp and merged_temp.exists():
                merged_temp.unlink(missing_ok=True)

            if cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                logger.info(f"Task {task.id} cancelled.")
                _broadcast("cancelled", {"task_id": task.id})
            else:
                task.mark_failed(str(exc))
                logger.error(f"Task {task.id} failed: {exc}")
                _broadcast("failed", {"task_id": task.id, "error": str(exc)})
            self.repository.save_download_task(task)
        finally:
            with self._lock:
                self._cancel_events.pop(task.id, None)
                self._pause_events.pop(task.id, None)
                self._active_tasks.pop(task.id, None)
            self._schedule_next()


# Default singleton instance
default_download_manager = DownloadManager()
