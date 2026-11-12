"""Canonical, versioned data contracts for Clippy editing templates.

This module deliberately describes editing intent, not FFmpeg or Remotion
implementation details. Renderer-specific translation belongs in adapters.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    """Immutable contract object that rejects undocumented fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


HexColor = str


class CanvasRecipe(ContractModel):
    width: int = Field(default=1080, ge=144, le=4096)
    height: int = Field(default=1920, ge=144, le=4096)
    fps: float = Field(default=30.0, gt=0, le=120)
    safe_top: float = Field(default=0.05, ge=0, lt=0.4)
    safe_right: float = Field(default=0.05, ge=0, lt=0.4)
    safe_bottom: float = Field(default=0.08, ge=0, lt=0.4)
    safe_left: float = Field(default=0.05, ge=0, lt=0.4)


class FramingRecipe(ContractModel):
    mode: Literal["auto", "cover", "contain", "manual"] = "auto"
    anchor_x: float = Field(default=0.5, ge=0, le=1)
    anchor_y: float = Field(default=0.5, ge=0, le=1)
    subject_tracking: bool = False


class CaptionRecipe(ContractModel):
    enabled: bool = False
    font_family: str = Field(default="Arial", min_length=1, max_length=120)
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
    anchor_x: float = Field(default=0.9, ge=0, le=1)
    anchor_y: float = Field(default=0.9, ge=0, le=1)
    width_ratio: float = Field(default=0.12, gt=0, le=1)
    opacity: float = Field(default=1.0, ge=0, le=1)
    rotation_degrees: float = Field(default=0.0, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_overlay_payload(self) -> "OverlayRecipe":
        if self.kind in ("watermark", "image") and not self.asset_id:
            raise ValueError(f"{self.kind} overlays require asset_id")
        if self.kind == "text" and not self.text:
            raise ValueError("text overlays require text")
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
    evidence: list[AnalysisEvidence] = Field(default_factory=list, max_length=1000)
    limitations: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("coverage")
    @classmethod
    def coverage_is_normalized(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not 0 <= score <= 1 for score in value.values()):
            raise ValueError("analysis coverage values must be between 0 and 1")
        return value


class TemplateDocument(ContractModel):
    schema: Literal["clippy.template"] = "clippy.template"
    schema_version: Literal[2] = 2
    id: str = Field(pattern=r"^tpl_[A-Za-z0-9_-]{8,64}$")
    revision: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="Uncategorized", min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=40)
    origin: TemplateOrigin = Field(default_factory=TemplateOrigin)
    analysis: TemplateAnalysis = Field(default_factory=TemplateAnalysis)
    recipe: TemplateRecipe = Field(default_factory=TemplateRecipe)
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
        referenced = {
            overlay.asset_id
            for overlay in self.recipe.overlays
            if overlay.asset_id is not None
        }
        missing = referenced - asset_ids
        if missing:
            raise ValueError(f"recipe references missing asset ids: {sorted(missing)}")
        evidence_assets = {
            item.asset_id for item in self.analysis.evidence if item.asset_id
        }
        if evidence_assets - asset_ids:
            raise ValueError("analysis evidence references an unknown asset")
        return self


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
