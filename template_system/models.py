"""Canonical, versioned data contracts for Clippy editing templates.

This module deliberately describes editing intent, not FFmpeg or Remotion
implementation details. Renderer-specific translation belongs in adapters.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator


class ContractModel(BaseModel):
    """Field-assignment-frozen contract object that rejects undocumented fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]



InterpretationProperty = Literal[
    "canvas.width", "canvas.height", "canvas.fps",
    "canvas.safe_top", "canvas.safe_right", "canvas.safe_bottom", "canvas.safe_left",
    "framing.mode", "framing.anchor_x", "framing.anchor_y", "framing.subject_tracking",
    "captions.enabled", "captions.font_family", "captions.font_size_ratio",
    "captions.font_color", "captions.highlight_color", "captions.outline_color",
    "captions.outline_ratio", "captions.shadow_ratio", "captions.position",
    "captions.anchor_x", "captions.anchor_y", "captions.max_lines",
    "captions.word_highlight", "captions.uppercase", "captions.reveal_by_word",
    "hook.enabled", "hook.font_family", "hook.font_size_ratio", "hook.color",
    "hook.background_color", "hook.position", "hook.anchor_x", "hook.anchor_y",
    "hook.entrance", "hook.start_seconds", "hook.duration_seconds",
    "background.mode", "background.color", "background.blur_radius_ratio",
    "rhythm.pace", "rhythm.target_shot_seconds", "rhythm.target_cuts_per_minute",
]
ClaimValue = StrictStr | StrictInt | StrictFloat | StrictBool | None


class InterpretationEvidence(ContractModel):
    asset_id: str = Field(min_length=1, max_length=80)
    timestamp_ms: int = Field(ge=0)


class InterpretationClaim(ContractModel):
    property_path: InterpretationProperty
    value: ClaimValue
    confidence: Literal["high", "medium", "low", "uncertain"]
    source: Literal["visual_observation", "inference", "deterministic_measurement", "human_correction"]
    status: Literal["pending", "accepted", "rejected", "corrected"] = "pending"
    evidence: list[InterpretationEvidence] = Field(min_length=1, max_length=4)
    rationale: str = Field(min_length=1, max_length=500)
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=128)
    reviewed_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def review_provenance(self) -> "InterpretationClaim":
        if self.status == "pending":
            if self.reviewed_by is not None or self.reviewed_at is not None or self.review_note is not None:
                raise ValueError("pending claims cannot contain review provenance")
        else:
            if not self.reviewed_by or not self.reviewed_by.strip() or self.reviewed_at is None:
                raise ValueError("reviewed claims require reviewer identity and timestamp")
            if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
                raise ValueError("reviewed_at must include a timezone")
        if self.status == "corrected" and self.source != "human_correction":
            raise ValueError("corrected claims must use human_correction as their source")
        if self.source == "human_correction" and self.status != "corrected":
            raise ValueError("human_correction claims must have corrected status")
        keys = [(item.asset_id, item.timestamp_ms) for item in self.evidence]
        if len(keys) != len(set(keys)):
            raise ValueError("claim evidence references must be unique")
        return self


class TemplateInterpretation(ContractModel):
    interpretation_type: Literal["clippy.template_interpretation"] = Field(
        default="clippy.template_interpretation", alias="schema"
    )
    schema_version: Literal[1] = 1
    provider_id: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1200)
    claims: list[InterpretationClaim] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_claim_paths(self) -> "TemplateInterpretation":
        paths = [claim.property_path for claim in self.claims]
        if len(paths) != len(set(paths)):
            raise ValueError("interpretation must contain at most one claim per property path")
        return self


