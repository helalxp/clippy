from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from template_system.adapters.python_ffmpeg import (
    PythonFFmpegAdapter,
    RenderCancelledError,
    RendererCompatibilityError,
)
from template_system.models import TemplateRecipe


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg adapter integration requires FFmpeg and FFprobe",
)


def make_source_video(path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr


def recipe_for(mode="cover", background="original"):
    return TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": mode},
        "background": {
            "mode": background,
            "color": "#112233" if background == "solid" else None,
            "blur_radius_ratio": 0.025,
        },
    })


def test_adapter_preflight_accepts_exact_cover_recipe():
    adapter = PythonFFmpegAdapter()
    report = adapter.preflight(recipe_for("cover", "original"))

    assert report.status == "compatible"
    assert {item.feature for item in report.exact} == {"canvas", "framing"}


@pytest.mark.parametrize("background", ["blur", "solid", "original"])
def test_adapter_renders_contain_background_modes(tmp_path, background):
    source = tmp_path / "source.mp4"
    output = tmp_path / f"contain-{background}.mp4"
    make_source_video(source)
    adapter = PythonFFmpegAdapter(timeout_seconds=120)
    progress = []

    result = adapter.render(
        source,
        output,
        recipe_for("contain", background),
        progress_callback=lambda stage, fraction: progress.append((stage, fraction)),
    )

    assert output.is_file()
    assert (result.width, result.height) == (360, 640)
    assert result.frame_rate == pytest.approx(24.0, abs=0.15)
    assert result.duration_seconds == pytest.approx(2.0, abs=0.15)
    assert result.has_audio is False
    assert result.compatibility.status == "compatible"
    assert progress[0] == ("rendering", 0.0)
    assert progress[-1] == ("complete", 1.0)


def test_adapter_renders_anchored_cover_crop(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "cover.mp4"
    make_source_video(source)
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "manual", "anchor_x": 0.25, "anchor_y": 0.65},
    })

    result = PythonFFmpegAdapter(timeout_seconds=120).render(source, output, recipe)

    assert result.output_path == output.resolve()
    assert (result.width, result.height) == (360, 640)


def test_adapter_refuses_unimplemented_recipe_features(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "should-not-exist.mp4"
    make_source_video(source)
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "captions": {"enabled": True},
    })

    with pytest.raises(RendererCompatibilityError, match="unsupported"):
        PythonFFmpegAdapter().render(source, output, recipe)

    assert not output.exists()


def test_adapter_refuses_subject_tracking_and_conflicting_background():
    adapter = PythonFFmpegAdapter()
    tracking = TemplateRecipe.model_validate({
        "framing": {"subject_tracking": True},
    })
    conflict = TemplateRecipe.model_validate({
        "framing": {"mode": "cover"},
        "background": {"mode": "blur"},
    })

    with pytest.raises(RendererCompatibilityError):
        adapter.preflight(tracking)
    with pytest.raises(RendererCompatibilityError):
        adapter.preflight(conflict)


def test_adapter_cancellation_before_start_does_not_create_output(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "cancelled.mp4"
    make_source_video(source)

    with pytest.raises(RenderCancelledError, match="before starting"):
        PythonFFmpegAdapter().render(
            source,
            output,
            recipe_for(),
            cancel_check=lambda: True,
        )

    assert not output.exists()


def test_adapter_preserves_existing_output_when_source_is_invalid(tmp_path):
    source = tmp_path / "invalid.mp4"
    source.write_bytes(b"not a video")
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"previous valid output")

    with pytest.raises(Exception):
        PythonFFmpegAdapter().render(source, output, recipe_for())

    assert output.read_bytes() == b"previous valid output"
