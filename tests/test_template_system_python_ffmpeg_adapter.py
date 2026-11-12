from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from template_system.adapters.python_ffmpeg import (
    PythonFFmpegAdapter,
    RenderCancelledError,
    RendererCompatibilityError,
)
from template_system.models import TemplateDocument, TemplateRecipe
from template_system.service import TemplateApplicationService
from template_system.storage import LocalTemplateStorage


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg adapter integration requires FFmpeg and FFprobe",
)


def make_source_video(path: Path, *, with_audio: bool = False):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
    ]
    if with_audio:
        command.extend([
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=2",
            "-map", "0:v:0", "-map", "1:a:0",
        ])
    command.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        *(["-c:a", "aac", "-shortest"] if with_audio else []),
        str(path),
    ])
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



def test_adapter_preserves_audio_streams(tmp_path):
    source = tmp_path / "source-with-audio.mp4"
    output = tmp_path / "render-with-audio.mp4"
    make_source_video(source, with_audio=True)

    result = PythonFFmpegAdapter(timeout_seconds=120).render(
        source,
        output,
        recipe_for("contain", "blur"),
    )

    assert result.has_audio is True



def test_adapter_refuses_to_silently_drop_subtitle_streams(tmp_path):
    source = tmp_path / "source-with-subtitles.mp4"
    subtitle = tmp_path / "captions.srt"
    output = tmp_path / "output.mp4"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nfixture subtitle\n",
        encoding="utf-8",
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
        "-i", str(subtitle), "-map", "0:v:0", "-map", "1:s:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:s", "mov_text",
        "-shortest", str(source),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert built.returncode == 0, built.stderr

    with pytest.raises(Exception, match="subtitle"):
        PythonFFmpegAdapter().render(source, output, recipe_for())

    assert not output.exists()



def extract_output_frame(path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.5",
        "-i", str(path), "-frames:v", "1", "-f", "image2pipe",
        "-vcodec", "png", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def test_solid_background_and_contain_geometry_match_recipe_pixels(tmp_path):
    source = tmp_path / "red-source.mp4"
    output = tmp_path / "solid-background.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=24:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert built.returncode == 0, built.stderr

    PythonFFmpegAdapter(timeout_seconds=120).render(
        source, output, recipe_for("contain", "solid")
    )
    frame = extract_output_frame(output)

    corner = frame.getpixel((5, 5))
    center = frame.getpixel((180, 320))
    assert all(abs(actual - expected) <= 8 for actual, expected in zip(corner, (17, 34, 51)))
    assert center[0] > 180 and center[1] < 80 and center[2] < 80


def test_manual_crop_anchor_changes_the_visible_source_region(tmp_path):
    source = tmp_path / "anchored-source.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=24:d=2,drawbox=x=0:y=0:w=120:h=240:color=red:t=fill",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert built.returncode == 0, built.stderr

    adapter = PythonFFmpegAdapter(timeout_seconds=120)
    left_output = tmp_path / "left-anchor.mp4"
    right_output = tmp_path / "right-anchor.mp4"
    base = {
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "manual", "anchor_y": 0.5},
    }
    left_recipe = TemplateRecipe.model_validate({
        **base,
        "framing": {**base["framing"], "anchor_x": 0.0},
    })
    right_recipe = TemplateRecipe.model_validate({
        **base,
        "framing": {**base["framing"], "anchor_x": 1.0},
    })
    adapter.render(source, left_output, left_recipe)
    adapter.render(source, right_output, right_recipe)

    left_center = extract_output_frame(left_output).getpixel((180, 320))
    right_center = extract_output_frame(right_output).getpixel((180, 320))
    assert left_center[0] > 170 and left_center[2] < 100
    assert right_center[2] > 150 and right_center[0] < 100



def test_adapter_never_modifies_the_clean_source_file(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "derived.mp4"
    make_source_video(source)
    original_bytes = source.read_bytes()

    PythonFFmpegAdapter(timeout_seconds=120).render(source, output, recipe_for())

    assert source.read_bytes() == original_bytes
    assert output.is_file()



def test_adapter_can_cancel_an_active_ffmpeg_process(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "cancel-during-render.mp4"
    make_source_video(source)
    checks = []

    def cancel_after_process_starts():
        checks.append(True)
        return len(checks) > 1

    with pytest.raises(RenderCancelledError, match="cancelled"):
        PythonFFmpegAdapter(timeout_seconds=120).render(
            source,
            output,
            recipe_for("contain", "blur"),
            cancel_check=cancel_after_process_starts,
        )

    assert len(checks) > 1
    assert not output.exists()
    assert list(tmp_path.glob(".*.tmp.mp4")) == []



def test_application_service_loads_template_resolves_and_returns_provenance(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "applied.mp4"
    make_source_video(source)
    storage = LocalTemplateStorage(tmp_path / "template-library")
    template = TemplateDocument(
        id="tpl_applyservice01",
        name="Application service fixture",
        recipe=recipe_for("contain", "blur"),
    )
    storage.create(template)
    service = TemplateApplicationService(storage)

    result = service.apply(
        template.id,
        source,
        output,
        job_overrides={"canvas": {"width": 400}},
        clip_overrides={"canvas": {"width": 420}},
        locks={"canvas.width": 360},
    )

    assert output.is_file()
    assert result.template_id == template.id
    assert result.template_revision == 1
    assert len(result.recipe_hash) == 64
    assert result.render.width == 360
    assert result.locked_paths == ("canvas.width",)
    serialized = result.to_dict()
    assert serialized["template_id"] == template.id
    assert serialized["output_fingerprint"] == result.render.output_fingerprint
    assert serialized["output_filename"] == output.name
    assert "output_path" not in serialized
    assert serialized["resolved_recipe"]["canvas"]["width"] == 360


def test_application_service_refuses_template_with_unsupported_features(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "should-not-exist.mp4"
    make_source_video(source)
    storage = LocalTemplateStorage(tmp_path / "template-library")
    template = TemplateDocument(
        id="tpl_unsupported01",
        name="Unsupported template",
        recipe=TemplateRecipe.model_validate({"captions": {"enabled": True}}),
    )
    storage.create(template)

    with pytest.raises(RendererCompatibilityError):
        TemplateApplicationService(storage).apply(template.id, source, output)

    assert not output.exists()



def test_adapter_refuses_to_overwrite_its_clean_source(tmp_path):
    source = tmp_path / "source.mp4"
    make_source_video(source)
    original_bytes = source.read_bytes()

    with pytest.raises(Exception, match="must not overwrite its clean source"):
        PythonFFmpegAdapter().render(source, source, recipe_for())

    assert source.read_bytes() == original_bytes


def test_adapter_refuses_hardlink_alias_of_clean_source(tmp_path):
    source = tmp_path / "source.mp4"
    alias = tmp_path / "source-alias.mp4"
    make_source_video(source)
    try:
        alias.hardlink_to(source)
    except OSError:
        pytest.skip("hard links are not supported by this filesystem")
    original_bytes = source.read_bytes()

    with pytest.raises(Exception, match="must not overwrite its clean source"):
        PythonFFmpegAdapter().render(source, alias, recipe_for())

    assert source.read_bytes() == original_bytes
    assert alias.read_bytes() == original_bytes
