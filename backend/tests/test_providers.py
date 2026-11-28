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


def test_strip_stale_waf_cookies_removes_ephemeral_waf_tokens() -> None:
    import http.cookiejar

    from xakumedia.extractors.video import strip_stale_waf_cookies

    jar = http.cookiejar.CookieJar()
    for name, domain in [
        ("_waftokenid", "www.tiktok.com"),
        ("sessionid", ".tiktok.com"),
        ("ttwid", ".tiktok.com"),
    ]:
        jar.set_cookie(
            http.cookiejar.Cookie(
                version=0,
                name=name,
                value="val",
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path="/",
                path_specified=True,
                secure=True,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={},
            )
        )

    class _FakeYdl:
        cookiejar = jar

    strip_stale_waf_cookies(_FakeYdl(), "https://www.tiktok.com/@user")
    remaining = {c.name for c in jar}
    assert remaining == {"sessionid", "ttwid"}


def test_ytdlp_tiktok_waf_fallback_extracts_secuid_and_flags_private() -> None:
    import http.cookiejar

    class _FakeTikTokUserIE:
        def __init__(self, payload_sequence: list[dict | None]) -> None:
            self._calls = 0
            self._payloads = payload_sequence
            self.cookiejar = http.cookiejar.CookieJar()
            self.solved = False

        def _generate_blockbuster_headers(self) -> dict[str, str]:
            return {"User-Agent": "Mozilla/5.0"}

        def _download_webpage(self, url: str, user_id: str, **kwargs: object) -> str:
            idx = min(self._calls, len(self._payloads) - 1)
            self._calls += 1
            return f"page-{idx}"

        def _get_universal_data(self, webpage: str, user_id: str) -> dict | None:
            idx = int(webpage.split("-")[-1])
            return self._payloads[idx]

        def _solve_challenge_and_set_cookies(self, webpage: str) -> tuple[str, ...]:
            self.solved = True
            return ("_wafchallengeid",)

    class _FakeYdl:
        def __init__(self, ie: _FakeTikTokUserIE) -> None:
            self._ie = ie
            self.extracted: list[str] = []

        def get_info_extractor(self, name: str) -> _FakeTikTokUserIE:
            return self._ie

        def extract_info(self, target: str, download: bool = False) -> dict[str, object]:
            self.extracted.append(target)
            return {"entries": [{"id": "7708817426581818630"}]}

    ie = _FakeTikTokUserIE(
        [
            None,
            {
                "webapp.user-detail": {
                    "userInfo": {
                        "user": {"secUid": "MS4wLjABAAAA_TEST", "privateAccount": False},
                        "stats": {"videoCount": 5},
                    }
                }
            },
        ]
    )
    ydl = _FakeYdl(ie)
    result = YtDlpProvider()._resolve_tiktok_profile_via_waf(
        ydl,  # type: ignore[arg-type]
        "https://www.tiktok.com/@dorybbi",
    )
    assert ie.solved is True
    assert ydl.extracted == ["tiktokuser:MS4wLjABAAAA_TEST"]
    assert result == {"entries": [{"id": "7708817426581818630"}]}

    private_ie = _FakeTikTokUserIE(
        [
            {
                "webapp.user-detail": {
                    "userInfo": {"user": {"privateAccount": True}, "stats": {"videoCount": 1}}
                }
            }
        ]
    )
    with pytest.raises(PrivateMediaError):
        YtDlpProvider()._resolve_tiktok_profile_via_waf(
            _FakeYdl(private_ie),  # type: ignore[arg-type]
            "https://www.tiktok.com/@privateuser",
        )


def test_registry_routes_focus_platforms_and_other() -> None:
    from xakumedia.providers import (
        FacebookProvider,
        InstagramProvider,
        OtherGalleryProvider,
        OtherProvider,
        OtherVideoProvider,
        TikTokProvider,
        XProvider,
        YouTubeProvider,
    )

    assert isinstance(resolve_provider("https://www.tiktok.com/@user"), TikTokProvider)
    assert isinstance(resolve_provider("https://vm.tiktok.com/ZM123/"), TikTokProvider)
    assert isinstance(resolve_provider("https://www.youtube.com/@SomeChannel"), YouTubeProvider)
    assert isinstance(resolve_provider("https://youtu.be/jNQXAC9IVRw"), YouTubeProvider)
    assert isinstance(resolve_provider("https://x.com/NASA"), XProvider)
    assert isinstance(resolve_provider("https://twitter.com/NASA"), XProvider)
    assert isinstance(resolve_provider("https://www.facebook.com/NASA"), FacebookProvider)
    assert isinstance(resolve_provider("https://fb.watch/abc123/"), FacebookProvider)
    assert isinstance(resolve_provider("https://www.instagram.com/nasa/"), InstagramProvider)
    assert isinstance(resolve_provider("https://instagr.am/p/abc123/"), InstagramProvider)

    vimeo = resolve_provider("https://vimeo.com/123456")
    assert isinstance(vimeo, OtherProvider)
    assert isinstance(vimeo, OtherVideoProvider)
    assert vimeo.name == "ytdlp"

    reddit = resolve_provider("https://www.reddit.com/r/pics/")
    assert isinstance(reddit, OtherProvider)
    assert isinstance(reddit, OtherGalleryProvider)
    assert reddit.name == "gallerydl"


