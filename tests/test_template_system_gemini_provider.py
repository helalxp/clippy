from __future__ import annotations

from types import SimpleNamespace

import pytest

from google.genai import types

from template_system.interpretation import InterpretationFrame, ProviderInterpretationPayload
from template_system.providers.gemini import GeminiProviderError, GeminiVisionInterpreter


class FakeModels:
    def __init__(self, response_text='{"summary":"A clear reference style.","claims":[]}'):
        self.response_text = response_text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.response_text)


class FakeClient:
    def __init__(self, response_text='{"summary":"A clear reference style.","claims":[]}'):
        self.models = FakeModels(response_text)


def test_gemini_provider_builds_bounded_structured_vision_request():
    client = FakeClient()
    provider = GeminiVisionInterpreter(client=client, model="gemini-test", consent_confirmed=True)
    frame = InterpretationFrame(
        asset_id="reference_frame_001",
        timestamp_ms=1250,
        media_type="image/png",
        image_bytes=b"png-frame-bytes",
    )

    response = provider([frame], [])

    assert '"claims":[]' in response
    call = client.models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is ProviderInterpretationPayload
    assert len(call["contents"]) == 3
    assert "reference_frame_001" in call["contents"][0].text
    assert call["contents"][1].inline_data.mime_type == "image/png"
    assert call["contents"][1].inline_data.data == b"png-frame-bytes"
    assert "Do not mark claims accepted" in call["contents"][2].text


def test_gemini_provider_requires_explicit_api_key_without_injected_client(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(GeminiProviderError, match="GEMINI_API_KEY"):
        GeminiVisionInterpreter(consent_confirmed=True)


def test_gemini_provider_rejects_empty_response():
    provider = GeminiVisionInterpreter(client=FakeClient(response_text=""), model="gemini-test", consent_confirmed=True)

    with pytest.raises(GeminiProviderError, match="no structured"):
        provider([], [])



def test_gemini_provider_requires_explicit_external_processing_consent():
    with pytest.raises(GeminiProviderError, match="explicit consent"):
        GeminiVisionInterpreter(client=FakeClient(), model="gemini-test")