class CanvasRecipe(ContractModel):
    width: int = Field(default=1080, ge=144, le=4096)
    height: int = Field(default=1920, ge=144, le=4096)
    fps: float = Field(default=30.0, gt=0, le=120)
    safe_top: float = Field(default=0.05, ge=0, lt=0.4)
    safe_right: float = Field(default=0.05, ge=0, lt=0.4)
    safe_bottom: float = Field(default=0.08, ge=0, lt=0.4)
    safe_left: float = Field(default=0.05, ge=0, lt=0.4)

    @model_validator(mode="after")
    def safe_area_fits_canvas(self) -> "CanvasRecipe":
        if self.safe_left + self.safe_right >= 1 or self.safe_top + self.safe_bottom >= 1:
            raise ValueError("opposing safe-area margins must sum to less than 1")
        return self


class FramingRecipe(ContractModel):
    mode: Literal["auto", "cover", "contain", "manual"] = "auto"
    anchor_x: float = Field(default=0.5, ge=0, le=1)
    anchor_y: float = Field(default=0.5, ge=0, le=1)
    subject_tracking: bool = False


class CaptionRecipe(ContractModel):
    enabled: bool = False
    font_family: str = Field(default="Arial", min_length=1, max_length=120)
    font_asset_id: str | None = None
    font_size_ratio: float = Field(default=0.035, gt=0, le=0.15)
    font_color: HexColor = "#FFFFFF"
    highlight_color: HexColor = "#FFE45E"
    outline_color: HexColor = "#000000"
    outline_ratio: float = Field(default=0.002, ge=0, le=0.03)
    shadow_ratio: float = Field(default=0.0, ge=0, le=0.05)
    position: Literal["top", "middle", "bottom", "custom"] = "bottom"
    anchor_x: float = Field(default=0.5, ge=0, le=1)
    anchor_y: float = Field(default=0.82, ge=0, le=1)
    max_lines: int = Field(default=2, ge=1, le=4)
    word_highlight: bool = False
    uppercase: bool = False
    reveal_by_word: bool = False


class HookRecipe(ContractModel):
    enabled: bool = False
    text: str = Field(default="", max_length=240)
    font_family: str = Field(default="Arial", min_length=1, max_length=120)
    font_asset_id: str | None = None
    font_size_ratio: float = Field(default=0.06, gt=0, le=0.2)
    color: HexColor = "#FFFFFF"
    background_color: HexColor | None = None
    position: Literal["top", "center", "bottom", "custom"] = "top"
    anchor_x: float = Field(default=0.5, ge=0, le=1)
    anchor_y: float = Field(default=0.16, ge=0, le=1)
    entrance: Literal["none", "fade", "slide_up", "spring", "pop"] = "fade"
    start_seconds: float = Field(default=0.0, ge=0)
    duration_seconds: float = Field(default=3.0, gt=0, le=120)

    @model_validator(mode="after")
    def enabled_hook_has_text(self) -> "HookRecipe":
        if self.enabled and not self.text:
            raise ValueError("an enabled hook must contain non-empty text")
        return self


class BackgroundRecipe(ContractModel):
    mode: Literal["original", "blur", "solid"] = "original"
    color: HexColor | None = None
    blur_radius_ratio: float = Field(default=0.035, ge=0, le=0.2)

    @model_validator(mode="after")
    def solid_background_has_color(self) -> "BackgroundRecipe":
        if self.mode == "solid" and self.color is None:
            raise ValueError("solid background mode requires a color")
        return self


