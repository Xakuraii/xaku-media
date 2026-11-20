"""Provider registry, stable identity, and gallery grouping tests (no network)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

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
from xakumedia.providers import ytdlp as ytdlp_module
from xakumedia.providers.base import media_identity
from xakumedia.providers.direct import DirectProvider
from xakumedia.providers.gallerydl import GalleryDlProvider
from xakumedia.providers.registry import provider_capabilities, resolve_provider
from xakumedia.providers.ytdlp import (
    YtDlpProvider,
    collection_urls,
    normalize_tiktok_photo_url,
)
from xakumedia.utils.stable_ids import canonical_media_url, stable_id


def test_registry_routes_known_sources() -> None:
    assert resolve_provider("https://www.youtube.com/@SomeChannel/videos").name == "ytdlp"
    assert resolve_provider("https://www.youtube.com/playlist?list=PL123").name == "ytdlp"
    assert resolve_provider("https://www.reddit.com/r/pics/").name == "gallerydl"
    assert resolve_provider("https://example.com/picture.jpg").name == "direct"


def test_registry_routes_tiktok_to_ytdlp() -> None:
    """TikTok needs yt-dlp's Chrome impersonation; gallery-dl gets a JS challenge."""
    provider = resolve_provider("https://www.tiktok.com/@someuser")
    assert provider.name == "ytdlp"
    assert provider.capabilities_for("https://www.tiktok.com/@someuser").profile_bulk
    assert resolve_provider("https://www.tiktok.com/@someuser/video/123").name == "ytdlp"


def test_tiktok_profile_is_bulk_and_single_video_is_not() -> None:
    provider = YtDlpProvider()
    profile_caps = provider.capabilities_for("https://www.tiktok.com/@someuser")
    assert profile_caps.source_type == "channel"
    assert profile_caps.videos is True
    assert profile_caps.pagination is True
    video_caps = provider.capabilities_for("https://www.tiktok.com/@someuser/video/123")
    assert video_caps.source_type == "video"
    assert video_caps.profile_bulk is False
    assert provider.classify("https://www.tiktok.com/@someuser").platform == "tiktok"


def test_tiktok_auth_opts_enable_chrome_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = YtDlpProvider()
    sentinel = object()
    monkeypatch.setattr(ytdlp_module, "tiktok_impersonation_target", lambda: sentinel)
    opts: dict[str, object] = {}
    provider._apply_auth("https://www.tiktok.com/@someuser", opts)
    assert opts.get("impersonate") is sentinel

    opts = {}
    provider._apply_auth("https://www.youtube.com/watch?v=abcdefghijk", opts)
    assert "impersonate" not in opts


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


def test_gallerydl_uses_display_url_for_video_thumbnails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [
        (Message.Directory, "", {"post_id": "p1", "username": "alice"}),
        (
            Message.Url,
            "https://cdn.example.com/reel.mp4",
            {
                "post_id": "p1",
                "id": "v1",
                "type": "post",
                "extension": "mp4",
                "display_url": "https://cdn.example.com/reel-poster.jpg",
            },
        ),
    ]
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FakeExtractor(items)
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/alice",
            ScanOptions(),
            threading.Event(),
        )
    )
    assert posts[0].media_items[0].thumbnail_url == (
        "https://cdn.example.com/reel-poster.jpg"
    )


class _TwitterPreviewExtractor:
    category = "twitter"
    subcategory = "user"

    def items(self):
        yield Message.Directory, "", {"post_id": "p1", "username": "alice"}
        yield (
            Message.Url,
            "https://cdn.example.com/clip.mp4",
            {"post_id": "p1", "id": "v1", "type": "video", "extension": "mp4"},
        )
        yield (
            Message.Url,
            "https://cdn.example.com/clip-poster.jpg",
            {"post_id": "p1", "id": "v1", "type": "preview", "extension": "jpg"},
        )


def test_gallerydl_twitter_preview_becomes_video_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _TwitterPreviewExtractor()
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/alice",
            ScanOptions(),
            threading.Event(),
        )
    )
    assert len(posts) == 1
    assert len(posts[0].media_items) == 1
    assert posts[0].media_items[0].thumbnail_url == (
        "https://cdn.example.com/clip-poster.jpg"
    )


