"""Per-folder JSON manifest of downloaded and skipped media.

Each media-kind folder (``Videos``, ``Images``, ``Audio``) keeps a small
``xakumedia-library.json`` file next to the media files. The manifest records
the provider identity of every item that was downloaded or explicitly skipped,
so a rescan (or another device sharing the folder) can tell what is already
handled without relying on the SQLite task history.

The manifest is deliberately plain JSON and is never part of the sequential
filename pattern, so it can be copied, diffed, or inspected by hand.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.config import default_config
from ..core.logging import get_logger
from ..models.media import MediaItem
from ..utils.stable_ids import url_fingerprint

logger = get_logger("downloader.library")

MANIFEST_FILENAME = "xakumedia-library.json"
MANIFEST_VERSION = 1

_LOCK = threading.Lock()


def media_identity(item: MediaItem) -> str:
    """Return a stable identity key for an item across rescans and restarts."""
    provider = (item.provider or "").lower()
    kind = str(item.media_type)
    if item.provider_media_id:
        key = f"{provider}:{kind}:{item.provider_media_id}"
        if item.attachment_index:
            key = f"{key}:{item.attachment_index}"
        return key
    fallback_url = item.original_url or item.source_url
    return f"url:{url_fingerprint(fallback_url)}"


def manifest_path(directory: Path | str) -> Path:
    """Return the manifest path inside a media-kind folder."""
    return Path(directory) / MANIFEST_FILENAME


def load_manifest(directory: Path | str) -> dict[str, Any]:
    """Read a folder manifest, returning an empty structure when absent/corrupt."""
    path = manifest_path(directory)
    if not path.exists():
        return {"version": MANIFEST_VERSION, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not read library manifest {path}: {exc}")
        return {"version": MANIFEST_VERSION, "items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"version": MANIFEST_VERSION, "items": {}}
    data.setdefault("version", MANIFEST_VERSION)
    return data


def _summarize_counts(items: dict[str, Any]) -> dict[str, int]:
    downloaded = 0
    skipped = 0
    for entry in items.values():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status == "downloaded":
            downloaded += 1
        elif status == "skipped":
            skipped += 1
    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "total": downloaded + skipped,
    }


def _write_manifest(directory: Path | str, data: dict[str, Any]) -> None:
    """Atomically replace a folder manifest without leaving a partial file."""
    path = manifest_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = MANIFEST_VERSION
    data["updated_at"] = datetime.now(UTC).isoformat()
    data["counts"] = _summarize_counts(data.get("items") or {})
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        logger.warning(f"Could not write library manifest {path}: {exc}")
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _entry(item: MediaItem, status: str, filename: str | None) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "identity": media_identity(item),
        "status": status,
        "media_type": str(item.media_type),
        "provider": item.provider,
        "provider_media_id": item.provider_media_id,
        "attachment_index": item.attachment_index,
        "title": item.title,
        "author": item.author,
        "source_url": item.source_url,
        "original_url": item.original_url,
        "post_url": item.post_url,
        "filename": filename,
        "updated_at": now,
    }


def _record(directory: Path, item: MediaItem, status: str, filename: str | None) -> str:
    identity = media_identity(item)
    with _LOCK:
        data = load_manifest(directory)
        previous = data["items"].get(identity)
        entry = _entry(item, status, filename)
        if isinstance(previous, dict) and previous.get("updated_at"):
            first_seen = previous.get("first_seen_at") or previous["updated_at"]
            entry.setdefault("first_seen_at", first_seen)
        else:
            entry["first_seen_at"] = entry["updated_at"]
        data["items"][identity] = entry
        _write_manifest(directory, data)
    return identity


def record_download(item: MediaItem, file_path: Path | str) -> str:
    """Record a completed download in its media-kind folder manifest."""
    path = Path(file_path)
    identity = media_identity(item)
    try:
        _record(path.parent, item, "downloaded", path.name)
    except Exception as exc:  # a manifest failure must never fail a download
        logger.warning(f"Could not record download in library manifest: {exc}")
    return identity


def record_skipped(items: Iterable[MediaItem]) -> list[str]:
    """Record explicitly skipped items and return their identities."""
    from .layout import destination_directory

    by_directory: dict[Path, list[MediaItem]] = {}
    identities: list[str] = []
    for item in items:
        try:
            directory = destination_directory(item)
            by_directory.setdefault(directory, []).append(item)
        except Exception as exc:
            logger.warning(f"Could not resolve destination for skipped media: {exc}")

    for directory, dir_items in by_directory.items():
        try:
            with _LOCK:
                data = load_manifest(directory)
                for item in dir_items:
                    identity = media_identity(item)
                    previous = data["items"].get(identity)
                    entry = _entry(item, "skipped", None)
                    if isinstance(previous, dict) and previous.get("updated_at"):
                        entry["first_seen_at"] = (
                            previous.get("first_seen_at") or previous["updated_at"]
                        )
                    else:
                        entry["first_seen_at"] = entry["updated_at"]
                    data["items"][identity] = entry
                    identities.append(identity)
                _write_manifest(directory, data)
        except Exception as exc:
            logger.warning(f"Could not record skipped media in library manifest: {exc}")
    return identities


def unskip_items(items: Iterable[MediaItem]) -> list[str]:
    """Remove ``skipped`` manifest entries so items show as new again."""
    from .layout import destination_directory

    by_directory: dict[Path, list[str]] = {}
    for item in items:
        try:
            directory = destination_directory(item)
            by_directory.setdefault(directory, []).append(media_identity(item))
        except Exception as exc:
            logger.warning(f"Could not resolve destination for unskip media: {exc}")

    removed: list[str] = []
    for directory, ids in by_directory.items():
        try:
            with _LOCK:
                data = load_manifest(directory)
                changed = False
                for identity in ids:
                    entry = data["items"].get(identity)
                    if isinstance(entry, dict) and entry.get("status") == "skipped":
                        data["items"].pop(identity, None)
                        removed.append(identity)
                        changed = True
                if changed:
                    _write_manifest(directory, data)
        except Exception as exc:
            logger.warning(f"Could not unskip media in library manifest: {exc}")
    return removed


def _resolve_existing_manifest_dir(directory: Path) -> Path:
    """Resolve ``directory`` case-insensitively when its manifest already exists."""
    if manifest_path(directory).exists() or directory.exists():
        return directory
    try:
        user_dir = directory.parent
        platform_dir = user_dir.parent
        if platform_dir.is_dir():
            target_user = user_dir.name.lower()
            target_kind = directory.name.lower()
            for child in platform_dir.iterdir():
                if child.is_dir() and child.name.lower() == target_user:
                    for sub in child.iterdir():
                        if sub.is_dir() and sub.name.lower() == target_kind:
                            return sub
    except OSError:
        pass
    return directory


def _find_manifest_entry(data: dict[str, Any], item: MediaItem) -> dict[str, Any] | None:
    """Match an item against a manifest by primary identity or fallback metadata."""
    items = data.get("items") or {}
    entry = items.get(media_identity(item))
    if isinstance(entry, dict):
        return entry

    target_pid = item.provider_media_id
    target_kind = str(item.media_type)
    target_url = item.original_url or ""
    for candidate in items.values():
        if not isinstance(candidate, dict):
            continue
        if (
            target_pid
            and candidate.get("provider_media_id") == target_pid
            and candidate.get("media_type") == target_kind
            and (candidate.get("attachment_index") or 0) == (item.attachment_index or 0)
        ):
            return candidate
        if target_url and candidate.get("original_url") == target_url:
            return candidate
    return None


def annotate_items(items: Iterable[MediaItem]) -> None:
    """Attach ``downloaded``/``skipped`` status from the folder manifests."""
    from .layout import destination_directory

    cache: dict[Path, dict[str, Any]] = {}
    for item in items:
        try:
            directory = _resolve_existing_manifest_dir(destination_directory(item))
            data = cache.get(directory)
            if data is None:
                data = load_manifest(directory)
                cache[directory] = data
            entry = _find_manifest_entry(data, item)
            if isinstance(entry, dict):
                status = entry.get("status")
                if status in {"downloaded", "skipped"}:
                    item.library_status = status
        except Exception as exc:
            logger.debug(f"Could not annotate media library status: {exc}")


def remove_file(file_path: Path | str) -> bool:
    """Forget a file's manifest entry after its media file is deleted."""
    path = Path(file_path)
    removed = False
    with _LOCK:
        data = load_manifest(path.parent)
        stale = [
            identity
            for identity, entry in data["items"].items()
            if isinstance(entry, dict) and entry.get("filename") == path.name
        ]
        for identity in stale:
            data["items"].pop(identity, None)
            removed = True
        if removed:
            _write_manifest(path.parent, data)
    return removed


