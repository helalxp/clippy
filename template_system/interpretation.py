"""Provider-neutral, evidence-linked interpretation and template synthesis.

This module owns the canonical claim contract, frame-evidence verification,
human review, resolver integration, and draft assembly. Optional network-backed
provider adapters live separately under template_system.providers.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import Field, ValidationError

from .analysis import FrameSample, ReferenceAnalysisResult
from .capabilities import CompatibilityReport, check_compatibility
from .models import (
    AdaptationProposal,
    AnalysisEvidence,
    ClaimValue,
    ContractModel,
    InterpretationClaim,
    InterpretationEvidence,
    InterpretationProperty,
    RendererCompatibilityDocument,
    TemplateAnalysis,
    TemplateAsset,
    TemplateDocument,
    TemplateInterpretation,
    TemplateOrigin,
    TemplateRecipe,
)
from .resolver import ResolvedRecipe, resolve_recipe
from .visuals import FrameVisualMeasurement


class ProviderInterpretationClaim(ContractModel):
    """Model-only claim shape. It deliberately has no review/status fields."""
    property_path: InterpretationProperty
    value: ClaimValue
    confidence: Literal["high", "medium", "low", "uncertain"]
    source: Literal["visual_observation", "inference"]
    evidence: list[InterpretationEvidence] = Field(min_length=1, max_length=4)
    rationale: str = Field(min_length=1, max_length=500)


class ProviderInterpretationPayload(ContractModel):
    """Provider response schema without caller-owned provider/model metadata."""
    summary: str = Field(default="", max_length=1200)
    claims: list[ProviderInterpretationClaim] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=100)


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
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError("reviewed_by must not be blank")
    if not isinstance(reviewed_at, datetime):
        raise TypeError("reviewed_at must be a datetime")
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



def build_template_draft(
    analysis_result: ReferenceAnalysisResult,
    interpretation: TemplateInterpretation,
    base_recipe: TemplateRecipe,
    *,
    template_id: str,
    name: str,
    description: str = "",
    category: str = "Uncategorized",
    tags: Sequence[str] = (),
) -> TemplateDocument:
    """Build a persistable template draft from deterministic and reviewed evidence."""
    analysis, assets = analysis_result.to_template_parts()
    synthesis = synthesize_draft_recipe(base_recipe, interpretation)
    analysis_data = analysis.model_dump(mode="python")
    interpretation_evidence = []
    valid_evidence_pairs = {
        (f"reference_frame_{index:03d}", sample.timestamp_ms)
        for index, sample in enumerate(analysis_result.samples, start=1)
    }

    for claim in interpretation.claims:
        note = json.dumps({
            "value": claim.value,
            "source": claim.source,
            "confidence": claim.confidence,
            "status": claim.status,
            "rationale": claim.rationale,
            "reviewed_by": claim.reviewed_by,
            "reviewed_at": claim.reviewed_at.isoformat() if claim.reviewed_at else None,
            "review_note": claim.review_note,
        }, ensure_ascii=False, sort_keys=True, default=str)[:1000]
        for evidence in claim.evidence:
            if (evidence.asset_id, evidence.timestamp_ms) not in valid_evidence_pairs:
                raise InterpretationSynthesisError(
                    f"claim {claim.property_path!r} cites evidence outside the analyzed reference"
                )
            interpretation_evidence.append(AnalysisEvidence(
                property_path=claim.property_path,
                method=f"vision:{interpretation.provider_id}"[:120],
                source_timestamp_ms=evidence.timestamp_ms,
                asset_id=evidence.asset_id,
                note=note,
            ))

    analysis_data["evidence"].extend(
        item.model_dump(mode="python") for item in interpretation_evidence
    )
    analysis_data["limitations"] = list(dict.fromkeys(
        [*analysis_data["limitations"], *interpretation.limitations]
    ))
    analysis = TemplateAnalysis.model_validate(analysis_data)

    now = datetime.now(timezone.utc)
    origin = TemplateOrigin(
        kind="reference_video",
        source_name=analysis_result.probe.source_name,
        source_fingerprint=f"sha256:{analysis_result.probe.source_fingerprint}",
        analyzed_at=now,
    )
    capability_documents = [
        RendererCompatibilityDocument.model_validate(report.as_dict())
        for report in synthesis.compatibility_reports
    ]
    return TemplateDocument.model_validate({
        "id": template_id,
        "name": name,
        "description": description,
        "category": category,
        "tags": list(tags),
        "origin": origin.model_dump(mode="python"),
        "analysis": analysis.model_dump(mode="python"),
        "interpretation": interpretation.model_dump(mode="python", by_alias=True),
        "recipe": synthesis.recipe.model_dump(mode="python"),
        "capabilities": [item.model_dump(mode="python") for item in capability_documents],
        "assets": [asset.model_dump(mode="python") for asset in assets],
        "created_at": now,
        "updated_at": now,
    })