class OverlayRecipe(ContractModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["watermark", "image", "text"]
    asset_id: str | None = None
    text: str | None = Field(default=None, max_length=240)
    font_family: str = Field(default="Arial", min_length=1, max_length=120)
    font_asset_id: str | None = None
    font_size_ratio: float = Field(default=0.045, gt=0, le=0.15)
    font_color: HexColor = "#FFFFFF"
    background_color: HexColor | None = None
    outline_color: HexColor = "#000000"
    outline_ratio: float = Field(default=0.002, ge=0, le=0.03)
    text_align: Literal["left", "center", "right"] = "center"
    text_box_width_ratio: float = Field(default=0.8, ge=0.1, le=1)
    text_box_height_ratio: float = Field(default=0.18, ge=0.04, le=0.6)
    max_lines: int = Field(default=2, ge=1, le=5)
    line_spacing_ratio: float = Field(default=0.005, ge=0, le=0.05)
    anchor_x: float = Field(default=0.9, ge=0, le=1)
    anchor_y: float = Field(default=0.9, ge=0, le=1)
    width_ratio: float = Field(default=0.12, gt=0, le=1)
    opacity: float = Field(default=1.0, ge=0, le=1)
    rotation_degrees: float = Field(default=0.0, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_overlay_payload(self) -> "OverlayRecipe":
        if self.kind in ("watermark", "image") and not self.asset_id:
            raise ValueError(f"{self.kind} overlays require asset_id")
        if self.kind == "text":
            if not self.text or not self.text.strip():
                raise ValueError("text overlays require non-empty text")
            if self.asset_id is not None:
                raise ValueError("text overlays cannot reference an image asset")
            if self.rotation_degrees != 0:
                raise ValueError("text overlay rotation is not supported")
            if len(self.text.replace("\\r\\n", "\\n").replace("\\r", "\\n").split("\\n")) > self.max_lines:
                raise ValueError("text overlay exceeds max_lines; add explicit line breaks or increase max_lines")
            estimated_height = self.font_size_ratio * self.max_lines * 1.35
            if self.text_box_height_ratio < estimated_height:
                raise ValueError("text_box_height_ratio is too small for font_size_ratio and max_lines")
            if self.anchor_x < self.text_box_width_ratio / 2 or self.anchor_x > 1 - self.text_box_width_ratio / 2:
                raise ValueError("text overlay horizontal anchor places its box outside the canvas")
            if self.anchor_y < self.text_box_height_ratio / 2 or self.anchor_y > 1 - self.text_box_height_ratio / 2:
                raise ValueError("text overlay vertical anchor places its box outside the canvas")
        elif self.font_asset_id is not None:
            raise ValueError("font_asset_id is only valid for text overlays")
        return self


class EffectSegment(ContractModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    zoom: float = Field(default=1.0, ge=0.5, le=3.0)
    center_x: float = Field(default=0.5, ge=0, le=1)
    center_y: float = Field(default=0.5, ge=0, le=1)
    brightness: float = Field(default=1.0, ge=0, le=3.0)
    contrast: float = Field(default=1.0, ge=0, le=3.0)
    saturation: float = Field(default=1.0, ge=0, le=3.0)

    @model_validator(mode="after")
    def valid_time_range(self) -> "EffectSegment":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("effect end_seconds must be greater than start_seconds")
        return self


class MotionRecipe(ContractModel):
    kind: Literal["punch_in", "slow_zoom", "pan"] = "punch_in"
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    intensity: float = Field(default=0.15, ge=0, le=1)
    center_x: float = Field(default=0.5, ge=0, le=1)
    center_y: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def valid_time_range(self) -> "MotionRecipe":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("motion end_seconds must be greater than start_seconds")
        return self


class TransitionRecipe(ContractModel):
    kind: Literal["cut", "fade", "dissolve", "slide", "wipe"]
    at_seconds: float = Field(ge=0)
    duration_seconds: float = Field(default=0.25, ge=0, le=5)


class RhythmRecipe(ContractModel):
    pace: Literal["relaxed", "balanced", "fast"] = "balanced"
    target_shot_seconds: float | None = Field(default=None, gt=0, le=60)
    target_cuts_per_minute: float | None = Field(default=None, ge=0, le=120)


class TemplateRecipe(ContractModel):
    """Normalized editing intent shared by analysis, preview and render adapters.

    Positions and dimensions ending in _ratio are normalized to the canvas.
    All timeline values are seconds from the beginning of the clip.
    Colors are six-digit sRGB hex values. Font sizes are ratios of canvas height.
    """

    canvas: CanvasRecipe = Field(default_factory=CanvasRecipe)
    framing: FramingRecipe = Field(default_factory=FramingRecipe)
    captions: CaptionRecipe = Field(default_factory=CaptionRecipe)
    hook: HookRecipe = Field(default_factory=HookRecipe)
    background: BackgroundRecipe = Field(default_factory=BackgroundRecipe)
    overlays: list[OverlayRecipe] = Field(default_factory=list, max_length=64)
    effects: list[EffectSegment] = Field(default_factory=list, max_length=256)
    motion: list[MotionRecipe] = Field(default_factory=list, max_length=256)
    transitions: list[TransitionRecipe] = Field(default_factory=list, max_length=256)
    rhythm: RhythmRecipe = Field(default_factory=RhythmRecipe)

    @model_validator(mode="after")
    def unique_overlay_ids(self) -> "TemplateRecipe":
        ids = [item.id for item in self.overlays]
        if len(ids) != len(set(ids)):
            raise ValueError("overlay ids must be unique within a recipe")
        return self


class TemplateAsset(ContractModel):
    id: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=240)
    media_type: Literal["image/png", "image/webp", "image/jpeg", "font/ttf", "font/otf"]
    size_bytes: int = Field(ge=0, le=250_000_000)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    source_timestamp_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def media_metadata_consistent(self) -> "TemplateAsset":
        if self.media_type.startswith("font/") and any(
            value is not None for value in (self.width, self.height, self.source_timestamp_ms)
        ):
            raise ValueError("font assets cannot contain frame dimensions or source timestamps")
        if (self.width is None) != (self.height is None):
            raise ValueError("image dimensions must be supplied together")
        if self.source_timestamp_ms is not None and self.width is None:
            raise ValueError("timestamped frame assets require image dimensions")
        return self

    @field_validator("path")
    @classmethod
    def relative_safe_asset_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("asset paths must use forward slashes")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise ValueError("asset path must be a safe relative path")
        return value


class TemplateOrigin(ContractModel):
    kind: Literal["manual", "reference_video", "imported"] = "manual"
    source_name: str | None = Field(default=None, max_length=240)
    source_fingerprint: str | None = Field(default=None, pattern=r"^(sha256:)?[a-fA-F0-9]{64}$")
    analyzed_at: datetime | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)


class AnalysisEvidence(ContractModel):
    property_path: str = Field(min_length=1, max_length=160)
    method: str = Field(min_length=1, max_length=120)
    source_timestamp_ms: int | None = Field(default=None, ge=0)
    asset_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = Field(default=None, max_length=1000)


class TemplateAnalysis(ContractModel):
    status: Literal["not_started", "partial", "complete", "failed"] = "not_started"
    coverage: dict[str, float] = Field(default_factory=dict)
    evidence: list[AnalysisEvidence] = Field(default_factory=list, max_length=2048)
    limitations: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("coverage")
    @classmethod
    def coverage_is_normalized(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not 0 <= score <= 1 for score in value.values()):
            raise ValueError("analysis coverage values must be between 0 and 1")
        return value



class RendererCapabilityFinding(ContractModel):
    feature: str = Field(min_length=1, max_length=80)
    level: Literal["exact", "approximate", "unsupported"]
    explanation: str = Field(min_length=1, max_length=500)


class RendererCompatibilityDocument(ContractModel):
    backend: Literal["python_ffmpeg", "remotion_preview", "remotion_render"]
    status: Literal["compatible", "partial", "incompatible"]
    exact: list[RendererCapabilityFinding] = Field(default_factory=list, max_length=32)
    approximate: list[RendererCapabilityFinding] = Field(default_factory=list, max_length=32)
    unsupported: list[RendererCapabilityFinding] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def findings_match_status(self) -> "RendererCompatibilityDocument":
        features = [
            item.feature for item in self.exact + self.approximate + self.unsupported
        ]
        if len(features) != len(set(features)):
            raise ValueError("renderer capability features must be unique")
        if self.unsupported and self.status != "incompatible":
            raise ValueError("unsupported features require incompatible status")
        if not self.unsupported and self.approximate and self.status != "partial":
            raise ValueError("approximate features require partial status")
        if not self.unsupported and not self.approximate and self.status != "compatible":
            raise ValueError("exact-only capabilities require compatible status")
        return self


class TemplateDocument(ContractModel):
    template_type: Literal["clippy.template"] = Field(default="clippy.template", alias="schema")
    schema_version: Literal[2] = 2
    id: str = Field(pattern=r"^tpl_[A-Za-z0-9_-]{8,64}$")
    revision: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="Uncategorized", min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=40)
    origin: TemplateOrigin = Field(default_factory=TemplateOrigin)
    analysis: TemplateAnalysis = Field(default_factory=TemplateAnalysis)
    interpretation: TemplateInterpretation | None = None
    recipe: TemplateRecipe = Field(default_factory=TemplateRecipe)
    capabilities: list[RendererCompatibilityDocument] = Field(default_factory=list, max_length=3)
    assets: list[TemplateAsset] = Field(default_factory=list, max_length=256)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("template timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def asset_references_resolve(self) -> "TemplateDocument":
        asset_ids = {asset.id for asset in self.assets}
        if len(asset_ids) != len(self.assets):
            raise ValueError("template asset ids must be unique")
        asset_by_id = {asset.id: asset for asset in self.assets}
        referenced = {
            overlay.asset_id
            for overlay in self.recipe.overlays
            if overlay.asset_id is not None
        }
        missing = referenced - asset_ids
        if missing:
            raise ValueError(f"recipe references missing asset ids: {sorted(missing)}")
        for overlay in self.recipe.overlays:
            if overlay.asset_id and not asset_by_id[overlay.asset_id].media_type.startswith("image/"):
                raise ValueError(f"overlay {overlay.id!r} must reference an image asset")
        font_refs = {
            asset_id
            for asset_id in (
                self.recipe.captions.font_asset_id,
                self.recipe.hook.font_asset_id,
                *(overlay.font_asset_id for overlay in self.recipe.overlays),
            )
            if asset_id is not None
        }
        if font_refs - asset_ids:
            raise ValueError(f"recipe references missing font asset ids: {sorted(font_refs - asset_ids)}")
        for font_id in font_refs:
            if not asset_by_id[font_id].media_type.startswith("font/"):
                raise ValueError(f"font reference {font_id!r} must point to a font asset")
        evidence_assets = {
            item.asset_id for item in self.analysis.evidence if item.asset_id
        }
        if self.interpretation is not None:
            evidence_assets.update(
                evidence.asset_id
                for claim in self.interpretation.claims
                for evidence in claim.evidence
            )
        if evidence_assets - asset_ids:
            raise ValueError("analysis or interpretation evidence references an unknown asset")
        for item in self.analysis.evidence:
            if item.asset_id and item.source_timestamp_ms is not None:
                asset = asset_by_id[item.asset_id]
                if asset.source_timestamp_ms is not None and asset.source_timestamp_ms != item.source_timestamp_ms:
                    raise ValueError("analysis evidence timestamp does not match its frame asset")
        if self.interpretation is not None:
            for claim in self.interpretation.claims:
                for evidence in claim.evidence:
                    asset = asset_by_id[evidence.asset_id]
                    if asset.source_timestamp_ms != evidence.timestamp_ms:
                        raise ValueError("interpretation evidence timestamp does not match its frame asset")
        backends = [item.backend for item in self.capabilities]
        if len(backends) != len(set(backends)):
            raise ValueError("template renderer capability assessments must be unique")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialize using the public contract keys, including the `schema` alias."""
        return self.model_dump(mode="json", by_alias=True)


class AdaptationProposal(ContractModel):
    path: str = Field(min_length=1, max_length=160)
    value: Any
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("path")
    @classmethod
    def dotted_property_path(cls, value: str) -> str:
        parts = value.split(".")
        if any(not part or not part.replace("_", "").isalnum() for part in parts):
            raise ValueError("adaptation path must be a dotted property path")
        return value
