"""Download folder layout tests for platform/media-type separation."""

from pathlib import Path

from xakumedia.downloader.layout import destination_directory
from xakumedia.models.media import MediaItem, MediaType


def _item(
    *,
    provider: str,
    media_type: MediaType,
    extractor: str,
    source_url: str,
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
        original_url="https://cdn.example.com/file.bin",
        provider=provider,
        provider_media_id=provider_media_id,
        post_id="post-hash",
        post_url=post_url,
        metadata_extra=extra,
    )


def test_tiktok_video_and_slideshow_images_use_post_folders(tmp_path: Path) -> None:
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
        tmp_path / "tiktok" / "videos" / "7634207163103071508"
    )
    assert destination_directory(slide, tmp_path) == (
        tmp_path / "tiktok" / "images" / "7634207163103071508"
    )


def test_instagram_reels_and_pictures_are_separate(tmp_path: Path) -> None:
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

    assert destination_directory(reel, tmp_path) == tmp_path / "instagram" / "reels"
    assert destination_directory(picture, tmp_path) == tmp_path / "instagram" / "images"


def test_youtube_shorts_and_videos_are_separate(tmp_path: Path) -> None:
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

    assert destination_directory(short, tmp_path) == tmp_path / "youtube" / "shorts"
    assert destination_directory(video, tmp_path) == tmp_path / "youtube" / "videos"


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

    assert destination_directory(facebook_video, tmp_path) == tmp_path / "facebook" / "videos"
    assert destination_directory(facebook_photo, tmp_path) == tmp_path / "facebook" / "images"
    assert destination_directory(x_video, tmp_path) == tmp_path / "x" / "videos"
    assert destination_directory(x_photo, tmp_path) == tmp_path / "x" / "images"