def apply_renames(renamed: Iterable[tuple[Path, Path]]) -> None:
    """Keep manifest filenames in sync after a sequence compaction rename."""
    by_directory: dict[Path, dict[str, str]] = {}
    for old, new in renamed:
        if old.parent != new.parent:
            continue
        by_directory.setdefault(old.parent, {})[old.name] = new.name

    for directory, names in by_directory.items():
        with _LOCK:
            data = load_manifest(directory)
            changed = False
            for entry in data["items"].values():
                if not isinstance(entry, dict):
                    continue
                filename = entry.get("filename")
                if filename in names:
                    entry["filename"] = names[filename]
                    changed = True
            if changed:
                _write_manifest(directory, data)


def status_for(item: MediaItem) -> str | None:
    """Return the manifest status for one item without mutating it."""
    from .layout import destination_directory

    directory = _resolve_existing_manifest_dir(destination_directory(item))
    entry = _find_manifest_entry(load_manifest(directory), item)
    if isinstance(entry, dict):
        status = entry.get("status")
        if status in {"downloaded", "skipped"}:
            return status
    return None


def unskip_entry_by_id(directory: Path | str, identity: str) -> bool:
    """Remove a single ``skipped`` entry from a folder manifest by identity."""
    folder = Path(directory)
    with _LOCK:
        data = load_manifest(folder)
        entry = data["items"].get(identity)
        if isinstance(entry, dict) and entry.get("status") == "skipped":
            data["items"].pop(identity, None)
            _write_manifest(folder, data)
            return True
    return False


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg"}
_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".ts", ".m4v"}
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
_MEDIA_EXTS = _IMAGE_EXTS | _VIDEO_EXTS | _AUDIO_EXTS


