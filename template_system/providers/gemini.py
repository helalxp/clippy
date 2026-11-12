"""Optional Google Gemini vision adapter for template interpretation.

This adapter only receives the bounded, sampled PNG evidence supplied by
interpret_reference. It never uploads the original reference video.
"""
from __future__ import annotations

import json
import os
from typing import Sequence

from ..interpretation import (
    InterpretationFrame,
    InterpretationProperty,
    ProviderInterpretationPayload,
)
from ..visuals import FrameVisualMeasurement


class GeminiProviderError(RuntimeError):
    pass


class GeminiVisionInterpreter:
    """Callable provider adapter compatible with interpret_reference()."""

    def __init__(
        self,
        *,
        client=None,
        api_key: str | None = None,
        model: str | None = None,
        consent_confirmed: bool = False,
    ):
        if consent_confirmed is not True:
            raise GeminiProviderError(
                "explicit consent is required before sending sampled frames to Google"
            )
        self.model = model or os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
        if client is not None:
            self.client = client
            return
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiProviderError(
                "GEMINI_API_KEY is required to enable external Gemini interpretation"
            )
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiProviderError("google-genai is not installed") from exc
        self.client = genai.Client(api_key=key)

    @staticmethod
    def _prompt(
        frames: Sequence[InterpretationFrame],
        measurements: Sequence[FrameVisualMeasurement],
    ) -> str:
        from typing import get_args

        allowed_paths = sorted(get_args(InterpretationProperty))
        evidence = [
            {"asset_id": frame.asset_id, "timestamp_ms": frame.timestamp_ms}
            for frame in frames
        ]
        measured = [item.to_dict() for item in measurements]
        return (
            "Analyze the editing style visible in the supplied reference frames. "
            "Return only a JSON object matching the supplied response schema.\n\n"
            "Rules:\n"
            "- Describe visible editing treatment, not the semantic identity of people or subjects.\n"
            "- Make a claim only when the supplied frames visibly support it.\n"
            "- Do not invent exact font names, brand identities, hidden transitions, or unseen text.\n"
            "- Use source='visual_observation' for directly visible properties and "
            "source='inference' for cautious interpretation.\n"
            "- Confidence must be qualitative: high, medium, low, or uncertain.\n"
            "- Every claim must cite one or more exact evidence asset_id/timestamp_ms pairs "
            "from the supplied evidence list.\n"
            "- Do not mark claims accepted, corrected, or rejected. The user reviews every claim.\n"
            "- Omit a property if it cannot be supported. Never guess to fill the schema.\n"
            "- Values must match the canonical property type and renderer-independent units.\n\n"
            f"Allowed property paths:\n{json.dumps(allowed_paths)}\n\n"
            f"Evidence frames:\n{json.dumps(evidence, sort_keys=True)}\n\n"
            f"Deterministic pixel measurements (descriptive evidence only):\n"
            f"{json.dumps(measured, sort_keys=True)}"
        )

    def __call__(
        self,
        frames: Sequence[InterpretationFrame],
        measurements: Sequence[FrameVisualMeasurement],
    ) -> str:
        try:
            from google.genai import types
        except ImportError as exc:
            raise GeminiProviderError("google-genai is required for Gemini vision calls") from exc

        parts = []
        for frame in frames:
            parts.append(types.Part.from_text(
                text=f"Evidence frame: asset_id={frame.asset_id}, timestamp_ms={frame.timestamp_ms}"
            ))
            parts.append(types.Part.from_bytes(
                data=frame.image_bytes,
                mime_type=frame.media_type,
            ))
        parts.append(types.Part.from_text(text=self._prompt(frames, measurements)))

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ProviderInterpretationPayload,
            temperature=0.1,
        )
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=parts,
                config=config,
            )
        except Exception as exc:
            raise GeminiProviderError(f"Gemini interpretation request failed: {exc}") from exc
        response_text = getattr(response, "text", None)
        if not response_text:
            raise GeminiProviderError("Gemini returned no structured interpretation response")
        return response_text
