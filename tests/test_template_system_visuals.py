from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from template_system.analysis import FrameSample
from template_system.visuals import VisualMeasurementError, measure_visual_samples


def _write_frame(path, color, size=(80, 80)):
    image = Image.new("RGB", size, color)
    image.save(path, format="PNG")
    payload = path.read_bytes()
    return FrameSample(
        timestamp_ms=1000,
        relative_path=path.name,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        width=size[0],
        height=size[1],
    )


def test_measure_visual_samples_reports_color_luminance_and_edges(tmp_path):
    sample = _write_frame(tmp_path / "red.png", (255, 0, 0))

    measurements = measure_visual_samples([sample], tmp_path)

    assert len(measurements) == 1
    measured = measurements[0]
    assert measured.timestamp_ms == 1000
    assert measured.dominant_colors[0].hex_color == "#FF0000"
    assert measured.dominant_colors[0].proportion == pytest.approx(1.0)
    assert measured.mean_luminance == pytest.approx(0.299, abs=0.01)
    assert measured.mean_saturation == pytest.approx(1.0)
    assert measured.edge_density == pytest.approx(0.0)
    assert measured.inter_sample_visual_change is None


def test_measure_visual_samples_reports_adjacent_frame_change(tmp_path):
    first = _write_frame(tmp_path / "first.png", (0, 0, 0))
    second = _write_frame(tmp_path / "second.png", (255, 255, 255))
    second = FrameSample(
        timestamp_ms=2000,
        relative_path=second.relative_path,
        sha256=second.sha256,
        size_bytes=second.size_bytes,
        width=second.width,
        height=second.height,
    )

    measurements = measure_visual_samples([first, second], tmp_path)

    assert measurements[0].inter_sample_visual_change is None
    assert measurements[1].inter_sample_visual_change == pytest.approx(1.0)


def test_measure_visual_samples_rejects_checksum_mismatch(tmp_path):
    sample = _write_frame(tmp_path / "frame.png", (20, 40, 60))
    tampered = FrameSample(
        timestamp_ms=sample.timestamp_ms,
        relative_path=sample.relative_path,
        sha256="0" * 64,
        size_bytes=sample.size_bytes,
        width=sample.width,
        height=sample.height,
    )

    with pytest.raises(VisualMeasurementError, match="checksum"):
        measure_visual_samples([tampered], tmp_path)


def test_measure_visual_samples_rejects_path_traversal(tmp_path):
    sample = FrameSample(
        timestamp_ms=0,
        relative_path="../outside.png",
        sha256="0" * 64,
        size_bytes=1,
        width=1,
        height=1,
    )

    with pytest.raises(VisualMeasurementError, match="safe relative"):
        measure_visual_samples([sample], tmp_path)


def test_measure_visual_samples_rejects_too_many_frames(tmp_path):
    sample = FrameSample(
        timestamp_ms=0,
        relative_path="unused.png",
        sha256="0" * 64,
        size_bytes=1,
        width=1,
        height=1,
    )

    with pytest.raises(ValueError, match="sample count"):
        measure_visual_samples([sample] * 65, tmp_path)


def test_measure_visual_samples_rejects_symlinked_evidence_file(tmp_path):
    actual = tmp_path / "actual.png"
    sample = _write_frame(actual, (0, 0, 0))
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable in this environment")
    linked = FrameSample(
        timestamp_ms=sample.timestamp_ms,
        relative_path=link.name,
        sha256=sample.sha256,
        size_bytes=sample.size_bytes,
        width=sample.width,
        height=sample.height,
    )

    with pytest.raises(VisualMeasurementError, match="symlinks"):
        measure_visual_samples([linked], tmp_path)