def _infer_media_type(folder_name: str, suffix: str) -> str:
    ext = suffix.lower()
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _IMAGE_EXTS:
        return "image"
    lowered = folder_name.lower()
    if lowered == "videos":
        return "video"
    if lowered == "audio":
        return "audio"
    return "image"


def _scan_kind_folder(folder: Path, platform_name: str, user_name: str) -> dict[str, Any]:
    """Read one media-kind leaf folder (disk files + xakumedia-library.json)."""
    manifest = load_manifest(folder)
    manifest_items = manifest.get("items") or {}

    by_filename: dict[str, dict[str, Any]] = {}
    skipped_entries: list[dict[str, Any]] = []

    for identity, entry in manifest_items.items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        filename = entry.get("filename")
        if status == "skipped":
            skipped_entries.append(
                {
                    "identity": entry.get("identity") or identity,
                    "status": "skipped",
                    "media_type": entry.get("media_type")
                    or _infer_media_type(folder.name, ""),
                    "filename": None,
                    "file_path": None,
                    "size_bytes": None,
                    "extension": None,
                    "title": entry.get("title") or entry.get("provider_media_id") or "Skipped item",
                    "author": entry.get("author") or user_name,
                    "platform": platform_name,
                    "provider": entry.get("provider"),
                    "provider_media_id": entry.get("provider_media_id"),
                    "attachment_index": entry.get("attachment_index") or 0,
                    "source_url": entry.get("source_url"),
                    "original_url": entry.get("original_url"),
                    "post_url": entry.get("post_url"),
                    "updated_at": entry.get("updated_at") or entry.get("first_seen_at"),
                }
            )
        elif status == "downloaded" and isinstance(filename, str) and filename:
            by_filename[filename] = entry

    disk_entries: list[dict[str, Any]] = []
    size_bytes = 0
    if folder.is_dir():
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            children = []
        for child in children:
            if not child.is_file():
                continue
            name = child.name
            if name == MANIFEST_FILENAME or name.startswith(".xakumedia-"):
                continue
            suffix = child.suffix.lower()
            if suffix in (".part", ".tmp") or suffix not in _MEDIA_EXTS:
                continue
            try:
                stat = child.stat()
                file_size = stat.st_size
                mtime_iso = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            except OSError:
                file_size = 0
                mtime_iso = None
            size_bytes += file_size
            entry = by_filename.get(name, {})
            disk_entries.append(
                {
                    "identity": entry.get("identity") or f"file:{name}",
                    "status": "downloaded",
                    "media_type": entry.get("media_type")
                    or _infer_media_type(folder.name, suffix),
                    "filename": name,
                    "file_path": str(child),
                    "size_bytes": file_size,
                    "extension": suffix.lstrip("."),
                    "title": entry.get("title") or child.stem,
                    "author": entry.get("author") or user_name,
                    "platform": platform_name,
                    "provider": entry.get("provider"),
                    "provider_media_id": entry.get("provider_media_id"),
                    "attachment_index": entry.get("attachment_index") or 0,
                    "source_url": entry.get("source_url"),
                    "original_url": entry.get("original_url"),
                    "post_url": entry.get("post_url"),
                    "updated_at": entry.get("updated_at") or mtime_iso,
                }
            )

    all_items = disk_entries + skipped_entries
    videos = sum(1 for item in disk_entries if item["media_type"] == "video")
    images = sum(1 for item in disk_entries if item["media_type"] == "image")
    return {
        "name": folder.name,
        "media_type": _infer_media_type(folder.name, ""),
        "path": str(folder),
        "downloaded_count": len(disk_entries),
        "skipped_count": len(skipped_entries),
        "video_count": videos,
        "image_count": images,
        "size_bytes": size_bytes,
        "items": all_items,
    }