def test_youtube_provider_injects_js_runtime_and_retries_without_stale_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yt_dlp.utils import ExtractorError

    from xakumedia.providers.platforms import youtube as yt_module

    monkeypatch.setattr(
        yt_module.shutil,
        "which",
        lambda exe: f"/bin/{exe}" if exe == "node" else None,
    )
    provider = yt_module.YouTubeProvider()
    opts = provider._base_opts()
    assert opts["js_runtimes"] == {"node": {"path": "/bin/node"}}

    calls: list[str | None] = []

    class _FakeYdl:
        def __init__(self, ydl_opts: dict) -> None:
            self._cookie = ydl_opts.get("cookiefile")

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def extract_info(self, url: str, download: bool = False):
            calls.append(self._cookie)
            if self._cookie:
                raise ExtractorError("Requested format is not available")
            return {"id": "jNQXAC9IVRw", "formats": [{"format_id": "18"}]}

    monkeypatch.setattr(yt_module.yt_dlp, "YoutubeDL", _FakeYdl)
    info = provider._extract_single_info(
        {"cookiefile": "stale_yt_cookies.txt"},
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    )
    assert calls == ["stale_yt_cookies.txt", None]
    assert info["id"] == "jNQXAC9IVRw"


def test_focus_platform_cookie_aliases_and_timestamp_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xakumedia.providers import (
        FacebookProvider,
        InstagramProvider,
        XProvider,
        YouTubeProvider,
    )
    from xakumedia.providers import base as base_module
    from xakumedia.providers.base import extract_published_timestamp, lookup_cookie_profile

    assert "https://x.com/" in XProvider()._cookie_candidate_urls("https://twitter.com/NASA")
    assert "https://www.facebook.com/" in FacebookProvider()._cookie_candidate_urls("https://fb.watch/x/")
    assert "https://www.instagram.com/" in InstagramProvider()._cookie_candidate_urls("https://instagr.am/p/x/")
    assert "https://www.youtube.com/" in YouTubeProvider()._cookie_candidate_urls("https://youtu.be/abc")

    seen: list[str] = []

    class _FakeRepo:
        def get_cookie_profile_for_domain(self, url: str):
            seen.append(url)
            if url == "https://x.com/":
                return SimpleNamespace(cookie_file_path="x_cookies.txt")
            return None

    from xakumedia import db as db_pkg

    monkeypatch.setattr(db_pkg, "default_repository", _FakeRepo())
    profile = lookup_cookie_profile(XProvider()._cookie_candidate_urls("https://twitter.com/NASA"))
    assert profile is not None
    assert profile.cookie_file_path == "x_cookies.txt"
    assert seen == ["https://twitter.com/NASA", "https://x.com/"]
    del base_module

    assert extract_published_timestamp({"timestamp": 1700000000}) == 1700000000.0
    assert extract_published_timestamp({"createTime": 1700000000000}) == 1700000000.0
    assert extract_published_timestamp({"upload_date": "20050424"}) == 1114300800.0
    assert extract_published_timestamp({"date": "2024-01-01T00:00:00Z"}) == 1704067200.0


def test_facebook_url_parsing_and_dash_mpd_formats() -> None:
    from xakumedia.providers.platforms.facebook import (
        FacebookProvider,
        _parse_facebook_url,
        parse_facebook_dash_mpd,
    )

    t_reels = _parse_facebook_url(
        "https://www.facebook.com/profile.php?id=61580886670213&sk=reels_tab"
    )
    assert t_reels.scope == "reels"
    assert t_reels.profile_base == "https://www.facebook.com/61580886670213"

    t_photos = _parse_facebook_url(
        "https://www.facebook.com/profile.php?id=61580886670213&sk=photos"
    )
    assert t_photos.scope == "photos"
    assert t_photos.canonical_gallery_url == "https://www.facebook.com/61580886670213/photos"

    t_tab = _parse_facebook_url("https://www.facebook.com/NASA/videos")
    assert t_tab.scope == "videos"
    assert FacebookProvider().classify("https://www.facebook.com/NASA/reels").is_supported

    mpd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MPD mediaPresentationDuration="PT12.5S">\n'
        '  <Period id="0">\n'
        '    <AdaptationSet contentType="video">\n'
        '      <Representation id="v1" codecs="av01.0.08M" width="720" '
        'height="1280" FBQualityLabel="720p" bandwidth="1200000">\n'
        "        <BaseURL>https://video.fbcdn.net/av1-720.mp4?a=1&amp;b=2</BaseURL>\n"
        "      </Representation>\n"
        '      <Representation id="v2" codecs="avc1.64001f" width="720" '
        'height="1280" FBQualityLabel="720p" bandwidth="1500000">\n'
        "        <BaseURL>https://video.fbcdn.net/h264-720.mp4?a=1&amp;b=2</BaseURL>\n"
        "      </Representation>\n"
        '      <Representation id="v3" codecs="vp09.00.21.08" width="360" '
        'height="640" FBQualityLabel="360p" bandwidth="500000">\n'
        "        <BaseURL>https://video.fbcdn.net/vp9-360.mp4</BaseURL>\n"
        "      </Representation>\n"
        "    </AdaptationSet>\n"
        '    <AdaptationSet contentType="audio">\n'
        '      <Representation id="a1" codecs="mp4a.40.5" bandwidth="64000">\n'
        "        <BaseURL>https://video.fbcdn.net/audio.m4a</BaseURL>\n"
        "      </Representation>\n"
        "    </AdaptationSet>\n"
        "  </Period>\n"
        "</MPD>"
    )
    formats, duration = parse_facebook_dash_mpd(mpd)
    assert duration == 12.5
    assert [f.format_id for f in formats] == ["720p-h264", "720p-av1", "360p-vp9", "audio"]
    assert all(f.requires_merge for f in formats[:-1])
    assert not formats[-1].requires_merge
    assert formats[0].url == "https://video.fbcdn.net/h264-720.mp4?a=1&b=2"
    assert formats[-1].audio_codec == "aac"


