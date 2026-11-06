import json

import pytest

import reference_templates


def test_create_persists_reference_and_detected_blueprint(tmp_path, monkeypatch):
    library = tmp_path / "library"
    monkeypatch.setenv("REFERENCE_TEMPLATES_DIR", str(library))
    source = tmp_path / "example.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(reference_templates, "analyze", lambda _: {
        "technical": {"duration_seconds": 12.5},
        "pacing": {"classification": "fast"},
        "style": {},
    })
    monkeypatch.setattr(reference_templates, "_poster", lambda *_: True)

    manifest = reference_templates.create(source, "example.mp4", "", "Gaming")

    assert manifest["name"] == "example"
    assert manifest["category"] == "Gaming"
    assert manifest["reference"]["video"] == "reference.mp4"
    assert (library / manifest["id"] / "reference.mp4").is_file()
    stored = json.loads((library / manifest["id"] / "manifest.json").read_text())
    assert stored["analysis"]["pacing"]["classification"] == "fast"


def test_manifest_ids_cannot_escape_template_root(tmp_path, monkeypatch):
    monkeypatch.setenv("REFERENCE_TEMPLATES_DIR", str(tmp_path / "library"))
    with pytest.raises(ValueError):
        reference_templates.manifest_path("../not-a-template")


def test_analyze_derives_pacing_from_hard_cuts(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")

    def fake_run(args, timeout=120):
        class Result:
            returncode = 0
            stdout = json.dumps({
                "format": {"duration": "10"},
                "streams": [
                    {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
                    {"codec_type": "audio"},
                ],
            }) if "ffprobe" in args[0] else ""
            stderr = "pts_time:1.000 pts_time:3.000 pts_time:6.000"
        return Result()

    monkeypatch.setattr(reference_templates, "_run", fake_run)
    monkeypatch.setenv("REFERENCE_TEMPLATE_ANALYSIS_SECONDS", "600")
    analysis = reference_templates.analyze(source)

    assert analysis["technical"]["aspect_ratio"] == "vertical"
    assert analysis["pacing"]["hard_cut_count"] == 3
    assert analysis["pacing"]["classification"] == "medium"
