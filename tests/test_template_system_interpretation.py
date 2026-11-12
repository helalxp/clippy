from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from template_system.analysis import FrameSample
from template_system.interpretation import (
    InterpretationError,
    InterpretationClaim,
    InterpretationEvidence,
    TemplateInterpretation,
    interpret_reference,
    interpretation_to_proposals,
    resolve_interpreted_recipe,
    synthesize_draft_recipe,
    InterpretationSynthesisError,
)
from template_system.models import TemplateAsset, TemplateRecipe


def make_frame(root: Path, name: str, timestamp_ms: int, color=(220, 40, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), color).save(buffer, format="PNG")
    payload = buffer.getvalue()
    (root / name).write_bytes(payload)
    sample = FrameSample(
        timestamp_ms=timestamp_ms,
        relative_path=name,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        width=80,
        height=80,
    )
    asset = TemplateAsset(
        id=f"asset_{timestamp_ms}",
        path=name,
        media_type="image/png",
        size_bytes=len(payload),
        sha256=sample.sha256,
    )
    return sample, asset


def provider_claim(asset_id, timestamp_ms, *, status="accepted", path="captions.enabled", value=True):
    return {
        "property_path": path,
        "value": value,
        "confidence": "high",
        "source": "visual_observation",
        "status": status,
        "evidence": [{"asset_id": asset_id, "timestamp_ms": timestamp_ms}],
        "rationale": "The sampled frame visibly supports this proposed setting.",
    }


def test_interpretation_provider_receives_verified_frames_and_claims_stay_pending(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1250)
    received = {}

    def provider(frames, metrics):
        received["frames"] = frames
        received["metrics"] = metrics
        return {
            "summary": "A bold caption treatment.",
            "claims": [provider_claim(asset.id, sample.timestamp_ms, status="accepted")],
            "limitations": ["Only one sampled frame was available."],
        }

    result = interpret_reference(
        [sample],
        [asset],
        tmp_path,
        provider,
        provider_id="fake-vision",
        model_id="fake-model-v1",
    )

    assert len(received["frames"]) == 1
    assert received["frames"][0].image_bytes == (tmp_path / "frame.png").read_bytes()
    assert received["frames"][0].asset_id == asset.id
    assert result.provider_id == "fake-vision"
    assert result.model_id == "fake-model-v1"
    assert result.claims[0].status == "pending"


def test_interpretation_rejects_claims_without_supplied_evidence(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1000)

    def provider(frames, metrics):
        return {
            "claims": [provider_claim("not-supplied", 1000)],
        }

    with pytest.raises(InterpretationError, match="not supplied"):
        interpret_reference(
            [sample], [asset], tmp_path, provider,
            provider_id="fake", model_id="v1",
        )


def test_interpretation_rejects_unknown_recipe_property(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1000)

    def provider(frames, metrics):
        return {
            "claims": [provider_claim(asset.id, 1000, path="captions.arbitrary_field")],
        }

    with pytest.raises(InterpretationError, match="interpretation contract"):
        interpret_reference(
            [sample], [asset], tmp_path, provider,
            provider_id="fake", model_id="v1",
        )


def test_interpretation_rejects_claim_without_evidence(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1000)

    def provider(frames, metrics):
        claim = provider_claim(asset.id, 1000)
        claim.pop("evidence")
        return {"claims": [claim]}

    with pytest.raises(InterpretationError, match="interpretation contract"):
        interpret_reference(
            [sample], [asset], tmp_path, provider,
            provider_id="fake", model_id="v1",
        )


def test_interpretation_verifies_frame_checksum_before_provider_call(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1000)
    (tmp_path / "frame.png").write_bytes(b"tampered")
    called = []

    def provider(frames, metrics):
        called.append(True)
        return {"claims": []}

    with pytest.raises(InterpretationError, match="checksum"):
        interpret_reference(
            [sample], [asset], tmp_path, provider,
            provider_id="fake", model_id="v1",
        )
    assert called == []


def test_interpretation_bounds_frames_and_provider_payload(tmp_path):
    samples, assets = [], []
    for index in range(4):
        sample, asset = make_frame(
            tmp_path, f"frame_{index}.png", index * 1000, color=(index * 40, 20, 20)
        )
        samples.append(sample)
        assets.append(asset)
    received_timestamps = []

    def provider(frames, metrics):
        received_timestamps.extend(frame.timestamp_ms for frame in frames)
        first = frames[0]
        return {"claims": [provider_claim(first.asset_id, first.timestamp_ms)]}

    interpret_reference(
        samples,
        assets,
        tmp_path,
        provider,
        provider_id="fake",
        model_id="v1",
        max_frames=2,
    )

    assert received_timestamps == [0, 3000]