def test_facebook_provider_paginates_all_reels_via_graphql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from xakumedia.providers.platforms.facebook import FacebookProvider

    html_page = (
        '"DTSGInitialData",[],{"token":"dtsg-tok"}'
        '"LSD",[],{"token":"lsd-tok"}'
        '"aggregated_fb_shorts":{"edges":[],"page_info":'
        '{"end_cursor":"c1","has_next_page":true}},"id":"COL123"'
    )
    mpd_1 = (
        '<?xml version="1.0"?><MPD mediaPresentationDuration="PT5S"><Period>'
        '<AdaptationSet contentType="video">'
        '<Representation codecs="avc1" width="720" height="1280" FBQualityLabel="720p">'
        "<BaseURL>https://cdn.example.com/r1.mp4</BaseURL></Representation></AdaptationSet>"
        '<AdaptationSet contentType="audio"><Representation codecs="mp4a.40.5">'
        "<BaseURL>https://cdn.example.com/r1.m4a</BaseURL></Representation></AdaptationSet>"
        "</Period></MPD>"
    )
    mpd_2 = mpd_1.replace("r1.", "r2.")

    page1 = json.dumps({
        "data": {
            "node": {
                "aggregated_fb_shorts": {
                    "edges": [{
                        "profile_reel_node": {
                            "node": {
                                "tracking": '{"publish_time":1700000001}',
                                "attachments": [{
                                    "media": {
                                        "id": "101",
                                        "permalink_url": "https://www.facebook.com/reel/101/",
                                        "first_frame_thumbnail": "https://cdn.example.com/t1.jpg",
                                        "videoDeliveryLegacyFields": {
                                            "dash_manifest_xml_string": mpd_1
                                        },
                                    }
                                }],
                            }
                        }
                    }],
                    "page_info": {"end_cursor": "cursor-2", "has_next_page": True},
                }
            }
        }
    })
    page2 = json.dumps({
        "data": {
            "node": {
                "aggregated_fb_shorts": {
                    "edges": [{
                        "profile_reel_node": {
                            "node": {
                                "tracking": '{"publish_time":1700000002}',
                                "attachments": [{
                                    "media": {
                                        "id": "102",
                                        "permalink_url": "https://www.facebook.com/reel/102/",
                                        "first_frame_thumbnail": "https://cdn.example.com/t2.jpg",
                                        "videoDeliveryLegacyFields": {
                                            "dash_manifest_xml_string": mpd_2
                                        },
                                    }
                                }],
                            }
                        }
                    }],
                    "page_info": {"end_cursor": None, "has_next_page": False},
                }
            }
        }
    })

    gql_calls: list[str | None] = []

    class _FakeExtractor:
        def request(self, url: str, method: str = "GET", fatal: bool = True, **kwargs):
            del fatal
            if "api/graphql" in url:
                variables = json.loads(kwargs["data"]["variables"])
                cursor = variables.get("cursor")
                gql_calls.append(cursor)
                body = page1 if cursor is None else page2
                return SimpleNamespace(status_code=200, text=body, url=url)
            return SimpleNamespace(status_code=200, text=html_page, url=url)

    monkeypatch.setattr(FacebookProvider, "_prepare_extractor", lambda self, url: _FakeExtractor())

    posts = list(
        FacebookProvider().iter_posts(
            "https://www.facebook.com/profile.php?id=61580886670213&sk=reels_tab",
            ScanOptions(include_videos=True, include_images=False),
            threading.Event(),
        )
    )

    assert gql_calls == [None, "cursor-2"]
    assert [p.media_items[0].provider_media_id for p in posts] == ["101", "102"]
    assert [p.media_items[0].thumbnail_url for p in posts] == [
        "https://cdn.example.com/t1.jpg",
        "https://cdn.example.com/t2.jpg",
    ]


def test_shared_dash_mpd_parses_instagram_and_facebook() -> None:
    from xakumedia.providers.dash import parse_dash_mpd
    from xakumedia.providers.platforms.facebook import parse_facebook_dash_mpd

    assert parse_facebook_dash_mpd is parse_dash_mpd

    ig_mpd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MPD mediaPresentationDuration="PT15S">\n'
        '  <Period id="0">\n'
        '    <AdaptationSet mimeType="video/mp4">\n'
        '      <Representation id="1" width="720" height="1280" '
        'codecs="vp09.00.31" bandwidth="1200000">\n'
        "        <BaseURL>https://ig.cdn/720.mp4</BaseURL>\n"
        "      </Representation>\n"
        '      <Representation id="2" width="1080" height="1920" '
        'codecs="vp09.00.40" bandwidth="1800000">\n'
        "        <BaseURL>https://ig.cdn/1080.mp4</BaseURL>\n"
        "      </Representation>\n"
        "    </AdaptationSet>\n"
        '    <AdaptationSet mimeType="audio/mp4">\n'
        '      <Representation id="3" codecs="mp4a.40.5" bandwidth="78000">\n'
        "        <BaseURL>https://ig.cdn/audio.m4a</BaseURL>\n"
        "      </Representation>\n"
        "    </AdaptationSet>\n"
        "  </Period>\n"
        "</MPD>"
    )
    formats, duration = parse_dash_mpd(ig_mpd)
    assert duration == 15.0
    assert [f.format_id for f in formats] == ["1080p-vp9", "720p-vp9", "audio"]
    assert all(f.requires_merge for f in formats[:-1])
    assert not formats[-1].requires_merge
    assert formats[0].url == "https://ig.cdn/1080.mp4"


