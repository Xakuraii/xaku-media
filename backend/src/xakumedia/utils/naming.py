"""Sequential filename generation, gap compaction, and sanitization utilities."""

import logging
import re
import uuid
from pathlib import Path

from ..models.media import MediaType
from .paths import WINDOWS_RESERVED_NAMES

logger = logging.getLogger(__name__)

# Characters forbidden in Windows filenames: \ / : * ? " < > |
FORBIDDEN_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|]')
# Matches the sequential pattern: {username}-{prefix}-{number}.{ext}
SEQUENCE_PATTERN = re.compile(
    r"^(?P<username>.+)-(?P<prefix>vdo|img|aud)-(?P<num>\d+)\.[^.]+$", re.IGNORECASE
)


def sanitize_username(username: str | None, fallback: str = "media") -> str:
    """Sanitize a username or author string for safe use in Windows filenames."""
    if not username:
        return fallback

    # Strip whitespace and forbidden characters
    cleaned = FORBIDDEN_CHARS_PATTERN.sub("_", username).strip(" .")
    # Normalize multiple underscores and trim boundary underscores/dots
    cleaned = re.sub(r"_+", "_", cleaned).strip("._ ")
    if not cleaned:
        return fallback

    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        return f"user_{cleaned}"

    return cleaned


def get_media_type_prefix(media_type: MediaType) -> str:
    """Return the sequential filename marker for a media type."""
    if media_type == MediaType.VIDEO:
        return "vdo"
    if media_type == MediaType.AUDIO:
        return "aud"
    return "img"


def format_sequential_filename(
    username: str,
    media_type: MediaType,
    sequence_number: int,
    extension: str,
) -> str:
    """Format filename according to project standards.

    Examples:
        format_sequential_filename("xakuraii", MediaType.VIDEO, 1, "mp4")
            -> "xakuraii-vdo-1.mp4"
        format_sequential_filename("xakuraii", MediaType.IMAGE, 12, "png")
            -> "xakuraii-img-12.png"
    """
    safe_user = sanitize_username(username)
    prefix = get_media_type_prefix(media_type)
    ext = extension.lstrip(".").lower()

    return f"{safe_user}-{prefix}-{sequence_number}.{ext}"


def extract_sequence_number(filename: str, username: str, media_type: MediaType) -> int | None:
    """Extract sequence number from an existing filename if it matches the pattern."""
    match = SEQUENCE_PATTERN.match(filename)
    if not match:
        return None

    safe_user = sanitize_username(username)
    prefix = get_media_type_prefix(media_type)

    if (
        match.group("username").lower() == safe_user.lower()
        and match.group("prefix").lower() == prefix
    ):
        try:
            return int(match.group("num"))
        except ValueError:
            return None

    return None


def get_next_sequence_number(directory: Path, username: str, media_type: MediaType) -> int:
    """Scan existing directory on disk to find the next sequential number.

    Even if a previous file was manually added or extensions differ (e.g. 1.jpg, 2.png),
    this scans all files to ensure no existing file is ever overwritten.
    """
    entries = list_sequence_files(directory, username, media_type)
    if not entries:
        return 1
    return max(number for number, _ in entries) + 1


def list_sequence_files(
    directory: Path,
    username: str,
    media_type: MediaType,
) -> list[tuple[int, Path]]:
    """Return ``(number, path)`` pairs for this user's files, ordered by number."""
    if not directory.exists() or not directory.is_dir():
        return []

    entries: list[tuple[int, Path]] = []
    safe_user = sanitize_username(username)

    for item in directory.iterdir():
        if not item.is_file():
            continue
        number = extract_sequence_number(item.name, safe_user, media_type)
        if number is not None:
            entries.append((number, item))

    entries.sort(key=lambda entry: (entry[0], entry[1].name.lower()))
    return entries


def compact_sequence_numbers(
    directory: Path,
    username: str,
    media_type: MediaType,
) -> list[tuple[Path, Path]]:
    """Renumber this user's files to 1..N so the sequence has no gaps.

    Returns the ``(old_path, new_path)`` pairs that were renamed. Renames run in
    two phases (stage, then finalize) so a target name can never collide with a
    file that has not been moved yet.
    """
    entries = list_sequence_files(directory, username, media_type)
    if not entries:
        return []

    plan: list[tuple[Path, Path]] = []
    for index, (_, path) in enumerate(entries, start=1):
        target = directory / format_sequential_filename(
            username, media_type, index, path.suffix.lstrip(".")
        )
        if target != path:
            plan.append((path, target))

    if not plan:
        return []

    staged: list[tuple[Path, Path, Path]] = []
    try:
        for index, (source, target) in enumerate(plan):
            temp = directory / f".xakumedia-renumber-{uuid.uuid4().hex}-{index}.tmp"
            source.rename(temp)
            staged.append((source, temp, target))
    except OSError as exc:
        logger.warning(f"Could not compact sequence in {directory}: {exc}")
        for source, temp, _ in reversed(staged):
            try:
                if temp.exists() and not source.exists():
                    temp.rename(source)
            except OSError:
                pass
        return []

    renamed: list[tuple[Path, Path]] = []
    for source, temp, target in staged:
        try:
            temp.rename(target)
        except OSError as exc:
            logger.warning(
                f"Could not finalize renumber {temp.name} -> {target.name}: {exc}"
            )
            try:
                temp.rename(source)
            except OSError:
                pass
            continue
        renamed.append((source, target))

    return renamed
