"""Provider registry, stable identity, and gallery grouping tests (no network)."""

from __future__ import annotations

import threading

import pytest
from gallery_dl.exception import NotFoundError
from gallery_dl.extractor.message import Message

from xakumedia.exceptions.base import (
    MediaUnavailableError,
    PrivateMediaError,
    UnsupportedSourceError,
)
from xakumedia.models.media import MediaFormatInfo, MediaItem, MediaType
from xakumedia.models.post import ScanOptions
from xakumedia.models.url import ClassifiedUrl, UrlCategory
from xakumedia.providers import direct as direct_module
from xakumedia.providers import gallerydl as gallery_module
from xakumedia.providers.base import media_identity
from xakumedia.providers.direct import DirectProvider
from xakumedia.providers.gallerydl import GalleryDlProvider
from xakumedia.providers.registry import provider_capabilities, resolve_provider
from xakumedia.providers.ytdlp import YtDlpProvider
from xakumedia.utils.stable_ids import canonical_media_url, stable_id


def test_registry_routes_known_sources() -> None:
    assert resolve_provider("https://www.youtube.com/@SomeChannel/videos").name == "ytdlp"
    assert resolve_provider("https://www.youtube.com/playlist?list=PL123").name == "ytdlp"
    assert resolve_provider("https://www.reddit.com/r/pics/").name == "gallerydl"
    assert resolve_provider("https://example.com/picture.jpg").name == "direct"


def test_registry_rejects_unknown_source() -> None:
    with pytest.raises(UnsupportedSourceError):
        resolve_provider("https://example.invalid/not-a-supported-page")


def test_youtube_channel_is_reported_as_bulk_capable() -> None:
    capabilities = provider_capabilities("https://www.youtube.com/@SomeChannel/videos")
    assert capabilities.profile_bulk is True
    assert capabilities.pagination is True
    assert capabilities.images is False
    assert capabilities.requires_auth is False


def test_stable_ids_and_canonical_urls() -> None:
    assert stable_id("post", "ytdlp", "abc") == stable_id("post", "ytdlp", "abc")
    assert stable_id("post", "ytdlp", "abc") != stable_id("post", "ytdlp", "abd")
    assert (
        canonical_media_url("HTTPS://Example.COM:443/a.jpg?x=1#frag")
        == "https://example.com/a.jpg?x=1"
    )


class _FakeExtractor:
    category = "fake"
    subcategory = "user"

    def __init__(self, items: list[tuple[str, str, dict]]) -> None:
        self._items = items

    def items(self):
        yield from self._items


def test_gallerydl_groups_attachments_into_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        (Message.Directory, "", {"post_id": "p1", "author": "alice", "title": "First"}),
        (Message.Url, "https://cdn.example.com/a.jpg", {"post_id": "p1", "id": "a"}),
        (Message.Url, "https://cdn.example.com/b.jpg", {"post_id": "p1", "id": "b"}),
        (Message.Directory, "", {"post_id": "p2", "author": "alice", "title": "Second"}),
        (Message.Url, "https://cdn.example.com/c.mp4", {"post_id": "p2", "id": "c"}),
    ]

    def fake_prepare(self, url: str):
        return _FakeExtractor(items)

    monkeypatch.setattr(GalleryDlProvider, "_prepare_extractor", fake_prepare)
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    provider = GalleryDlProvider()
    posts = list(
        provider.iter_posts(
            "https://fake.example/alice",
            ScanOptions(),
            threading.Event(),
        )
    )

    assert len(posts) == 2
    assert len(posts[0].media_items) == 2
    assert posts[0].media_items[0].media_type == MediaType.IMAGE
    assert posts[0].post_type.value == "album"
    assert posts[1].media_items[0].media_type == MediaType.VIDEO