def test_gallerydl_skips_manifest_urls_without_direct_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    items = [
        (
            Message.Url,
            "https://cdn.example.com/stream.m3u8?tag=1",
            {"post_id": "p1", "id": "v1"},
        ),
        (
            Message.Url,
            "https://cdn.example.com/stream2.m3u8?tag=1",
            {
                "post_id": "p2",
                "id": "v2",
                "_fallback": ("https://cdn.example.com/direct.mp4",),
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
            on_warning=warnings.append,
        )
    )
    assert len(posts) == 1
    assert posts[0].media_items[0].media_type == MediaType.VIDEO
    assert posts[0].media_items[0].original_url == "https://cdn.example.com/direct.mp4"
    assert any("manifest-only" in w for w in warnings)


def test_instagram_url_parsing_and_profile_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xakumedia.providers.platforms.instagram import (
        InstagramProvider,
        _parse_instagram_url,
    )

    assert _parse_instagram_url("https://www.instagram.com/alice/").scope == "profile"
    assert _parse_instagram_url("https://www.instagram.com/alice/posts/").canonical_url == (
        "https://www.instagram.com/alice/"
    )
    assert _parse_instagram_url("https://www.instagram.com/alice/reels/").scope == "reels"
    assert _parse_instagram_url("https://www.instagram.com/stories/alice/123/").scope == "stories"
    assert (
        _parse_instagram_url("https://www.instagram.com/stories/highlights/99/").scope
        == "highlight"
    )
    p_short = _parse_instagram_url("https://instagr.am/p/AbC123/")
    assert p_short.scope == "post" and p_short.shortcode == "AbC123"
    r_short = _parse_instagram_url("https://m.instagram.com/reel/XyZ99/")
    assert r_short.scope == "post" and r_short.shortcode == "XyZ99"

    ig_mpd = (
        '<MPD mediaPresentationDuration="PT8S"><Period>'
        '<AdaptationSet mimeType="video/mp4">'
        '<Representation width="1080" height="1920" codecs="vp09.00.40" bandwidth="1500000">'
        "<BaseURL>https://ig.cdn/r2_1080.mp4</BaseURL></Representation></AdaptationSet>"
        '<AdaptationSet mimeType="audio/mp4"><Representation codecs="mp4a.40.5">'
        "<BaseURL>https://ig.cdn/r2_audio.m4a</BaseURL></Representation></AdaptationSet>"
        "</Period></MPD>"
    )
    hydrated_calls: list[str] = []

    class _FakeIgApi:
        def user(self, username: str):
            return {"id": "42", "username": username}

        def user_feed(self, username: str):
            yield {
                "pk": "1",
                "code": "P_PHOTO",
                "taken_at": 1700000001,
                "user": {"username": username},
                "image_versions2": {
                    "candidates": [{"url": "https://ig.cdn/p1.jpg", "width": 1080, "height": 1080}]
                },
            }
            yield {
                "pk": "2",
                "code": "P_CAROUSEL",
                "taken_at": 1700000002,
                "user": {"username": username},
                "carousel_media": [
                    {
                        "pk": "201",
                        "image_versions2": {
                            "candidates": [
                                {"url": "https://ig.cdn/c1.jpg", "width": 1080, "height": 1350}
                            ]
                        },
                    },
                    {
                        "pk": "202",
                        "video_versions": [
                            {"url": "https://ig.cdn/c2.mp4", "width": 720, "height": 1280}
                        ],
                        "image_versions2": {
                            "candidates": [
                                {"url": "https://ig.cdn/c2.jpg", "width": 720, "height": 1280}
                            ]
                        },
                    },
                ],
            }
            # Static photo backed by music (frameRate="1/1" must stay an image)
            yield {
                "pk": "3",
                "code": "P_STATIC_MUSIC",
                "taken_at": 1700000003,
                "user": {"username": username},
                "video_dash_manifest": '<MPD><Representation frameRate="1/1"/></MPD>',
                "video_versions": [
                    {"url": "https://ig.cdn/dummy.mp4", "width": 720, "height": 720}
                ],
                "image_versions2": {
                    "candidates": [
                        {"url": "https://ig.cdn/static.jpg", "width": 1080, "height": 1080}
                    ]
                },
            }
            yield {
                "pk": "4",
                "code": "REEL_SHARED",
                "product_type": "clips",
                "taken_at": 1700000004,
                "user": {"username": username},
                "video_versions": [
                    {"url": "https://ig.cdn/r1_720.mp4", "width": 720, "height": 1280}
                ],
                "image_versions2": {
                    "candidates": [
                        {"url": "https://ig.cdn/r1.jpg", "width": 720, "height": 1280}
                    ]
                },
            }

        def user_reels(self, username: str):
            yield {"media": {"pk": "4", "code": "REEL_SHARED"}}
            yield {"media": {"pk": "5", "code": "REEL_ONLY"}}
            yield {"media": {"pk": "6", "code": "REEL_BROKEN"}}

        def media(self, code: str):
            hydrated_calls.append(code)
            if code == "REEL_BROKEN":
                raise RuntimeError("transient error")
            if code == "REEL_ONLY":
                yield {
                    "pk": "5",
                    "code": "REEL_ONLY",
                    "product_type": "clips",
                    "taken_at": 1700000005,
                    "user": {"username": "alice"},
                    "video_dash_manifest": ig_mpd,
                    "video_versions": [
                        {"url": "https://ig.cdn/r2_720.mp4", "width": 720, "height": 1280}
                    ],
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://ig.cdn/r2.jpg", "width": 720, "height": 1280}
                        ]
                    },
                }

        def highlights_tray(self, username: str):
            yield {"id": "highlight:777"}

        def reels_media(self, ids: list[str]):
            if ids == ["42"]:
                return [
                    {
                        "items": [
                            {
                                "pk": "70",
                                "taken_at": 1700000006,
                                "image_versions2": {
                                    "candidates": [
                                        {
                                            "url": "https://ig.cdn/story.jpg",
                                            "width": 1080,
                                            "height": 1920,
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ]
            return [
                {
                    "id": "highlight:777",
                    "title": "Travel",
                    "items": [
                        {
                            "pk": "80",
                            "taken_at": 1700000007,
                            "image_versions2": {
                                "candidates": [
                                    {
                                        "url": "https://ig.cdn/hl.jpg",
                                        "width": 1080,
                                        "height": 1920,
                                    }
                                ]
                            },
                        },
                        {
                            "pk": "81",
                            "product_type": "story",
                            "taken_at": 1700000008,
                            "video_duration": 15.0,
                            "video_dash_manifest": (
                                '<MPD><Representation frameRate="16384/16384"/></MPD>'
                            ),
                            "video_versions": [
                                {
                                    "type": 101,
                                    "url": "https://ig.cdn/hl_music_story.mp4",
                                }
                            ],
                            "image_versions2": {
                                "candidates": [
                                    {
                                        "url": "https://ig.cdn/hl_music_story.jpg",
                                        "width": 720,
                                        "height": 1280,
                                    }
                                ]
                            },
                        },
                    ],
                }
            ]

    monkeypatch.setattr(
        InstagramProvider,
        "_prepare_extractor",
        lambda self, url: SimpleNamespace(api=_FakeIgApi(), category="instagram"),
    )

    warnings: list[str] = []
    posts = list(
        InstagramProvider().iter_posts(
            "https://www.instagram.com/alice/posts/",
            ScanOptions(),
            threading.Event(),
            on_warning=warnings.append,
        )
    )

    # REEL_SHARED must NOT trigger api.media(), REEL_BROKEN is skipped gracefully
    assert hydrated_calls == ["REEL_ONLY", "REEL_BROKEN", "REEL_BROKEN"]
    assert any("REEL_BROKEN" in w for w in warnings)
    post_ids = [p.provider_post_id for p in posts]
    assert post_ids == ["1", "2", "3", "4", "5", "70", "80", "81"]
    # Static 1fps music feed post stays an IMAGE, while music-backed Highlight stays a VIDEO
    assert posts[2].media_items[0].media_type == MediaType.IMAGE
    assert posts[7].media_items[0].media_type == MediaType.VIDEO
    # Reels-only video exposes 1080p DASH + audio + 720p muxed preview URL
    reel_only_item = posts[4].media_items[0]
    assert reel_only_item.media_type == MediaType.VIDEO
    assert [f.format_id for f in reel_only_item.available_formats] == [
        "1080p-vp9",
        "audio",
        "720p-progressive",
    ]
    assert reel_only_item.original_url == "https://ig.cdn/r2_720.mp4"


def test_facebook_profile_scans_albums_avatar_and_order_independent_page_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from xakumedia.providers.platforms.facebook import FacebookProvider

    # Note: has_next_page appears BEFORE end_cursor to prove order independence.
    html_reels = (
        '"DTSGInitialData",[],{"token":"dtsg"}'
        '"LSD",[],{"token":"lsd"}'
        '"aggregated_fb_shorts":{"edges":[],"page_info":'
        '{"has_next_page":true,"end_cursor":null}},"id":"COL99"}'
    )
    mpd = (
        '<MPD mediaPresentationDuration="PT4S"><Period>'
        '<AdaptationSet contentType="video"><Representation codecs="avc1" width="720" '
        'height="1280" FBQualityLabel="720p">'
        "<BaseURL>https://fb.cdn/r1.mp4</BaseURL></Representation></AdaptationSet>"
        '<AdaptationSet contentType="audio"><Representation codecs="mp4a.40.5">'
        "<BaseURL>https://fb.cdn/r1.m4a</BaseURL></Representation></AdaptationSet>"
        "</Period></MPD>"
    )
    gql_page = json.dumps(
        {
            "data": {
                "node": {
                    "aggregated_fb_shorts": {
                        "edges": [
                            {
                                "profile_reel_node": {
                                    "node": {
                                        "attachments": [
                                            {
                                                "media": {
                                                    "id": "501",
                                                    "permalink_url": "https://www.facebook.com/reel/501/",
                                                    "videoDeliveryLegacyFields": {
                                                        "dash_manifest_xml_string": mpd
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False, "end_cursor": None},
                    }
                }
            }
        }
    )
    gql_attempts = 0

    class _FakeExtractor:
        category = "facebook"
        subcategory = "user"

        def request(self, url: str, method: str = "GET", fatal: bool = True, **kwargs):
            nonlocal gql_attempts
            del fatal
            if "api/graphql" in url:
                gql_attempts += 1
                if gql_attempts == 1:
                    return SimpleNamespace(status_code=500, text="", url=url)
                return SimpleNamespace(status_code=200, text=gql_page, url=url)
            if url.endswith("/reels"):
                return SimpleNamespace(status_code=200, text=html_reels, url=url)
            return SimpleNamespace(status_code=200, text="<html></html>", url=url)

    def fake_discover(self, url: str, cancel_event, warn, on_page, state, depth: int):
        if url.endswith("/photos"):
            raise MediaUnavailableError("no set_id on photos_by")
        if url.endswith("/photos_albums"):
            state.posts_emitted += 1
            state.media_count += 1
            yield SimpleNamespace(
                id="p_alb",
                provider="gallerydl",
                provider_post_id="alb1",
                source_url=url,
                post_url=url,
                author="alice",
                title="Album 1",
                post_type=MediaType.IMAGE,
                media_items=[
                    SimpleNamespace(
                        provider_media_id="img_shared",
                        original_url="https://fb.cdn/shared.jpg",
                    )
                ],
            )
        if url.endswith("/avatar"):
            # Duplicate img_shared must be deduplicated cleanly against photos_albums.
            state.posts_emitted += 1
            state.media_count += 1
            yield SimpleNamespace(
                id="p_av",
                provider="gallerydl",
                provider_post_id="av1",
                source_url=url,
                post_url=url,
                author="alice",
                title="Avatar",
                post_type=MediaType.IMAGE,
                media_items=[
                    SimpleNamespace(
                        provider_media_id="img_shared",
                        original_url="https://fb.cdn/shared.jpg",
                    )
                ],
            )

    monkeypatch.setattr(FacebookProvider, "_prepare_extractor", lambda self, url: _FakeExtractor())
    monkeypatch.setattr(GalleryDlProvider, "_discover", fake_discover)
    monkeypatch.setattr("xakumedia.providers.platforms.facebook.time.sleep", lambda _s: None)

    warnings: list[str] = []
    posts = list(
        FacebookProvider().iter_posts(
            "https://www.facebook.com/alice",
            ScanOptions(include_videos=True, include_images=True),
            threading.Event(),
            on_warning=warnings.append,
        )
    )
    assert gql_attempts == 2
    assert [p.provider_post_id for p in posts] == ["501", "alb1"]
    assert any("photos discovery ended early" in w.lower() for w in warnings)


def test_x_provider_combines_timelines_filters_authors_and_exposes_mp4_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xakumedia.providers.platforms.x import XProvider, _parse_x_url

    assert _parse_x_url("https://x.com/alice/media").scope == "profile"
    assert _parse_x_url("https://twitter.com/alice/tweets").canonical_url == "https://x.com/alice"
    st = _parse_x_url("https://x.com/alice/status/999")
    assert st.scope == "status" and st.tweet_id == "999"

    def make_tweet(tid: str, screen_name: str, *, video: bool = False, photo: bool = False):
        media = []
        if video:
            media.append(
                {
                    "id_str": f"m_{tid}_v",
                    "type": "video",
                    "media_url_https": f"https://pbs.twimg.com/{tid}_thumb.jpg",
                    "original_info": {"width": 1080, "height": 1920},
                    "video_info": {
                        "duration_millis": 5200,
                        "variants": [
                            {
                                "content_type": "application/x-mpegURL",
                                "url": "https://video.twimg.com/a.m3u8",
                            },
                            {
                                "bitrate": 632000,
                                "content_type": "video/mp4",
                                "url": "https://video.twimg.com/vid/avc1/320x568/low.mp4",
                            },
                            {
                                "bitrate": 2176000,
                                "content_type": "video/mp4",
                                "url": "https://video.twimg.com/vid/avc1/720x1280/hd.mp4",
                            },
                        ],
                    },
                }
            )
        if photo:
            media.append(
                {
                    "id_str": f"m_{tid}_p",
                    "type": "photo",
                    "media_url_https": f"https://pbs.twimg.com/media/{tid}.jpg",
                    "original_info": {"width": 1200, "height": 1600},
                }
            )
        return {
            "rest_id": tid,
            "core": {"user_results": {"result": {"core": {"screen_name": screen_name}}}},
            "legacy": {
                "id_str": tid,
                "created_at": "Wed Oct 10 20:19:24 +0000 2024",
                "full_text": f"Tweet {tid}",
                "extended_entities": {"media": media},
            },
        }

    class _FakeXApi:
        def user_by_screen_name(self, handle: str):
            return {"rest_id": "u1", "legacy": {}}

        def user_media(self, handle: str):
            yield make_tweet("101", "Alice", video=True, photo=True)

        def user_original_timeline(self, handle: str):
            # 101 is duplicate, 102 is pinned/missed photo by Alice, 103 is another user
            yield make_tweet("101", "alice", video=True)
            yield make_tweet("102", "alice", photo=True)
            yield make_tweet("103", "otheruser", photo=True)

    monkeypatch.setattr(
        XProvider,
        "_prepare_extractor",
        lambda self, url: SimpleNamespace(api=_FakeXApi(), category="twitter"),
    )

    posts = list(
        XProvider().iter_posts(
            "https://x.com/alice/media",
            ScanOptions(),
            threading.Event(),
        )
    )
    assert [p.provider_post_id for p in posts] == ["101", "102"]
    vid_item, photo_item = posts[0].media_items
    assert vid_item.media_type == MediaType.VIDEO
    assert [f.format_id for f in vid_item.available_formats] == ["720p", "320p"]
    assert all(f.container == "mp4" for f in vid_item.available_formats)
    assert photo_item.original_url == "https://pbs.twimg.com/media/101?format=jpg&name=orig"


def test_youtube_featured_url_and_cookieless_tab_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yt_dlp.utils import ExtractorError

    from xakumedia.providers.platforms import youtube as yt_module
    from xakumedia.providers.ytdlp import _EntryHydrator, is_collection_url

    assert is_collection_url("https://www.youtube.com/@SomeChannel/featured") is True
    assert is_collection_url("https://www.youtube.com/channel/UC123/shorts") is True
    assert collection_urls("https://www.youtube.com/@SomeChannel/featured") == [
        "https://www.youtube.com/@SomeChannel/videos",
        "https://www.youtube.com/@SomeChannel/shorts",
        "https://www.youtube.com/@SomeChannel/streams",
    ]
    assert collection_urls("https://www.youtube.com/channel/UC123/shorts") == [
        "https://www.youtube.com/channel/UC123/shorts"
    ]

    tab_calls: list[str | None] = []

    class _FakeTabYdl:
        def __init__(self, opts: dict) -> None:
            self._cookie = opts.get("cookiefile")

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def extract_info(self, url: str, download: bool = False):
            tab_calls.append(self._cookie)
            if self._cookie:
                raise ExtractorError("Sign in to confirm you're not a bot")
            return {"entries": [{"id": "abc12345678", "url": "abc12345678"}]}

    monkeypatch.setattr(ytdlp_module.yt_dlp, "YoutubeDL", _FakeTabYdl)
    res = yt_module.YouTubeProvider()._enumerate_tab(
        {"cookiefile": "yt.txt"},
        "https://www.youtube.com/@SomeChannel/videos",
    )
    assert tab_calls == ["yt.txt", None]
    assert res and len(res["entries"]) == 1

    # Verify bare 11-char YouTube ID normalization and transient timeout retry.
    hydrate_calls: list[str] = []

    class _FlakyHydrateYdl:
        def extract_info(self, url: str, download: bool = False):
            hydrate_calls.append(url)
            if len(hydrate_calls) == 1:
                raise ExtractorError("HTTP Error 429: Too Many Requests")
            return {"id": "abc12345678"}

        def close(self) -> None:
            pass

    monkeypatch.setattr(ytdlp_module.time, "sleep", lambda _s: None)
    hydrator = _EntryHydrator({})
    hydrator._ydl = lambda: _FlakyHydrateYdl()  # type: ignore[method-assign]
    info, err = hydrator.hydrate({"url": "abc12345678", "ie_key": "Youtube"})
    assert err == ""
    assert info == {"id": "abc12345678"}
    assert hydrate_calls == [
        "https://www.youtube.com/watch?v=abc12345678",
        "https://www.youtube.com/watch?v=abc12345678",
    ]


def test_tiktok_capabilities_and_profile_slideshow_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xakumedia.providers.platforms.tiktok import TikTokProvider
    from xakumedia.providers.ytdlp import _EntryHydrator

    provider = TikTokProvider()
    caps = provider.capabilities_for("https://www.tiktok.com/@creator")
    assert caps.images is True and caps.videos is True

    monkeypatch.setattr(
        _EntryHydrator,
        "hydrate",
        lambda self, entry: (None, "slideshow extract failed"),
    )
    monkeypatch.setattr(
        provider,
        "_tiktok_image_post",
        lambda page_url, source_url, info, warn: SimpleNamespace(
            media_items=[SimpleNamespace(media_type=MediaType.IMAGE)],
            page_url=page_url,
        ),
    )

    posts = list(
        provider._hydrate_entries(
            [{"id": "777", "url": "https://www.tiktok.com/@creator/photo/777"}],
            {},
            10,
            threading.Event(),
            lambda _m: None,
            "https://www.tiktok.com/@creator",
            ScanOptions(include_images=True, include_videos=True),
        )
    )
    assert len(posts) == 1
    assert posts[0].page_url == "https://www.tiktok.com/@creator/video/777"


def test_facebook_story_highlights_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from xakumedia.providers.platforms.facebook import (
        FacebookProvider,
        _extract_highlight_bucket_ids,
        _parse_facebook_url,
    )

    st_target = _parse_facebook_url("https://www.facebook.com/stories/9876543210/")
    assert st_target.scope == "stories" and st_target.video_id == "9876543210"

    profile_html = (
        '"DTSGInitialData",[],{"token":"dtsg"}'
        '"LSD",[],{"token":"lsd"}'
        '"userID":"61580886670213"'
        '"adp_ProfileCometTimelineListViewRootQueryRelayPreloader_123",'
        '"queryID":"29875146502090540","variables":{"userID":"61580886670213","scale":1},'
        '"queryName":"ProfileCometTimelineListViewRootQuery"'
        '"story_bucket":{"nodes":[{"id":"111222333"}]}'
    )
    timeline_payload = {
        "data": {
            "user": {
                "id": "61580886670213",
                "highlight_units_section": {
                    "featured_highlights": {
                        "edges": [
                            {"node": {"__typename": "HighlightStoryBucket", "id": "444555666"}}
                        ]
                    }
                },
            }
        }
    }
    bucket_ids = _extract_highlight_bucket_ids(
        profile_html, [timeline_payload], exclude_ids={"61580886670213"}
    )
    assert bucket_ids == ["111222333", "444555666"]

    # StoryHighlightContainer inside ProfileTileViewFeaturedHighlightsRenderer must not leak
    # its cover_card media ID as a fake bucket ID.
    featured_tile_payload = {
        "__typename": "ProfileTileViewFeaturedHighlightsRenderer",
        "view": {
            "profile_tile_items": {
                "edges": [
                    {
                        "node": {
                            "__typename": "ProfileTileItem",
                            "node": {
                                "__typename": "StoryHighlightContainer",
                                "id": "2288669021575524",
                                "cover_card": {
                                    "attachments": [
                                        {
                                            "media": {
                                                "__typename": "Photo",
                                                "id": "801871782241475",
                                            }
                                        }
                                    ]
                                },
                            },
                        }
                    }
                ]
            }
        },
    }
    assert _extract_highlight_bucket_ids("", [featured_tile_payload]) == ["2288669021575524"]

    mpd_hl = (
        '<MPD mediaPresentationDuration="PT6S"><Period>'
        '<AdaptationSet contentType="video"><Representation codecs="avc1" width="720" '
        'height="1280" FBQualityLabel="720p">'
        "<BaseURL>https://fb.cdn/hl_vid.mp4</BaseURL></Representation></AdaptationSet>"
        '<AdaptationSet contentType="audio"><Representation codecs="mp4a.40.5">'
        "<BaseURL>https://fb.cdn/hl_vid.m4a</BaseURL></Representation></AdaptationSet>"
        "</Period></MPD>"
    )
    bucket_story_payload = json.dumps(
        {
            "data": {
                "bucket": {
                    "id": "444555666",
                    "story_bucket_owner": {"id": "61580886670213", "name": "AliceFB"},
                    "unified_stories": {
                        "edges": [
                            {
                                "node": {
                                    "id": "story_v1",
                                    "attachments": [
                                        {
                                            "media": {
                                                "__typename": "Video",
                                                "id": "99001122",
                                                "videoDeliveryLegacyFields": {
                                                    "dash_manifest_xml_string": mpd_hl
                                                },
                                            }
                                        }
                                    ],
                                }
                            },
                            {
                                "node": {
                                    "id": "story_p1",
                                    "attachments": [
                                        {
                                            "media": {
                                                "__typename": "Photo",
                                                "id": "88007766",
                                                "image": {
                                                    "uri": "https://fb.cdn/hl_pic.jpg",
                                                    "width": 1080,
                                                    "height": 1920,
                                                },
                                            }
                                        }
                                    ],
                                }
                            },
                        ]
                    },
                }
            }
        }
    )

    class _FakeFbExtractor:
        def request(self, url: str, method: str = "GET", fatal: bool = True, **kwargs):
            del fatal
            if "api/graphql" in url:
                friendly = (kwargs.get("data") or {}).get("fb_api_req_friendly_name")
                if friendly == "ProfileCometTimelineListViewRootQuery":
                    return SimpleNamespace(
                        status_code=200, text=json.dumps(timeline_payload), url=url
                    )
                if friendly == "StoriesSuspenseContentPaneRootWithEntryPointQuery":
                    return SimpleNamespace(
                        status_code=200, text=bucket_story_payload, url=url
                    )
            if url == "https://www.facebook.com/61580886670213":
                return SimpleNamespace(status_code=200, text=profile_html, url=url)
            if url.startswith("https://www.facebook.com/stories/"):
                return SimpleNamespace(
                    status_code=200,
                    text='"DTSGInitialData",[],{"token":"dtsg"}"LSD",[],{"token":"lsd"}',
                    url=url,
                )
            return SimpleNamespace(status_code=200, text="<html></html>", url=url)

    monkeypatch.setattr(FacebookProvider, "_prepare_extractor", lambda self, u: _FakeFbExtractor())
    monkeypatch.setattr(
        FacebookProvider, "_iter_paginated_reels", lambda *a, **kw: iter(())
    )
    monkeypatch.setattr(
        FacebookProvider, "_iter_paginated_videos", lambda *a, **kw: iter(())
    )
    monkeypatch.setattr(
        FacebookProvider, "_iter_profile_photos_and_albums", lambda *a, **kw: iter(())
    )

    posts = list(
        FacebookProvider().iter_posts(
            "https://www.facebook.com/61580886670213",
            ScanOptions(include_images=True, include_videos=True),
            threading.Event(),
        )
    )
    assert [p.provider_post_id for p in posts] == ["99001122", "88007766"]
    assert posts[0].media_items[0].media_type == MediaType.VIDEO
    assert posts[1].media_items[0].media_type == MediaType.IMAGE
    assert posts[0].author == "AliceFB"

    # /stories/highlights/<id> URLs must target the highlight bucket ID, not "highlights",
    # and unrelated buckets in the navigation tray must not leak into results.
    from xakumedia.providers.platforms.facebook import _collect_story_nodes_from_payloads

    hl_target = _parse_facebook_url("https://www.facebook.com/stories/highlights/444555666")
    assert hl_target.scope == "stories"
    assert hl_target.video_id == "444555666"

    nav_tray = {
        "data": {
            "other_bucket": {
                "__isStoryBucket": "DirectMessageThreadBucket",
                "id": "999999999",
                "story_bucket_owner": {"id": "777", "name": "Stranger"},
                "unified_stories": {"edges": [{"node": {"id": "other_card"}}]},
            },
            "target_bucket": {
                "__isStoryBucket": "DirectMessageThreadBucket",
                "id": "444555666",
                "story_bucket_owner": {"id": "61580886670213", "name": "AliceFB"},
                "unified_stories": {"edges": [{"node": {"id": "target_card"}}]},
            },
        }
    }
    filtered_nodes, filtered_owner = _collect_story_nodes_from_payloads(
        [nav_tray], target_bucket_id="444555666"
    )
    assert [n["id"] for n in filtered_nodes] == ["target_card"]
    assert filtered_owner == "AliceFB"



