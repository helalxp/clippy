from __future__ import annotations

import pytest

from template_system.jobs import AnalysisJobStore
from template_system.reference_report import (
    EvidenceFrame,
    NormalizedBox,
    ReferenceStyleReport,
    TextRegionObservation,
    TypographyObservation,
)
from template_system.reviews import ReviewDecisionRequest, apply_review_decision


def _store_with_report(tmp_path, report):
    store = AnalysisJobStore(tmp_path / "analysis")
    staged = store.new_upload_path(".mp4")
    staged.write_bytes(b"reference")
    job = store.create(staged, original_filename="reference.mp4")
    evidence = [
        {"asset_id": "reference_frame_001", "timestamp_ms": 1000}
    ] if report.text_regions else []
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {"samples": evidence},
        "ai_status": "complete",
        "ai_report": report.model_dump(mode="json"),
    })
    return store, job


def _report():
    return ReferenceStyleReport(text_regions=[TextRegionObservation(
        id="caption-1",
        role="caption",
        visible_text="Example",
        box=NormalizedBox(x=0.1, y=0.7, width=0.8, height=0.1),
        typography=TypographyObservation(),
        evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        confidence="medium",
    )])


def test_review_records_acceptance_without_mutating_ai_report(tmp_path):
    original = _report()
    store, job = _store_with_report(tmp_path, original)

    result = apply_review_decision(
        store, job["id"],
        ReviewDecisionRequest(target_type="text_regions", target_id="caption-1", decision="accepted"),
    )

    assert result["items"][0]["decision"] == "accepted"
    assert result["items"][0]["reviewed_at"]
    assert store.get_report(job["id"])["ai_report"] == original.model_dump(mode="json")


def test_review_decision_upserts_instead_of_duplicating(tmp_path):
    store, job = _store_with_report(tmp_path, _report())

    apply_review_decision(store, job["id"], ReviewDecisionRequest(
        target_type="text_regions", target_id="caption-1", decision="accepted"
    ))
    result = apply_review_decision(store, job["id"], ReviewDecisionRequest(
        target_type="text_regions", target_id="caption-1", decision="rejected",
        note="Wrong style classification",
    ))

    assert len(result["items"]) == 1
    assert result["items"][0]["decision"] == "rejected"


def test_review_rejects_tampered_report_evidence(tmp_path):
    store, job = _store_with_report(tmp_path, _report())
    wrapper = store.get_report(job["id"])
    wrapper["ai_report"]["text_regions"][0]["evidence"][0]["timestamp_ms"] = 3000
    store.save_report(job["id"], wrapper)

    with pytest.raises(ValueError, match="saved report evidence is invalid"):
        apply_review_decision(store, job["id"], ReviewDecisionRequest(
            target_type="text_regions", target_id="caption-1", decision="accepted"
        ))


def test_review_target_must_exist(tmp_path):
    store, job = _store_with_report(tmp_path, _report())

    with pytest.raises(KeyError, match="visual finding not found"):
        apply_review_decision(store, job["id"], ReviewDecisionRequest(
            target_type="text_regions", target_id="missing", decision="accepted"
        ))


def test_review_request_rejects_unknown_target_type():
    with pytest.raises(Exception):
        ReviewDecisionRequest(target_type="not-a-finding", target_id="x", decision="accepted")


def test_review_cannot_create_a_sidecar_for_a_missing_job(tmp_path):
    store = AnalysisJobStore(tmp_path / "analysis")

    with pytest.raises(FileNotFoundError):
        store.record_review(
            "tjob_0123456789abcdef0123456789abcdef",
            {
                "target_type": "overview",
                "target_id": "overview",
                "decision": "accepted",
                "note": None,
                "reviewed_at": "2026-11-18T00:00:00+00:00",
            },
        )