class _FacebookExtractor:
    category = "facebook"
    subcategory = "reel"

    def items(self):
        yield Message.Directory, "", {"post_id": "r1", "author": "alice"}
        yield (
            Message.Url,
            "https://cdn.example.com/reel.mp4",
            {"post_id": "r1", "id": "r1", "extension": "mp4"},
        )


def test_gallerydl_enriches_facebook_video_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FacebookExtractor()
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)
    monkeypatch.setattr(
        ytdlp_module.YtDlpProvider,
        "fetch_thumbnail",
        lambda self, url: "https://cdn.example.com/reel-poster.jpg",
    )

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://www.facebook.com/reel/123",
            ScanOptions(),
            threading.Event(),
        )
    )
    assert len(posts) == 1
    assert posts[0].media_items[0].thumbnail_url == (
        "https://cdn.example.com/reel-poster.jpg"
    )


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


def test_channel_root_enumerates_videos_shorts_and_streams() -> None:
    """A channel root must scan every upload tab, not only /videos."""
    assert collection_urls("https://www.youtube.com/@SomeChannel") == [
        "https://www.youtube.com/@SomeChannel/videos",
        "https://www.youtube.com/@SomeChannel/shorts",
        "https://www.youtube.com/@SomeChannel/streams",
    ]
    assert collection_urls("https://www.youtube.com/@SomeChannel/") == [
        "https://www.youtube.com/@SomeChannel/videos",
        "https://www.youtube.com/@SomeChannel/shorts",
        "https://www.youtube.com/@SomeChannel/streams",
    ]


def test_explicit_channel_tab_and_playlist_are_not_expanded() -> None:
    """Explicit tab/playlist URLs are scanned exactly as requested."""
    assert collection_urls("https://www.youtube.com/@SomeChannel/shorts") == [
        "https://www.youtube.com/@SomeChannel/shorts"
    ]
    playlist = "https://www.youtube.com/playlist?list=PL123"
    assert collection_urls(playlist) == [playlist]


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


