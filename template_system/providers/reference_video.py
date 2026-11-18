"""Gemini visual interpreter for bounded reference-video evidence frames."""
from __future__ import annotations

import json
import os

from ..reference_report import EvidenceFrame, ReferenceStyleReport, validate_report_evidence
from ..analysis import ReferenceAnalysisResult


class GeminiReferenceAnalysisError(RuntimeError):
    pass


class GeminiReferenceAnalyzer:
    """Analyze sampled frames only; the original video is never uploaded."""

    def __init__(
        self, *, client=None, api_key: str | None = None,
        model: str | None = None, consent_confirmed: bool = False,
    ):
        if consent_confirmed is not True:
            raise GeminiReferenceAnalysisError(
                "explicit consent is required before sending sampled frames to Google"
            )
        self.model = model or os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
        if client is not None:
            self.client = client
            return
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiReferenceAnalysisError(
                "GEMINI_API_KEY is required for visual reference analysis"
            )
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiReferenceAnalysisError("google-genai is not installed") from exc
        self.client = genai.Client(api_key=key)

    @staticmethod
    def _prompt(result: ReferenceAnalysisResult) -> str:
        _, assets = result.to_template_parts()
        frames = [
            {
                "asset_id": asset.id,
                "timestamp_ms": asset.source_timestamp_ms,
                "width": asset.width,
                "height": asset.height,
            }
            for asset in assets
        ]
        measurements = [item.to_dict() for item in result.visual_measurements]
        return (
            "You are a forensic short-form video editor analyzing a FINISHED reference video. "
            "Describe the editing and graphic treatment visible in the supplied sampled frames. "
            "Return only the supplied structured JSON schema.\n\n"
            "Evidence rules:\n"
            "- Every finding must cite exact supplied asset_id and timestamp_ms pairs.\n"
            "- Do not invent unseen events, exact durations, or hidden transitions. If timing "
            "cannot be established from sampled frames, leave time fields null or describe it as unknown.\n"
            "- A frame sample is evidence of appearance at that instant, not proof that an element "
            "is continuously visible between samples.\n"
            "- Bounding boxes are estimates in normalized source-frame coordinates (0..1), with "
            "origin at top-left. Include text/graphic boxes only when visible.\n"
            "- Font names are visual candidates, NOT verified font identification. Give a short "
            "ranked candidate list and explain the visual basis. Use no candidate when uncertain.\n"
            "- Estimate typography, alignment, fill, outline, shadow, backing, line count and "
            "placement. Separate visually observed facts from uncertain interpretation in notes.\n"
            "- Identify scene content and editorial purpose at a broad level; do not identify "
            "real people or guess private attributes.\n"
            "- Identify visible motion/effects and transition types only when evidence supports them.\n"
            "- Describe background treatment explicitly: original footage, blurred duplicate, solid fill, gradient, image/video background, or unknown.\n"
            "- Describe composition explicitly: subject framing, split/stacked/screen/picture-in-picture arrangements, with normalized subject-region boxes where visible.\n"
            "- For text, report entrance/reveal animation only when sampled evidence supports it; otherwise use unknown.\n"
            "- For each palette color, provide a valid hex value, a visual role (background/accent/caption/hook/overlay/dominant/other), confidence and frame evidence.\n"
            "- Do not infer audio effects from silent frames. Audio treatment may be described only "
            "as unknown unless separately measured.\n"
            "- Omit absent properties. Never fill a field with a guess to satisfy the schema.\n"
            "- Keep IDs stable and unique within each list. Use concise, useful descriptions.\n\n"
            "- If you provide any summary, visual_identity, editorial_style or overall_pacing conclusion, cite its supporting frames in overview_evidence. Do not provide unsupported global conclusions.\\n"
            "- Do not return audio_treatment; audio is outside this visual analysis.\\n\\n"
            f"VIDEO FACTS:\n{json.dumps(result.probe.to_dict(), sort_keys=True)}\n\n"
            f"DETERMINISTIC CUT CANDIDATES (seconds):\n{json.dumps(list(result.scene_boundaries_seconds))}\n\n"
            f"SUPPLIED FRAMES (only valid evidence references):\n{json.dumps(frames, sort_keys=True)}\n\n"
            f"DETERMINISTIC PIXEL MEASUREMENTS (do not call these semantic detections):\n"
            f"{json.dumps(measurements, sort_keys=True)}\n\n"
            f"ANALYSIS LIMITATIONS:\n{json.dumps(list(result.limitations))}"
        )

    def analyze(self, result: ReferenceAnalysisResult, evidence_root: str) -> ReferenceStyleReport:
        try:
            from google.genai import types
            from ..interpretation import _load_interpretation_frames
        except ImportError as exc:
            raise GeminiReferenceAnalysisError(
                "google-genai dependencies are unavailable"
            ) from exc

        _, assets = result.to_template_parts()
        try:
            frames = _load_interpretation_frames(
                result.samples, assets, evidence_root,
                max_frames=24,
                max_frame_bytes=12 * 1024 * 1024,
                max_total_bytes=64 * 1024 * 1024,
            )
        except Exception as exc:
            raise GeminiReferenceAnalysisError(
                f"Could not prepare bounded visual evidence: {exc}"
            ) from exc

        parts = []
        for frame in frames:
            parts.append(types.Part.from_text(
                text=f"Evidence frame asset_id={frame.asset_id}; timestamp_ms={frame.timestamp_ms}"
            ))
            parts.append(types.Part.from_bytes(
                data=frame.image_bytes, mime_type=frame.media_type
            ))
        parts.append(types.Part.from_text(text=self._prompt(result)))
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReferenceStyleReport,
            temperature=0.1,
        )
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=parts,
                config=config,
            )
        except Exception as exc:
            raise GeminiReferenceAnalysisError(
                f"Gemini reference analysis failed: {exc}"
            ) from exc

        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            try:
                report = ReferenceStyleReport.model_validate(
                    parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
                )
            except Exception as exc:
                raise GeminiReferenceAnalysisError(
                    f"Gemini structured response is invalid: {exc}"
                ) from exc
        else:
            response_text = getattr(response, "text", None)
            if not response_text:
                raise GeminiReferenceAnalysisError("Gemini returned no analysis report")
            try:
                report = ReferenceStyleReport.model_validate_json(response_text)
            except Exception as exc:
                raise GeminiReferenceAnalysisError(
                    f"Gemini response does not match the report schema: {exc}"
                ) from exc

        allowed = [
            EvidenceFrame(
                asset_id=f"reference_frame_{index:03d}",
                timestamp_ms=sample.timestamp_ms,
            )
            for index, sample in enumerate(result.samples, start=1)
        ]
        try:
            return validate_report_evidence(report, allowed)
        except ValueError as exc:
            raise GeminiReferenceAnalysisError(str(exc)) from exc
