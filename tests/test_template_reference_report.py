from __future__ import annotations

import pytest
from pydantic import ValidationError

from template_system.reference_report import (
    BackgroundObservation,
    CompositionObservation,
    EvidenceFrame,
    FontCandidate,
    NormalizedBox,
    ReferenceStyleReport,
    TextRegionObservation,
    TypographyObservation,
    validate_report_evidence,
)


def _text_finding(asset_id="reference_frame_001", timestamp_ms=1000):
    return TextRegionObservation(
        id="caption-1",
        role="caption",
        visible_text="Example caption",
        box=NormalizedBox(x=0.1, y=0.75, width=0.8, height=0.1),
        typography=TypographyObservation(
            font_candidates=[
                FontCandidate(family="Arial", confidence="medium", reason="Sans-serif shape")
            ],
            size_ratio=0.04,
            fill_color="#FFFFFF",
            highlight_color="#FFE45E",
            outline_color="#000000",
            outline_strength="medium",
            alignment="center",
        ),
        evidence=[EvidenceFrame(asset_id=asset_id, timestamp_ms=timestamp_ms)],
        confidence="medium",
    )


def test_report_records_normalized_positions_and_font_candidates():
    report = ReferenceStyleReport(text_regions=[_text_finding()])

    assert report.text_regions[0].box.y == 0.75
    assert report.text_regions[0].typography.font_candidates[0].family == "Arial"
    assert report.text_regions[0].typography.font_candidates[0].confidence == "medium"
    assert report.text_regions[0].typography.highlight_color == "#FFE45E"


def test_normalized_box_cannot_extend_outside_frame():
    with pytest.raises(ValidationError, match="fit inside"):
        NormalizedBox(x=0.8, y=0.2, width=0.3, height=0.2)


def test_report_rejects_evidence_not_supplied_to_model():
    report = ReferenceStyleReport(text_regions=[_text_finding()])

    with pytest.raises(ValueError, match="not supplied"):
        validate_report_evidence(
            report,
            [EvidenceFrame(asset_id="reference_frame_002", timestamp_ms=2000)],
        )


def test_report_accepts_exact_supplied_evidence_pair():
    report = ReferenceStyleReport(text_regions=[_text_finding()])

    validated = validate_report_evidence(
        report,
        [EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
    )

    assert validated == report


def test_timed_text_region_requires_both_start_and_end():
    with pytest.raises(ValidationError, match="must be supplied together"):
        TextRegionObservation(
            id="caption-2",
            role="caption",
            box=NormalizedBox(x=0.1, y=0.75, width=0.8, height=0.1),
            typography=TypographyObservation(),
            first_seen_ms=1000,
            evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
            confidence="low",
        )


def test_report_accepts_background_and_composition_observations_with_evidence():
    evidence = EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)
    report = ReferenceStyleReport(
        backgrounds=[BackgroundObservation(
            id="bg-1",
            kind="blurred_duplicate",
            description="The source image appears enlarged and blurred behind the centered subject.",
            colors=["#101010", "#555555"],
            evidence=[evidence],
            confidence="medium",
        )],
        compositions=[CompositionObservation(
            id="layout-1",
            kind="picture_in_picture",
            framing="medium",
            description="A presenter occupies the main region while a small inset appears in the top corner.",
            subject_regions=[
                NormalizedBox(x=0.1, y=0.2, width=0.8, height=0.7),
                NormalizedBox(x=0.72, y=0.04, width=0.22, height=0.18),
            ],
            evidence=[evidence],
            confidence="medium",
        )],
    )

    validated = validate_report_evidence(report, [evidence])
    assert validated.backgrounds[0].kind == "blurred_duplicate"
    assert validated.compositions[0].subject_regions[1].x == 0.72


def test_report_rejects_background_claim_with_unprovided_evidence():
    report = ReferenceStyleReport(backgrounds=[BackgroundObservation(
        id="bg-1",
        kind="solid_color",
        description="A solid background appears behind the subject.",
        evidence=[EvidenceFrame(asset_id="not-provided", timestamp_ms=5000)],
        confidence="low",
    )])

    with pytest.raises(ValueError, match="not supplied"):
        validate_report_evidence(
            report,
            [EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        )
