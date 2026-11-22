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


def annotate_items(items: Iterable[MediaItem]) -> None:
    """Attach ``downloaded``/``skipped`` status from the folder manifests."""
    from .layout import destination_directory

    cache: dict[Path, dict[str, Any]] = {}
    for item in items:
        try:
            directory = destination_directory(item)
            data = cache.get(directory)
            if data is None:
                data = load_manifest(directory)
                cache[directory] = data
            entry = data["items"].get(media_identity(item))
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

    entry = load_manifest(destination_directory(item))["items"].get(media_identity(item))
    if isinstance(entry, dict):
        status = entry.get("status")
        if status in {"downloaded", "skipped"}:
            return status
    return None


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
    "status_for",
    "unskip_items",
]