def test_interpretation_rejects_model_claim_as_human_correction(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1000)

    def provider(frames, metrics):
        claim = provider_claim(asset.id, 1000)
        claim["source"] = "human_correction"
        return {"claims": [claim]}

    with pytest.raises(InterpretationError, match="observations or inferences"):
        interpret_reference(
            [sample], [asset], tmp_path, provider,
            provider_id="fake", model_id="v1",
        )


def test_interpretation_wraps_provider_failures(tmp_path):
    sample, asset = make_frame(tmp_path, "frame.png", 1000)

    def provider(frames, metrics):
        raise TimeoutError("provider timeout")

    with pytest.raises(InterpretationError, match="provider failed"):
        interpret_reference(
            [sample], [asset], tmp_path, provider,
            provider_id="fake", model_id="v1",
        )


def _direct_interpretation():
    evidence = [InterpretationEvidence(asset_id="frame_asset", timestamp_ms=1000)]
    return TemplateInterpretation(
        provider_id="review",
        model_id="human-reviewed",
        claims=[
            InterpretationClaim(
                property_path="captions.enabled",
                value=True,
                confidence="high",
                source="human_correction",
                status="corrected",
                evidence=evidence,
                rationale="User confirmed captions should be enabled.",
            ),
            InterpretationClaim(
                property_path="captions.font_size_ratio",
                value=0.1,
                confidence="medium",
                source="visual_observation",
                status="pending",
                evidence=evidence,
                rationale="The sampled text appears relatively large.",
            ),
            InterpretationClaim(
                property_path="background.mode",
                value="solid",
                confidence="low",
                source="inference",
                status="rejected",
                evidence=evidence,
                rationale="This was only a weak background inference.",
            ),
        ],
    )


def test_synthesis_applies_only_accepted_or_corrected_claims():
    interpretation = _direct_interpretation()

    result = synthesize_draft_recipe(TemplateRecipe(), interpretation)

    assert result.recipe.captions.enabled is True
    assert result.recipe.captions.font_size_ratio == TemplateRecipe().captions.font_size_ratio
    assert result.recipe.background.mode == "original"
    assert result.accepted_paths == ("captions.enabled",)
    assert result.pending_paths == ("captions.font_size_ratio",)
    assert result.rejected_paths == ("background.mode",)
    reports = {report.backend: report for report in result.compatibility_reports}
    assert set(reports) == {"python_ffmpeg", "remotion_preview", "remotion_render"}
    assert reports["python_ffmpeg"].status == "partial"
    assert reports["remotion_preview"].status == "partial"


def test_resolver_proposals_include_only_accepted_or_corrected_claims():
    proposals = interpretation_to_proposals(_direct_interpretation())

    assert len(proposals) == 1
    assert proposals[0].path == "captions.enabled"
    assert proposals[0].value is True


def test_synthesis_rejects_accepted_values_outside_recipe_ranges():
    evidence = [InterpretationEvidence(asset_id="frame_asset", timestamp_ms=1000)]
    interpretation = TemplateInterpretation(
        provider_id="review",
        model_id="human-reviewed",
        claims=[InterpretationClaim(
            property_path="captions.font_size_ratio",
            value=0.5,
            confidence="high",
            source="human_correction",
            status="accepted",
            evidence=evidence,
            rationale="Invalid size supplied by a faulty review client.",
        )],
    )

    with pytest.raises(InterpretationSynthesisError, match="valid recipe"):
        synthesize_draft_recipe(TemplateRecipe(), interpretation)


def test_interpretation_contract_rejects_duplicate_property_claims():
    evidence = [InterpretationEvidence(asset_id="frame_asset", timestamp_ms=1000)]
    claim = InterpretationClaim(
        property_path="captions.enabled",
        value=True,
        confidence="high",
        source="visual_observation",
        status="pending",
        evidence=evidence,
        rationale="Observed in frame.",
    )

    with pytest.raises(ValueError, match="one claim per property"):
        TemplateInterpretation(
            provider_id="fake",
            model_id="v1",
            claims=[claim, claim],
        )



def test_reviewed_interpretation_uses_clip_override_and_lock_precedence():
    interpretation = _direct_interpretation()

    clipped = resolve_interpreted_recipe(
        TemplateRecipe(),
        interpretation,
        clip_overrides={"captions": {"enabled": False}},
    )
    assert clipped.recipe.captions.enabled is False
    assert clipped.adaptation_decisions[0].accepted is False
    assert "clip override" in clipped.adaptation_decisions[0].reason

    locked = resolve_interpreted_recipe(
        TemplateRecipe(),
        interpretation,
        clip_overrides={"captions": {"enabled": False}},
        locks={"captions.enabled": True},
    )
    assert locked.recipe.captions.enabled is True
    assert locked.adaptation_decisions[0].accepted is False
    assert "explicit lock" in locked.adaptation_decisions[0].reason
