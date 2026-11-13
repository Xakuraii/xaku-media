"""Background scan-job engine for progressive, cancellable discovery.

Each job resolves a provider, creates a scan row immediately, then streams the
provider's posts into the UI and the database as they are discovered. Users can
stop at any time and keep everything found so far.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..core.logging import get_logger
from ..db import default_repository
from ..exceptions.base import XakuMediaError
from ..models.media import MediaType
from ..models.post import (
    Post,
    ProviderCapabilities,
    ScanOptions,
    ScanProgress,
    ScanStatus,
)
from ..models.url import ClassifiedUrl, UrlCategory
from ..providers.base import host_of
from ..providers.registry import provider_capabilities, resolve_provider
from ..server.loop import send_notification
from ..server.protocol import JsonRpcNotification
from ..utils.security import validate_url_security

logger = get_logger("scanning.manager")

MAX_RETAINED_JOBS = 100
PROGRESS_INTERVAL_SECONDS = 0.15


def _broadcast(name: str, payload: dict[str, Any]) -> None:
    """Send dual-format JSON-RPC notifications (colon and underscore syntax)."""
    for method_name in (f"scan:{name}", f"scan_{name}"):
        try:
            send_notification(JsonRpcNotification(method=method_name, params=payload))
        except Exception:
            pass


@dataclass
class ScanJob:
    """Mutable in-memory state for one discovery job."""

    job_id: str
    url: str
    scan_id: str | None = None
    provider: str | None = None
    status: ScanStatus = ScanStatus.QUEUED
    capabilities: ProviderCapabilities | None = None
    classified: dict[str, Any] | None = None
    progress: ScanProgress = field(default_factory=ScanProgress)
    posts: list[Post] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    error_category: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "scan_id": self.scan_id,
            "url": self.url,
            "provider": self.provider,
            "status": str(self.status),
            "capabilities": self.capabilities.model_dump() if self.capabilities else None,
            "classified_url": self.classified,
            "progress": self.progress.model_dump(),
            "posts": [post.model_dump(mode="json") for post in self.posts],
            "warnings": list(self.warnings),
            "error": self.error,
            "error_category": self.error_category,
            "error_details": dict(self.error_details),
            "stop_reason": self.stop_reason,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class ScanManager:
    """Owns scan jobs, worker threads, cancellation, and persistence."""

    def __init__(self, repository: Any = None, max_workers: int = 3) -> None:
        self.repository = repository or default_repository
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="xaku-scan"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, ScanJob] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------------ jobs
    def start(self, url: str, options: ScanOptions | None = None) -> dict[str, Any]:
        """Validate a source, create a scan row, and start discovery in the background."""
        if not url or not isinstance(url, str):
            raise ValueError("A source URL is required.")
        safe_url = validate_url_security(url.strip())
        scan_options = options or ScanOptions()

        provider = resolve_provider(safe_url)
        capabilities = provider_capabilities(safe_url)

        classify_error: XakuMediaError | None = None
        try:
            classified = provider.classify(safe_url)
        except XakuMediaError as exc:
            classify_error = exc
            classified = self._fallback_classification(safe_url, provider.name)
        except Exception as exc:  # defensive: never let classification crash start_scan
            classify_error = XakuMediaError(str(exc))
            classified = self._fallback_classification(safe_url, provider.name)

        job = ScanJob(
            job_id=str(uuid.uuid4()),
            url=safe_url,
            provider=provider.name,
            capabilities=capabilities,
            classified=classified.model_dump(mode="json"),
            status=ScanStatus.FAILED if classify_error else ScanStatus.QUEUED,
            error=classify_error.message if classify_error else None,
            error_category=classify_error.code if classify_error else None,
            error_details=dict(classify_error.details) if classify_error else {},
            stop_reason="error" if classify_error else None,
            finished_at=datetime.now(UTC) if classify_error else None,
        )
        job.scan_id = self.repository.create_scan(
            classified,
            provider=provider.name,
            status="failed" if classify_error else "running",
        )

        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._trim_locked()

        _broadcast(
            "started",
            {
                "job_id": job.job_id,
                "scan_id": job.scan_id,
                "url": job.url,
                "provider": job.provider,
                "capabilities": capabilities.model_dump(),
                "classified_url": job.classified,
            },
        )

        if classify_error is not None:
            try:
                self.repository.finalize_scan(
                    job.scan_id,
                    "failed",
                    stop_reason="error",
                    error=job.error,
                )
            except Exception as exc:
                logger.warning(f"Could not finalize failed scan {job.scan_id}: {exc}")
            self._broadcast_job_finished(job)
            return job.snapshot()

        self._executor.submit(self._run, job, provider, scan_options)
        return job.snapshot()

    @staticmethod
    def _fallback_classification(url: str, provider_name: str) -> ClassifiedUrl:
        """Minimal classification used when provider.classify fails up front."""
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=url,
            category=UrlCategory.UNKNOWN,
            platform=provider_name,
            domain=host_of(url),
            is_supported=True,
        )

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Request cancellation; partial results are kept."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown scan job: {job_id}")
        if job.status in (ScanStatus.COMPLETED, ScanStatus.CANCELLED, ScanStatus.FAILED):
            return job.snapshot()
        job.cancel_event.set()
        job.stop_reason = "cancelled"
        return job.snapshot()

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown scan job: {job_id}")
        return job.snapshot()

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(reversed(self._order[-limit:]))
            jobs = [self._jobs[jid] for jid in ids if jid in self._jobs]
        return [job.snapshot() for job in jobs]

    # ------------------------------------------------------------------ worker
    def _run(self, job: ScanJob, provider: Any, options: ScanOptions) -> None:
        job.status = ScanStatus.RUNNING
        job.started_at = datetime.now(UTC)
        last_progress = 0.0
        seen_posts: set[str] = set()
        seen_media: set[str] = set()
        order = 0
        max_media = options.max_media

        def emit_progress(force: bool = False) -> None:
            nonlocal last_progress
            now = time.monotonic()
            if not force and (now - last_progress) < PROGRESS_INTERVAL_SECONDS:
                return
            last_progress = now
            _broadcast(
                "progress",
                {
                    "job_id": job.job_id,
                    "scan_id": job.scan_id,
                    "status": str(job.status),
                    "progress": job.progress.model_dump(),
                },
            )

        def on_page(page: int) -> None:
            job.progress.pages_fetched = max(job.progress.pages_fetched, page)
            emit_progress()

        def on_warning(message: str) -> None:
            if message not in job.warnings:
                job.warnings.append(message)
                _broadcast(
                    "warning",
                    {"job_id": job.job_id, "scan_id": job.scan_id, "message": message},
                )

        try:
            emit_progress(force=True)
            for post in provider.iter_posts(
                job.url,
                options,
                job.cancel_event,
                on_page=on_page,
                on_warning=on_warning,
            ):
                if job.cancel_event.is_set():
                    job.stop_reason = "cancelled"
                    break
                if post.id in seen_posts:
                    continue
                seen_posts.add(post.id)

                new_items = [
                    item
                    for item in post.media_items
                    if item.id not in seen_media
                    and (options.include_images or item.media_type != MediaType.IMAGE)
                    and (options.include_videos or item.media_type != MediaType.VIDEO)
                ]
                duplicates = sum(1 for item in post.media_items if item.id in seen_media)
                if not new_items:
                    job.progress.duplicates_skipped += duplicates or 1
                    continue
                job.progress.duplicates_skipped += duplicates
                for item in new_items:
                    seen_media.add(item.id)

                post.media_items = new_items
                job.posts.append(post)
                job.progress.posts_discovered += 1
                job.progress.media_discovered += len(new_items)
                job.progress.images_discovered += sum(
                    1 for item in new_items if item.media_type == MediaType.IMAGE
                )
                job.progress.videos_discovered += sum(
                    1 for item in new_items if item.media_type == MediaType.VIDEO
                )

                try:
                    self.repository.save_scan_post(job.scan_id, post, order)
                except Exception as exc:  # persistence must not abort discovery
                    logger.warning(f"Could not persist post {post.id}: {exc}")
                order += 1

                _broadcast(
                    "post",
                    {
                        "job_id": job.job_id,
                        "scan_id": job.scan_id,
                        "post": post.model_dump(mode="json"),
                        "progress": job.progress.model_dump(),
                    },
                )
                emit_progress()

                if max_media is not None and job.progress.media_discovered >= max_media:
                    job.progress.limit_applied = True
                    job.stop_reason = "media_limit"
                    break
                if (
                    options.max_posts is not None
                    and job.progress.posts_discovered >= options.max_posts
                ):
                    job.progress.limit_applied = True
                    job.stop_reason = "post_limit"
                    break
        except Exception as exc:
            logger.warning(f"Scan job {job.job_id} failed: {exc}")
            job.status = ScanStatus.FAILED
            job.error = getattr(exc, "message", str(exc))
            job.error_category = (
                exc.code if isinstance(exc, XakuMediaError) else type(exc).__name__
            )
            job.error_details = dict(exc.details) if isinstance(exc, XakuMediaError) else {}
            job.stop_reason = "error"
        else:
            if job.cancel_event.is_set():
                job.status = ScanStatus.CANCELLED
                job.stop_reason = job.stop_reason or "cancelled"
            else:
                job.status = ScanStatus.COMPLETED
                job.stop_reason = job.stop_reason or "completed"
        finally:
            job.finished_at = datetime.now(UTC)
            try:
                self.repository.finalize_scan(
                    job.scan_id,
                    str(job.status),
                    posts_count=job.progress.posts_discovered,
                    images_count=job.progress.images_discovered,
                    videos_count=job.progress.videos_discovered,
                    pages_fetched=job.progress.pages_fetched,
                    stop_reason=job.stop_reason,
                    error=job.error,
                )
            except Exception as exc:
                logger.warning(f"Could not finalize scan {job.scan_id}: {exc}")

            self._broadcast_job_finished(job)

    def _broadcast_job_finished(self, job: ScanJob) -> None:
        event = {
            ScanStatus.COMPLETED: "completed",
            ScanStatus.CANCELLED: "cancelled",
            ScanStatus.FAILED: "failed",
        }.get(job.status, "completed")
        _broadcast(
            event,
            {
                "job_id": job.job_id,
                "scan_id": job.scan_id,
                "status": str(job.status),
                "progress": job.progress.model_dump(),
                "warnings": job.warnings,
                "error": job.error,
                "error_category": job.error_category,
                "error_details": dict(job.error_details),
                "stop_reason": job.stop_reason,
            },
        )

    def _trim_locked(self) -> None:
        """Drop the oldest finished jobs once the retention cap is exceeded."""
        while len(self._order) > MAX_RETAINED_JOBS:
            oldest = self._order[0]
            job = self._jobs.get(oldest)
            if job is not None and job.status in (
                ScanStatus.COMPLETED,
                ScanStatus.CANCELLED,
                ScanStatus.FAILED,
            ):
                self._order.pop(0)
                self._jobs.pop(oldest, None)
            else:
                break


default_scan_manager = ScanManager()

__all__ = ["ScanManager", "ScanJob", "default_scan_manager"]
