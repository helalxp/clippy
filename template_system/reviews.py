"""Human review decisions for evidence-backed reference-video findings.

Review decisions live separately from the provider report. The original AI
output and its evidence are immutable; this module records explicit human
acceptance or rejection before later recipe synthesis.
"""
from __future__ import annotations

import re

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .reference_report import EvidenceFrame, NormalizedBox, ReferenceStyleReport, validate_report_evidence


ReviewTargetType = Literal[
    "overview", "color_palette", "backgrounds", "compositions",
    "text_regions", "graphic_overlays", "effects", "transitions", "scenes",
]

 
class _CorrectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _BoxCorrection(_CorrectionModel):
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)


class _TypographyCorrection(_CorrectionModel):
    font_family: str | None = Field(default=None, min_length=1, max_length=120)
    weight: str | None = Field(default=None, max_length=40)
    style: Literal["normal", "italic", "oblique", "unknown"] | None = None
    size_ratio: float | None = Field(default=None, gt=0, le=0.3)
    fill_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_strength: Literal["none", "thin", "medium", "heavy", "unknown"] | None = None
    shadow: Literal["none", "subtle", "strong", "unknown"] | None = None
    background_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    alignment: Literal["left", "center", "right", "unknown"] | None = None
    uppercase: bool | None = None
    line_count: int | None = Field(default=None, ge=1, le=12)


class _OverviewCorrection(_CorrectionModel):
    summary: str | None = Field(default=None, max_length=2000)
    visual_identity: str | None = Field(default=None, max_length=1500)
    editorial_style: str | None = Field(default=None, max_length=1500)
    overall_pacing: str | None = Field(default=None, max_length=300)


class _ColorCorrection(_CorrectionModel):
    hex_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    role: Literal["background", "accent", "caption", "hook", "overlay", "dominant", "other"] | None = None


class _BackgroundCorrection(_CorrectionModel):
    kind: Literal["original_footage", "blurred_duplicate", "solid_color", "gradient", "image", "video", "other", "unknown"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    colors: list[str] | None = Field(default=None, max_length=8)

    @field_validator("colors")
    @classmethod
    def colors_are_hex(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not re.fullmatch(r"^#[0-9A-Fa-f]{6}$", item) for item in value):
            raise ValueError("background correction colors must be six-digit hex values")
        return value


class _CompositionCorrection(_CorrectionModel):
    kind: Literal["single_subject", "picture_in_picture", "split_screen", "side_by_side", "stacked", "screen_recording", "collage", "other", "unknown"] | None = None
    framing: Literal["extreme_closeup", "closeup", "medium", "wide", "full_frame", "unknown"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    subject_regions: list[NormalizedBox] | None = Field(default=None, max_length=8)


class _TextRegionCorrection(_CorrectionModel):
    role: Literal["caption", "hook", "title", "lower_third", "label", "watermark_text", "other"] | None = None
    visible_text: str | None = Field(default=None, max_length=500)
    box: _BoxCorrection | None = None
    typography: _TypographyCorrection | None = None
    first_seen_ms: int | None = Field(default=None, ge=0)
    last_seen_ms: int | None = Field(default=None, ge=0)
    animation: Literal["none", "fade", "slide", "pop", "typewriter", "word_by_word", "karaoke_highlight", "pulse", "other", "unknown"] | None = None
    animation_notes: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=600)


class _GraphicOverlayCorrection(_CorrectionModel):
    kind: Literal["logo", "watermark", "image", "badge", "emoji", "shape", "frame", "other"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=400)
    box: _BoxCorrection | None = None
    opacity: float | None = Field(default=None, ge=0, le=1)


class _EffectCorrection(_CorrectionModel):
    kind: Literal["zoom", "pan", "shake", "slow_motion", "speed_ramp", "blur", "glitch", "color_grade", "vignette", "grain", "stabilization", "other"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class _TransitionCorrection(_CorrectionModel):
    kind: Literal["cut", "fade", "dissolve", "wipe", "slide", "whip_pan", "zoom", "flash", "match_cut", "other", "uncertain"] | None = None
    at_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0, le=10000)
    notes: str | None = Field(default=None, max_length=400)


class _SceneCorrection(_CorrectionModel):
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    content_type: str | None = Field(default=None, max_length=80)
    mood: str | None = Field(default=None, max_length=80)
    energy: Literal["low", "medium", "high", "variable", "unknown"] | None = None
    editorial_role: str | None = Field(default=None, max_length=100)


_CORRECTION_SCHEMAS = {
    "overview": _OverviewCorrection,
    "color_palette": _ColorCorrection,
    "backgrounds": _BackgroundCorrection,
    "compositions": _CompositionCorrection,
    "text_regions": _TextRegionCorrection,
    "graphic_overlays": _GraphicOverlayCorrection,
    "effects": _EffectCorrection,
    "transitions": _TransitionCorrection,
    "scenes": _SceneCorrection,
}


def _has_patch_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_patch_value(item) for item in value.values())
    return value is not None


