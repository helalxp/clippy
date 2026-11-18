from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from template_system.jobs import AnalysisJobStore, execute_reference_analysis_job


def _create_job(tmp_path, *, consent=False):
    store = AnalysisJobStore(tmp_path / "template-analysis")
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"small deterministic fixture")
    job = store.create(
        staged,
        original_filename="reference.mp4",
        name="Reference",
        category="Podcast",
        gemini_consent=consent,
    )
    return store, job


def test_job_store_persists_source_metadata_and_uses_non_output_root(tmp_path):
    store, job = _create_job(tmp_path)

    assert job["status"] == "queued"
    assert job["gemini_consent"] is False
    assert store.source_path(job["id"]).read_bytes() == b"small deterministic fixture"
    assert job["source_sha256"]
    assert store.get(job["id"])["original_filename"] == "reference.mp4"


def test_job_ids_and_evidence_ids_are_strictly_validated(tmp_path):
    store, job = _create_job(tmp_path)

    with pytest.raises(ValueError, match="invalid template analysis job id"):
        store.get("../outside")
    with pytest.raises(ValueError, match="invalid reference evidence asset id"):
        store.evidence_path(job["id"], "../manifest")


def test_recovery_requeues_jobs_interrupted_while_running(tmp_path):
    store, job = _create_job(tmp_path)
    store.update(job["id"], status="running", stage="frame_sampling", progress=51)

    assert store.recover_interrupted() == [job["id"]]
    recovered = store.get(job["id"])
    assert recovered["status"] == "queued"
    assert recovered["progress"] == 0
    assert recovered["cancel_requested"] is False


def test_cancelled_queued_job_is_not_started(tmp_path):
    store, job = _create_job(tmp_path)
    store.request_cancel(job["id"])

    execute_reference_analysis_job(store, job["id"])

    result = store.get(job["id"])
    assert result["status"] == "cancelled"
    assert result["stage"] == "cancelled"

    assert result["ai_status"] == "cancelled"
    assert result["ai_error"] == "Cancellation was requested before analysis began."


def test_deterministic_analysis_is_kept_when_gemini_is_not_consented(tmp_path, monkeypatch):
    import template_system.analysis as analysis_module

    store, job = _create_job(tmp_path, consent=False)

    class FakeProbe:
        def to_dict(self):
            return {"duration_seconds": 12.0, "width": 1080, "height": 1920}

    class FakeResult:
        probe = FakeProbe()
        scene_boundaries_seconds = (2.0,)
        visual_measurements = ()
        coverage = {"media_probe": 1.0}
        status = "complete"
        limitations = ()

        def to_template_parts(self):
            return None, []

    def fake_analyze(source, output, *, progress_callback, cancel_check):
        progress_callback("frame_sampling", 0.5)
        assert cancel_check() is False
        return FakeResult()

    monkeypatch.setattr(analysis_module, "analyze_reference_video", fake_analyze)
    execute_reference_analysis_job(store, job["id"])

    saved = store.get(job["id"])
    report = store.get_report(job["id"])
    assert saved["status"] == "partial"
    assert saved["ai_status"] == "not_consented"
    assert report["deterministic"]["technical"]["duration_seconds"] == 12.0
    assert report["ai_report"] is None
    assert json.loads((store._job_dir(job["id"]) / "report.json").read_text()) == report


def test_gemini_failure_does_not_discard_deterministic_result(tmp_path, monkeypatch):
    import template_system.analysis as analysis_module

    store, job = _create_job(tmp_path, consent=True)

    class FakeProbe:
        def to_dict(self):
            return {"duration_seconds": 8.0}

    class FakeResult:
        probe = FakeProbe()
        scene_boundaries_seconds = ()
        visual_measurements = ()
        coverage = {"media_probe": 1.0}
        status = "complete"
        limitations = ()

        def to_template_parts(self):
            return None, []

    def fake_analyze(source, output, *, progress_callback, cancel_check):
        progress_callback("frame_sampling", 0.5)
        return FakeResult()

    class BrokenAnalyzer:
        def __init__(self, **kwargs):
            assert kwargs == {"consent_confirmed": True}

        def analyze(self, result, evidence_root):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(analysis_module, "analyze_reference_video", fake_analyze)
    execute_reference_analysis_job(
        store, job["id"], analyzer_factory=BrokenAnalyzer
    )

    saved = store.get(job["id"])
    report = store.get_report(job["id"])
    assert saved["status"] == "partial"
    assert saved["ai_status"] == "failed"
    assert "provider unavailable" in saved["ai_error"]
    assert report["deterministic"]["technical"]["duration_seconds"] == 8.0


