"""Caption presets: the API, the MCP tool and the dashboard agree on them."""
import asyncio
import re

from subtitles import AUTO_CAPTION_STYLE, CAPTION_PRESETS, line_budget


def test_dashboard_offers_every_server_preset():
    src = open("dashboard/src/components/SubtitleModal.jsx").read()
    ids = set(re.findall(r"\{ id: '([a-z]+)'", src))
    missing = set(CAPTION_PRESETS) - ids
    assert not missing, f"presets the dashboard does not offer: {missing}"


def test_default_preset_is_what_clips_ship_with():
    d = CAPTION_PRESETS["default"]
    for k in ("font_name", "font_size", "highlight_color", "border_width",
              "effect", "uppercase", "max_chars", "max_duration"):
        assert d[k] == AUTO_CAPTION_STYLE[k], k


def test_line_budget_shrinks_with_size_and_wide_fonts():
    assert line_budget("Anton", 44) == 16
    assert line_budget("Anton", 70) < line_budget("Anton", 44) < line_budget("Anton", 34)
    assert line_budget("Montserrat ExtraBold", 44) < line_budget("Anton", 44)


class _FakeResp:
    status_code = 200

    def json(self):
        return {"ok": True}


class _FakeClient:
    def __init__(self):
        self.body = None

    async def post(self, path, json):
        assert path == "/api/subtitle"
        self.body = json
        return _FakeResp()


def _call(**args):
    from mcp_server import _tool_add_subtitles
    client = _FakeClient()
    asyncio.run(_tool_add_subtitles(client, {"job_id": "j", "clip_index": 0, **args}))
    return client.body


def test_mcp_forwards_preset_and_new_options():
    body = _call(preset="pill", reveal=True, shadow=2, effect="highlight")
    assert body["preset"] == "pill"
    assert (body["reveal"], body["shadow"], body["effect"]) == (True, 2, "highlight")
    assert "max_chars" not in body  # the preset's own budget applies


def test_mcp_one_word_and_resize_set_the_line_budget():
    assert _call(one_word=True)["max_chars"] == 1
    assert _call(font_size=70)["max_chars"] == line_budget("Anton", 70)
    # Resizing the one-word preset keeps it one word.
    assert "max_chars" not in _call(preset="oneword", font_size=56)


def test_unknown_preset_is_a_400():
    import pytest
    from fastapi import HTTPException
    from app import SubtitleRequest, add_subtitles
    with pytest.raises(HTTPException) as exc:
        asyncio.run(add_subtitles(SubtitleRequest(job_id="j", clip_index=0, preset="nope"), None))
    assert exc.value.status_code == 400


def test_preset_fills_only_fields_not_sent():
    from app import SubtitleRequest
    req = SubtitleRequest(job_id="j", clip_index=0, preset="hormozi", highlight_color="#00FF00")
    merged = req.model_copy(update={k: v for k, v in CAPTION_PRESETS["hormozi"].items()
                                    if k not in req.model_fields_set})
    assert merged.highlight_color == "#00FF00"
    assert merged.reveal is True and merged.font_name == "Montserrat ExtraBold"
