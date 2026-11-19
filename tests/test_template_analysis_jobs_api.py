from __future__ import annotations

import asyncio
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
