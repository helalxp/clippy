from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    subprocess.run(
        ["ffmpeg", "-version"],
        capture_output=True,
        text=True,
        check=False,
    ).returncode != 0,
    reason="Template API integration requires FFmpeg",
)


def _make_video(path: Path):
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_template_apply_api_updates_clip_from_clean_canonical_and_persists_provenance(
    tmp_path, monkeypatch
):
    import app as app_module
    from template_system.models import TemplateDocument, TemplateRecipe
    from template_system.storage import LocalTemplateStorage

    job_id = "template-api-fixture"
    output_dir = tmp_path / "output"
    job_dir = output_dir / job_id
    job_dir.mkdir(parents=True)
    metadata_path = job_dir / "fixture_metadata.json"
    clean_source = job_dir / "fixture_clip_1.mp4"
    previous_delivery = job_dir / "previous-style.mp4"
    _make_video(clean_source)
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
    finally:
        app_module.jobs.pop(job_id, None)
        app_module._rerender_locks.pop(job_id, None)


async def _async_noop(*args, **kwargs):
    return None


async def _async_none(*args, **kwargs):
    return None


async def _async_filename(request, job_id, filename):
    return filename
