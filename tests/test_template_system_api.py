from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_template_apply_api_updates_clip_from_clean_canonical_and_persists_provenance(
    tmp_path, monkeypatch
):
    import app as app_module
    from template_system.models import TemplateDocument, TemplateRecipe
    from template_system.service import TemplateApplicationService
    from template_system.storage import LocalTemplateStorage

    job_id = "template-api-fixture"
    output_dir = tmp_path / "output"
    job_dir = output_dir / job_id
    job_dir.mkdir(parents=True)
    metadata_path = job_dir / "fixture_metadata.json"
    clean_source = job_dir / "fixture_clip_1.mp4"
    previous_delivery = job_dir / "previous-style.mp4"
    clean_source.write_bytes(b"clean canonical source fixture")
    previous_delivery.write_bytes(b"previous derivative is deliberately not a video")

    metadata = {
        "shorts": [{
            "start": 0,
            "end": 2,
            "video_url": f"/videos/{job_id}/{previous_delivery.name}",
        }]
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    app_module.jobs[job_id] = {
        "status": "completed",
        "result": {"clips": [dict(metadata["shorts"][0])]},
    }

    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(output_dir))
    template_library_dir = tmp_path / "template-library"
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(template_library_dir))
    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_ensure_job_files", _async_noop)
    monkeypatch.setattr(app_module, "_assert_job_owner", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _async_none)
    monkeypatch.setattr(app_module, "_deliver", _async_filename)
    monkeypatch.setattr(app_module, "_archive_clip_edit_bg", lambda *args: None)
    app_module._rerender_locks[job_id] = asyncio.Lock()

    scope = hashlib.sha256(b"local-installation").hexdigest()[:32]
    storage = LocalTemplateStorage(template_library_dir / scope)
    template = TemplateDocument(
        id="tpl_api_fixture001",
        name="API integration fixture",
        recipe=TemplateRecipe.model_validate({
            "canvas": {"width": 360, "height": 640, "fps": 24},
            "framing": {"mode": "contain"},
            "background": {"mode": "solid", "color": "#112233"},
        }),
    )
    storage.create(template)

    rendered_paths = []

    def fake_apply(self, template_id, source_path, output_path, **kwargs):
        assert Path(source_path) == clean_source
        Path(output_path).write_bytes(b"rendered template fixture")
        rendered_paths.append(Path(output_path))
        compatibility = SimpleNamespace(as_dict=lambda: {"status": "compatible"})
        render = SimpleNamespace(
            output_path=Path(output_path),
            source_fingerprint="a" * 64,
            output_fingerprint="b" * 64,
            duration_seconds=2.0,
            width=360,
            height=640,
            frame_rate=24.0,
            has_audio=False,
            compatibility=compatibility,
        )
        return SimpleNamespace(
            template_id=template.id,
            resolved_recipe=SimpleNamespace(
                model_dump=lambda **options: {"canvas": {"width": 360, "height": 640}}
            ),
            render=render,
            to_dict=lambda: {
                "template_id": template.id,
                "template_name": template.name,
                "template_revision": 1,
                "recipe_hash": "c" * 64,
                "output_filename": Path(output_path).name,
                "source_fingerprint": "a" * 64,
                "output_fingerprint": "b" * 64,
                "adaptation_decisions": [],
                "locked_paths": [],
            },
        )

    monkeypatch.setattr(TemplateApplicationService, "apply", fake_apply)

    request = SimpleNamespace()
    req = app_module.TemplateApplyRequest(
        job_id=job_id,
        clip_index=0,
        template_id=template.id,
    )
    original_source = clean_source.read_bytes()

    try:
        response = asyncio.run(app_module.apply_template_to_clip(req, request))
        saved = json.loads(metadata_path.read_text(encoding="utf-8"))
        clip = saved["shorts"][0]

        assert response["success"] is True
        assert clip["video_url"] == response["new_video_url"]
        assert clip["template_id"] == template.id
        assert clip["template_application"]["template_revision"] == 1
        assert clip["template_application"]["source_filename"] == clean_source.name
        assert clip["template_application"]["source_fingerprint"]
        assert clip["template_application"]["output_fingerprint"]
        assert "output_path" not in clip["template_application"]
        assert (job_dir / clip["template_application"]["output_filename"]).is_file()
        assert clean_source.read_bytes() == original_source
        assert app_module.jobs[job_id]["result"]["clips"][0]["template_id"] == template.id

        # A metadata replacement failure must leave the last valid manifest and
        # served render intact, and remove only the uncommitted new render.
        previous_metadata = metadata_path.read_bytes()
        previous_video_url = clip["video_url"]

        def fail_metadata_replace(source, destination):
            raise OSError("simulated atomic metadata replacement failure")

        monkeypatch.setattr(app_module.os, "replace", fail_metadata_replace)
        with pytest.raises(HTTPException) as failed:
            asyncio.run(app_module.apply_template_to_clip(req, request))

        assert failed.value.status_code == 500
        assert metadata_path.read_bytes() == previous_metadata
        assert json.loads(metadata_path.read_text(encoding="utf-8"))["shorts"][0]["video_url"] == previous_video_url
        assert rendered_paths[0].is_file()
        assert len(rendered_paths) == 2
        assert not rendered_paths[1].exists()
    finally:
        app_module.jobs.pop(job_id, None)
        app_module._rerender_locks.pop(job_id, None)