def validate_finding_correction(target_type: str, correction: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate a sparse, category-specific correction without accepting evidence edits."""
    if correction is None:
        return None
    schema = _CORRECTION_SCHEMAS.get(target_type)
    if schema is None:
        raise ValueError(f"corrections are not supported for target type: {target_type}")
    validated = schema.model_validate(correction)
    payload = validated.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    if not _has_patch_value(payload):
        raise ValueError("a correction must change at least one supported finding field")
    return payload


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_finding_correction(
    report: ReferenceStyleReport,
    target_type: str,
    target_id: str,
    correction: dict[str, Any],
) -> ReferenceStyleReport:
    """Apply a correction to a copy for cross-field validation; never mutate the AI report."""
    payload = report.model_dump(mode="python")
    if target_type == "overview":
        if target_id != "overview":
            raise KeyError(f"visual finding not found: {target_type}/{target_id}")
        payload.update(correction)
    else:
        collection = payload[target_type]
        if target_type == "color_palette":
            try:
                index = int(target_id)
            except (TypeError, ValueError):
                raise KeyError(f"visual finding not found: {target_type}/{target_id}")
            if str(index) != target_id or index < 0 or index >= len(collection):
                raise KeyError(f"visual finding not found: {target_type}/{target_id}")
        elif target_type == "scenes":
            matches = [i for i, item in enumerate(collection) if str(item["index"]) == target_id]
            if len(matches) != 1:
                raise KeyError(f"visual finding not found: {target_type}/{target_id}")
            index = matches[0]
        else:
            matches = [i for i, item in enumerate(collection) if item.get("id") == target_id]
            if len(matches) != 1:
                raise KeyError(f"visual finding not found: {target_type}/{target_id}")
            index = matches[0]
        patch = dict(correction)
        # A manually identified font family is review metadata, not a claim made by Gemini.
        typography = patch.get("typography")
        if target_type == "text_regions" and isinstance(typography, dict):
            typography = dict(typography)
            typography.pop("font_family", None)
            if typography:
                patch["typography"] = typography
            else:
                patch.pop("typography", None)
        payload[target_type][index] = _deep_merge(payload[target_type][index], patch)
    try:
        return ReferenceStyleReport.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"correction would make the visual finding invalid: {exc}") from exc


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_type: ReviewTargetType
    target_id: str = Field(min_length=1, max_length=80)
    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)
    correction: dict[str, Any] | None = None
    reviewed_at: datetime

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def correction_matches_target(self) -> "ReviewItem":
        if self.correction is not None:
            self.correction = validate_finding_correction(self.target_type, self.correction)
        return self


class ReviewDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    job_id: str = Field(pattern=r"^tjob_[a-f0-9]{32}$")
    updated_at: datetime | None = None
    items: list[ReviewItem] = Field(default_factory=list, max_length=1024)

    @field_validator("updated_at")
    @classmethod
    def updated_at_is_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("review timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def finding_keys_are_unique(self) -> "ReviewDocument":
        keys = [(item.target_type, item.target_id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("review document contains duplicate finding decisions")
        return self


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_type: ReviewTargetType
    target_id: str = Field(min_length=1, max_length=80)
    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)
    correction: dict[str, Any] | None = None

    @model_validator(mode="after")
    def correction_requires_acceptance(self) -> "ReviewDecisionRequest":
        if self.correction is not None:
            self.correction = validate_finding_correction(self.target_type, self.correction)
            if self.decision != "accepted":
                raise ValueError("a corrected finding must be accepted")
        return self


def _target_exists(report: ReferenceStyleReport, target_type: str, target_id: str) -> bool:
    if target_type == "overview":
        return target_id == "overview" and bool(
            report.summary or report.visual_identity or report.editorial_style
            or report.overall_pacing not in {"", "unknown"}
        )

    collection = getattr(report, target_type)
    if target_type == "color_palette":
        try:
            index = int(target_id)
        except (TypeError, ValueError):
            return False
        return str(index) == target_id and 0 <= index < len(collection)
    if target_type == "scenes":
        matches = [item for item in collection if str(item.index) == target_id]
    else:
        matches = [item for item in collection if item.id == target_id]
    return len(matches) == 1


def apply_review_decision(store, job_id: str, request: ReviewDecisionRequest) -> dict:
    """Validate a target against the saved visual report, then persist a decision."""
    store.get(job_id)
    wrapper = store.get_report(job_id)
    if not wrapper:
        raise ValueError("analysis report is not available for review")
    ai_report = wrapper.get("ai_report")
    if ai_report is None:
        raise ValueError("AI visual findings are not available for review")

    try:
        report = ReferenceStyleReport.model_validate(ai_report)
    except ValidationError as exc:
        raise ValueError(f"saved visual report is invalid: {exc}") from exc

    deterministic = wrapper.get("deterministic") or {}
    samples = deterministic.get("samples") or []
    supplied_frames = [
        EvidenceFrame(
            asset_id=str(item["asset_id"]),
            timestamp_ms=int(item["timestamp_ms"]),
        )
        for item in samples
        if isinstance(item, dict) and "asset_id" in item and "timestamp_ms" in item
    ]
    try:
        validate_report_evidence(report, supplied_frames)
    except ValueError as exc:
        raise ValueError(f"saved report evidence is invalid: {exc}") from exc

    if not _target_exists(report, request.target_type, request.target_id):
        raise KeyError(f"visual finding not found: {request.target_type}/{request.target_id}")

    current_review = store.get_review(job_id)
    previous = next(
        (
            item for item in current_review.get("items", [])
            if item.get("target_type") == request.target_type
            and item.get("target_id") == request.target_id
        ),
        None,
    )
    correction_was_supplied = "correction" in request.model_fields_set
    if correction_was_supplied:
        if request.correction is None:
            correction = None
        else:
            correction = _deep_merge(
                dict((previous or {}).get("correction") or {}),
                request.correction,
            )
            correction = validate_finding_correction(request.target_type, correction)
    else:
        correction = (previous or {}).get("correction")

    if correction is not None and request.decision == "accepted":
        corrected_report = _apply_finding_correction(
            report, request.target_type, request.target_id, correction
        )
        try:
            validate_report_evidence(corrected_report, supplied_frames)
        except ValueError as exc:
            raise ValueError(f"correction would invalidate finding evidence: {exc}") from exc

    item = ReviewItem(
        target_type=request.target_type,
        target_id=request.target_id,
        decision=request.decision,
        note=request.note or None,
        correction=correction,
        reviewed_at=datetime.now(timezone.utc),
    )
    return store.record_review(job_id, item.model_dump(mode="json"))
