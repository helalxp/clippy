"""Evidence-backed visual analysis report contracts for reference videos.

This report is deliberately separate from TemplateRecipe: analysis describes
what appears in the supplied video, while a template recipe describes what a
renderer can reproduce. Estimated visual values must never be presented as
pixel-perfect measurements or exact font identification.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Confidence = Literal["high", "medium", "low", "uncertain"]


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceFrame(ReportModel):
    asset_id: str = Field(min_length=1, max_length=80)
    timestamp_ms: int = Field(ge=0)


class NormalizedBox(ReportModel):
    """Estimated rectangle in source-frame coordinates, normalized to 0..1."""
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fits_frame(self) -> "NormalizedBox":
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("normalized box must fit inside the source frame")
        return self


class FontCandidate(ReportModel):
    family: str = Field(min_length=1, max_length=120)
    confidence: Confidence
    reason: str = Field(default="", max_length=300)


class TypographyObservation(ReportModel):
    font_candidates: list[FontCandidate] = Field(default_factory=list, max_length=5)
    weight: str | None = Field(default=None, max_length=40)
    style: Literal["normal", "italic", "oblique", "unknown"] = "unknown"
    size_ratio: float | None = Field(default=None, gt=0, le=0.3)
    fill_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_strength: Literal["none", "thin", "medium", "heavy", "unknown"] = "unknown"
    shadow: Literal["none", "subtle", "strong", "unknown"] = "unknown"
    background_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    alignment: Literal["left", "center", "right", "unknown"] = "unknown"
    uppercase: bool | None = None
    line_count: int | None = Field(default=None, ge=1, le=12)


class TextRegionObservation(ReportModel):
    id: str = Field(min_length=1, max_length=80)
    role: Literal["caption", "hook", "title", "lower_third", "label", "watermark_text", "other"]
    visible_text: str | None = Field(default=None, max_length=500)
    box: NormalizedBox
    typography: TypographyObservation
    first_seen_ms: int | None = Field(default=None, ge=0)
    last_seen_ms: int | None = Field(default=None, ge=0)
    animation: Literal["none", "fade", "slide", "pop", "typewriter", "word_by_word", "karaoke_highlight", "pulse", "other", "unknown"] = "unknown"
    animation_notes: str = Field(default="", max_length=400)
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence
    notes: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def valid_visibility_interval(self) -> "TextRegionObservation":
        if (self.first_seen_ms is None) != (self.last_seen_ms is None):
            raise ValueError("first_seen_ms and last_seen_ms must be supplied together")
        if self.first_seen_ms is not None and self.last_seen_ms < self.first_seen_ms:
            raise ValueError("last_seen_ms cannot precede first_seen_ms")
        return self


class GraphicOverlayObservation(ReportModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["logo", "watermark", "image", "badge", "emoji", "shape", "frame", "other"]
    description: str = Field(min_length=1, max_length=400)
    box: NormalizedBox
    opacity: float | None = Field(default=None, ge=0, le=1)
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence


class EffectObservation(ReportModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal[
        "zoom", "pan", "shake", "slow_motion", "speed_ramp", "blur",
        "glitch", "color_grade", "vignette", "grain", "stabilization", "other"
    ]
    description: str = Field(min_length=1, max_length=500)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence

    @model_validator(mode="after")
    def valid_effect_interval(self) -> "EffectObservation":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("effect start_ms and end_ms must be supplied together")
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("effect end_ms must be greater than start_ms")
        return self


class TransitionObservation(ReportModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal[
        "cut", "fade", "dissolve", "wipe", "slide", "whip_pan",
        "zoom", "flash", "match_cut", "other", "uncertain"
    ]
    at_ms: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0, le=10000)
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence
    notes: str = Field(default="", max_length=400)


class SceneObservation(ReportModel):
    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=500)
    content_type: str = Field(default="unknown", max_length=80)
    mood: str = Field(default="unknown", max_length=80)
    energy: Literal["low", "medium", "high", "variable", "unknown"] = "unknown"
    editorial_role: str = Field(default="unknown", max_length=100)
    confidence: Confidence
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def valid_scene_interval(self) -> "SceneObservation":
        if self.end_ms <= self.start_ms:
            raise ValueError("scene end_ms must be greater than start_ms")
        return self


class ColorObservation(ReportModel):
    hex_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    role: Literal["background", "accent", "caption", "hook", "overlay", "dominant", "other"] = "dominant"
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence


class BackgroundObservation(ReportModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["original_footage", "blurred_duplicate", "solid_color", "gradient", "image", "video", "other", "unknown"]
    description: str = Field(min_length=1, max_length=500)
    colors: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence


class CompositionObservation(ReportModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["single_subject", "picture_in_picture", "split_screen", "side_by_side", "stacked", "screen_recording", "collage", "other", "unknown"]
    framing: Literal["extreme_closeup", "closeup", "medium", "wide", "full_frame", "unknown"] = "unknown"
    description: str = Field(min_length=1, max_length=500)
    subject_regions: list[NormalizedBox] = Field(default_factory=list, max_length=8)
    evidence: list[EvidenceFrame] = Field(min_length=1, max_length=12)
    confidence: Confidence


class ReferenceStyleReport(ReportModel):
    schema_version: Literal[1] = 1
    summary: str = Field(default="", max_length=2000)
    visual_identity: str = Field(default="", max_length=1500)
    editorial_style: str = Field(default="", max_length=1500)
    overall_pacing: str = Field(default="unknown", max_length=300)
    color_palette: list[ColorObservation] = Field(default_factory=list, max_length=12)
    backgrounds: list[BackgroundObservation] = Field(default_factory=list, max_length=64)
    compositions: list[CompositionObservation] = Field(default_factory=list, max_length=64)
    text_regions: list[TextRegionObservation] = Field(default_factory=list, max_length=128)
    graphic_overlays: list[GraphicOverlayObservation] = Field(default_factory=list, max_length=64)
    effects: list[EffectObservation] = Field(default_factory=list, max_length=128)
    transitions: list[TransitionObservation] = Field(default_factory=list, max_length=256)
    scenes: list[SceneObservation] = Field(default_factory=list, max_length=128)
    overview_evidence: list[EvidenceFrame] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def overview_requires_evidence(self) -> "ReferenceStyleReport":
        has_overview = bool(
            self.summary or self.visual_identity or self.editorial_style
            or self.overall_pacing not in {"", "unknown"}
        )
        if has_overview and not self.overview_evidence:
            raise ValueError("overview findings require at least one evidence frame")
        return self


def validate_report_evidence(
    report: ReferenceStyleReport,
    supplied_frames: list[EvidenceFrame] | tuple[EvidenceFrame, ...],
) -> ReferenceStyleReport:
    """Reject any model finding that cites a frame/time pair it did not receive."""
    valid = {(item.asset_id, item.timestamp_ms) for item in supplied_frames}
    findings = [
        *report.text_regions,
        *report.graphic_overlays,
        *report.effects,
        *report.transitions,
        *report.scenes,
        *report.color_palette,
        *report.backgrounds,
        *report.compositions,
    ]
    for evidence in report.overview_evidence:
        if (evidence.asset_id, evidence.timestamp_ms) not in valid:
            raise ValueError("overview references evidence that was not supplied to the model")
    for finding in findings:
        for evidence in finding.evidence:
            if (evidence.asset_id, evidence.timestamp_ms) not in valid:
                identifier = getattr(finding, "id", getattr(finding, "index", "?"))
                raise ValueError(
                    f"finding {identifier!r} references evidence that was not supplied to the model"
                )
        timestamps = [item.timestamp_ms for item in finding.evidence]
        if isinstance(finding, TextRegionObservation) and finding.first_seen_ms is not None:
            if any(ts < finding.first_seen_ms or ts > finding.last_seen_ms for ts in timestamps):
                raise ValueError(f"text finding {finding.id!r} has evidence outside its observed visibility interval")
        elif isinstance(finding, EffectObservation) and finding.start_ms is not None:
            if any(ts < finding.start_ms or ts > finding.end_ms for ts in timestamps):
                raise ValueError(f"effect finding {finding.id!r} has evidence outside its observed interval")
        elif isinstance(finding, SceneObservation):
            if any(ts < finding.start_ms or ts > finding.end_ms for ts in timestamps):
                raise ValueError(f"scene finding {finding.index!r} has evidence outside its scene interval")
        elif isinstance(finding, TransitionObservation):
            if len(timestamps) == 1 and finding.at_ms != timestamps[0]:
                raise ValueError(f"transition finding {finding.id!r} must cite the exact observed timestamp when only one frame is supplied")
            if len(timestamps) > 1 and not min(timestamps) <= finding.at_ms <= max(timestamps):
                raise ValueError(f"transition finding {finding.id!r} falls outside its cited evidence window")
    return report