async def _async_noop(*args, **kwargs):
    return None


async def _async_none(*args, **kwargs):
    return None


async def _async_filename(request, job_id, filename):
    return filename



def test_template_apply_api_blocks_managed_mode_without_durable_user_storage(monkeypatch):
    import app as app_module
    from fastapi import HTTPException

    monkeypatch.setattr(app_module, "BILLING_ENABLED", True)
    req = app_module.TemplateApplyRequest(
        job_id="job-not-read",
        clip_index=0,
        template_id="tpl_api_fixture001",
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(app_module.apply_template_to_clip(req, SimpleNamespace()))

    assert raised.value.status_code == 503
    assert "durable per-user storage" in raised.value.detail


def test_template_library_api_supports_owner_scoped_crud_and_revision_checks(
    tmp_path, monkeypatch
):
    import app as app_module
    from fastapi import HTTPException
    from template_system.models import TemplateDocument, TemplateRecipe

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _request_owner_id)
    request = SimpleNamespace(owner_id="creator-a")

    original = TemplateDocument(
        id="tpl_library_crud01",
        name="Initial template",
        recipe=TemplateRecipe.model_validate({"canvas": {"width": 720}}),
    )
    created = asyncio.run(
        app_module.create_template(original.to_storage_dict(), request)
    )
    assert created["template"]["id"] == original.id
    assert created["template"]["revision"] == 1

    listed = asyncio.run(app_module.list_templates(request))
    assert [item["id"] for item in listed["templates"]] == [original.id]

    fetched = asyncio.run(app_module.get_template(original.id, request))
    assert fetched["template"]["name"] == "Initial template"

    changed = original.model_copy(
        update={
            "revision": 2,
            "name": "Updated template",
            "recipe": TemplateRecipe.model_validate({"canvas": {"width": 900}}),
        }
    )
    updated = asyncio.run(
        app_module.update_template(
            original.id,
            {
                "expected_revision": 1,
                "template": changed.to_storage_dict(),
            },
            request,
        )
    )
    assert updated["template"]["revision"] == 2
    assert updated["template"]["name"] == "Updated template"
    assert updated["template"]["recipe"]["canvas"]["width"] == 900
    from datetime import datetime

    def parse_timestamp(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse_timestamp(updated["template"]["updated_at"]) > parse_timestamp(
        created["template"]["updated_at"]
    )

    with pytest.raises(HTTPException) as stale:
        asyncio.run(
            app_module.update_template(
                original.id,
                {
                    "expected_revision": 1,
                    "template": changed.to_storage_dict(),
                },
                request,
            )
        )
    assert stale.value.status_code == 409

    stale_delete_request = SimpleNamespace(
        owner_id="creator-a",
        query_params={"expected_revision": "1"},
    )
    with pytest.raises(HTTPException) as stale_delete:
        asyncio.run(app_module.delete_template(original.id, stale_delete_request))
    assert stale_delete.value.status_code == 409

    delete_request = SimpleNamespace(
        owner_id="creator-a",
        query_params={"expected_revision": "2"},
    )
    deleted = asyncio.run(app_module.delete_template(original.id, delete_request))
    assert deleted == {"success": True, "template_id": original.id}
    with pytest.raises(HTTPException) as missing:
        asyncio.run(app_module.get_template(original.id, request))
    assert missing.value.status_code == 404


def test_template_library_api_isolates_templates_between_owners(tmp_path, monkeypatch):
    import app as app_module
    from fastapi import HTTPException
    from template_system.models import TemplateDocument

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _request_owner_id)

    document = TemplateDocument(
        id="tpl_owner_isolation01",
        name="Private template",
    )
    owner_a = SimpleNamespace(owner_id="owner-a")
    owner_b = SimpleNamespace(owner_id="owner-b")
    asyncio.run(app_module.create_template(document.to_storage_dict(), owner_a))

    with pytest.raises(HTTPException) as hidden:
        asyncio.run(app_module.get_template(document.id, owner_b))
    assert hidden.value.status_code == 404
    assert asyncio.run(app_module.list_templates(owner_b))["templates"] == []


def test_template_library_api_rejects_asset_manifests_until_upload_api_exists(
    tmp_path, monkeypatch
):
    import app as app_module
    from fastapi import HTTPException
    from template_system.models import TemplateDocument, TemplateAsset

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _request_owner_id)

    payload = TemplateDocument(
        id="tpl_asset_gate01",
        name="Asset-bearing template",
        assets=[
            TemplateAsset(
                id="asset_logo",
                path="assets/logo.png",
                media_type="image/png",
                size_bytes=1,
                sha256="0" * 64,
                width=1,
                height=1,
            )
        ],
    ).to_storage_dict()

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(
            app_module.create_template(payload, SimpleNamespace(owner_id="owner-a"))
        )
    assert rejected.value.status_code == 422
    assert "asset upload is not available" in rejected.value.detail.lower()


