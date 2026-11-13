from __future__ import annotations

import hashlib
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError

from template_system.models import TemplateAsset, TemplateDocument
from template_system.storage import (
    LocalTemplateStorage,
    TemplateAlreadyExists,
    TemplateAssetInUse,
    TemplateIntegrityError,
    TemplateNotFound,
    TemplateRevisionConflict,
)


def make_document(template_id="tpl_storage123", *, assets=(), revision=1, created_at=None, updated_at=None):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return TemplateDocument.model_validate({
        "id": template_id,
        "name": "Storage fixture",
        "revision": revision,
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "assets": [asset.model_dump() for asset in assets],
    })


def make_asset(payload=b"logo-bytes", *, path="assets/logo.png", asset_id="logo"):
    return TemplateAsset(
        id=asset_id,
        path=path,
        media_type="image/png",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )



def _process_create(root, document_data, result_queue):
    storage = LocalTemplateStorage(root)
    document = TemplateDocument.model_validate(document_data)
    try:
        storage.create(document)
        result_queue.put("created")
    except TemplateAlreadyExists:
        result_queue.put("exists")


def _process_update(root, document_data, name, result_queue):
    storage = LocalTemplateStorage(root)
    document = TemplateDocument.model_validate(document_data)
    updated = document.model_copy(update={"revision": document.revision + 1, "name": name})
    try:
        storage.update(updated, expected_revision=document.revision)
        result_queue.put("saved")
    except TemplateRevisionConflict:
        result_queue.put("conflict")


def test_create_get_and_list_template(tmp_path):
    storage = LocalTemplateStorage(tmp_path / "library")
    document = make_document()

    storage.create(document)

    assert storage.get(document.id).name == document.name
    assert [item.id for item in storage.list()] == [document.id]


