"""Scan job engine tests using a deterministic fake provider."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from xakumedia.db.repository import MediaRepository
from xakumedia.exceptions.base import NetworkTimeoutError
from xakumedia.models.media import MediaType
from xakumedia.models.post import ProviderCapabilities, ScanOptions
from xakumedia.models.queue import DownloadTask
from xakumedia.models.url import ClassifiedUrl, UrlCategory
from xakumedia.providers.base import make_media_item, make_post
from xakumedia.scanning import manager as scan_module
from xakumedia.scanning.manager import ScanManager


class FakeProvider:
    name = "fake"
    label = "Fake"

    def classify(self, url: str) -> ClassifiedUrl:
        return ClassifiedUrl(
            raw_url=url,
            normalized_url=url,
            category=UrlCategory.CHANNEL,
            platform="fake",
            domain="example.com",
            is_supported=True,
        )

    def iter_posts(self, url, options, cancel_event, on_page=None, on_warning=None):
        if on_page:
            on_page(1)
        for index in range(5):
            if cancel_event.is_set():
                return
            if options.max_posts is not None and index >= options.max_posts:
                return
            post_id = f"post-{index}"
            item = make_media_item(
                provider=self.name,
                source_url=url,
                media_url=f"https://cdn.example.com/{index}.jpg",
                media_type=MediaType.IMAGE,
                post_id="",
                provider_media_id=f"asset-{index}",
                post_url=f"https://example.com/p/{index}",
            )
            yield make_post(
                provider=self.name,
                source_url=url,
                post_key=post_id,
                provider_post_id=post_id,
                author="alice",
                title=f"Post {index}",
                media_items=[item],
                post_url=f"https://example.com/p/{index}",
            )


class BlockingProvider(FakeProvider):
    """Yields one post, then waits for cancellation."""

    def iter_posts(self, url, options, cancel_event, on_page=None, on_warning=None):
        if on_page:
            on_page(1)
        item = make_media_item(
            provider=self.name,
            source_url=url,
            media_url="https://cdn.example.com/0.jpg",
            media_type=MediaType.IMAGE,
            post_id="",
            provider_media_id="asset-0",
        )
        yield make_post(
            provider=self.name,
            source_url="https://example.com",
            post_key="post-0",
            provider_post_id="post-0",
            author="alice",
            title="Post 0",
            media_items=[item],
        )
        deadline = time.monotonic() + 5
        while not cancel_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)


def _wait_for(manager: ScanManager, job_id: str, predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = manager.get(job_id)
        if predicate(snapshot):
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for job {job_id}: {manager.get(job_id)['status']}")


@pytest.fixture
def fake_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ScanManager, MediaRepository]:
    repo = MediaRepository(tmp_path / "scan.db")
    manager = ScanManager(repository=repo, max_workers=1)
    capabilities = ProviderCapabilities(
        provider="fake",
        label="Fake",
        source_type="profile",
        profile_bulk=True,
        pagination=True,
    )
    monkeypatch.setattr(scan_module, "resolve_provider", lambda url: FakeProvider())
    monkeypatch.setattr(scan_module, "provider_capabilities", lambda url: capabilities)
    monkeypatch.setattr(scan_module, "_broadcast", lambda name, payload: None)
    return manager, repo


def test_scan_completes_and_persists_posts(fake_manager) -> None:
    manager, repo = fake_manager
    job = manager.start("https://example.com/profile", ScanOptions(max_posts=3))

    snapshot = _wait_for(manager, job["job_id"], lambda data: data["status"] == "completed")
    assert snapshot["progress"]["posts_discovered"] == 3
    assert snapshot["progress"]["media_discovered"] == 3
    assert snapshot["progress"]["images_discovered"] == 3
    assert len(snapshot["posts"]) == 3

    posts = repo.get_scan_posts(job["scan_id"])
    assert len(posts) == 3
    stats = repo.get_library_stats()
    assert stats["media_total"] == 3
    assert stats["posts"] == 3
    assert stats["scans"] == 1


def test_scan_items_fall_back_to_posts(fake_manager) -> None:
    manager, repo = fake_manager
    job = manager.start("https://example.com/profile", ScanOptions(max_posts=2))
    _wait_for(manager, job["job_id"], lambda data: data["status"] == "completed")

    items = repo.get_scan_items(job["scan_id"])
    assert len(items) == 2
    assert {item.media_type for item in items} == {MediaType.IMAGE}


def test_rescan_is_idempotent(fake_manager) -> None:
    manager, repo = fake_manager
    first = manager.start("https://example.com/profile")
    _wait_for(manager, first["job_id"], lambda data: data["status"] == "completed")
    second = manager.start("https://example.com/profile")
    _wait_for(manager, second["job_id"], lambda data: data["status"] == "completed")

    stats = repo.get_library_stats()
    assert stats["media_total"] == 5
    assert stats["posts"] == 5
    assert stats["scans"] == 2


def test_cancel_keeps_partial_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MediaRepository(tmp_path / "cancel.db")
    manager = ScanManager(repository=repo, max_workers=1)
    capabilities = ProviderCapabilities(provider="fake", label="Fake", profile_bulk=True)
    monkeypatch.setattr(scan_module, "resolve_provider", lambda url: BlockingProvider())
    monkeypatch.setattr(scan_module, "provider_capabilities", lambda url: capabilities)
    monkeypatch.setattr(scan_module, "_broadcast", lambda name, payload: None)

    job = manager.start("https://example.com/profile")
    _wait_for(manager, job["job_id"], lambda data: data["progress"]["posts_discovered"] == 1)
    manager.cancel(job["job_id"])

    snapshot = _wait_for(manager, job["job_id"], lambda data: data["status"] == "cancelled")
    assert snapshot["progress"]["posts_discovered"] == 1
    assert len(repo.get_scan_posts(job["scan_id"])) == 1


def test_unknown_job_raises(fake_manager) -> None:
    manager, _ = fake_manager
    with pytest.raises(ValueError):
        manager.get("missing")


def test_classify_failure_returns_failed_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = MediaRepository(tmp_path / "classify.db")
    manager = ScanManager(repository=repo, max_workers=1)

    class BrokenProvider(FakeProvider):
        def classify(self, url: str):
            raise NetworkTimeoutError(
                "Connection timed out while probing URL", details={"url": url}
            )

    monkeypatch.setattr(scan_module, "resolve_provider", lambda url: BrokenProvider())
    monkeypatch.setattr(
        scan_module,
        "provider_capabilities",
        lambda url: ProviderCapabilities(provider="fake", label="Fake"),
    )
    monkeypatch.setattr(scan_module, "_broadcast", lambda name, payload: None)

    snapshot = manager.start("https://example.com/profile")

    assert snapshot["status"] == "failed"
    assert snapshot["error_category"] == "NETWORK_TIMEOUT"
    assert snapshot["error_details"]["url"] == "https://example.com/profile"
    assert snapshot["stop_reason"] == "error"
    history = repo.get_scan_history(limit=5)
    assert len(history) == 1
    assert history[0]["status"] == "failed"


def test_save_media_items_reuses_provider_identity(tmp_path: Path) -> None:
    repo = MediaRepository(tmp_path / "identity.db")
    first = make_media_item(
        provider="direct",
        source_url="https://cdn.example.com/a.jpg",
        media_url="https://cdn.example.com/a.jpg",
        media_type=MediaType.IMAGE,
        post_id="",
        provider_media_id="https://cdn.example.com/a.jpg",
    )
    repo.save_media_items([first])

    # Simulate a legacy row id pointing at the same provider asset.
    repo.save_media_items([first.model_copy(update={"id": "legacy-random-id"})])

    assert repo.get_library_stats()["media_total"] == 1


def test_download_task_uses_canonical_media_id(tmp_path: Path) -> None:
    """A stale in-memory media id must not break the download_tasks FK."""
    repo = MediaRepository(tmp_path / "download-identity.db")
    item = make_media_item(
        provider="direct",
        source_url="https://cdn.example.com/a.jpg",
        media_url="https://cdn.example.com/a.jpg",
        media_type=MediaType.IMAGE,
        post_id="",
        provider_media_id="https://cdn.example.com/a.jpg",
    )
    repo.save_media_items([item])

    stale = item.model_copy(update={"id": "stale-id-from-another-scan"})
    task = DownloadTask(media_item=stale)

    repo.save_download_tasks([task])

    stored = repo.get_download_tasks(limit=5)
    assert len(stored) == 1
    assert stored[0].media_item.id == item.id
