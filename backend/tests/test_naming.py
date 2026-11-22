"""Unit tests for sequential filename generation, gap compaction, and collision logic."""

from pathlib import Path

from xakumedia.models.media import MediaType
from xakumedia.utils.naming import (
    compact_sequence_numbers,
    extract_sequence_number,
    format_sequential_filename,
    get_next_sequence_number,
    sanitize_username,
)


def test_sanitize_username() -> None:
    assert sanitize_username("normal_user") == "normal_user"
    assert sanitize_username("bad:user/name*?test") == "bad_user_name_test"
    assert sanitize_username("..leading.and.trailing..") == "leading.and.trailing"
    assert sanitize_username("   whitespace   ") == "whitespace"
    assert sanitize_username("") == "media"
    assert sanitize_username(None) == "media"
    assert sanitize_username(":::***???") == "media"


def test_format_sequential_filename() -> None:
    assert (
        format_sequential_filename("xakuraii", MediaType.VIDEO, 1, "mp4")
        == "xakuraii-vdo-1.mp4"
    )
    assert (
        format_sequential_filename("xakuraii", MediaType.VIDEO, 25, "webm")
        == "xakuraii-vdo-25.webm"
    )

    assert (
        format_sequential_filename("photographer", MediaType.IMAGE, 7, ".jpg")
        == "photographer-img-7.jpg"
    )
    assert (
        format_sequential_filename("photographer", MediaType.IMAGE, 99, "PNG")
        == "photographer-img-99.png"
    )

    # Numbers are never truncated once they pass 999.
    assert (
        format_sequential_filename("creator", MediaType.VIDEO, 1000, "mkv")
        == "creator-vdo-1000.mkv"
    )
    assert (
        format_sequential_filename("creator", MediaType.IMAGE, 10500, "webp")
        == "creator-img-10500.webp"
    )


def test_extract_sequence_number() -> None:
    assert extract_sequence_number("xakuraii-vdo-1.mp4", "xakuraii", MediaType.VIDEO) == 1
    assert extract_sequence_number("xakuraii-img-42.jpg", "xakuraii", MediaType.IMAGE) == 42

    # A username that itself contains a hyphen still parses from the right.
    assert extract_sequence_number(
        "some-user-name-vdo-7.mp4", "some-user-name", MediaType.VIDEO
    ) == 7

    # Different user or prefix should return None
    assert extract_sequence_number("other-vdo-1.mp4", "xakuraii", MediaType.VIDEO) is None
    assert extract_sequence_number("xakuraii-img-1.jpg", "xakuraii", MediaType.VIDEO) is None
    assert extract_sequence_number("random_filename.mp4", "xakuraii", MediaType.VIDEO) is None


def test_get_next_sequence_number(tmp_path: Path) -> None:
    assert get_next_sequence_number(tmp_path, "artist", MediaType.VIDEO) == 1

    (tmp_path / "artist-vdo-1.mp4").touch()
    (tmp_path / "artist-vdo-2.webm").touch()
    assert get_next_sequence_number(tmp_path, "artist", MediaType.VIDEO) == 3

    (tmp_path / "artist-vdo-9.mp4").touch()
    assert get_next_sequence_number(tmp_path, "artist", MediaType.VIDEO) == 10

    # Videos and images have independent sequences.
    assert get_next_sequence_number(tmp_path, "artist", MediaType.IMAGE) == 1
    (tmp_path / "artist-img-1.jpg").touch()
    assert get_next_sequence_number(tmp_path, "artist", MediaType.IMAGE) == 2

    # Different usernames have independent sequences.
    assert get_next_sequence_number(tmp_path, "other_creator", MediaType.VIDEO) == 1


def test_compact_sequence_numbers_closes_gaps(tmp_path: Path) -> None:
    (tmp_path / "artist-vdo-1.mp4").touch()
    (tmp_path / "artist-vdo-3.mp4").touch()
    (tmp_path / "artist-vdo-7.mp4").touch()
    (tmp_path / "artist-img-1.jpg").touch()
    (tmp_path / "unrelated.mp4").touch()

    renamed = compact_sequence_numbers(tmp_path, "artist", MediaType.VIDEO)

    assert [new.name for _, new in renamed] == ["artist-vdo-2.mp4", "artist-vdo-3.mp4"]
    assert sorted(p.name for p in tmp_path.glob("artist-vdo-*.mp4")) == [
        "artist-vdo-1.mp4",
        "artist-vdo-2.mp4",
        "artist-vdo-3.mp4",
    ]
    # The image sequence and unrelated files are untouched.
    assert (tmp_path / "artist-img-1.jpg").exists()
    assert (tmp_path / "unrelated.mp4").exists()
    assert get_next_sequence_number(tmp_path, "artist", MediaType.VIDEO) == 4


def test_compact_sequence_numbers_is_a_noop_when_contiguous(tmp_path: Path) -> None:
    (tmp_path / "artist-vdo-1.mp4").touch()
    (tmp_path / "artist-vdo-2.mp4").touch()

    assert compact_sequence_numbers(tmp_path, "artist", MediaType.VIDEO) == []


def test_compact_sequence_numbers_handles_duplicates(tmp_path: Path) -> None:
    (tmp_path / "artist-img-1.jpg").touch()
    (tmp_path / "artist-img-1.png").touch()

    renamed = compact_sequence_numbers(tmp_path, "artist", MediaType.IMAGE)

    assert len(renamed) == 1
    assert sorted(p.name for p in tmp_path.glob("artist-img-*")) == [
        "artist-img-1.jpg",
        "artist-img-2.png",
    ]