def test_create_rejects_duplicate_template(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document()
    storage.create(document)

    with pytest.raises(TemplateAlreadyExists):
        storage.create(document)


def test_create_writes_and_verifies_asset_bytes(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    payload = b"brand-logo"
    asset = make_asset(payload)
    document = make_document(assets=[asset])

    storage.create(document, asset_payloads={"logo": payload})

    assert storage.get(document.id).assets[0].sha256 == asset.sha256
    assert (tmp_path / document.id / "assets" / "logo.png").read_bytes() == payload


def test_create_rejects_missing_asset_payload(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document(assets=[make_asset()])

    with pytest.raises(TemplateIntegrityError, match="payload mismatch"):
        storage.create(document)

    assert not (tmp_path / document.id).exists()


def test_create_rejects_asset_checksum_mismatch(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document(assets=[make_asset(b"expected")])

    with pytest.raises(TemplateIntegrityError, match="checksum"):
        storage.create(document, asset_payloads={"logo": b"tampered"})

    assert not (tmp_path / document.id).exists()


def test_get_rejects_missing_or_modified_asset(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    payload = b"image"
    document = make_document(assets=[make_asset(payload)])
    storage.create(document, asset_payloads={"logo": payload})
    (tmp_path / document.id / "assets" / "logo.png").write_bytes(b"changed")

    with pytest.raises(TemplateIntegrityError, match="size|checksum"):
        storage.get(document.id)


def test_get_rejects_malformed_manifest(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document()
    storage.create(document)
    (tmp_path / document.id / "manifest.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(TemplateIntegrityError, match="manifest is invalid"):
        storage.get(document.id)


def test_update_requires_expected_revision_and_increments(tmp_path):
    from datetime import datetime, timezone

    storage = LocalTemplateStorage(tmp_path)
    original = make_document()
    storage.create(original)
    updated = original.model_copy(update={
        "revision": 2,
        "name": "Updated",
        "updated_at": datetime.now(timezone.utc) + timedelta(seconds=1),
    })

    saved = storage.update(updated, expected_revision=1)

    assert saved.revision == 2
    assert storage.get(original.id).name == "Updated"
    with pytest.raises(TemplateRevisionConflict):
        storage.update(updated, expected_revision=1)


def test_failed_update_preserves_previous_manifest(tmp_path, monkeypatch):
    storage = LocalTemplateStorage(tmp_path)
    original = make_document()
    storage.create(original)
    updated = original.model_copy(update={"revision": 2, "name": "Not committed"})

    def fail_write(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(storage, "_atomic_write_manifest", fail_write)
    with pytest.raises(OSError, match="simulated"):
        storage.update(updated, expected_revision=1)

    monkeypatch.undo()
    assert storage.get(original.id).name == original.name
    assert storage.get(original.id).revision == 1


def test_update_cannot_change_asset_inventory(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    original = make_document()
    storage.create(original)
    updated = original.model_copy(update={"revision": 2, "assets": [make_asset()]})

    with pytest.raises(TemplateIntegrityError, match="asset inventory"):
        storage.update(updated, expected_revision=1)


def test_delete_removes_only_target_template(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    first, second = make_document("tpl_first123"), make_document("tpl_second123")
    storage.create(first)
    storage.create(second)

    storage.delete(first.id)

    with pytest.raises(TemplateNotFound):
        storage.get(first.id)
    assert storage.get(second.id).id == second.id


def test_delete_missing_template_raises(tmp_path):
    storage = LocalTemplateStorage(tmp_path)

    with pytest.raises(TemplateNotFound):
        storage.delete("tpl_missing123")


def test_template_id_cannot_escape_library_root(tmp_path):
    storage = LocalTemplateStorage(tmp_path)

    with pytest.raises(ValueError, match="invalid template id"):
        storage.get("../outside")


def test_asset_path_symlink_escape_is_rejected(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document(assets=[make_asset(path="assets/logo.png")])
    storage.create(document, asset_payloads={"logo": b"logo-bytes"})
    template_dir = tmp_path / document.id
    outside = tmp_path / "outside"
    outside.mkdir()
    link = template_dir / "assets" / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable in this environment")

    with pytest.raises(TemplateIntegrityError):
        storage._asset_path(template_dir, "assets/link/payload.bin")


def test_concurrent_creates_do_not_overwrite_each_other(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document()

    def create():
        try:
            storage.create(document)
            return "created"
        except TemplateAlreadyExists:
            return "exists"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: create(), range(8)))

    assert outcomes.count("created") == 1
    assert outcomes.count("exists") == 7
    assert storage.get(document.id).id == document.id


def test_concurrent_revision_updates_use_compare_and_swap(tmp_path):
    from datetime import datetime, timezone

    storage = LocalTemplateStorage(tmp_path)
    original = make_document()
    storage.create(original)
    barrier = threading.Barrier(2)

    def update(name):
        updated = original.model_copy(update={
            "revision": 2,
            "name": name,
            "updated_at": datetime.now(timezone.utc) + timedelta(seconds=1),
        })
        barrier.wait()
        try:
            storage.update(updated, expected_revision=1)
            return "saved"
        except TemplateRevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(update, ("A", "B")))

    assert outcomes.count("saved") == 1
    assert outcomes.count("conflict") == 1
    assert storage.get(original.id).revision == 2



def test_cross_process_creates_are_serialized_by_file_lock(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    document = make_document()
    payload = document.model_dump(mode="json", by_alias=True)
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    workers = [
        context.Process(target=_process_create, args=(str(tmp_path), payload, results))
        for _ in range(2)
    ]

    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    outcomes = [results.get(timeout=5), results.get(timeout=5)]
    assert outcomes.count("created") == 1
    assert outcomes.count("exists") == 1
    assert storage.get(document.id).id == document.id


def test_cross_process_revision_updates_use_file_lock(tmp_path):
    storage = LocalTemplateStorage(tmp_path)
    original = make_document()
    storage.create(original)
    payload = original.model_dump(mode="json", by_alias=True)
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    workers = [
        context.Process(
            target=_process_update,
            args=(str(tmp_path), payload, name, results),
        )
        for name in ("Worker A", "Worker B")
    ]

    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    outcomes = [results.get(timeout=5), results.get(timeout=5)]
    assert outcomes.count("saved") == 1
    assert outcomes.count("conflict") == 1
    assert storage.get(original.id).revision == 2


def test_add_and_remove_asset_uses_revision_checks_and_preserves_manifest(
    tmp_path,
):
    storage = LocalTemplateStorage(tmp_path / "library")
    document = make_document()
    storage.create(document)

    payload = b"new-template-image-bytes"
    asset = make_asset(payload, path="assets/asset_logo.png", asset_id="asset_logo")
    updated = storage.add_asset(
        document.id,
        asset,
        payload,
        expected_revision=1,
    )
    assert updated.revision == 2
    assert storage.get(document.id).assets == [asset]
    stored_path = tmp_path / "library" / document.id / asset.path
    assert stored_path.read_bytes() == payload

    with pytest.raises(TemplateRevisionConflict):
        storage.add_asset(document.id, asset, payload, expected_revision=1)

    with pytest.raises(TemplateRevisionConflict):
        storage.remove_asset(document.id, asset.id, expected_revision=1)
    assert stored_path.is_file()

    removed = storage.remove_asset(document.id, asset.id, expected_revision=2)
    assert removed.revision == 3
    assert removed.assets == []
    assert not stored_path.exists()
    assert storage.get(document.id).assets == []


def test_remove_asset_refuses_to_delete_a_text_overlay_font(tmp_path):
    from datetime import datetime, timezone

    storage = LocalTemplateStorage(tmp_path / "library")
    document = make_document()
    storage.create(document)
    payload = b"referenced-text-font"
    asset = TemplateAsset(
        id="asset_textfont",
        path="assets/textfont.ttf",
        media_type="font/ttf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    added = storage.add_asset(document.id, asset, payload, expected_revision=1)

    data = added.model_dump(mode="python", by_alias=True)
    data["revision"] = 3
    data["updated_at"] = datetime.now(timezone.utc)
    data["recipe"] = {
        "overlays": [{
            "id": "brand-copy",
            "kind": "text",
            "text": "Brand",
            "font_asset_id": asset.id,
        }],
    }
    referenced = TemplateDocument.model_validate(data)
    storage.update(referenced, expected_revision=2)

    with pytest.raises(TemplateAssetInUse):
        storage.remove_asset(document.id, asset.id, expected_revision=3)

    assert storage.get(document.id).assets == [asset]
    assert (tmp_path / "library" / document.id / asset.path).read_bytes() == payload


def test_remove_asset_refuses_to_delete_an_asset_still_referenced_by_recipe(
    tmp_path,
):
    from datetime import datetime, timezone

    from template_system.models import TemplateDocument

    storage = LocalTemplateStorage(tmp_path / "library")
    document = make_document()
    storage.create(document)
    payload = b"referenced-image"
    asset = make_asset(payload, path="assets/referenced.png", asset_id="asset_ref")
    added = storage.add_asset(document.id, asset, payload, expected_revision=1)

    data = added.model_dump(mode="python", by_alias=True)
    data["revision"] = 3
    data["updated_at"] = datetime.now(timezone.utc)
    data["recipe"] = {
        "overlays": [
            {
                "id": "brand-mark",
                "kind": "image",
                "asset_id": asset.id,
            }
        ]
    }
    referenced = TemplateDocument.model_validate(data)
    storage.update(referenced, expected_revision=2)

    with pytest.raises(TemplateAssetInUse):
        storage.remove_asset(document.id, asset.id, expected_revision=3)

    assert storage.get(document.id).assets == [asset]
    assert (tmp_path / "library" / document.id / asset.path).read_bytes() == payload
