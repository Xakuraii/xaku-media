"""Tests for the per-folder downloaded/skipped library manifest."""

import json
from pathlib import Path

import pytest

from xakumedia.core.config import default_config
from xakumedia.downloader.layout import destination_directory
from xakumedia.downloader.library import (
    MANIFEST_FILENAME,
    annotate_items,
    apply_renames,
    load_manifest,
    manifest_path,
    media_identity,
    record_download,
    record_skipped,
    remove_file,
)
from xakumedia.models.media import MediaItem, MediaType
from xakumedia.server.dispatcher import RpcDispatcher
from xakumedia.server.protocol import JsonRpcRequest


@pytest.fixture(autouse=True)
def isolated_download_dir(tmp_path: Path) -> Path:
    original = default_config.download_dir
    default_config.download_dir = tmp_path / "downloads"
    try:
        yield default_config.download_dir
    finally:
        default_config.download_dir = original


def _item(
    media_type: MediaType = MediaType.VIDEO,
    *,
    provider_media_id: str = "asset-1",
    provider: str = "ytdlp",
    extractor: str = "Youtube",
    author: str = "xakuraii",
) -> MediaItem:
    return MediaItem(
        id=f"item-{provider_media_id}",
        source_url="https://www.youtube.com/@alice",
        original_url=f"https://cdn.example.com/{provider_media_id}.mp4",
        media_type=media_type,
        author=author,
        provider=provider,
        provider_media_id=provider_media_id,
        metadata_extra={"extractor": extractor},
    )


def test_record_download_writes_manifest_next_to_file(isolated_download_dir: Path) -> None:
    item = _item()
    folder = destination_directory(item)
    folder.mkdir(parents=True)
    file_path = folder / "xakuraii-vdo-1.mp4"
    file_path.touch()

    identity = record_download(item, file_path)

    data = load_manifest(folder)
    assert manifest_path(folder).name == MANIFEST_FILENAME
    entry = data["items"][identity]
    assert entry["status"] == "downloaded"
    assert entry["filename"] == "xakuraii-vdo-1.mp4"
    assert entry["original_url"] == item.original_url
    assert entry["title"] is None
    assert "updated_at" in entry


def test_skipped_items_are_annotated_and_not_new(isolated_download_dir: Path) -> None:
    item = _item(MediaType.IMAGE, provider_media_id="picture-9", extractor="instagram")

    identities = record_skipped([item])

    raw = json.loads(manifest_path(destination_directory(item)).read_text(encoding="utf-8"))
    assert identities == [media_identity(item)]
    assert raw["items"][identities[0]]["status"] == "skipped"
    assert raw["items"][identities[0]]["filename"] is None

    rescanned = _item(MediaType.IMAGE, provider_media_id="picture-9", extractor="instagram")
    assert rescanned.library_status is None
    annotate_items([rescanned])
    assert rescanned.library_status == "skipped"


def test_downloaded_status_survives_a_rescan(isolated_download_dir: Path) -> None:
    item = _item()
    folder = destination_directory(item)
    folder.mkdir(parents=True)
    record_download(item, folder / "xakuraii-vdo-1.mp4")

    rescanned = _item()
    annotate_items([rescanned])

    assert rescanned.library_status == "downloaded"


def test_manifest_identity_is_stable_and_url_fallback() -> None:
    first = _item()
    second = _item()
    assert media_identity(first) == media_identity(second)

    no_id = MediaItem(
        source_url="https://example.com/gallery",
        original_url="https://cdn.example.com/a.jpg?token=1",
        media_type=MediaType.IMAGE,
        author="alice",
    )
    same_url = MediaItem(
        source_url="https://example.com/gallery",
        original_url="https://cdn.example.com/a.jpg?token=1",
        media_type=MediaType.IMAGE,
        author="alice",
    )
    assert media_identity(no_id) == media_identity(same_url)
    assert media_identity(no_id).startswith("url:")


def test_delete_forgets_entry_and_rename_updates_filename(
    isolated_download_dir: Path,
) -> None:
    item = _item()
    folder = destination_directory(item)
    folder.mkdir(parents=True)
    old = folder / "xakuraii-vdo-3.mp4"
    new = folder / "xakuraii-vdo-2.mp4"
    old.touch()

    record_download(item, old)
    apply_renames([(old, new)])
    assert load_manifest(folder)["items"][media_identity(item)]["filename"] == new.name

    assert remove_file(new) is True
    assert load_manifest(folder)["items"] == {}


def test_skip_rpc_records_items_in_folder_manifest(isolated_download_dir: Path) -> None:
    item = _item(MediaType.IMAGE, provider_media_id="picture-rpc", extractor="instagram")
    dispatcher = RpcDispatcher()

    response = dispatcher.dispatch(
        JsonRpcRequest(
            id="skip-1",
            method="skip_media_items",
            params={"items": [item.model_dump(mode="json")]},
        )
    )

    assert response.error is None
    assert response.result == {
        "count": 1,
        "identities": [media_identity(item)],
        "status": "skipped",
    }
    entry = load_manifest(destination_directory(item))["items"][media_identity(item)]
    assert entry["status"] == "skipped"
    assert entry["filename"] is None


def test_skip_rpc_rejects_empty_payload() -> None:
    response = RpcDispatcher().dispatch(
        JsonRpcRequest(id="skip-2", method="skip_media_items", params={"items": []})
    )

    assert response.error is not None
    assert "non-empty list" in response.error.message