def test_template_library_api_is_disabled_in_managed_mode(monkeypatch):
    import app as app_module
    from fastapi import HTTPException

    monkeypatch.setattr(app_module, "BILLING_ENABLED", True)
    with pytest.raises(HTTPException) as blocked:
        asyncio.run(app_module.list_templates(SimpleNamespace(owner_id="owner-a")))
    assert blocked.value.status_code == 503


async def _request_owner_id(request):
    return request.owner_id


def test_template_library_api_uploads_and_removes_owner_scoped_image_assets(
    tmp_path, monkeypatch
):
    import hashlib
    import io
    from PIL import Image
    import app as app_module
    from fastapi import HTTPException
    from template_system.models import TemplateDocument

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _request_owner_id)

    document = TemplateDocument(
        id="tpl_asset_upload01",
        name="Asset upload fixture",
    )
    owner = SimpleNamespace(owner_id="asset-owner")
    asyncio.run(app_module.create_template(document.to_storage_dict(), owner))

    image_bytes = io.BytesIO()
    Image.new("RGBA", (32, 16), (20, 40, 60, 255)).save(image_bytes, format="PNG")
    payload = image_bytes.getvalue()
    upload = _FakeTemplateUpload(payload, "image/png")
    upload_request = _FakeMultipartRequest(
        owner_id="asset-owner",
        form_data={"file": upload, "expected_revision": "1"},
    )

    response = asyncio.run(
        app_module.upload_template_asset(document.id, upload_request)
    )
    asset = response["asset"]
    assert asset["id"].startswith("asset_")
    assert asset["path"] == f"assets/{asset['id']}.png"
    assert asset["media_type"] == "image/png"
    assert (asset["width"], asset["height"]) == (32, 16)
    assert asset["size_bytes"] == len(payload)
    assert asset["sha256"] == hashlib.sha256(payload).hexdigest()
    assert response["template_revision"] == 2

    scope = hashlib.sha256(b"asset-owner").hexdigest()[:32]
    asset_path = (
        tmp_path / "libraries" / scope / document.id / asset["path"]
    )
    assert asset_path.read_bytes() == payload

    stale_delete = _FakeMultipartRequest(
        owner_id="asset-owner",
        query_params={"expected_revision": "1"},
    )
    with pytest.raises(HTTPException) as stale:
        asyncio.run(
            app_module.delete_template_asset(document.id, asset["id"], stale_delete)
        )
    assert stale.value.status_code == 409
    assert asset_path.is_file()

    delete_request = _FakeMultipartRequest(
        owner_id="asset-owner",
        query_params={"expected_revision": "2"},
    )
    deleted = asyncio.run(
        app_module.delete_template_asset(document.id, asset["id"], delete_request)
    )
    assert deleted == {
        "success": True,
        "asset_id": asset["id"],
        "template_revision": 3,
    }
    assert not asset_path.exists()

    final = asyncio.run(app_module.get_template(document.id, owner))
    assert final["template"]["assets"] == []
    assert final["template"]["revision"] == 3


def test_template_library_api_rejects_mismatched_asset_mime_type(
    tmp_path, monkeypatch
):
    import io
    from PIL import Image
    import app as app_module
    from fastapi import HTTPException
    from template_system.models import TemplateDocument

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _request_owner_id)

    document = TemplateDocument(id="tpl_asset_mime01", name="MIME fixture")
    owner = SimpleNamespace(owner_id="asset-owner")
    asyncio.run(app_module.create_template(document.to_storage_dict(), owner))

    image_bytes = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(image_bytes, format="PNG")
    request = _FakeMultipartRequest(
        owner_id="asset-owner",
        form_data={
            "file": _FakeTemplateUpload(image_bytes.getvalue(), "image/jpeg"),
            "expected_revision": "1",
        },
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.upload_template_asset(document.id, request))
    assert rejected.value.status_code == 415
    assert asyncio.run(app_module.get_template(document.id, owner))["template"]["assets"] == []


class _FakeTemplateUpload:
    def __init__(self, payload, content_type):
        self.payload = payload
        self.content_type = content_type
        self.filename = "untrusted-client-name.png"
        self.closed = False

    async def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]

    async def close(self):
        self.closed = True


class _FakeMultipartRequest:
    def __init__(self, *, owner_id, form_data=None, query_params=None):
        self.owner_id = owner_id
        self.headers = {}
        self.query_params = query_params or {}
        self._form_data = form_data or {}

    async def form(self, **kwargs):
        assert kwargs.get("max_files") == 1
        assert kwargs.get("max_fields") == 1
        return self._form_data


async def _request_owner_id(request):
    return request.owner_id
