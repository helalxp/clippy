"""Create portable local template drafts from reviewed reference analysis jobs.

The provider report remains immutable. A draft stores the original report, the
reviewed/corrected view, the review decisions, sampled evidence, and a
renderer-independent interpretation made only from explicitly accepted
findings. Unsupported observations are preserved but never silently mapped to
a renderer setting.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from typing import Any

from PIL import Image

from .analysis import FrameSample, MediaProbe, ReferenceAnalysisResult
from .interpretation import build_template_draft
from .models import (
    InterpretationClaim,
    InterpretationEvidence,
    TemplateAsset,
    TemplateDocument,
    TemplateInterpretation,
    TemplateRecipe,
)
from .reference_report import (
    EvidenceFrame,
    ReferenceStyleReport,
    validate_report_evidence,
)
from .reviews import (
    ReviewDocument,
    _apply_finding_correction,
    _target_exists,
)
from .storage import LocalTemplateStorage
from .visuals import ColorShare, FrameVisualMeasurement


class ReferenceDraftError(ValueError):
    """The reviewed analysis cannot safely be converted into a template draft."""


_CONFIDENCE_RANK = {"uncertain": 0, "low": 1, "medium": 2, "high": 3}


def _review_map(review: ReviewDocument) -> dict[tuple[str, str], Any]:
    return {(item.target_type, item.target_id): item for item in review.items}


def _finding_id(target_type: str, index: int, finding: Any) -> str:
    if target_type == "overview":
        return "overview"
    if target_type == "color_palette":
        return str(index)
    if target_type == "scenes":
        return str(finding.index)
    return str(finding.id)


def _accepted_finding(review_by_key, target_type: str, index: int, finding: Any):
    target_id = _finding_id(target_type, index, finding)
    decision = review_by_key.get((target_type, target_id))
    if decision is None or decision.decision != "accepted":
        return None
    return target_id, decision


def _box_center(box) -> tuple[float, float]:
    return (float(box.x + box.width / 2), float(box.y + box.height / 2))


def _vertical_position(center_y: float) -> str:
    if center_y < 0.34:
        return "top"
    if center_y < 0.67:
        return "middle"
    return "bottom"


def _human_font(review_item) -> str | None:
    if review_item is None or not review_item.correction:
        return None
    typography = review_item.correction.get("typography") or {}
    value = typography.get("font_family")
    return value if isinstance(value, str) and value.strip() else None


def _make_claim_candidates(report: ReferenceStyleReport, review: ReviewDocument):
    """Translate only accepted, supported observations into recipe-property candidates."""
    by_key = _review_map(review)
    candidates: dict[str, list[dict[str, Any]]] = {}

    def add(path: str, value: Any, finding: Any, review_item: Any, rationale: str, *, inferred=False):
        if value is None or not finding.evidence:
            return
        evidence = [
            InterpretationEvidence(asset_id=item.asset_id, timestamp_ms=item.timestamp_ms)
            for item in finding.evidence[:4]
        ]
        candidates.setdefault(path, []).append({
            "value": value,
            "confidence": finding.confidence,
            "source": "human_correction" if review_item.correction else ("inference" if inferred else "visual_observation"),
            "status": "corrected" if review_item.correction else "accepted",
            "evidence": evidence,
            "rationale": (rationale or "Accepted visual observation from the reference video")[:500],
            "reviewed_at": review_item.reviewed_at,
            "review_note": review_item.note,
        })

    # Color roles have direct meaning in the canonical caption/hook/background recipe.
    for index, item in enumerate(report.color_palette):
        selected = _accepted_finding(by_key, "color_palette", index, item)
        if not selected:
            continue
        _target_id, review_item = selected
        path = {
            "caption": "captions.font_color",
            "hook": "hook.color",
            "background": "background.color",
        }.get(item.role)
        if path:
            add(path, item.hex_color, item, review_item, f"Accepted {item.role} color from the reference palette")

    for index, item in enumerate(report.backgrounds):
        selected = _accepted_finding(by_key, "backgrounds", index, item)
        if not selected:
            continue
        _target_id, review_item = selected
        rationale = item.description
        color = item.colors[0] if item.colors else None
        if item.kind == "original_footage":
            add("background.mode", "original", item, review_item, rationale)
        elif item.kind == "blurred_duplicate":
            add("background.mode", "blur", item, review_item, rationale)
        elif item.kind == "solid_color":
            if color and re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                add("background.mode", "solid", item, review_item, rationale)
                add("background.color", color, item, review_item, rationale)
            else:
                candidates.setdefault("_limitations", []).append({
                    "value": "An accepted solid-color background had no confirmed color; background mode was not added to the recipe."
                })

    for index, item in enumerate(report.compositions):
        selected = _accepted_finding(by_key, "compositions", index, item)
        if not selected:
            continue
        _target_id, review_item = selected
        if item.kind == "single_subject" and len(item.subject_regions) == 1:
            anchor_x, anchor_y = _box_center(item.subject_regions[0])
            add("framing.mode", "manual", item, review_item, item.description, inferred=True)
            add("framing.anchor_x", float(anchor_x), item, review_item, "Center of the accepted subject region", inferred=True)
            add("framing.anchor_y", float(anchor_y), item, review_item, "Center of the accepted subject region", inferred=True)

    for item in report.text_regions:
        selected = _accepted_finding(by_key, "text_regions", 0, item)
        if not selected:
            continue
        # Find the stable decision by ID, not by list position.
        review_item = by_key.get(("text_regions", item.id))
        if review_item is None or review_item.decision != "accepted":
            continue
        typography = item.typography
        is_hook = item.role == "hook"
        if item.role not in {"caption", "hook"}:
            continue

        group = "hook" if is_hook else "captions"
        if is_hook:
            if not item.visible_text or len(item.visible_text) > 240:
                candidates.setdefault("_limitations", []).append({
                    "value": f"Accepted hook finding {item.id} had missing or overlong text; it was not enabled in the recipe."
                })
                continue
            add("hook.enabled", True, item, review_item, "An accepted text region identifies this hook treatment")
            add("hook.text", item.visible_text, item, review_item, "Visible hook text from the accepted finding")
            entrance = {
                "none": "none", "fade": "fade", "slide": "slide_up", "pop": "pop",
            }.get(item.animation)
            if entrance:
                add("hook.entrance", entrance, item, review_item, item.animation_notes or item.notes or "Accepted hook entrance treatment")
            if item.first_seen_ms is not None and item.last_seen_ms is not None:
                start = item.first_seen_ms / 1000
                duration = (item.last_seen_ms - item.first_seen_ms) / 1000
                if 0 < duration <= 120:
                    add("hook.start_seconds", float(start), item, review_item, "Estimated hook visibility start", inferred=True)
                    add("hook.duration_seconds", float(duration), item, review_item, "Estimated hook visibility duration", inferred=True)
                elif duration > 120:
                    candidates.setdefault("_limitations", []).append({
                        "value": f"Hook finding {item.id} visibility exceeds the canonical 120-second duration limit."
                    })
            if typography.background_color:
                add("hook.background_color", typography.background_color, item, review_item, "Observed hook text backing color")
        else:
            add("captions.enabled", True, item, review_item, "An accepted caption region identifies this caption treatment")
            if item.animation == "karaoke_highlight":
                add("captions.word_highlight", True, item, review_item, "Observed karaoke-style word highlighting")
            elif item.animation == "none":
                add("captions.word_highlight", False, item, review_item, "No caption word-highlighting animation observed")
            if item.animation == "word_by_word":
                add("captions.reveal_by_word", True, item, review_item, "Observed word-by-word caption reveal")
            elif item.animation == "none":
                add("captions.reveal_by_word", False, item, review_item, "No word-by-word caption reveal observed")

        if typography.size_ratio is not None:
            maximum_size = 0.2 if is_hook else 0.15
            if typography.size_ratio <= maximum_size:
                add(f"{group}.font_size_ratio", float(typography.size_ratio), item, review_item, "Accepted estimated text size")
            else:
                candidates.setdefault("_limitations", []).append({
                    "value": f"Finding {item.id} estimated text size exceeds the canonical {group} limit and was not applied."
                })
        if typography.fill_color:
            add(f"{group}.font_color" if not is_hook else "hook.color", typography.fill_color, item, review_item, "Accepted text fill color")
        if typography.highlight_color and not is_hook:
            add("captions.highlight_color", typography.highlight_color, item, review_item, "Accepted caption highlight color")
        if typography.outline_color and not is_hook:
            add("captions.outline_color", typography.outline_color, item, review_item, "Accepted caption outline color")

        confirmed_font = _human_font(review_item)
        if confirmed_font:
            add(f"{group}.font_family", confirmed_font, item, review_item, "Font family explicitly confirmed by the user")
        elif typography.font_candidates:
            candidates.setdefault("_limitations", []).append({
                "value": f"Finding {item.id} has visual font candidates but no human-confirmed font; no font family was applied."
            })

        if item.box:
            anchor_x, anchor_y = _box_center(item.box)
            add(f"{group}.anchor_x", float(anchor_x), item, review_item, "Center of accepted text bounding box", inferred=True)
            add(f"{group}.anchor_y", float(anchor_y), item, review_item, "Center of accepted text bounding box", inferred=True)
            position = _vertical_position(anchor_y)
            if is_hook and position == "middle":
                position = "center"
            add(f"{group}.position", position, item, review_item, "Vertical placement inferred from accepted text bounding box", inferred=True)
        if typography.line_count is not None and not is_hook:
            if typography.line_count <= 4:
                add("captions.max_lines", int(typography.line_count), item, review_item, "Accepted observed caption line count")
            else:
                candidates.setdefault("_limitations", []).append({
                    "value": f"Finding {item.id} exceeds the canonical four-line caption limit and was not applied."
                })
        if typography.uppercase is not None and not is_hook:
            add("captions.uppercase", bool(typography.uppercase), item, review_item, "Accepted observed capitalization")

    return candidates


def _compile_interpretation(report: ReferenceStyleReport, review: ReviewDocument) -> tuple[TemplateInterpretation, list[str]]:
    candidates = _make_claim_candidates(report, review)
    limitations = list(report.limitations)
    limitations.extend(item["value"] for item in candidates.pop("_limitations", []))
    claims: list[InterpretationClaim] = []

    for path, values in candidates.items():
        distinct = {json.dumps(item["value"], sort_keys=True) for item in values}
        if len(distinct) != 1:
            limitations.append(
                f"Accepted findings disagree about {path}; the value was left out of the draft recipe."
            )
            continue
        best = max(values, key=lambda item: (
            _CONFIDENCE_RANK.get(item["confidence"], 0),
            len(item["evidence"]),
            item["reviewed_at"],
        ))
        evidence = []
        seen = set()
        for candidate in values:
            for item in candidate["evidence"]:
                key = (item.asset_id, item.timestamp_ms)
                if key not in seen:
                    seen.add(key)
                    evidence.append(item)
                if len(evidence) == 4:
                    break
            if len(evidence) == 4:
                break
        reviewed_at = max(item["reviewed_at"] for item in values)
        corrected = any(item["status"] == "corrected" for item in values)
        notes = list(dict.fromkeys(item["review_note"] for item in values if item["review_note"]))
        rationale = "; ".join(dict.fromkeys(item["rationale"] for item in values))[:500]
        claims.append(InterpretationClaim(
            property_path=path,
            value=best["value"],
            confidence=best["confidence"],
            source="human_correction" if corrected else (
                "inference" if best["source"] == "inference" else "visual_observation"
            ),
            status="corrected" if corrected else "accepted",
            evidence=evidence,
            rationale=rationale,
            reviewed_by="local_user",
            reviewed_at=reviewed_at,
            review_note="; ".join(notes)[:500] or None,
        ))

    # A solid background is invalid in the canonical recipe without a color.
    if any(item.value == "solid" for item in claims if item.property_path == "background.mode") and not any(item.property_path == "background.color" for item in claims):
        claims = [item for item in claims if item.property_path != "background.mode"]
        limitations.append("A solid background had conflicting or unavailable color evidence; the background mode was left unchanged.")

    # A hook is only a valid recipe when one unambiguous, readable text value survives.
    if any(item.property_path == "hook.enabled" and item.value is True for item in claims) and not any(item.property_path == "hook.text" for item in claims):
        claims = [item for item in claims if not item.property_path.startswith("hook.")]
        limitations.append("Accepted hook findings did not produce one unambiguous readable text value; no hook settings were applied.")

    provider_id = "gemini"
    model_id = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
    return TemplateInterpretation(
        provider_id=provider_id,
        model_id=model_id,
        summary=report.summary[:1200],
        claims=claims,
        limitations=list(dict.fromkeys(limitations))[:100],
    ), list(dict.fromkeys(limitations))


def _restore_analysis_result(job_report: dict[str, Any], store, job_id: str) -> tuple[ReferenceAnalysisResult, dict[str, bytes]]:
    deterministic = job_report.get("deterministic") or {}
    technical = deterministic.get("technical") or {}
    if not technical:
        raise ReferenceDraftError("deterministic media metadata is missing from this analysis")

    fingerprint = str(technical.get("source_fingerprint") or "")
    if fingerprint.startswith("sha256:"):
        fingerprint = fingerprint.split(":", 1)[1]
    if not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint):
        raise ReferenceDraftError("source fingerprint is missing or invalid")

    try:
        probe = MediaProbe(
            source_name=str(technical["source_name"]),
            source_fingerprint=fingerprint,
            file_size_bytes=int(technical["file_size_bytes"]),
            duration_seconds=float(technical["duration_seconds"]),
            width=int(technical["width"]),
            height=int(technical["height"]),
            frame_rate=(float(technical["frame_rate"]) if technical.get("frame_rate") is not None else None),
            pixel_aspect_ratio=(float(technical["pixel_aspect_ratio"]) if technical.get("pixel_aspect_ratio") is not None else None),
            video_codec=str(technical.get("video_codec") or "unknown"),
            pixel_format=technical.get("pixel_format"),
            has_audio=bool(technical.get("has_audio")),
            audio_codec=technical.get("audio_codec"),
            audio_channels=(int(technical["audio_channels"]) if technical.get("audio_channels") is not None else None),
            audio_sample_rate=(int(technical["audio_sample_rate"]) if technical.get("audio_sample_rate") is not None else None),
            rotation_degrees=int(technical.get("rotation_degrees") or 0),
            video_stream_count=int(technical.get("video_stream_count") or 1),
            audio_stream_count=int(technical.get("audio_stream_count") or 0),
            other_stream_types=tuple(technical.get("other_stream_types") or ()),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ReferenceDraftError("deterministic media metadata is malformed") from exc

    raw_samples = deterministic.get("samples") or []
    if not isinstance(raw_samples, list) or not raw_samples or len(raw_samples) > 64:
        raise ReferenceDraftError("sampled evidence frames are missing or exceed the 64-frame limit")
    samples: list[FrameSample] = []
    image_payloads: dict[str, bytes] = {}
    total_image_bytes = 0
    for index, item in enumerate(raw_samples, start=1):
        asset_id = f"reference_frame_{index:03d}"
        if not isinstance(item, dict) or item.get("asset_id") != asset_id:
            raise ReferenceDraftError("sample evidence identifiers are not in canonical order")
        try:
            timestamp_ms = int(item["timestamp_ms"])
            width = int(item["width"])
            height = int(item["height"])
            size_bytes = int(item["size_bytes"])
            sha256 = str(item["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ReferenceDraftError("sample evidence metadata is incomplete") from exc
        if (
            timestamp_ms < 0
            or width < 1 or width > 16384
            or height < 1 or height > 16384
            or width * height > 50_000_000
            or size_bytes < 1 or size_bytes > 12 * 1024 * 1024
            or not re.fullmatch(r"[a-fA-F0-9]{64}", sha256)
        ):
            raise ReferenceDraftError("sample evidence metadata is outside supported limits")
        total_image_bytes += size_bytes
        if total_image_bytes > 80 * 1024 * 1024:
            raise ReferenceDraftError("sampled evidence exceeds the 80 MB portable-template limit")

        path = f"assets/{asset_id}.png"
        sample = FrameSample(
            timestamp_ms=timestamp_ms,
            relative_path=path,
            sha256=sha256,
            size_bytes=size_bytes,
            width=width,
            height=height,
        )
        try:
            evidence_path = store.evidence_path(job_id, asset_id)
        except (FileNotFoundError, ValueError) as exc:
            raise ReferenceDraftError(f"sample frame {asset_id} is missing or unsafe") from exc
        if evidence_path.is_symlink() or not evidence_path.is_file():
            raise ReferenceDraftError(f"sample frame {asset_id} is missing or unsafe")
        payload = evidence_path.read_bytes()
        if len(payload) != size_bytes or hashlib.sha256(payload).hexdigest().lower() != sha256.lower():
            raise ReferenceDraftError(f"sample frame {asset_id} failed its size or checksum check")
        try:
            with Image.open(evidence_path) as opened:
                if opened.format != "PNG" or opened.size != (width, height):
                    raise ReferenceDraftError(f"sample frame {asset_id} dimensions do not match the manifest")
                opened.verify()
        except ReferenceDraftError:
            raise
        except Exception as exc:
            raise ReferenceDraftError(f"sample frame {asset_id} is not a valid PNG") from exc

        samples.append(sample)
        image_payloads[asset_id] = payload

    visual_measurements = []
    for item in deterministic.get("visual_measurements") or []:
        try:
            colors = tuple(
                ColorShare(hex_color=str(color["hex_color"]), proportion=float(color["proportion"]))
                for color in item.get("dominant_colors", [])
            )
            numbers = [
                float(item["mean_luminance"]),
                float(item["luminance_stddev"]),
                float(item["mean_saturation"]),
                float(item["edge_density"]),
            ]
            change_value = (
                float(item["inter_sample_visual_change"])
                if item.get("inter_sample_visual_change") is not None else None
            )
            if any(not math.isfinite(value) for value in numbers) or (
                change_value is not None and not math.isfinite(change_value)
            ):
                raise ValueError("non-finite deterministic visual measurement")
            visual_measurements.append(FrameVisualMeasurement(
                timestamp_ms=int(item["timestamp_ms"]),
                dominant_colors=colors,
                mean_luminance=numbers[0],
                luminance_stddev=numbers[1],
                mean_saturation=numbers[2],
                edge_density=numbers[3],
                inter_sample_visual_change=change_value,
            ))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ReferenceDraftError("deterministic visual measurements are malformed") from exc

    boundaries = deterministic.get("scene_boundaries_seconds")
    if not isinstance(boundaries, list):
        boundaries = [int(value) / 1000 for value in (deterministic.get("scene_boundaries_ms") or [])]
    if probe.file_size_bytes <= 0 or probe.duration_seconds <= 0 or not math.isfinite(probe.duration_seconds):
        raise ReferenceDraftError("deterministic media dimensions or duration are invalid")
    parsed_boundaries = tuple(float(value) for value in boundaries)
    if any(
        not math.isfinite(value) or value < 0 or value > probe.duration_seconds
        for value in parsed_boundaries
    ):
        raise ReferenceDraftError("deterministic scene boundaries are outside the media duration")
    result = ReferenceAnalysisResult(
        probe=probe,
        scene_boundaries_seconds=parsed_boundaries,
        samples=tuple(samples),
        coverage=dict(deterministic.get("coverage") or {}),
        limitations=tuple(deterministic.get("limitations") or []),
        status=str(deterministic.get("status") or "partial"),
        visual_measurements=tuple(visual_measurements),
    )
    return result, image_payloads


def _save_reviewed_reference_template_locked(
    store,
    template_storage: LocalTemplateStorage,
    job_id: str,
    *,
    name: str | None = None,
    description: str = "",
    category: str | None = None,
    tags: list[str] | None = None,
) -> TemplateDocument:
    """Validate a reviewed reference job and persist a portable local template draft."""
    job = store.get(job_id)
    if job.get("status") not in {"completed", "partial"}:
        raise ReferenceDraftError("analysis must reach a terminal state before it can be saved as a template")
    wrapper = store.get_report(job_id)
    if not wrapper or wrapper.get("ai_status") != "complete" or wrapper.get("ai_report") is None:
        raise ReferenceDraftError("a completed Gemini visual report is required before saving a reviewed template")

    try:
        source_report = ReferenceStyleReport.model_validate(wrapper["ai_report"])
    except Exception as exc:
        raise ReferenceDraftError(f"saved visual report is invalid: {exc}") from exc

    deterministic = wrapper.get("deterministic") or {}
    supplied_frames = [
        EvidenceFrame(asset_id=str(item["asset_id"]), timestamp_ms=int(item["timestamp_ms"]))
        for item in (deterministic.get("samples") or [])
        if isinstance(item, dict) and "asset_id" in item and "timestamp_ms" in item
    ]
    try:
        validate_report_evidence(source_report, supplied_frames)
        review = ReviewDocument.model_validate(store.get_review(job_id))
    except Exception as exc:
        raise ReferenceDraftError(f"analysis evidence or review document is invalid: {exc}") from exc

    accepted = [item for item in review.items if item.decision == "accepted"]
    if not accepted:
        raise ReferenceDraftError("accept at least one report finding before saving a template draft")

    reviewed_report = source_report
    for item in accepted:
        if not _target_exists(source_report, item.target_type, item.target_id):
            raise ReferenceDraftError(f"review target no longer exists: {item.target_type}/{item.target_id}")
        if item.correction:
            reviewed_report = _apply_finding_correction(
                reviewed_report, item.target_type, item.target_id, item.correction
            )

    try:
        validate_report_evidence(reviewed_report, supplied_frames)
    except ValueError as exc:
        raise ReferenceDraftError(f"reviewed corrections invalidate evidence: {exc}") from exc

    analysis_result, image_payloads = _restore_analysis_result(wrapper, store, job_id)
    interpretation, conversion_limitations = _compile_interpretation(reviewed_report, review)
    draft = build_template_draft(
        analysis_result,
        interpretation,
        TemplateRecipe(),
        template_id=f"tpl_{uuid.uuid4().hex[:16]}",
        name=(name or job.get("name") or "Reference template").strip()[:120] or "Reference template",
        description=description[:2000],
        category=(category or job.get("category") or "Uncategorized").strip()[:80] or "Uncategorized",
        tags=tags or [],
    )

    archive = {
        "schema": "clippy.reference-template-review",
        "schema_version": 1,
        "source_analysis_job": job_id,
        "ai_report": source_report.model_dump(mode="json"),
        "reviewed_report": reviewed_report.model_dump(mode="json"),
        "review": review.model_dump(mode="json"),
    }
    archive_bytes = json.dumps(
        archive, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(archive_bytes) > 2 * 1024 * 1024:
        raise ReferenceDraftError("reviewed reference report exceeds the 2 MB template archive limit")

    report_asset = TemplateAsset(
        id="reference_report",
        path="assets/reference-report.json",
        media_type="application/json",
        size_bytes=len(archive_bytes),
        sha256=hashlib.sha256(archive_bytes).hexdigest(),
    )
    document_data = draft.to_storage_dict()
    document_data["assets"] = [
        *document_data.get("assets", []),
        report_asset.model_dump(mode="json"),
    ]
    document = TemplateDocument.model_validate(document_data)

    asset_payloads = {
        **image_payloads,
        "reference_report": archive_bytes,
    }
    try:
        return template_storage.create(document, asset_payloads=asset_payloads)
    except Exception:
        # Storage.create performs atomic cleanup itself; bubble up an actionable error.
        raise


def save_reviewed_reference_template(
    store,
    template_storage: LocalTemplateStorage,
    job_id: str,
    *,
    name: str | None = None,
    description: str = "",
    category: str | None = None,
    tags: list[str] | None = None,
) -> TemplateDocument:
    """Save while holding the analysis-job lock so deletion cannot race asset copying."""
    directory = store._job_dir(job_id)
    with store._lock(str(directory)):
        return _save_reviewed_reference_template_locked(
            store,
            template_storage,
            job_id,
            name=name,
            description=description,
            category=category,
            tags=tags,
        )
