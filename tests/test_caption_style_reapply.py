"""The caption look picked in the modal survives a hook / edit / recut.

Those paths derive a new file from the clean clip and put captions back on
top (_reapply_captions). They used to burn the default look, so adding a hook
swapped the user's captions for big yellow Anton (github issue #82).
/api/subtitle now records the look on the clip and the re-burn uses it.
"""
import json
import os

import pytest

app_module = pytest.importorskip("app")


STYLE = {"style": "karaoke", "position": "bottom", "font_size": 20,
         "font_name": "Noto Serif", "font_color": "#FFFFFF",
         "highlight_color": "#FFFFFF", "effect": "box", "max_chars": 24}

TRANSCRIPT = {"language": "en", "segments": [{
    "start": 10.0, "end": 12.0, "text": " Portugal? Okay, if",
    "words": [{"word": " Portugal?", "start": 10.0, "end": 10.6},
              {"word": " Okay,", "start": 10.7, "end": 11.2},
              {"word": " if", "start": 11.3, "end": 11.5}]}]}


def _job(tmp_path, monkeypatch, clip):
    job_id = "job1"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "base_metadata.json").write_text(json.dumps(
        {"transcript": TRANSCRIPT, "shorts": [clip]}))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    return job_id, str(job_dir / "hooked_1_base_clip_1.mp4")


def test_recorded_style_is_reburned(tmp_path, monkeypatch):
    job_id, video = _job(tmp_path, monkeypatch,
                         {"start": 10.0, "end": 12.0, "caption_style": STYLE})
    seen = {}

    def fake_restyle(path, transcript, start, end, style, layout=None):
        seen.update(path=path, start=start, end=end, style=style)
        return "subtitled_x.mp4"

    monkeypatch.setattr(app_module, "_restyle_captions", fake_restyle)
    assert app_module._reapply_captions(job_id, 0, video) == "subtitled_x.mp4"
    assert seen == {"path": video, "start": 10.0, "end": 12.0, "style": STYLE}


def test_edited_words_are_reburned_verbatim(tmp_path, monkeypatch):
    words = [{"word": " Lisboa", "start": 0.0, "end": 0.5},
             {"word": " ahi", "start": 0.6, "end": 1.0}]
    job_id, video = _job(tmp_path, monkeypatch, {
        "start": 10.0, "end": 12.0, "caption_style": STYLE,
        "caption_words": words})
    seen = {}

    def fake_restyle(path, transcript, start, end, style, layout=None):
        seen.update(transcript=transcript, start=start, end=end)
        return "out.mp4"

    monkeypatch.setattr(app_module, "_restyle_captions", fake_restyle)
    app_module._reapply_captions(job_id, 0, video)
    assert (seen["start"], seen["end"]) == (0.0, 1.0)
    assert seen["transcript"]["segments"][0]["words"] == words


def test_no_recorded_style_keeps_the_default_look(tmp_path, monkeypatch):
    job_id, video = _job(tmp_path, monkeypatch, {"start": 10.0, "end": 12.0})
    import sys
    import types
    calls = []
    fake_main = types.SimpleNamespace(
        auto_caption_clip=lambda *a, **k: calls.append(a) or "auto.mp4")
    monkeypatch.setitem(sys.modules, "main", fake_main)
    monkeypatch.setattr(app_module, "_restyle_captions",
                        lambda *a, **k: pytest.fail("no style was recorded"))
    assert app_module._reapply_captions(job_id, 0, video) == "auto.mp4"
    assert calls[0][2:] == (10.0, 12.0)


def test_burn_maps_the_recorded_fields(tmp_path, monkeypatch):
    gen, burn = {}, {}
    monkeypatch.setattr(app_module, "generate_ass",
                        lambda t, s, e, path, **k: gen.update(k) or True)
    monkeypatch.setattr(app_module, "burn_subtitles",
                        lambda v, sub, out, **k: burn.update(k))
    ok = app_module._burn_caption_style(
        "in.mp4", "out.mp4", str(tmp_path / "s.ass"), TRANSCRIPT, 10.0, 12.0,
        {**STYLE, "max_chars": 99})
    assert ok
    assert gen["font_name"] == "Noto Serif" and gen["fontsize"] == 20
    assert gen["effect"] == "box" and gen["alignment"] == "bottom"
    assert gen["max_chars"] == 40  # clamped exactly like the endpoint
    # Fields the style did not carry take the request defaults.
    assert gen["border_width"] == app_module.SubtitleRequest.model_fields["border_width"].default
    assert burn["font_name"] == "Noto Serif" and burn["fontsize"] == 20


def test_classic_style_writes_an_srt(tmp_path, monkeypatch):
    srt = {}
    monkeypatch.setattr(app_module, "generate_srt",
                        lambda t, s, e, path, mc, md: srt.update(mc=mc, md=md) or True)
    monkeypatch.setattr(app_module, "generate_ass",
                        lambda *a, **k: pytest.fail("classic is not karaoke"))
    monkeypatch.setattr(app_module, "burn_subtitles", lambda *a, **k: None)
    assert app_module._burn_caption_style(
        "in.mp4", "out.mp4", str(tmp_path / "s.srt"), TRANSCRIPT, 10.0, 12.0,
        {"style": "classic"})
    assert srt == {"mc": 20, "md": 2.0}


def test_restyle_names_the_output_like_auto_captions(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_burn_caption_style",
                        lambda *a, **k: True)
    video = str(tmp_path / "hooked_1_base_clip_1.mp4")
    out = app_module._restyle_captions(video, TRANSCRIPT, 10.0, 12.0, STYLE)
    name = os.path.basename(out)
    assert name.startswith("subtitled_") and name.endswith("_hooked_1_base_clip_1.mp4")


def test_recut_captioner_only_with_a_recorded_style():
    assert app_module._recut_captioner({}) is None
    assert callable(app_module._recut_captioner({"caption_style": STYLE}))
