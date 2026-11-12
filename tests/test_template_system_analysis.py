from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from template_system.analysis import (
    ReferenceAnalysisError,
    choose_sample_timestamps,
    detect_scene_boundaries,
    extract_sample_frames,
    probe_media,
)


def _probe_payload(*, audio=True, duration="12.5"):
    streams = [{
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30000/1001",
        "pix_fmt": "yuv420p",
        "side_data_list": [{"rotation": 90}],
    }]
    if audio:
        streams.append({
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
        })
    return {"streams": streams, "format": {"duration": duration}}


def _png(width=320, height=180):
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )


def test_probe_media_returns_stream_facts_and_content_fingerprint(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"fixture-video")
    payload = _probe_payload()

    def fake_run(command, **kwargs):
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = probe_media(source)

    assert result.source_name == "reference.mp4"
    assert result.source_fingerprint == hashlib.sha256(b"fixture-video").hexdigest()
    assert result.duration_seconds == 12.5
    assert (result.width, result.height) == (1920, 1080)
    assert result.frame_rate == pytest.approx(29.97002997)
    assert result.has_audio is True
    assert result.audio_codec == "aac"
    assert result.rotation_degrees == 90


def test_probe_media_supports_video_without_audio(tmp_path, monkeypatch):
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"video")

    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, json.dumps(_probe_payload(audio=False)), ""))

    result = probe_media(source)
    assert result.has_audio is False
    assert result.audio_codec is None
    assert result.audio_channels is None


def test_probe_rejects_file_without_video_stream(tmp_path, monkeypatch):
    source = tmp_path / "audio.mp4"
    source.write_bytes(b"audio")
    payload = {"streams": [{"codec_type": "audio"}], "format": {"duration": "2"}}
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, json.dumps(payload), ""))

    with pytest.raises(ReferenceAnalysisError, match="no video stream"):
        probe_media(source)


def test_probe_rejects_invalid_duration(tmp_path, monkeypatch):
    source = tmp_path / "bad.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, json.dumps(_probe_payload(duration="NaN")), ""))

    with pytest.raises(ReferenceAnalysisError, match="positive finite"):
        probe_media(source)


def test_probe_rejects_oversized_source(tmp_path):
    source = tmp_path / "large.mp4"
    source.write_bytes(b"12345")

    with pytest.raises(ReferenceAnalysisError, match="size limit"):
        probe_media(source, max_file_size_bytes=4)


def test_probe_rejects_symlink_source(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    link = tmp_path / "link.mp4"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable in this environment")

    with pytest.raises(ReferenceAnalysisError, match="symbolic link"):
        probe_media(link)


def test_scene_detection_parses_and_bounds_cut_timestamps(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    stderr = (
        "[Parsed_showinfo] n:0 pts_time:0.000\n"
        "[Parsed_showinfo] n:1 pts_time:2.500\n"
        "[Parsed_showinfo] n:2 pts_time:2.520\n"
        "[Parsed_showinfo] n:3 pts_time:8.000\n"
        "[Parsed_showinfo] n:4 pts_time:12.500\n"
    )
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, b"", stderr))

    assert detect_scene_boundaries(source, 12.5) == [2.5, 8.0]


def test_scene_detection_reports_ffmpeg_failure(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 1, b"", b"decode error"))

    with pytest.raises(ReferenceAnalysisError, match="decode error"):
        detect_scene_boundaries(source, 12.5)


def test_choose_samples_uses_uniform_bounded_fallback():
    samples = choose_sample_timestamps(60, [], max_samples=6)

    assert len(samples) == 6
    assert samples == pytest.approx([5, 15, 25, 35, 45, 55])


def test_choose_samples_prioritizes_scene_midpoints_and_stays_bounded():
    samples = choose_sample_timestamps(20, [3, 7, 12, 16], max_samples=5)

    assert len(samples) == 5
    assert samples == sorted(samples)
    assert all(0 < value < 20 for value in samples)


def test_choose_samples_rejects_unbounded_request():
    with pytest.raises(ValueError, match="max_samples"):
        choose_sample_timestamps(10, [], max_samples=1000)


def test_extract_sample_frames_writes_hash_checked_png_evidence(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "evidence"
    payload = _png()

    def fake_run(command, **kwargs):
        assert "-ss" in command
        return subprocess.CompletedProcess(command, 0, payload, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    samples = extract_sample_frames(source, [2.25], output)

    assert len(samples) == 1
    sample = samples[0]
    assert sample.timestamp_ms == 2250
    assert sample.width == 320 and sample.height == 180
    assert sample.sha256 == hashlib.sha256(payload).hexdigest()
    assert (output / sample.relative_path).read_bytes() == payload


def test_extract_sample_frames_rejects_invalid_png(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, b"not-png", b""))

    with pytest.raises(ReferenceAnalysisError, match="valid PNG"):
        extract_sample_frames(source, [1.0], tmp_path / "evidence")


def test_extract_sample_frames_rejects_oversized_frame(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    payload = _png()

    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, payload, b""))

    with pytest.raises(ReferenceAnalysisError, match="byte limit"):
        extract_sample_frames(
            source, [1.0], tmp_path / "evidence", max_frame_bytes=len(payload) - 1
        )


def test_extract_sample_frames_refuses_to_overwrite_existing_evidence(tmp_path, monkeypatch):
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "frame_001_0000001000ms.png").write_bytes(b"previous")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, _png(), b""))

    with pytest.raises(ReferenceAnalysisError, match="already exists"):
        extract_sample_frames(source, [1.0], output)
