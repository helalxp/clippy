from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

import pytest
from PIL import Image

import app as app_module

from template_system.jobs import AnalysisJobStore
from template_system.packages import export_template_package, import_template_package
from template_system.reference_drafts import (
    ReferenceDraftError,
    save_reviewed_reference_template,
)
from template_system.reference_report import (
    EvidenceFrame,
    NormalizedBox,
    ReferenceStyleReport,
    TextRegionObservation,
    TypographyObservation,
)
from template_system.reviews import ReviewDecisionRequest, apply_review_decision
from template_system.storage import LocalTemplateStorage


def _create_reviewable_job(tmp_path):
    store = AnalysisJobStore(tmp_path / "analysis")
    staged = store.new_upload_path(".mp4")
    source_bytes = b"reference-video-placeholder"
    staged.write_bytes(source_bytes)
    job = store.create(
        staged,
        original_filename="reference.mp4",
        name="Podcast captions",
        category="Podcast",
        gemini_consent=True,
    )

    evidence_dir = store._job_dir(job["id"]) / "evidence"
    evidence_dir.mkdir()
    image_path = evidence_dir / "frame_001_0000001000ms.png"
    Image.new("RGB", (4, 4), (255, 255, 255)).save(image_path, format="PNG")
    frame_bytes = image_path.read_bytes()
    source_fingerprint = hashlib.sha256(source_bytes).hexdigest()

    report = ReferenceStyleReport(text_regions=[TextRegionObservation(
        id="caption-main",
        role="caption",
        visible_text="Original words",
        box=NormalizedBox(x=0.1, y=0.7, width=0.8, height=0.12),
        typography=TypographyObservation(
            size_ratio=0.05,
            fill_color="#FFFFFF",
            highlight_color="#FFCC00",
            outline_color="#111111",
            line_count=2,
        ),
        evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        confidence="high",
    )])
    store.save_report(job["id"], {
        "schema_version": 1,
        "deterministic": {
            "technical": {
                "source_name": "source.mp4",
                "source_fingerprint": "sha256:" + source_fingerprint,
                "file_size_bytes": len(source_bytes),
                "duration_seconds": 12.0,
                "width": 1920,
                "height": 1080,
                "frame_rate": 30.0,
                "pixel_aspect_ratio": 1.0,
                "video_codec": "h264",
                "pixel_format": "yuv420p",
                "has_audio": False,
                "audio_codec": None,
                "audio_channels": None,
                "audio_sample_rate": None,
                "rotation_degrees": 0,
                "video_stream_count": 1,
                "audio_stream_count": 0,
                "other_stream_types": [],
            },
            "scene_boundaries_seconds": [4.0, 8.0],
            "samples": [{
                "asset_id": "reference_frame_001",
                "timestamp_ms": 1000,
                "width": 4,
                "height": 4,
                "sha256": hashlib.sha256(frame_bytes).hexdigest(),
                "size_bytes": len(frame_bytes),
            }],
            "visual_measurements": [],
            "coverage": {"media_probe": 1.0, "frame_sampling": 1.0},
            "status": "complete",
            "limitations": [],
        },
        "ai_status": "complete",
        "ai_report": report.model_dump(mode="json"),
    })
    store.update(
        job["id"],
        status="completed",
        stage="completed",
        progress=100,
        ai_status="complete",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    return store, job, report


def test_saves_reviewed_template_with_corrections_and_portable_evidence(tmp_path):
    store, job, original_report = _create_reviewable_job(tmp_path)
    apply_review_decision(
        store,
        job["id"],
        ReviewDecisionRequest(
            target_type="text_regions",
            target_id="caption-main",
            decision="accepted",
            note="Confirmed by editor.",
            correction={
                "visible_text": "Human-corrected words",
                "typography": {
                    "font_family": "Montserrat",
                    "fill_color": "#33AAFF",
                },
            },
        ),
    )
    template_storage = LocalTemplateStorage(tmp_path / "templates")

    document = save_reviewed_reference_template(
        store,
        template_storage,
        job["id"],
    )

    assert document.name == "Podcast captions"
    assert document.origin.kind == "reference_video"
    assert document.recipe.captions.enabled is True
    assert document.recipe.captions.font_family == "Montserrat"
    assert document.recipe.captions.font_size_ratio == pytest.approx(0.05)
    assert document.recipe.captions.font_color == "#33AAFF"
    assert document.recipe.captions.highlight_color == "#FFCC00"
    assert document.recipe.captions.outline_color == "#111111"
    assert {asset.id for asset in document.assets} == {
        "reference_frame_001", "reference_report"
    }
    image_asset, image_path = template_storage.get_asset(document.id, "reference_frame_001")
    report_asset, report_path = template_storage.get_asset(document.id, "reference_report")
    assert image_asset.media_type == "image/png"
    assert image_path.read_bytes()
    assert report_asset.media_type == "application/json"

    archived = json.loads(report_path.read_text(encoding="utf-8"))
    assert archived["ai_report"] == original_report.model_dump(mode="json")
    assert archived["reviewed_report"]["text_regions"][0]["visible_text"] == "Human-corrected words"
    assert archived["review"]["items"][0]["correction"]["typography"]["font_family"] == "Montserrat"
    assert store.get_report(job["id"])["ai_report"] == original_report.model_dump(mode="json")

    # The template is self-contained: deleting the source analysis job does not delete its assets.
    store.delete(job["id"])
    reloaded = template_storage.get(document.id)
    assert reloaded.id == document.id
    assert template_storage.get_asset(document.id, "reference_frame_001")[1].is_file()
    assert template_storage.get_asset(document.id, "reference_report")[1].is_file()


def test_reviewed_template_package_round_trips_reference_report_asset(tmp_path):
    store, job, _report = _create_reviewable_job(tmp_path)
    apply_review_decision(
        store,
        job["id"],
        ReviewDecisionRequest(
            target_type="text_regions",
            target_id="caption-main",
            decision="accepted",
        ),
    )
    storage = LocalTemplateStorage(tmp_path / "templates")
    document = save_reviewed_reference_template(store, storage, job["id"])

    package = export_template_package(storage, document.id)
    imported = import_template_package(storage, package)

    assert imported.origin.kind == "imported"
    assert {asset.media_type for asset in imported.assets} == {"image/png", "application/json"}
    _, report_path = storage.get_asset(imported.id, "reference_report")
    archive = json.loads(report_path.read_text(encoding="utf-8"))
    assert archive["schema"] == "clippy.reference-template-review"
    assert archive["ai_report"]["text_regions"][0]["id"] == "caption-main"


def test_draft_requires_an_accepted_finding(tmp_path):
    store, job, _report = _create_reviewable_job(tmp_path)
    storage = LocalTemplateStorage(tmp_path / "templates")

    with pytest.raises(ReferenceDraftError, match="accept at least one"):
        save_reviewed_reference_template(store, storage, job["id"])

    assert storage.list() == []


def test_draft_refuses_missing_or_tampered_evidence(tmp_path):
    store, job, report = _create_reviewable_job(tmp_path)
    apply_review_decision(
        store,
        job["id"],
        ReviewDecisionRequest(
            target_type="text_regions",
            target_id="caption-main",
            decision="accepted",
        ),
    )
    evidence_path = store.evidence_path(job["id"], "reference_frame_001")
    evidence_path.write_bytes(b"tampered")
    storage = LocalTemplateStorage(tmp_path / "templates")

    with pytest.raises(ReferenceDraftError, match="failed its size or checksum"):
        save_reviewed_reference_template(store, storage, job["id"])

    assert storage.list() == []


def test_api_saves_and_lists_local_template_drafts(tmp_path, monkeypatch):
    store, job, _report = _create_reviewable_job(tmp_path)
    apply_review_decision(
        store,
        job["id"],
        ReviewDecisionRequest(
            target_type="text_regions",
            target_id="caption-main",
            decision="accepted",
        ),
    )
    template_storage = LocalTemplateStorage(tmp_path / "templates")
    monkeypatch.setattr(app_module, "_template_analysis_store", lambda: store)
    monkeypatch.setattr(app_module, "_template_system_storage", lambda: template_storage)
    monkeypatch.setattr(app_module, "_assert_data_storage_available", lambda: None)
    monkeypatch.setattr(app_module, "_reference_templates_local_only", lambda: None)

    saved = asyncio.run(app_module.save_template_analysis_draft(
        job["id"],
        app_module.TemplateAnalysisDraftRequest(
            name="API-created template",
            description="A reviewed local draft.",
            category="Podcast",
        ),
    ))
    listed = asyncio.run(app_module.list_template_system_documents())

    assert saved["template"]["name"] == "API-created template"
    assert len(listed["templates"]) == 1
    assert listed["templates"][0]["id"] == saved["template"]["id"]
