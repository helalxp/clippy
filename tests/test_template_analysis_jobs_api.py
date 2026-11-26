from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app as app_module
from template_system.jobs import AnalysisJobStore


class FakeUpload:
    def __init__(self, payload=b"reference-video", filename="reference.mp4"):
        self.payload = payload
        self.filename = filename
        self.closed = False

    async def read(self, size=-1):
        if not self.payload:
            return b""
        if size < 0:
            chunk, self.payload = self.payload, b""
            return chunk
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk

    async def close(self):
        self.closed = True


def _configure(monkeypatch, tmp_path):
    store = AnalysisJobStore(tmp_path / "persistent-template-analysis")
    monkeypatch.setattr(app_module, "_template_analysis_store", lambda: store)
    monkeypatch.setattr(app_module, "_assert_data_storage_available", lambda: None)
    monkeypatch.setattr(app_module, "_reference_templates_local_only", lambda: None)
    monkeypatch.setattr(app_module, "MAX_FILE_SIZE_MB", 1)
    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    return store


def test_upload_endpoint_uses_the_explicit_gemini_request_header(
    tmp_path, monkeypatch
):
    store = _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    scheduled = []
    monkeypatch.setattr(
        app_module,
        "_schedule_template_analysis_job",
        lambda job_id, api_key=None: scheduled.append((job_id, api_key)),
    )
    request = SimpleNamespace(headers={"X-Gemini-Key": "header-only-test-key"})
    upload = FakeUpload()

    response = asyncio.run(app_module.create_template_analysis_job(
        request, upload, "My reference", "Podcast", True, True
    ))

    job = response["job"]
    assert job["gemini_consent"] is True
    assert scheduled == [(job["id"], "header-only-test-key")]
    assert "api_key" not in store.get(job["id"])
    assert upload.closed is True


def test_local_template_library_failure_returns_diagnostic_and_logs_traceback(
    monkeypatch, caplog
):
    monkeypatch.setattr(app_module, "_assert_data_storage_available", lambda: None)
    monkeypatch.setattr(app_module, "_reference_templates_local_only", lambda: None)

    def missing_package():
        raise ModuleNotFoundError("template_system")

    monkeypatch.setattr(app_module, "_template_system_storage", missing_package)

    with caplog.at_level(logging.ERROR, logger="clippy.template_analysis"):
        with pytest.raises(HTTPException) as failure:
            asyncio.run(app_module.list_template_system_documents())

    assert failure.value.status_code == 500
    assert "diagnostic ID:" in failure.value.detail
    assert "template_system" not in failure.value.detail
    assert any(
        record.exc_info and "Could not read local template library" in record.message
        for record in caplog.records
    )


def test_template_analysis_list_failure_returns_diagnostic_and_logs_traceback(
    monkeypatch, caplog
):
    monkeypatch.setattr(app_module, "_assert_data_storage_available", lambda: None)
    monkeypatch.setattr(app_module, "_reference_templates_local_only", lambda: None)

    def missing_package():
        raise ModuleNotFoundError("template_system")

    monkeypatch.setattr(app_module, "_template_analysis_store", missing_package)

    with caplog.at_level(logging.ERROR, logger="clippy.template_analysis"):
        with pytest.raises(HTTPException) as failure:
            asyncio.run(app_module.list_template_analysis_jobs())

    assert failure.value.status_code == 500
    assert "diagnostic ID:" in failure.value.detail
    assert any(
        record.exc_info and "Could not list reference-analysis jobs" in record.message
        for record in caplog.records
    )


