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


def test_manifest_tracks_downloaded_and_skipped_counts(isolated_download_dir: Path) -> None:
    vid = _item(MediaType.VIDEO, provider_media_id="v1", extractor="youtube")
    vid_skip = _item(MediaType.VIDEO, provider_media_id="v2", extractor="youtube")
    folder = destination_directory(vid)
    folder.mkdir(parents=True)
    record_download(vid, folder / "xakuraii-vdo-1.mp4")
    record_skipped([vid_skip])

    data = load_manifest(folder)
    assert data["counts"] == {"downloaded": 1, "skipped": 1, "total": 2}


def test_unskip_rpc_removes_skipped_entries(isolated_download_dir: Path) -> None:
    item = _item(MediaType.IMAGE, provider_media_id="pic-unskip", extractor="instagram")
    dispatcher = RpcDispatcher()

    dispatcher.dispatch(
        JsonRpcRequest(
            id="s1",
            method="skip_media_items",
            params={"items": [item.model_dump(mode="json")]},
        )
    )
    unskip_res = dispatcher.dispatch(
        JsonRpcRequest(
            id="u1",
            method="unskip_media_items",
            params={"items": [item.model_dump(mode="json")]},
        )
    )

    assert unskip_res.error is None
    assert unskip_res.result == {
        "count": 1,
        "identities": [media_identity(item)],
        "status": "unskipped",
    }
    data = load_manifest(destination_directory(item))
    assert data["items"] == {}
    assert data["counts"] == {"downloaded": 0, "skipped": 0, "total": 0}


def test_incremental_rescan_respects_folder_manifest_without_db_history(
    isolated_download_dir: Path, tmp_path: Path
) -> None:
    from unittest.mock import patch

    from xakumedia.db.repository import MediaRepository
    from xakumedia.models.source import SavedSource
    from xakumedia.sources.rescan import incremental_rescan_source

    repo = MediaRepository(tmp_path / "fresh-device.db")
    downloaded_item = _item(MediaType.IMAGE, provider_media_id="img-1", extractor="instagram")
    skipped_item = _item(MediaType.IMAGE, provider_media_id="img-2", extractor="instagram")
    new_item = _item(MediaType.IMAGE, provider_media_id="img-3", extractor="instagram")

    folder = destination_directory(downloaded_item)
    folder.mkdir(parents=True)
    record_download(downloaded_item, folder / "xakuraii-img-1.jpg")
    record_skipped([skipped_item])

    source = SavedSource(id="src-1", url="https://www.instagram.com/xakuraii/", title="xakuraii")
    repo.save_source(source)

    with patch(
        "xakumedia.sources.rescan.scan_source_url",
        return_value=(None, [downloaded_item, skipped_item, new_item]),
    ):
        result = incremental_rescan_source(source, repository=repo)

    assert result.total_found == 3
    assert [i.provider_media_id for i in result.new_items] == ["img-3"]
    assert {i.provider_media_id for i in result.existing_items} == {"img-1", "img-2"}


def test_cross_device_detection_matches_provider_id_or_url(
    isolated_download_dir: Path,
) -> None:
    saved = _item(MediaType.VIDEO, provider="ytdlp", provider_media_id="vid-99", extractor="tiktok")
    record_skipped([saved])

    # Different provider wrapper / missing provider name on another scan still matches
    # by provider_media_id or original_url inside the creator's manifest.
    rescanned = MediaItem(
        id="new-uuid",
        source_url="https://www.tiktok.com/@xakuraii",
        original_url=saved.original_url,
        media_type=MediaType.VIDEO,
        author="xakuraii",
        provider="gallerydl",
        provider_media_id="vid-99",
        metadata_extra={"extractor": "TikTok"},
    )
    annotate_items([rescanned])
    assert rescanned.library_status == "skipped"


def test_scan_download_library_and_actions(isolated_download_dir: Path) -> None:
    from xakumedia.downloader.library import scan_download_library

    vid_dl = _item(MediaType.VIDEO, provider_media_id="v-1", extractor="tiktok")
    vid_skip = _item(MediaType.VIDEO, provider_media_id="v-2", extractor="tiktok")
    img_dl = _item(MediaType.IMAGE, provider_media_id="i-1", extractor="instagram")

    vid_dir = destination_directory(vid_dl)
    vid_dir.mkdir(parents=True)
    vid_file = vid_dir / "xakuraii-vdo-1.mp4"
    vid_file.write_bytes(b"video-bytes")
    record_download(vid_dl, vid_file)
    record_skipped([vid_skip])

    img_dir = destination_directory(img_dl)
    img_dir.mkdir(parents=True)
    img_file = img_dir / "xakuraii-img-1.jpg"
    img_file.write_bytes(b"img-bytes")
    record_download(img_dl, img_file)

    # Unrelated folders without xakumedia-library.json must be ignored.
    unrelated = isolated_download_dir / "ThirdPartyApp" / "someone" / "Videos"
    unrelated.mkdir(parents=True)
    (unrelated / "other-1.mp4").write_bytes(b"ignored")

    snapshot = scan_download_library(isolated_download_dir)
    assert snapshot["totals"]["platforms"] == 2
    assert snapshot["totals"]["downloaded"] == 2
    assert snapshot["totals"]["skipped"] == 1
    assert snapshot["totals"]["videos"] == 1
    assert snapshot["totals"]["images"] == 1

    dispatcher = RpcDispatcher()
    stats_res = dispatcher.dispatch(JsonRpcRequest(id="lib-stats", method="get_library_stats"))
    assert stats_res.error is None
    assert stats_res.result["images"] == 1
    assert stats_res.result["videos"] == 1
    assert stats_res.result["skipped"] == 1
    assert stats_res.result["users"] == 2
    assert stats_res.result["media_total"] == 2

    tiktok = next(p for p in snapshot["platforms"] if p["name"] == "Tiktok")
    user = tiktok["users"][0]
    assert user["name"] == "xakuraii"
    assert user["downloaded_count"] == 1
    assert user["skipped_count"] == 1
    assert [entry["status"] for entry in user["folders"][0]["items"]] == ["downloaded", "skipped"]

    # RPC unskip_library_entry + delete_library_file
    dispatcher = RpcDispatcher()
    unskip_res = dispatcher.dispatch(
        JsonRpcRequest(
            id="lib-unskip",
            method="unskip_library_entry",
            params={"folder_path": str(vid_dir), "identity": media_identity(vid_skip)},
        )
    )
    assert unskip_res.error is None
    assert unskip_res.result["removed"] is True

    del_res = dispatcher.dispatch(
        JsonRpcRequest(
            id="lib-del",
            method="delete_library_file",
            params={"file_path": str(vid_file)},
        )
    )
    assert del_res.error is None
    assert del_res.result["deleted"] is True
    assert not vid_file.exists()

    # Path traversal must be rejected
    bad_del = dispatcher.dispatch(
        JsonRpcRequest(
            id="lib-bad",
            method="delete_library_file",
            params={"file_path": str(isolated_download_dir.parent / "outside.mp4")},
        )
    )
    assert bad_del.error is not None