def test_gallerydl_respects_media_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        (
            Message.Url,
            f"https://cdn.example.com/{index}.jpg",
            {"post_id": str(index), "id": str(index)},
        )
        for index in range(10)
    ]
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FakeExtractor(items)
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/alice",
            ScanOptions(max_media=3),
            threading.Event(),
        )
    )
    assert len(posts) == 3


def test_youtube_collection_detection_is_offline() -> None:
    provider = YtDlpProvider()
    assert provider.capabilities_for("https://www.youtube.com/@SomeChannel/videos").profile_bulk
    assert not provider.capabilities_for(
        "https://www.youtube.com/watch?v=abcdefghijk"
    ).profile_bulk


def test_direct_provider_assigns_stable_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://cdn.example.com/cat.jpg"
    classified = ClassifiedUrl(
        raw_url=url,
        normalized_url=url,
        category=UrlCategory.DIRECT_IMAGE,
        platform="direct",
        domain="cdn.example.com",
        is_supported=True,
    )
    legacy_item = MediaItem(
        id="legacy-random-id",
        source_url=url,
        original_url=url,
        media_type=MediaType.IMAGE,
        available_formats=[MediaFormatInfo(format_id="direct", url=url)],
    )
    monkeypatch.setattr(
        direct_module, "classify_direct_url", lambda _url: (classified, legacy_item)
    )

    posts = list(
        DirectProvider().iter_posts(url, ScanOptions(), threading.Event())
    )
    item = posts[0].media_items[0]
    assert item.id == media_identity("direct", url, url)
    assert item.id != "legacy-random-id"


class _QueueExtractor:
    category = "fake"
    subcategory = "user"

    def items(self):
        yield Message.Queue, "https://fake.example/board/one", {}


class _BoardExtractor:
    category = "fake"
    subcategory = "board"

    def items(self):
        yield Message.Directory, "", {"post_id": "p1", "author": "alice"}
        yield Message.Url, "https://cdn.example.com/a.jpg", {"post_id": "p1", "id": "a"}


class _EmptyExtractor:
    category = "instagram"
    subcategory = "user"

    def items(self):
        return iter(())


def test_gallerydl_expands_nested_queues(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []

    def fake_prepare(self, url: str):
        return _BoardExtractor() if "/board/" in url else _QueueExtractor()

    monkeypatch.setattr(GalleryDlProvider, "_prepare_extractor", fake_prepare)
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/alice",
            ScanOptions(),
            threading.Event(),
            on_warning=warnings.append,
        )
    )

    assert len(posts) == 1
    assert posts[0].media_items[0].original_url == "https://cdn.example.com/a.jpg"
    assert not any("Skipped nested queue" in warning for warning in warnings)


def test_gallerydl_empty_auth_site_explains_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _EmptyExtractor()
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    with pytest.raises(PrivateMediaError) as exc_info:
        list(
            GalleryDlProvider().iter_posts(
                "https://www.instagram.com/instagram/",
                ScanOptions(),
                threading.Event(),
            )
        )

    error = exc_info.value
    assert error.details.get("requires_cookies") is True
    assert "Settings" in error.message and "cookie" in error.message.lower()
    assert "Settings" in str(error) and "cookie" in str(error).lower()


class _NotFoundExtractor:
    category = "instagram"
    subcategory = "user"

    def items(self):
        raise NotFoundError("user")


def test_gallerydl_auth_site_failure_explains_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gallery_dl.exception import NotFoundError as GalleryNotFoundError

    def boom(self):
        raise GalleryNotFoundError("user")

    monkeypatch.setattr(_NotFoundExtractor, "items", boom)
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _NotFoundExtractor()
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    with pytest.raises(MediaUnavailableError) as exc_info:
        list(
            GalleryDlProvider().iter_posts(
                "https://www.instagram.com/instagram/",
                ScanOptions(),
                threading.Event(),
            )
        )

    error = exc_info.value
    assert error.details.get("requires_cookies") is True
    assert error.details.get("remediation") == "add_cookies"
    assert "cookie" in str(error).lower()