def test_upload_endpoint_creates_job_and_schedules_without_applying_generation(
    tmp_path, monkeypatch
):
    store = _configure(monkeypatch, tmp_path)
    scheduled = []
    async def resolve_key(_request):
        return "temporary-request-key"

    monkeypatch.setattr(app_module, "resolve_gemini", resolve_key)
    monkeypatch.setattr(
        app_module,
        "_schedule_template_analysis_job",
        lambda job_id, api_key=None: scheduled.append((job_id, api_key)),
    )
    upload = FakeUpload()
    response = asyncio.run(app_module.create_template_analysis_job(
        SimpleNamespace(),
        upload,
        "My reference",
        "Podcast",
        True,
        True,
    ))

    job = response["job"]
    assert job["status"] == "queued"
    assert job["gemini_consent"] is True
    assert job["original_filename"] == "reference.mp4"
    assert store.source_path(job["id"]).read_bytes() == b"reference-video"
    assert "api_key" not in store.get(job["id"])
    assert scheduled == [(job["id"], "temporary-request-key")]
    assert upload.closed is True


def test_upload_endpoint_requires_rights_confirmation(tmp_path, monkeypatch):
    _configure(monkeypatch, tmp_path)
    upload = FakeUpload()

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.create_template_analysis_job(
            SimpleNamespace(), upload, None, None, False, False
        ))

    assert rejected.value.status_code == 400
    assert upload.closed is True


def test_upload_endpoint_requires_key_when_gemini_consent_is_enabled(
    tmp_path, monkeypatch
):
    store = _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def no_key(_request):
        return None

    monkeypatch.setattr(app_module, "resolve_gemini", no_key)
    upload = FakeUpload()

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.create_template_analysis_job(
            SimpleNamespace(), upload, None, None, True, True
        ))

    assert rejected.value.status_code == 400
    assert store.list() == []
    assert upload.closed is True


def test_upload_endpoint_rejects_unsupported_file_extension(tmp_path, monkeypatch):
    _configure(monkeypatch, tmp_path)
    upload = FakeUpload(filename="reference.exe")

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.create_template_analysis_job(
            SimpleNamespace(), upload, None, None, True, False
        ))

    assert rejected.value.status_code == 400


def test_list_endpoint_returns_durable_analysis_jobs(tmp_path, monkeypatch):
    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video")
    created = store.create(staged, original_filename="reference.mp4")

    response = asyncio.run(app_module.list_template_analysis_jobs())

    assert [job["id"] for job in response["jobs"]] == [created["id"]]
    assert "source_file" not in response["jobs"][0]


def test_source_endpoint_serves_only_the_job_original_video(tmp_path, monkeypatch):
    from pathlib import Path

    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video-source")
    job = store.create(staged, original_filename="reference.mp4")

    response = asyncio.run(app_module.get_template_analysis_source(job["id"]))

    assert isinstance(response, app_module.FileResponse)
    assert Path(response.path) == store.source_path(job["id"])
    assert response.media_type == "video/mp4"
    assert "content-disposition" not in response.headers


def test_source_and_evidence_query_token_allowlist_is_exact():
    assert app_module._TEMPLATE_ANALYSIS_SOURCE_PATH_RE.fullmatch(
        "/api/template-analysis/jobs/tjob_0123456789abcdef0123456789abcdef/source"
    )
    assert not app_module._TEMPLATE_ANALYSIS_SOURCE_PATH_RE.fullmatch(
        "/api/template-analysis/jobs/tjob_0123456789abcdef0123456789abcdef/source/extra"
    )
    assert app_module._TEMPLATE_ANALYSIS_EVIDENCE_PATH_RE.fullmatch(
        "/api/template-analysis/jobs/tjob_0123456789abcdef0123456789abcdef/evidence/reference_frame_001"
    )
    assert not app_module._TEMPLATE_ANALYSIS_EVIDENCE_PATH_RE.fullmatch(
        "/api/template-analysis/jobs/tjob_0123456789abcdef0123456789abcdef/evidence/../job.json"
    )


def test_delete_endpoint_removes_terminal_analysis_and_source_files(tmp_path, monkeypatch):
    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"delete-me")
    job = store.create(staged, original_filename="delete-me.mp4")
    store.update(job["id"], status="cancelled", stage="cancelled")

    response = asyncio.run(app_module.delete_template_analysis_job(job["id"]))

    assert response == {"deleted": job["id"]}
    with pytest.raises(FileNotFoundError):
        store.get(job["id"])


