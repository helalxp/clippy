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
    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "require_managed_entitlement", _async_noop)
    monkeypatch.setattr(app_module, "_ensure_job_files", _async_noop)
    monkeypatch.setattr(app_module, "_assert_job_owner", _async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _async_none)
    monkeypatch.setattr(app_module, "_deliver", _async_filename)
    monkeypatch.setattr(app_module, "_archive_clip_edit_bg", lambda *args: None)
    app_module._rerender_locks[job_id] = asyncio.Lock()

    scope = hashlib.sha256(b"local-installation").hexdigest()[:32]
    storage = LocalTemplateStorage(output_dir / "template_library" / scope)
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