def test_gallerydl_pairs_separate_audio_with_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facebook-style DASH entries become one video plus an audio format."""
    items = [
        (Message.Directory, "", {"post_id": "p1", "user": "Facebook"}),
        (
            Message.Url,
            "https://cdn.example.com/reel.mp4",
            {"post_id": "p1", "id": "v1", "type": "video", "extension": "mp4"},
        ),
        (
            Message.Url,
            "https://cdn.example.com/reel.m4a",
            {"post_id": "p1", "id": "v1", "type": "audio", "extension": "m4a"},
        ),
    ]
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FakeExtractor(items)
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/reel/1",
            ScanOptions(),
            threading.Event(),
        )
    )

    assert len(posts) == 1
    assert len(posts[0].media_items) == 1
    item = posts[0].media_items[0]
    assert item.media_type == MediaType.VIDEO
    formats = {fmt.format_id: fmt for fmt in item.available_formats}
    assert formats["original"].url == "https://cdn.example.com/reel.mp4"
    assert formats["original"].video_codec == "h264"
    assert formats["original"].audio_codec is None
    assert formats["audio"].url == "https://cdn.example.com/reel.m4a"
    assert formats["audio"].audio_codec == "aac"
    assert formats["audio"].video_codec is None


def test_facebook_video_ids_dedupe_across_tabs() -> None:
    videos = '"__typename":"Video","id":"111"'
    reels = '"video_id":"222"'
    escaped = '\\"__typename\\":\\"Video\\",\\"id\\":\\"333\\"'

    assert gallery_module._facebook_video_ids(
        [videos + reels, reels + escaped, videos]
    ) == ["111", "222", "333"]


def test_facebook_profile_base_only_targets_profile_roots() -> None:
    assert (
        gallery_module._facebook_profile_base("https://www.facebook.com/zerm.mer")
        == "https://www.facebook.com/zerm.mer"
    )
    assert (
        gallery_module._facebook_profile_base(
            "https://www.facebook.com/profile.php?id=100035424692970"
        )
        == "https://www.facebook.com/100035424692970"
    )
    assert (
        gallery_module._facebook_profile_base("https://www.facebook.com/zerm.mer/photos")
        is None
    )
    assert (
        gallery_module._facebook_profile_base("https://www.facebook.com/reel/123")
        is None
    )
    assert (
        gallery_module._facebook_profile_base("https://www.instagram.com/nasa/")
        is None
    )


def test_facebook_video_pages_warms_session_and_reads_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []
    pages = {
        "https://www.facebook.com/alice/videos": '"__typename":"Video","id":"111"',
        "https://www.facebook.com/alice/reels": '"video_id":"222"',
    }

    class _SessionExtractor:
        def request(self, url: str, fatal: bool = True):
            requested.append(f"{url}|{fatal}")
            return SimpleNamespace(status_code=200, text=pages.get(url, ""))

    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _SessionExtractor()
    )

    found = GalleryDlProvider()._facebook_video_pages(
        "https://www.facebook.com/alice", threading.Event(), lambda _message: None
    )

    assert requested == [
        "https://www.facebook.com/alice/photos_by|False",
        "https://www.facebook.com/alice/videos|False",
        "https://www.facebook.com/alice/reels|False",
    ]
    assert found == [
        pages["https://www.facebook.com/alice/videos"],
        pages["https://www.facebook.com/alice/reels"],
    ]


def test_gallerydl_facebook_profile_scans_videos_before_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile root must include reels even though gallery-dl lists photos only."""
    profile_url = "https://www.facebook.com/alice"

    class _PhotoUser:
        category = "facebook"
        subcategory = "user"

        def items(self):
            yield Message.Directory, "", {"post_id": "photo1", "username": "alice"}
            yield Message.Url, "https://cdn.example.com/photo1.jpg", {
                "post_id": "photo1",
                "id": "photo1",
                "extension": "jpg",
            }

    class _ReelVideo:
        category = "facebook"
        subcategory = "video"

        def items(self):
            yield Message.Directory, "", {"post_id": "video1", "username": "alice"}
            yield Message.Url, "https://cdn.example.com/video1.mp4", {
                "post_id": "video1",
                "id": "video1",
                "type": "video",
                "extension": "mp4",
            }
            yield Message.Url, "https://cdn.example.com/video1.m4a", {
                "post_id": "video1",
                "id": "video1",
                "type": "audio",
                "extension": "m4a",
            }

    monkeypatch.setattr(
        GalleryDlProvider,
        "_prepare_extractor",
        lambda self, url: _ReelVideo() if "/reel/" in url else _PhotoUser(),
    )
    monkeypatch.setattr(
        GalleryDlProvider,
        "_facebook_video_pages",
        lambda self, profile, cancel, warn: ['{"__typename":"Video","id":"123"}'],
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            profile_url,
            ScanOptions(include_images=True, include_videos=True),
            threading.Event(),
        )
    )

    assert [post.media_items[0].media_type for post in posts] == [
        MediaType.VIDEO,
        MediaType.IMAGE,
    ]
    video = posts[0].media_items[0]
    assert {fmt.format_id for fmt in video.available_formats} == {"original", "audio"}
    assert video.metadata_extra["extractor"] == "facebook"


