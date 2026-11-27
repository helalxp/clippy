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


def test_palette_colors_require_valid_evidence_and_confidence():
    from template_system.reference_report import ColorObservation

    report = ReferenceStyleReport(color_palette=[ColorObservation(
        hex_color="#FFCC33",
        role="accent",
        evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        confidence="high",
    )])

    assert validate_report_evidence(
        report,
        [EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
    ).color_palette[0].hex_color == "#FFCC33"


def test_scene_observation_requires_confidence_and_valid_evidence():
    from template_system.reference_report import SceneObservation

    evidence = EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)
    report = ReferenceStyleReport(scenes=[SceneObservation(
        index=0,
        start_ms=0,
        end_ms=2500,
        description="A presenter speaks directly to the camera.",
        content_type="talking_head",
        mood="informative",
        energy="medium",
        editorial_role="explanation",
        confidence="medium",
        evidence=[evidence],
    )])

    assert validate_report_evidence(report, [evidence]).scenes[0].confidence == "medium"


def test_overview_conclusions_require_evidence():
    with pytest.raises(ValidationError, match="overview findings require"):
        ReferenceStyleReport(summary="A bold, high-energy podcast editing style.")


def test_overview_evidence_must_be_in_the_supplied_frame_set():
    report = ReferenceStyleReport(
        summary="A bold, high-energy podcast editing style.",
        overview_evidence=[
            EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)
        ],
    )

    with pytest.raises(ValueError, match="overview references evidence"):
        validate_report_evidence(
            report,
            [EvidenceFrame(asset_id="reference_frame_002", timestamp_ms=2000)],
        )


def test_scene_evidence_must_fall_inside_claimed_scene_interval():
    from template_system.reference_report import SceneObservation

    report = ReferenceStyleReport(scenes=[SceneObservation(
        index=0,
        start_ms=0,
        end_ms=500,
        description="A presenter is on screen.",
        confidence="medium",
        evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
    )])

    with pytest.raises(ValueError, match="outside its scene interval"):
        validate_report_evidence(
            report,
            [EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        )


def test_transition_timestamp_must_be_supported_by_its_evidence_window():
    from template_system.reference_report import TransitionObservation

    report = ReferenceStyleReport(transitions=[TransitionObservation(
        id="transition-1",
        kind="cut",
        at_ms=3000,
        evidence=[
            EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000),
            EvidenceFrame(asset_id="reference_frame_002", timestamp_ms=2000),
        ],
        confidence="low",
    )])

    with pytest.raises(ValueError, match="outside its cited evidence window"):
        validate_report_evidence(
            report,
            [
                EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000),
                EvidenceFrame(asset_id="reference_frame_002", timestamp_ms=2000),
            ],
        )


def test_single_frame_transition_must_use_exact_observed_timestamp():
    from template_system.reference_report import TransitionObservation

    report = ReferenceStyleReport(transitions=[TransitionObservation(
        id="transition-1",
        kind="flash",
        at_ms=1500,
        evidence=[EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        confidence="low",
    )])

    with pytest.raises(ValueError, match="exact observed timestamp"):
        validate_report_evidence(
            report,
            [EvidenceFrame(asset_id="reference_frame_001", timestamp_ms=1000)],
        )


def test_report_schema_converts_with_application_google_genai_version():
    # Exercise the SDK's actual Pydantic-to-response-schema conversion without
    # making a network request. CI installs the same google-genai pin as the
    # desktop runtime. Keep schema constraints within Google's supported subset.
    from google.genai import types
    from google.genai._transformers import t_schema

    schema = t_schema(None, ReferenceStyleReport)

    assert schema is not None
    assert schema.properties["schema_version"].type == types.Type.INTEGER
    assert schema.properties["schema_version"].minimum == 1
    assert schema.properties["schema_version"].maximum == 1
    assert schema.properties["compositions"].items.properties["subject_regions"].items.properties["width"].minimum > 0
    assert schema.properties["text_regions"].items.properties["typography"].properties["size_ratio"].minimum > 0
    with pytest.raises(ValidationError):
        ReferenceStyleReport(schema_version=2)


def test_audio_treatment_is_not_part_of_visual_report_contract():
    with pytest.raises(ValidationError, match="audio_treatment"):
        ReferenceStyleReport.model_validate({"audio_treatment": ["Bass boost detected"]})