def test_store_deletes_only_terminal_jobs(tmp_path):
    store, job = _create_job(tmp_path)
    with pytest.raises(ValueError, match="terminal state"):
        store.delete(job["id"])

    store.update(job["id"], status="completed", stage="complete")
    store.delete(job["id"])

    with pytest.raises(FileNotFoundError):
        store.get(job["id"])


def test_cancellation_during_gemini_preserves_deterministic_report(tmp_path, monkeypatch):
    import template_system.analysis as analysis_module
    from template_system.reference_report import ReferenceStyleReport

    store, job = _create_job(tmp_path, consent=True)

    class FakeProbe:
        has_audio = False
        def to_dict(self):
            return {"duration_seconds": 8.0}

    class FakeResult:
        probe = FakeProbe()
        scene_boundaries_seconds = ()
        visual_measurements = ()
        coverage = {"media_probe": 1.0}
        status = "complete"
        limitations = ()

        def to_template_parts(self):
            return None, []

    def fake_analyze(source, output, *, progress_callback, cancel_check):
        progress_callback("frame_sampling", 0.5)
        return FakeResult()

    class CancellingAnalyzer:
        def __init__(self, **kwargs):
            assert kwargs == {"consent_confirmed": True}

        def analyze(self, result, evidence_root):
            store.request_cancel(job["id"])
            return ReferenceStyleReport(summary="This result must be discarded")

    monkeypatch.setattr(analysis_module, "analyze_reference_video", fake_analyze)
    execute_reference_analysis_job(
        store, job["id"], analyzer_factory=CancellingAnalyzer
    )

    saved = store.get(job["id"])
    report = store.get_report(job["id"])
    assert saved["status"] == "cancelled"
    assert saved["ai_status"] == "cancelled"
    assert report["ai_report"] is None
    assert report["deterministic"]["technical"]["duration_seconds"] == 8.0


def test_request_cancel_does_not_reopen_a_terminal_job(tmp_path):
    store, job = _create_job(tmp_path)
    store.update(job["id"], status="completed", stage="complete")

    returned = store.request_cancel(job["id"])

    assert returned["status"] == "completed"
    assert returned["cancel_requested"] is False


def test_atomic_finish_honors_cancel_requested_before_commit(tmp_path):
    store, job = _create_job(tmp_path)
    store.update(job["id"], status="running", stage="gemini_interpretation")
    store.request_cancel(job["id"])

    result = store.finish(
        job["id"],
        {
            "schema_version": 1,
            "deterministic": {"technical": {"duration_seconds": 3}},
            "ai_status": "complete",
            "ai_report": {"summary": "must not be saved"},
        },
        status="completed",
        ai_status="complete",
    )

    saved_report = store.get_report(job["id"])
    assert result["status"] == "cancelled"
    assert result["ai_status"] == "cancelled"
    assert saved_report["ai_status"] == "cancelled"
    assert saved_report["ai_report"] is None
    assert saved_report["deterministic"]["technical"]["duration_seconds"] == 3


def test_recovery_does_not_resurrect_a_cancelled_job(tmp_path):
    store, job = _create_job(tmp_path)
    store.update(job["id"], status="running", stage="gemini_interpretation")
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {"technical": {"duration_seconds": 5}},
        "ai_status": "running",
        "ai_report": None,
    })
    store.request_cancel(job["id"])

    assert store.recover_interrupted() == []
    recovered = store.get(job["id"])
    report = store.get_report(job["id"])
    assert recovered["status"] == "cancelled"
    assert recovered["cancel_requested"] is True
    assert report["ai_status"] == "cancelled"
    assert report["deterministic"]["technical"]["duration_seconds"] == 5


def test_cancelled_queued_job_marks_gemini_cancelled_when_consent_was_given(tmp_path):
    store, job = _create_job(tmp_path, consent=True)
    store.request_cancel(job["id"])

    execute_reference_analysis_job(store, job["id"])

    result = store.get(job["id"])
    assert result["status"] == "cancelled"
    assert result["ai_status"] == "cancelled"


def test_source_path_rejects_manifest_path_traversal(tmp_path):
    import json

    store, job = _create_job(tmp_path)
    manifest_path = store._manifest_path(job["id"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_file"] = "../outside.mp4"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest path is unsafe"):
        store.source_path(job["id"])