def test_delete_endpoint_rejects_active_job(tmp_path, monkeypatch):
    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"do-not-delete")
    job = store.create(staged, original_filename="active.mp4")
    store.update(job["id"], status="running", stage="frame_sampling")
    task = SimpleNamespace(done=lambda: False)
    monkeypatch.setattr(app_module, "_TEMPLATE_ANALYSIS_TASKS", {job["id"]: task})

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.delete_template_analysis_job(job["id"]))

    assert rejected.value.status_code == 409
    assert store.source_path(job["id"]).read_bytes() == b"do-not-delete"


def test_list_endpoint_omits_saved_report_payload(tmp_path, monkeypatch):
    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video")
    job = store.create(staged, original_filename="reference.mp4")
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {"technical": {"duration_seconds": 15}},
        "ai_status": "complete",
        "ai_report": {"summary": "large report payload"},
    })

    response = asyncio.run(app_module.list_template_analysis_jobs())

    assert response["jobs"][0]["id"] == job["id"]
    assert "report" not in response["jobs"][0]


def test_get_endpoint_returns_report_for_selected_job(tmp_path, monkeypatch):
    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video")
    job = store.create(staged, original_filename="reference.mp4")
    report = {
        "schema_version": 1,
        "deterministic": {"technical": {"duration_seconds": 15}},
        "ai_status": "not_consented",
        "ai_report": None,
    }
    store.save_report(job["id"], report)

    response = asyncio.run(app_module.get_template_analysis_job(job["id"]))

    assert response["job"]["report"] == report


def test_review_endpoint_records_decisions_without_mutating_ai_report(tmp_path, monkeypatch):
    from template_system.reference_report import (
        EvidenceFrame,
        NormalizedBox,
        ReferenceStyleReport,
        TextRegionObservation,
        TypographyObservation,
    )

    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video")
    job = store.create(staged, original_filename="reference.mp4")
    original = ReferenceStyleReport(
        text_regions=[TextRegionObservation(
            id="caption-1",
            role="caption",
            visible_text="Original",
            box=NormalizedBox(x=0.1, y=0.7, width=0.8, height=0.1),
            typography=TypographyObservation(),
            evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
            confidence="medium",
        )]
    ).model_dump(mode="json")
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {"samples": [{"asset_id": "reference_frame_001", "timestamp_ms": 1000}]},
        "ai_status": "complete",
        "ai_report": original,
    })

    accepted = asyncio.run(app_module.update_template_analysis_review(
        job["id"],
        app_module.TemplateAnalysisReviewRequest(
            target_type="text_regions", target_id="caption-1", decision="accepted"
        ),
    ))
    rejected = asyncio.run(app_module.update_template_analysis_review(
        job["id"],
        app_module.TemplateAnalysisReviewRequest(
            target_type="text_regions", target_id="caption-1", decision="rejected",
            note="This text region was misidentified.",
        ),
    ))

    assert accepted["review"]["items"][0]["decision"] == "accepted"
    assert rejected["review"]["items"][0]["decision"] == "rejected"
    assert rejected["review"]["items"][0]["note"] == "This text region was misidentified."
    assert store.get_report(job["id"])["ai_report"] == original


def test_review_endpoint_rejects_jobs_without_ai_report(tmp_path, monkeypatch):
    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video")
    job = store.create(staged, original_filename="reference.mp4")
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {"samples": []},
        "ai_status": "not_consented",
        "ai_report": None,
    })

    with pytest.raises(HTTPException) as unavailable:
        asyncio.run(app_module.update_template_analysis_review(
            job["id"],
            app_module.TemplateAnalysisReviewRequest(
                target_type="overview", target_id="overview", decision="accepted"
            ),
        ))
    assert unavailable.value.status_code == 409



