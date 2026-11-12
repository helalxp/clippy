"""Provider-neutral, evidence-linked semantic interpretation of reference frames.

No network calls or model provider are implemented here. Callers inject a
provider explicitly, making consent, provider choice, and transport boundaries
the responsibility of the application layer.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, model_validator

from .analysis import FrameSample
from .capabilities import CompatibilityReport, RendererBackend, check_compatibility
from .models import AdaptationProposal, ContractModel, TemplateAsset, TemplateRecipe
from .resolver import ResolvedRecipe, resolve_recipe
from .visuals import FrameVisualMeasurement


InterpretationProperty = Literal[
    "canvas.width",
    "canvas.height",
    "canvas.fps",
    "canvas.safe_top",
    "canvas.safe_right",
    "canvas.safe_bottom",
    "canvas.safe_left",
    "framing.mode",
    "framing.anchor_x",
    "framing.anchor_y",
    "framing.subject_tracking",
    "captions.enabled",
    "captions.font_family",
    "captions.font_size_ratio",
    "captions.font_color",
    "captions.highlight_color",
    "captions.outline_color",
    "captions.outline_ratio",
    "captions.shadow_ratio",
    "captions.position",
    "captions.anchor_x",
    "captions.anchor_y",
    "captions.max_lines",
    "captions.word_highlight",
    "captions.uppercase",
    "captions.reveal_by_word",
    "hook.enabled",
    "hook.font_family",
    "hook.font_size_ratio",
    "hook.color",
    "hook.background_color",
    "hook.position",
    "hook.anchor_x",
    "hook.anchor_y",
    "hook.entrance",
    "hook.start_seconds",
    "hook.duration_seconds",
    "background.mode",
    "background.color",
    "background.blur_radius_ratio",
    "rhythm.pace",
    "rhythm.target_shot_seconds",
    "rhythm.target_cuts_per_minute",
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
    evidence: list[InterpretationEvidence] = Field(min_length=1, max_length=8)
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
        return self

    @model_validator(mode="after")
    def unique_evidence(self) -> "InterpretationClaim":
        keys = [(item.asset_id, item.timestamp_ms) for item in self.evidence]
        if len(keys) != len(set(keys)):
            raise ValueError("claim evidence references must be unique")
        return self


class ProviderInterpretationClaim(ContractModel):
    """Model-only claim shape. It deliberately has no review/status fields."""
    property_path: InterpretationProperty
    value: ClaimValue
    confidence: Literal["high", "medium", "low", "uncertain"]
    source: Literal["visual_observation", "inference"]
    evidence: list[InterpretationEvidence] = Field(min_length=1, max_length=8)
    rationale: str = Field(min_length=1, max_length=500)


class ProviderInterpretationPayload(ContractModel):
    """Provider response schema without caller-owned provider/model metadata."""
    summary: str = Field(default="", max_length=1200)
    claims: list[ProviderInterpretationClaim] = Field(default_factory=list, max_length=256)
    limitations: list[str] = Field(default_factory=list, max_length=100)


class TemplateInterpretation(ContractModel):
    interpretation_type: Literal["clippy.template_interpretation"] = Field(
        default="clippy.template_interpretation", alias="schema"
    )
    schema_version: Literal[1] = 1
    provider_id: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1200)
    claims: list[InterpretationClaim] = Field(default_factory=list, max_length=256)
    limitations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_claim_paths(self) -> "TemplateInterpretation":
        paths = [claim.property_path for claim in self.claims]
        if len(paths) != len(set(paths)):
            raise ValueError("interpretation must contain at most one claim per property path")
        return self


@dataclass(frozen=True)
class InterpretationFrame:
    asset_id: str
    timestamp_ms: int
    media_type: str
    image_bytes: bytes


@dataclass(frozen=True)
class DraftRecipeSynthesis:
    recipe: TemplateRecipe
    accepted_paths: tuple[str, ...]
    pending_paths: tuple[str, ...]
    rejected_paths: tuple[str, ...]
    limitations: tuple[str, ...]
    compatibility_reports: tuple[CompatibilityReport, ...]


class InterpretationError(RuntimeError):
    """A provider response or its evidence references are invalid."""


class InterpretationSynthesisError(RuntimeError):
    """Accepted interpretation claims cannot form a valid canonical recipe."""


def _selected_indices(count: int, limit: int) -> list[int]:
    if count <= limit:
        return list(range(count))
    if limit == 1:
        return [count // 2]
    return sorted({
        round(index * (count - 1) / (limit - 1))
        for index in range(limit)
    })


def _load_interpretation_frames(
    samples: Sequence[FrameSample],
    assets: Sequence[TemplateAsset],
    evidence_root: str | Path,
    *,
    max_frames: int,
    max_frame_bytes: int,
    max_total_bytes: int,
) -> tuple[InterpretationFrame, ...]:
    if not 1 <= max_frames <= 64:
        raise ValueError("max_frames must be between 1 and 64")
    if not samples:
        raise InterpretationError("no sampled evidence frames were supplied")
    asset_by_path = {
        asset.path: asset for asset in assets if asset.media_type == "image/png"
    }
    root_input = Path(evidence_root).expanduser()
    if root_input.is_symlink():
        raise InterpretationError("evidence root cannot be a symbolic link")
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise InterpretationError(f"evidence root is unavailable: {exc}") from exc
    if not root.is_dir():
        raise InterpretationError("evidence root is not a directory")

    selected = [samples[index] for index in _selected_indices(len(samples), max_frames)]
    frames: list[InterpretationFrame] = []
    total_bytes = 0
    for sample in selected:
        pure = PurePosixPath(sample.relative_path)
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise InterpretationError("sample path is not a safe relative path")
        if "\\" in sample.relative_path:
            raise InterpretationError("sample paths must use forward slashes")
        asset = asset_by_path.get(sample.relative_path)
        if asset is None:
            raise InterpretationError(f"sample has no matching PNG template asset: {sample.relative_path}")
        if asset.sha256.lower() != sample.sha256.lower() or asset.size_bytes != sample.size_bytes:
            raise InterpretationError("sample metadata does not match its template asset")
        path = root.joinpath(*pure.parts)
        try:
            if not path.resolve(strict=True).is_relative_to(root):
                raise InterpretationError("sample path escapes evidence root")
        except OSError as exc:
            raise InterpretationError(f"sample frame is missing: {sample.relative_path}") from exc
        current = root
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise InterpretationError("sample path cannot traverse symlinks")
        if not path.is_file() or path.stat().st_size > max_frame_bytes:
            raise InterpretationError("sample frame is missing or exceeds the byte limit")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest().lower() != sample.sha256.lower():
            raise InterpretationError("sample frame checksum mismatch")
        total_bytes += len(payload)
        if total_bytes > max_total_bytes:
            raise InterpretationError("selected evidence exceeds the total byte limit")
        frames.append(InterpretationFrame(
            asset_id=asset.id,
            timestamp_ms=sample.timestamp_ms,
            media_type="image/png",
            image_bytes=payload,
        ))
    return tuple(frames)


def interpret_reference(
    samples: Sequence[FrameSample],
    assets: Sequence[TemplateAsset],
    evidence_root: str | Path,
    provider: Callable[[Sequence[InterpretationFrame], Sequence[FrameVisualMeasurement]], Mapping[str, Any] | str],
    *,
    provider_id: str,
    model_id: str,
    visual_measurements: Sequence[FrameVisualMeasurement] = (),
    max_frames: int = 24,
    max_frame_bytes: int = 12 * 1024 * 1024,
    max_total_bytes: int = 64 * 1024 * 1024,
) -> TemplateInterpretation:
    """Call an explicitly injected provider and validate all claims and evidence."""
    frames = _load_interpretation_frames(
        samples,
        assets,
        evidence_root,
        max_frames=max_frames,
        max_frame_bytes=max_frame_bytes,
        max_total_bytes=max_total_bytes,
    )
    selected_timestamps = {frame.timestamp_ms for frame in frames}
    selected_measurements = tuple(
        item for item in visual_measurements
        if item.timestamp_ms in selected_timestamps
    )
    try:
        raw = provider(frames, selected_measurements)
    except Exception as exc:
        raise InterpretationError(f"interpretation provider failed: {type(exc).__name__}: {exc}") from exc
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InterpretationError("provider returned invalid JSON") from exc
    if not isinstance(raw, Mapping):
        raise InterpretationError("provider response must be a JSON object")

    payload = dict(raw)
    payload["provider_id"] = provider_id
    payload["model_id"] = model_id
    raw_claims = payload.get("claims", [])
    if not isinstance(raw_claims, list):
        raise InterpretationError("provider claims must be a JSON array")
    sanitized_claims = []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, Mapping):
            raise InterpretationError("each provider claim must be a JSON object")
        claim = dict(raw_claim)
        if claim.get("source") not in {"visual_observation", "inference"}:
            raise InterpretationError("provider claims must be observations or inferences")
        # Review metadata is caller-owned and never accepted from a model response.
        for field_name in ("status", "reviewed_by", "reviewed_at", "review_note"):
            claim.pop(field_name, None)
        claim["status"] = "pending"
        sanitized_claims.append(claim)
    payload["claims"] = sanitized_claims
    try:
        interpretation = TemplateInterpretation.model_validate(payload)
    except ValidationError as exc:
        raise InterpretationError(f"provider response violates the interpretation contract: {exc}") from exc

    valid_evidence = {(frame.asset_id, frame.timestamp_ms) for frame in frames}
    for claim in interpretation.claims:
        for evidence in claim.evidence:
            if (evidence.asset_id, evidence.timestamp_ms) not in valid_evidence:
                raise InterpretationError(
                    f"claim {claim.property_path!r} cites evidence that was not supplied to the provider"
                )
    return interpretation


def interpretation_to_proposals(
    interpretation: TemplateInterpretation,
) -> list[AdaptationProposal]:
    """Convert only user-accepted/corrected claims into resolver proposals."""
    return [
        AdaptationProposal(
            path=claim.property_path,
            value=claim.value,
            reason=claim.rationale,
        )
        for claim in interpretation.claims
        if claim.status in {"accepted", "corrected"}
    ]


def synthesize_draft_recipe(
    base_recipe: TemplateRecipe,
    interpretation: TemplateInterpretation,
) -> DraftRecipeSynthesis:
    """Apply accepted claims to a copy of the base recipe and validate it strictly."""
    data = base_recipe.model_dump(mode="python")
    accepted: list[str] = []
    pending: list[str] = []
    rejected: list[str] = []

    for claim in interpretation.claims:
        if claim.status == "rejected":
            rejected.append(claim.property_path)
            continue
        if claim.status == "pending":
            pending.append(claim.property_path)
            continue
        group, field_name = claim.property_path.split(".", 1)
        if group not in data or not isinstance(data[group], dict) or field_name not in data[group]:
            raise InterpretationSynthesisError(
                f"claim path {claim.property_path!r} is not a canonical recipe field"
            )
        data[group][field_name] = claim.value
        accepted.append(claim.property_path)

    try:
        recipe = TemplateRecipe.model_validate(data)
    except ValidationError as exc:
        raise InterpretationSynthesisError(
            f"accepted claims do not form a valid recipe: {exc}"
        ) from exc

    return DraftRecipeSynthesis(
        recipe=recipe,
        accepted_paths=tuple(accepted),
        pending_paths=tuple(pending),
        rejected_paths=tuple(rejected),
        limitations=tuple(interpretation.limitations),
        compatibility_reports=tuple(
            check_compatibility(recipe, backend)
            for backend in ("python_ffmpeg", "remotion_preview", "remotion_render")
        ),
    )



def resolve_interpreted_recipe(
    base_recipe: TemplateRecipe,
    interpretation: TemplateInterpretation,
    *,
    revision: Mapping[str, Any] | None = None,
    job_overrides: Mapping[str, Any] | None = None,
    clip_overrides: Mapping[str, Any] | None = None,
    locks: Mapping[str, Any] | None = None,
) -> ResolvedRecipe:
    """Feed reviewed interpretation claims through the canonical precedence resolver."""
    return resolve_recipe(
        template=base_recipe,
        revision=revision,
        job_overrides=job_overrides,
        adaptations=interpretation_to_proposals(interpretation),
        clip_overrides=clip_overrides,
        locks=locks,
    )


_REVIEW_VALUE_UNSET = object()


def review_interpretation_claim(
    interpretation: TemplateInterpretation,
    property_path: str,
    *,
    decision: Literal["accepted", "rejected", "corrected"],
    reviewed_by: str,
    reviewed_at: datetime,
    review_note: str | None = None,
    corrected_value: Any = _REVIEW_VALUE_UNSET,
) -> TemplateInterpretation:
    """Return a new interpretation with an explicit, attributable human decision."""
    if not reviewed_by.strip():
        raise ValueError("reviewed_by must not be blank")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must include a timezone")
    if decision == "corrected" and corrected_value is _REVIEW_VALUE_UNSET:
        raise ValueError("a corrected claim requires corrected_value")
    if decision != "corrected" and corrected_value is not _REVIEW_VALUE_UNSET:
        raise ValueError("corrected_value is only valid for a corrected decision")

    payload = interpretation.model_dump(mode="python", by_alias=True)
    target = next(
        (claim for claim in payload["claims"] if claim["property_path"] == property_path),
        None,
    )
    if target is None:
        raise KeyError(f"interpretation claim not found: {property_path}")
    if target["status"] != "pending":
        raise ValueError("only pending claims can receive a review decision")

    target["status"] = decision
    target["reviewed_by"] = reviewed_by
    target["reviewed_at"] = reviewed_at
    target["review_note"] = review_note
    if decision == "corrected":
        target["source"] = "human_correction"
        target["value"] = corrected_value
    return TemplateInterpretation.model_validate(payload)