def test_gallerydl_media_cap_keeps_video_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cap that lands on a video must still attach its following audio entry."""
    items = [
        (Message.Directory, "", {"post_id": "p1", "username": "alice"}),
        (
            Message.Url,
            "https://cdn.example.com/reel.mp4",
            {"post_id": "p1", "id": "v1", "type": "video", "extension": "mp4"},
        ),
        (
            Message.Url,
            "https://cdn.example.com/reel.m4a",
            {"post_id": "p1", "id": "v1", "type": "audio", "extension": "m4a"},
        ),
        (
            Message.Url,
            "https://cdn.example.com/ignored.jpg",
            {"post_id": "p1", "id": "ignored", "extension": "jpg"},
        ),
    ]
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FakeExtractor(items)
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/post/1",
            ScanOptions(max_media=1),
            threading.Event(),
        )
    )

    assert len(posts) == 1
    assert len(posts[0].media_items) == 1
    formats = {fmt.format_id: fmt for fmt in posts[0].media_items[0].available_formats}
    assert formats["audio"].url == "https://cdn.example.com/reel.m4a"


def test_gallerydl_keeps_every_file_with_repeated_post_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slideshow/carousel files share a post id but must stay separate items."""
    author = {"id": 7015676321389511706, "uniqueId": "hxung_d_xakuraii"}
    items = [
        (
            Message.Url,
            "https://cdn.example.com/slide-1.jpg",
            {"post_id": "p1", "id": "video1", "num": 1, "author": author},
        ),
        (
            Message.Url,
            "https://cdn.example.com/slide-2.jpg",
            {"post_id": "p1", "id": "video1", "num": 2, "author": author},
        ),
    ]
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FakeExtractor(items)
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/post/1",
            ScanOptions(),
            threading.Event(),
        )
    )

    assert len(posts) == 1
    assert len(posts[0].media_items) == 2
    assert {item.provider_media_id for item in posts[0].media_items} == {
        "video1:1",
        "video1:2",
    }
    assert {item.author for item in posts[0].media_items} == {"hxung_d_xakuraii"}
    assert posts[0].author == "hxung_d_xakuraii"


def test_gallerydl_prefers_direct_dash_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ytdl: pseudo URL is replaced with gallery-dl's progressive fallback."""
    items = [
        (
            Message.Url,
            "ytdl:https://fake.example/post/1.mp4",
            {
                "post_id": "p1",
                "id": "v1",
                "extension": "mp4",
                "_fallback": ("https://cdn.example.com/progressive.mp4",),
            },
        )
    ]
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _FakeExtractor(items)
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)

    posts = list(
        GalleryDlProvider().iter_posts(
            "https://fake.example/post/1",
            ScanOptions(),
            threading.Event(),
        )
    )

    item = posts[0].media_items[0]
    assert item.original_url == "https://cdn.example.com/progressive.mp4"
    assert item.available_formats[0].url == "https://cdn.example.com/progressive.mp4"


def test_x_profile_queue_uses_media_tab() -> None:
    assert (
        gallery_module._prefer_media_queue("https://x.com/elonmusk/tweets")
        == "https://x.com/elonmusk/media"
    )
    assert (
        gallery_module._prefer_media_queue("https://twitter.com/nasa/tweets/")
        == "https://twitter.com/nasa/media"
    )
    assert (
        gallery_module._prefer_media_queue("https://x.com/elonmusk/with_replies")
        == "https://x.com/elonmusk/with_replies"
    )


def test_tiktok_audio_only_post_is_never_published_as_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A photo post without available slides must not surface its MP3 track."""
    provider = YtDlpProvider()
    monkeypatch.setattr(provider, "_tiktok_image_post", lambda *args, **kwargs: None)
    info = {
        "id": "123",
        "webpage_url": "https://www.tiktok.com/@fake/video/123",
        "formats": [
            {
                "format_id": "audio",
                "ext": "mp3",
                "vcodec": "none",
                "acodec": "mp3",
                "url": "https://cdn.example.com/slideshow.mp3",
            }
        ],
    }

    post = provider._post_from_info(
        info, "https://www.tiktok.com/@fake/video/123"
    )

    assert post is None


def test_tiktok_photo_url_is_rewritten_to_video_path() -> None:
    """TikTok's own extractor only matches /video/, but share sheets emit /photo/."""
    assert (
        normalize_tiktok_photo_url(
            "https://www.tiktok.com/@user/photo/7634207163103071508?is_from_webapp=1"
        )
        == "https://www.tiktok.com/@user/video/7634207163103071508?is_from_webapp=1"
    )
    assert (
        normalize_tiktok_photo_url("https://www.tiktok.com/@user/video/123")
        == "https://www.tiktok.com/@user/video/123"
    )
    assert (
        normalize_tiktok_photo_url("https://www.tiktok.com/@user")
        == "https://www.tiktok.com/@user"
    )
    assert (
        normalize_tiktok_photo_url("https://example.com/@user/photo/123")
        == "https://example.com/@user/photo/123"
    )


