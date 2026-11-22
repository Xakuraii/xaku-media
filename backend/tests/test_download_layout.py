"""Download folder layout tests for platform/user/media-type separation."""

from pathlib import Path

from xakumedia.downloader.layout import destination_directory, platform_folder
from xakumedia.models.media import MediaItem, MediaType


def _item(
    *,
    provider: str,
    media_type: MediaType,
    extractor: str,
    source_url: str,
    author: str = "xakuraii",
    post_url: str | None = None,
    provider_media_id: str | None = None,
    metadata_extra: dict | None = None,
) -> MediaItem:
    extra = {"extractor": extractor}
    if metadata_extra:
        extra.update(metadata_extra)
    return MediaItem(
        id=f"{provider}-{extractor}-{media_type}",
        source_url=source_url,
        media_type=media_type,
        author=author,
        original_url="https://cdn.example.com/file.bin",
        provider=provider,
        provider_media_id=provider_media_id,
        post_id="post-hash",
        post_url=post_url,
        metadata_extra=extra,
    )


def test_tiktok_videos_and_slides_share_the_user_library(tmp_path: Path) -> None:
    video = _item(
        provider="ytdlp",
        media_type=MediaType.VIDEO,
        extractor="TikTok",
        source_url="https://www.tiktok.com/@alice",
        post_url="https://www.tiktok.com/@alice/video/7634207163103071508",
        provider_media_id="7634207163103071508",
    )
    slide = _item(
        provider="ytdlp",
        media_type=MediaType.IMAGE,
        extractor="TikTok",
        source_url="https://www.tiktok.com/@alice",
        post_url="https://www.tiktok.com/@alice/video/7634207163103071508",
        provider_media_id="7634207163103071508:2",
        metadata_extra={"post_id": "7634207163103071508", "slideshow": True},
    )

    assert destination_directory(video, tmp_path) == (
        tmp_path / "Tiktok" / "xakuraii" / "Videos"
    )
    assert destination_directory(slide, tmp_path) == (
        tmp_path / "Tiktok" / "xakuraii" / "Images"
    )


def test_instagram_videos_and_pictures_are_separate(tmp_path: Path) -> None:
    reel = _item(
        provider="gallerydl",
        media_type=MediaType.VIDEO,
        extractor="instagram",
        source_url="https://www.instagram.com/p/ABC/",
        post_url="https://www.instagram.com/p/ABC/",
    )
    picture = _item(
        provider="gallerydl",
        media_type=MediaType.IMAGE,
        extractor="instagram",
        source_url="https://www.instagram.com/p/ABC/",
        post_url="https://www.instagram.com/p/ABC/",
    )

    assert destination_directory(reel, tmp_path) == (
        tmp_path / "Instagram" / "xakuraii" / "Videos"
    )
    assert destination_directory(picture, tmp_path) == (
        tmp_path / "Instagram" / "xakuraii" / "Images"
    )


def test_youtube_videos_all_land_in_one_user_folder(tmp_path: Path) -> None:
    short = _item(
        provider="ytdlp",
        media_type=MediaType.VIDEO,
        extractor="Youtube",
        source_url="https://www.youtube.com/@alice/shorts",
        post_url="https://www.youtube.com/shorts/abc123",
    )
    video = _item(
        provider="ytdlp",
        media_type=MediaType.VIDEO,
        extractor="Youtube",
        source_url="https://www.youtube.com/@alice/videos",
        post_url="https://www.youtube.com/watch?v=abc123",
    )

    assert destination_directory(short, tmp_path) == (
        tmp_path / "Youtube" / "xakuraii" / "Videos"
    )
    assert destination_directory(video, tmp_path) == (
        tmp_path / "Youtube" / "xakuraii" / "Videos"
    )


def test_facebook_and_x_split_videos_from_pictures(tmp_path: Path) -> None:
    facebook_video = _item(
        provider="gallerydl",
        media_type=MediaType.VIDEO,
        extractor="facebook",
        source_url="https://www.facebook.com/reel/123",
    )
    facebook_photo = _item(
        provider="gallerydl",
        media_type=MediaType.IMAGE,
        extractor="facebook",
        source_url="https://www.facebook.com/alice",
    )
    x_video = _item(
        provider="gallerydl",
        media_type=MediaType.VIDEO,
        extractor="twitter",
        source_url="https://x.com/alice/status/123",
    )
    x_photo = _item(
        provider="gallerydl",
        media_type=MediaType.IMAGE,
        extractor="twitter",
        source_url="https://x.com/alice/status/123",
    )

    assert destination_directory(facebook_video, tmp_path) == (
        tmp_path / "Facebook" / "xakuraii" / "Videos"
    )
    assert destination_directory(facebook_photo, tmp_path) == (
        tmp_path / "Facebook" / "xakuraii" / "Images"
    )
    assert destination_directory(x_video, tmp_path) == (
        tmp_path / "X" / "xakuraii" / "Videos"
    )
    assert destination_directory(x_photo, tmp_path) == (
        tmp_path / "X" / "xakuraii" / "Images"
    )


def test_unlisted_platforms_share_one_others_folder(tmp_path: Path) -> None:
    reddit = _item(
        provider="gallerydl",
        media_type=MediaType.IMAGE,
        extractor="reddit",
        source_url="https://www.reddit.com/r/pics/",
        author="bad:user/name",
    )
    artstation = _item(
        provider="gallerydl",
        media_type=MediaType.IMAGE,
        extractor="artstation",
        source_url="https://www.artstation.com/alice",
        author="bad:user/name",
    )

    assert platform_folder(reddit) == "Others"
    assert platform_folder(artstation) == "Others"
    assert destination_directory(reddit, tmp_path) == (
        tmp_path / "Others" / "bad_user_name" / "Images"
    )
    assert destination_directory(artstation, tmp_path) == (
        tmp_path / "Others" / "bad_user_name" / "Images"
    )


def test_missing_author_falls_back_to_media_folder(tmp_path: Path) -> None:
    item = _item(
        provider="direct",
        media_type=MediaType.VIDEO,
        extractor="",
        source_url="https://example.com/clip.mp4",
        author="",
    )

    assert destination_directory(item, tmp_path) == (
        tmp_path / "Others" / "media" / "Videos"
    )


def test_short_host_aliases_map_to_canonical_platform_folders(tmp_path: Path) -> None:
    fb_watch = _item(
        provider="gallerydl",
        media_type=MediaType.VIDEO,
        extractor="",
        source_url="https://fb.watch/abc123/",
        author="xakuraii",
    )
    ig_short = _item(
        provider="gallerydl",
        media_type=MediaType.IMAGE,
        extractor="",
        source_url="https://instagr.am/p/xyz/",
        author="xakuraii",
    )

    assert platform_folder(fb_watch) == "Facebook"
    assert platform_folder(ig_short) == "Instagram"