def test_review_endpoint_accepts_typed_corrections_without_mutating_report(tmp_path, monkeypatch):
    from template_system.reference_report import (
        EvidenceFrame,
        NormalizedBox,
        ReferenceStyleReport,
        TextRegionObservation,
        TypographyObservation,
    )

    store = _configure(monkeypatch, tmp_path)
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference-video")
    job = store.create(staged, original_filename="reference.mp4")
    original = ReferenceStyleReport(text_regions=[TextRegionObservation(
        id="caption-1",
        role="caption",
        visible_text="Original",
        box=NormalizedBox(x=0.1, y=0.7, width=0.8, height=0.1),
        typography=TypographyObservation(),
        evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        confidence="medium",
    )]).model_dump(mode="json")
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {"samples": [{"asset_id": "reference_frame_001", "timestamp_ms": 1000}]},
        "ai_status": "complete",
        "ai_report": original,
    })

    response = asyncio.run(app_module.update_template_analysis_review(
        job["id"],
        app_module.TemplateAnalysisReviewRequest(
            target_type="text_regions",
            target_id="caption-1",
            decision="accepted",
            correction={"visible_text": "Human corrected caption"},
        ),
    ))

    assert response["review"]["items"][0]["correction"]["visible_text"] == "Human corrected caption"
    assert store.get_report(job["id"])["ai_report"] == original


def test_analysis_scheduler_registers_task_with_desktop_maintenance_tracker(monkeypatch):
    tasks = {}
    started = asyncio.Event()
    release = asyncio.Event()
    job_id = "tjob_0123456789abcdef0123456789abcdef"

    async def hold_analysis(_job_id, _api_key=None):
        started.set()
        await release.wait()

    monkeypatch.setattr(app_module, "_TEMPLATE_ANALYSIS_TASKS", tasks)
    monkeypatch.setattr(app_module, "_run_template_analysis_job", hold_analysis)

    async def exercise():
        before = app_module._MAINTENANCE_ACTIVE_BACKGROUND_TASKS
        app_module._schedule_template_analysis_job(job_id)
        task = tasks[job_id]
        await started.wait()
        assert app_module._MAINTENANCE_ACTIVE_BACKGROUND_TASKS == before + 1
        release.set()
        await task
        await asyncio.sleep(0)
        assert app_module._MAINTENANCE_ACTIVE_BACKGROUND_TASKS == before

    asyncio.run(exercise())

def test_template_compatibility_endpoint_reports_every_renderer_without_applying(
    tmp_path, monkeypatch
):
    from template_system.models import TemplateDocument, TemplateRecipe

    _configure(monkeypatch, tmp_path)
    document = TemplateDocument(
        id="tpl_0123456789",
        name="Compatibility fixture",
        recipe=TemplateRecipe.model_validate({
            "captions": {"enabled": True},
            "transitions": [{"kind": "fade", "at_seconds": 1.0}],
        }),
    )

    class FakeTemplateStorage:
        def get(self, template_id):
            assert template_id == document.id
            return document

    monkeypatch.setattr(
        app_module, "_template_system_storage", lambda: FakeTemplateStorage()
    )

    response = asyncio.run(
        app_module.get_template_system_compatibility(document.id)
    )

    assert response["template_id"] == document.id
    assert response["revision"] == document.revision
    assert set(response["reports"]) == {
        "python_ffmpeg", "remotion_preview", "remotion_render"
    }
    assert response["reports"]["python_ffmpeg"]["unsupported"][0]["feature"] == "transitions"
    assert response["reports"]["remotion_preview"]["approximate"][0]["feature"] == "captions"
    assert response["reports"]["remotion_render"]["unsupported"][0]["feature"] == "transitions"


def test_template_compatibility_endpoint_returns_not_found_for_missing_template(
    tmp_path, monkeypatch
):
    from template_system.storage import TemplateNotFound

    _configure(monkeypatch, tmp_path)

    class MissingTemplateStorage:
        def get(self, _template_id):
            raise TemplateNotFound("tpl_0123456789")

    monkeypatch.setattr(
        app_module, "_template_system_storage", lambda: MissingTemplateStorage()
    )

    with pytest.raises(HTTPException) as missing:
        asyncio.run(
            app_module.get_template_system_compatibility("tpl_0123456789")
        )

    assert missing.value.status_code == 404