def test_tiktok_slideshow_items_build_one_image_per_slide() -> None:
    data = {
        "imagePost": {
            "images": [
                {
                    "imageURL": {"urlList": ["https://cdn.example.com/a.jpeg?x=1"]},
                    "imageWidth": 1080,
                    "imageHeight": 1920,
                },
                {
                    "imageURL": {"urlList": ["https://cdn.example.com/b.jpeg"]},
                    "imageWidth": 1440,
                    "imageHeight": 1920,
                },
                {
                    "imageURL": {"urlList": []},
                    "displayImage": {"urlList": ["https://cdn.example.com/c.jpeg"]},
                },
            ]
        }
    }

    items = YtDlpProvider._tiktok_slideshow_items(
        data,
        author="creator",
        title="slides",
        video_id="123",
        page_url="https://www.tiktok.com/@creator/video/123",
    )

    assert len(items) == 3
    assert [item.provider_media_id for item in items] == ["123:0", "123:1", "123:2"]
    assert all(item.media_type == MediaType.IMAGE for item in items)
    assert items[0].width == 1080 and items[0].height == 1920
    assert items[0].metadata_extra["slideshow"] is True
    assert items[2].original_url == "https://cdn.example.com/c.jpeg"


def test_tiktok_image_post_uses_embedded_slide_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The impersonated yt-dlp session replaces the 403-prone gallery-dl path."""
    provider = YtDlpProvider()
    monkeypatch.setattr(
        provider,
        "_tiktok_web_data",
        lambda *args, **kwargs: {
            "desc": "caption",
            "author": {"uniqueId": "creator"},
            "imagePost": {
                "images": [
                    {"imageURL": {"urlList": ["https://cdn.example.com/a.jpeg"]}},
                    {"imageURL": {"urlList": ["https://cdn.example.com/b.jpeg"]}},
                ]
            },
        },
    )
    monkeypatch.setattr(
        provider,
        "_tiktok_gallery_image_post",
        lambda *args, **kwargs: pytest.fail("gallery-dl fallback should not run"),
    )
    url = "https://www.tiktok.com/@creator/video/123"

    post = provider._tiktok_image_post(url, url, {}, None)

    assert post is not None
    assert post.provider_post_id == "123"
    assert post.author == "creator"
    assert post.title == "caption"
    assert len(post.media_items) == 2
    assert post.metadata_extra["media_provider"] == "ytdlp"
    assert all(item.post_id == post.id for item in post.media_items)


def test_gallerydl_auth_sites_use_chrome_user_agent_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth-heavy extractors need gallery-dl's "+chrome" preset, not a literal UA."""
    from xakumedia.db import default_repository

    configured: list[tuple[tuple[str, ...], str, object]] = []
    extractor = SimpleNamespace(
        category="instagram",
        subcategory="",
        initialize=lambda: None,
        log=SimpleNamespace(exception=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(gallery_module, "_find_extractor", lambda url: extractor)
    monkeypatch.setattr(
        default_repository, "get_cookie_profile_for_domain", lambda url: None
    )
    monkeypatch.setattr(
        gallery_module.gdl_config,
        "set",
        lambda keys, key, value: configured.append((keys, key, value)),
    )

    GalleryDlProvider()._prepare_extractor("https://www.instagram.com/nasa/")

    assert (("extractor", "instagram"), "user-agent", "+chrome") in configured
    assert (("extractor", "instagram"), "videos", "merged") in configured


def test_gallerydl_empty_auth_site_explains_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xakumedia.db import default_repository

    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _EmptyExtractor()
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)
    monkeypatch.setattr(default_repository, "get_cookie_profile_for_domain", lambda url: None)

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

    from xakumedia.db import default_repository

    def boom(self):
        raise GalleryNotFoundError("user")

    monkeypatch.setattr(_NotFoundExtractor, "items", boom)
    monkeypatch.setattr(
        GalleryDlProvider, "_prepare_extractor", lambda self, url: _NotFoundExtractor()
    )
    monkeypatch.setattr(gallery_module, "validate_url_security", lambda url: url)
    monkeypatch.setattr(default_repository, "get_cookie_profile_for_domain", lambda url: None)

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