def _classify_manifest_rel(
    rel_parts: tuple[str, ...], root_name: str
) -> tuple[str, str, str]:
    """Map a manifest folder's relative path to ``(platform, user, kind_folder)``."""
    if len(rel_parts) >= 3:
        return rel_parts[0], rel_parts[1], "/".join(rel_parts[2:])
    if len(rel_parts) == 2:
        return rel_parts[0], rel_parts[1], "Files"
    if len(rel_parts) == 1:
        return rel_parts[0], rel_parts[0], "Files"
    return root_name or "Library", "Root", "Files"


def scan_download_library(base_dir: Path | str | None = None) -> dict[str, Any]:
    """Scan ``download_dir`` by detecting all ``xakumedia-library.json`` files.

    Builds the real folder hierarchy (Platform -> User -> Videos/Images/Audio)
    from every directory containing a ``xakumedia-library.json`` manifest,
    including both real media files on disk in those folders and skipped items
    recorded in each manifest. Unrelated folders without a manifest are ignored.
    """
    root = Path(base_dir) if base_dir else default_config.download_dir
    platforms: list[dict[str, Any]] = []
    total_users = 0
    total_downloaded = 0
    total_skipped = 0
    total_videos = 0
    total_images = 0
    total_size = 0

    if root.exists() and root.is_dir():
        try:
            manifest_files = sorted(
                root.rglob(MANIFEST_FILENAME),
                key=lambda p: str(p).lower(),
            )
        except OSError:
            manifest_files = []

        # platform_name -> {"path": Path, "users": {user_name -> {"path": Path, "folders": [...]}}}
        tree: dict[str, dict[str, Any]] = {}

        for mf in manifest_files:
            folder = mf.parent
            try:
                rel_parts = folder.relative_to(root).parts
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel_parts):
                continue

            platform_name, user_name, kind_label = _classify_manifest_rel(rel_parts, root.name)
            folder_info = _scan_kind_folder(folder, platform_name, user_name)
            folder_info["name"] = kind_label
            if folder_info["downloaded_count"] == 0 and folder_info["skipped_count"] == 0:
                continue

            platform_path = root / platform_name if rel_parts else root
            user_path = (
                root / platform_name / user_name
                if len(rel_parts) >= 2
                else platform_path
            )

            p_bucket = tree.setdefault(
                platform_name, {"path": platform_path, "users": {}}
            )
            u_bucket = p_bucket["users"].setdefault(
                user_name, {"path": user_path, "folders": []}
            )
            u_bucket["folders"].append(folder_info)

        for platform_name in sorted(tree.keys(), key=str.lower):
            p_bucket = tree[platform_name]
            users: list[dict[str, Any]] = []

            for user_name in sorted(p_bucket["users"].keys(), key=str.lower):
                u_bucket = p_bucket["users"][user_name]
                folders = sorted(
                    u_bucket["folders"], key=lambda f: f["name"].lower()
                )
                if not folders:
                    continue

                u_dl = sum(f["downloaded_count"] for f in folders)
                u_skip = sum(f["skipped_count"] for f in folders)
                u_vid = sum(f["video_count"] for f in folders)
                u_img = sum(f["image_count"] for f in folders)
                u_size = sum(f["size_bytes"] for f in folders)
                preview_path = next(
                    (
                        item["file_path"]
                        for f in folders
                        for item in f["items"]
                        if item["status"] == "downloaded"
                        and item["media_type"] == "image"
                        and item.get("file_path")
                    ),
                    None,
                )
                users.append(
                    {
                        "name": user_name,
                        "path": str(u_bucket["path"]),
                        "downloaded_count": u_dl,
                        "skipped_count": u_skip,
                        "video_count": u_vid,
                        "image_count": u_img,
                        "size_bytes": u_size,
                        "preview_path": preview_path,
                        "folders": folders,
                    }
                )

            if not users:
                continue

            p_dl = sum(u["downloaded_count"] for u in users)
            p_skip = sum(u["skipped_count"] for u in users)
            p_vid = sum(u["video_count"] for u in users)
            p_img = sum(u["image_count"] for u in users)
            p_size = sum(u["size_bytes"] for u in users)
            total_users += len(users)
            total_downloaded += p_dl
            total_skipped += p_skip
            total_videos += p_vid
            total_images += p_img
            total_size += p_size
            platforms.append(
                {
                    "name": platform_name,
                    "path": str(p_bucket["path"]),
                    "user_count": len(users),
                    "downloaded_count": p_dl,
                    "skipped_count": p_skip,
                    "video_count": p_vid,
                    "image_count": p_img,
                    "size_bytes": p_size,
                    "users": users,
                }
            )

    return {
        "root_dir": str(root),
        "totals": {
            "platforms": len(platforms),
            "users": total_users,
            "downloaded": total_downloaded,
            "skipped": total_skipped,
            "videos": total_videos,
            "images": total_images,
            "size_bytes": total_size,
        },
        "platforms": platforms,
    }


__all__ = [
    "MANIFEST_FILENAME",
    "annotate_items",
    "apply_renames",
    "load_manifest",
    "manifest_path",
    "media_identity",
    "record_download",
    "record_skipped",
    "remove_file",
    "scan_download_library",
    "status_for",
    "unskip_entry_by_id",
    "unskip_items",
]
