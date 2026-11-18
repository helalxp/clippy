"""Human review decisions for evidence-backed reference-video findings.

Review decisions live separately from the provider report. The original AI
output and its evidence are immutable; this module records explicit human
acceptance or rejection before later recipe synthesis.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .reference_report import EvidenceFrame, ReferenceStyleReport, validate_report_evidence


ReviewTargetType = Literal[
    "overview", "color_palette", "backgrounds", "compositions",
    "text_regions", "graphic_overlays", "effects", "transitions", "scenes",
]


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_type: ReviewTargetType
    target_id: str = Field(min_length=1, max_length=80)
    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)
    reviewed_at: datetime

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review timestamps must include a timezone")
        return value


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

    item = ReviewItem(
        target_type=request.target_type,
        target_id=request.target_id,
        decision=request.decision,
        note=request.note or None,
        reviewed_at=datetime.now(timezone.utc),
    )
    return store.record_review(job_id, item.model_dump(mode="json"))
