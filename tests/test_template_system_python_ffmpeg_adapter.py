from __future__ import annotations

import io
from PIL import ImageChops, ImageStat
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from template_system.adapters.python_ffmpeg import (
    PythonFFmpegAdapter,
    RenderAdapterError,
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


@pytest.mark.parametrize("background", ["original", "blur", "solid"])
def test_adapter_renders_timed_template_hook_on_every_background_path(tmp_path, background):
    source = tmp_path / "black-source.mp4"
    output = tmp_path / f"hook-{background}.mp4"
    make_black_source_video(source)
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "auto"},
        "background": {
            "mode": background,
            "color": "#000000" if background == "solid" else None,
        },
        "hook": {
            "enabled": True,
            "text": "CLIPPY TEMPLATE",
            "font_family": "DejaVu Sans",
            "font_size_ratio": 0.09,
            "color": "#FFFFFF",
            "background_color": "#112233",
            "position": "custom",
            "anchor_x": 0.5,
            "anchor_y": 0.25,
            "entrance": "fade",
            "start_seconds": 0.2,
            "duration_seconds": 0.7,
        },
    })

    result = PythonFFmpegAdapter(timeout_seconds=120).render(source, output, recipe)
    visible = extract_output_frame(output, seconds=0.5)
    expired = extract_output_frame(output, seconds=1.5)
    visible_pixels = sum(1 for pixel in visible.getdata() if sum(pixel) > 300)
    expired_pixels = sum(1 for pixel in expired.getdata() if sum(pixel) > 100)

    assert result.compatibility.status == "compatible"
    assert visible_pixels > 40
    assert expired_pixels < 10
    assert not list(tmp_path.glob("clippy_template_render_*"))


def test_hook_text_is_written_to_a_file_not_interpolated_into_filter_syntax(tmp_path):
    from template_system.adapters.hooks import write_hook_text

    recipe = TemplateRecipe.model_validate({
        "hook": {
            "enabled": True,
            "text": "Quoted: 'hello', [world] %{metadata\\:title}\\nsecond line",
            "entrance": "slide_up",
        },
    })
    text_path = tmp_path / "hook.txt"
    filter_value = write_hook_text(
        recipe.hook, recipe.canvas, text_path
    )

    assert text_path.read_text(encoding="utf-8") == "Quoted: 'hello', [world] %{metadata\\:title}\\nsecond line"
    assert "Quoted" not in filter_value
    assert filter_value.startswith(",drawtext=textfile=")
    assert "textfile=" in filter_value
    assert "expansion=none" in filter_value
    assert "enable='between(t,0,3)'" in filter_value


def test_adapter_preflight_accepts_supported_motion_and_color_effects():
    recipe = TemplateRecipe.model_validate({
        "motion": [{
            "kind": "slow_zoom",
            "start_seconds": 0.25,
            "end_seconds": 1.5,
            "intensity": 0.2,
            "center_x": 0.6,
            "center_y": 0.4,
        }],
        "effects": [{
            "start_seconds": 0.5,
            "end_seconds": 1.25,
            "brightness": 1.1,
            "contrast": 1.2,
            "saturation": 0.8,
        }],
    })

    report = PythonFFmpegAdapter().preflight(recipe)

    assert report.status == "compatible"
    assert {item.feature for item in report.exact} >= {"motion", "effects"}


def test_effect_segment_zoom_is_rejected_instead_of_silently_ignored():
    recipe = TemplateRecipe.model_validate({
        "effects": [{
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "zoom": 1.2,
        }],
    })

    with pytest.raises(RendererCompatibilityError, match="effects"):
        PythonFFmpegAdapter().preflight(recipe)


def test_adapter_renders_frame_timed_slow_zoom_motion(tmp_path):
    source = tmp_path / "motion-source.mp4"
    baseline = tmp_path / "motion-baseline.mp4"
    output = tmp_path / "motion-output.mp4"
    make_source_video(source)
    adapter = PythonFFmpegAdapter(timeout_seconds=120)
    adapter.render(source, baseline, recipe_for())
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "cover"},
        "motion": [{
            "kind": "slow_zoom",
            "start_seconds": 0.5,
            "end_seconds": 1.5,
            "intensity": 0.45,
            "center_x": 0.65,
            "center_y": 0.35,
        }],
    })

    result = adapter.render(source, output, recipe)
    before_delta = ImageStat.Stat(ImageChops.difference(
        extract_output_frame(baseline, seconds=0.2),
        extract_output_frame(output, seconds=0.2),
    )).mean
    active_delta = ImageStat.Stat(ImageChops.difference(
        extract_output_frame(baseline, seconds=1.0),
        extract_output_frame(output, seconds=1.0),
    )).mean
    after_delta = ImageStat.Stat(ImageChops.difference(
        extract_output_frame(baseline, seconds=1.8),
        extract_output_frame(output, seconds=1.8),
    )).mean

    assert result.duration_seconds == pytest.approx(2.0, abs=0.15)
    assert result.frame_rate == pytest.approx(24.0, abs=0.15)
    assert sum(active_delta) > sum(before_delta) + 8
    assert sum(active_delta) > sum(after_delta) + 8


def test_adapter_renders_time_bounded_brightness_effect(tmp_path):
    source = tmp_path / "effect-source.mp4"
    output = tmp_path / "effect-output.mp4"
    built = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x404040:s=320x240:r=24:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], capture_output=True, text=True, timeout=60, check=False)
    assert built.returncode == 0, built.stderr
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "cover"},
        "effects": [{
            "start_seconds": 0.5,
            "end_seconds": 1.5,
            "brightness": 1.6,
            "contrast": 1.0,
            "saturation": 1.0,
        }],
    })

    result = PythonFFmpegAdapter(timeout_seconds=120).render(source, output, recipe)
    before = extract_output_frame(output, seconds=0.2).getpixel((180, 320))
    active = extract_output_frame(output, seconds=1.0).getpixel((180, 320))
    after = extract_output_frame(output, seconds=1.8).getpixel((180, 320))

    assert result.compatibility.status == "compatible"
    assert sum(active) > sum(before) + 80
    assert sum(active) > sum(after) + 80
    assert sum(before) == pytest.approx(sum(after), abs=18)


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



def extract_output_frame(path: Path, seconds: float = 0.5):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seconds),
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
        recipe=TemplateRecipe.model_validate({"effects": [{"start_seconds": 0.0, "end_seconds": 1.0, "zoom": 1.2}]}),
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


def make_black_source_video(path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:size=320x240:rate=24:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr


def test_adapter_renders_canonical_caption_recipe_with_word_highlight(tmp_path):
    source = tmp_path / "black-source.mp4"
    output = tmp_path / "captioned.mp4"
    make_black_source_video(source)
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "auto"},
        "background": {"mode": "solid", "color": "#000000"},
        "captions": {
            "enabled": True,
            "font_family": "DejaVu Sans",
            "font_size_ratio": 0.035,
            "font_color": "#FFFFFF",
            "highlight_color": "#FFE500",
            "outline_color": "#000000",
            "outline_ratio": 0.002,
            "position": "bottom",
            "max_lines": 2,
            "word_highlight": True,
            "uppercase": True,
            "reveal_by_word": True,
        },
    })
    transcript = {
        "language": "en",
        "segments": [{
            "start": 0.2,
            "end": 1.4,
            "words": [
                {"word": " HELLO", "start": 0.2, "end": 0.7},
                {"word": " WORLD", "start": 0.7, "end": 1.4},
            ],
        }],
    }

    result = PythonFFmpegAdapter(timeout_seconds=120).render(
        source,
        output,
        recipe,
        caption_transcript=transcript,
    )

    frame = extract_output_frame(output)
    bright_pixels = sum(
        1 for pixel in frame.convert("RGB").getdata()
        if sum(pixel) > 300
    )
    assert result.output_path == output.resolve()
    assert result.compatibility.status == "compatible"
    assert bright_pixels > 40
    assert not list(tmp_path.glob("clippy_template_caption_*"))


@pytest.mark.parametrize("background", ["original", "blur", "solid"])
def test_adapter_renders_image_overlay_with_opacity_rotation_and_center_anchor(tmp_path, background):
    source = tmp_path / "black-source.mp4"
    output = tmp_path / f"image-overlay-{background}.mp4"
    image_path = tmp_path / "logo.png"
    make_black_source_video(source)
    Image.new("RGBA", (80, 40), (255, 0, 0, 255)).save(image_path)
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "framing": {"mode": "auto"},
        "background": {
            "mode": background,
            "color": "#000000" if background == "solid" else None,
        },
        "overlays": [{
            "id": "brand-mark",
            "kind": "watermark",
            "asset_id": "asset_logo",
            "anchor_x": 0.8,
            "anchor_y": 0.75,
            "width_ratio": 0.2,
            "opacity": 0.5,
            "rotation_degrees": 90,
        }],
    })

    result = PythonFFmpegAdapter(timeout_seconds=120).render(
        source,
        output,
        recipe,
        overlay_asset_paths={"asset_logo": image_path},
    )

    frame = extract_output_frame(output)
    center = frame.getpixel((288, 480))
    corner = frame.getpixel((5, 5))
    assert result.compatibility.status == "compatible"
    assert center[0] > 70 and center[0] < 210
    assert center[1] < 70 and center[2] < 70
    assert max(corner) < 35
    assert not list(tmp_path.glob("clippy_template_render_*"))


def test_adapter_renders_styled_text_overlay_without_expanding_user_text(tmp_path):
    source = tmp_path / "black-source.mp4"
    output = tmp_path / "text-overlay.mp4"
    make_black_source_video(source)
    recipe = TemplateRecipe.model_validate({
        "canvas": {"width": 360, "height": 640, "fps": 24},
        "overlays": [{
            "id": "brand-copy",
            "kind": "text",
            "text": "CLIPPY\\n%{metadata\\:title}",
            "font_family": "DejaVu Sans",
            "font_size_ratio": 0.06,
            "font_color": "#FFFFFF",
            "background_color": "#112233",
            "outline_color": "#000000",
            "outline_ratio": 0.002,
            "text_align": "center",
            "text_box_width_ratio": 0.8,
            "text_box_height_ratio": 0.24,
            "text_anchor_x": 0.5,
            "text_anchor_y": 0.5,
            "max_lines": 2,
            "opacity": 0.9,
        }],
    })

    result = PythonFFmpegAdapter(timeout_seconds=120).render(source, output, recipe)
    frame = extract_output_frame(output)
    backing_pixels = sum(
        1 for pixel in frame.getdata()
        if 8 <= pixel[0] <= 35 and 18 <= pixel[1] <= 55 and 28 <= pixel[2] <= 75
    )
    text_pixels = sum(
        1 for pixel in frame.getdata()
        if min(pixel) > 180
    )

    assert result.compatibility.status == "compatible"
    assert backing_pixels > 500
    assert text_pixels > 20
    assert not list(tmp_path.glob("clippy_template_render_*"))


def test_text_overlay_file_is_literal_and_uses_configured_style(tmp_path):
    from template_system.adapters.text_overlays import write_text_overlay

    overlay = TemplateRecipe.model_validate({
        "overlays": [{
            "id": "literal-copy",
            "kind": "text",
            "text": "Percent %{metadata\\:title}\\nsecond line",
            "font_family": "DejaVu Sans",
            "text_align": "right",
            "background_color": "#123456",
        }],
    }).overlays[0]
    text_path = tmp_path / "overlay.txt"
    filter_value = write_text_overlay(
        overlay,
        TemplateRecipe().canvas,
        text_path,
    )

    assert text_path.read_text(encoding="utf-8") == "Percent %{metadata\\:title}\\nsecond line"
    assert "Percent" not in filter_value
    assert filter_value.startswith(",drawtext=textfile=")
    assert "expansion=none" in filter_value
    assert "font='DejaVu Sans'" in filter_value
    assert "text_align=right+middle" in filter_value
    assert "boxcolor=0x123456@1.0000" in filter_value


def test_adapter_requires_transcript_when_template_captions_are_enabled(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "captioned.mp4"
    make_source_video(source)
    recipe = TemplateRecipe.model_validate({
        "captions": {"enabled": True},
    })

    with pytest.raises(RenderAdapterError, match="no clip-relative transcript"):
        PythonFFmpegAdapter().render(source, output, recipe)

    assert not output.exists()


def test_template_service_resolves_uploaded_font_and_passes_caption_context(tmp_path):
    import hashlib

    from template_system.capabilities import check_compatibility
    from template_system.models import TemplateAsset
    from template_system.adapters.python_ffmpeg import RenderResult

    payload = b"stored-font-fixture"
    asset = TemplateAsset(
        id="asset_fontfixture",
        path="assets/asset_fontfixture.ttf",
        media_type="font/ttf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    recipe = TemplateRecipe.model_validate({
        "captions": {
            "enabled": True,
            "font_asset_id": asset.id,
        },
        "hook": {
            "enabled": True,
            "text": "Template hook font",
            "font_asset_id": asset.id,
        },
    })
    template = TemplateDocument(
        id="tpl_caption_font01",
        name="Caption font fixture",
        recipe=recipe,
        assets=[asset],
    )
    storage = LocalTemplateStorage(tmp_path / "template-library")
    storage.create(template, asset_payloads={asset.id: payload})

    class CapturingAdapter:
        def __init__(self):
            self.kwargs = None

        def render(self, source, output, resolved_recipe, **kwargs):
            self.kwargs = kwargs
            return RenderResult(
                output_path=Path(output).resolve(),
                source_fingerprint="source",
                output_fingerprint="output",
                duration_seconds=1.0,
                width=360,
                height=640,
                frame_rate=24.0,
                has_audio=False,
                compatibility=check_compatibility(resolved_recipe, "python_ffmpeg"),
            )

    adapter = CapturingAdapter()
    transcript = {"language": "en", "segments": [{"start": 0, "end": 1, "words": []}]}
    TemplateApplicationService(storage, adapter=adapter).apply(
        template.id,
        tmp_path / "source.mp4",
        tmp_path / "rendered.mp4",
        caption_transcript=transcript,
    )

    assert adapter.kwargs["caption_transcript"] == transcript
    assert Path(adapter.kwargs["font_path"]).read_bytes() == payload
    assert Path(adapter.kwargs["hook_font_path"]).read_bytes() == payload


def test_template_service_resolves_uploaded_image_overlay_asset(tmp_path):
    import hashlib
    from io import BytesIO

    from template_system.capabilities import check_compatibility
    from template_system.models import TemplateAsset
    from template_system.adapters.python_ffmpeg import RenderResult

    image_buffer = BytesIO()
    Image.new("RGBA", (8, 4), (255, 0, 0, 255)).save(image_buffer, format="PNG")
    payload = image_buffer.getvalue()
    asset = TemplateAsset(
        id="asset_overlayfixture",
        path="assets/asset_overlayfixture.png",
        media_type="image/png",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        width=8,
        height=4,
    )
    recipe = TemplateRecipe.model_validate({
        "overlays": [{
            "id": "logo",
            "kind": "image",
            "asset_id": asset.id,
            "anchor_x": 0.9,
            "anchor_y": 0.9,
            "width_ratio": 0.1,
        }],
    })
    template = TemplateDocument(
        id="tpl_overlayasset01",
        name="Overlay asset fixture",
        recipe=recipe,
        assets=[asset],
    )
    storage = LocalTemplateStorage(tmp_path / "template-library")
    storage.create(template, asset_payloads={asset.id: payload})

    class CapturingAdapter:
        def __init__(self):
            self.kwargs = None

        def render(self, source, output, resolved_recipe, **kwargs):
            self.kwargs = kwargs
            return RenderResult(
                output_path=Path(output).resolve(),
                source_fingerprint="source",
                output_fingerprint="output",
                duration_seconds=1.0,
                width=360,
                height=640,
                frame_rate=24.0,
                has_audio=False,
                compatibility=check_compatibility(resolved_recipe, "python_ffmpeg"),
            )

    adapter = CapturingAdapter()
    TemplateApplicationService(storage, adapter=adapter).apply(
        template.id,
        tmp_path / "source.mp4",
        tmp_path / "rendered.mp4",
    )

    resolved_path = adapter.kwargs["overlay_asset_paths"][asset.id]
    assert Path(resolved_path).read_bytes() == payload


def test_template_service_resolves_uploaded_text_overlay_font(tmp_path):
    import hashlib
    from template_system.capabilities import check_compatibility
    from template_system.models import TemplateAsset
    from template_system.adapters.python_ffmpeg import RenderResult

    payload = b"stored-text-font-fixture"
    asset = TemplateAsset(
        id="asset_textfont01",
        path="assets/asset_textfont01.ttf",
        media_type="font/ttf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    recipe = TemplateRecipe.model_validate({
        "overlays": [{
            "id": "title-card",
            "kind": "text",
            "text": "Brand message",
            "font_asset_id": asset.id,
        }],
    })
    template = TemplateDocument(
        id="tpl_textfontasset1",
        name="Text font fixture",
        recipe=recipe,
        assets=[asset],
    )
    storage = LocalTemplateStorage(tmp_path / "template-library")
    storage.create(template, asset_payloads={asset.id: payload})

    class CapturingAdapter:
        def __init__(self):
            self.kwargs = None

        def render(self, source, output, resolved_recipe, **kwargs):
            self.kwargs = kwargs
            return RenderResult(
                output_path=Path(output).resolve(),
                source_fingerprint="source",
                output_fingerprint="output",
                duration_seconds=1.0,
                width=360,
                height=640,
                frame_rate=24.0,
                has_audio=False,
                compatibility=check_compatibility(resolved_recipe, "python_ffmpeg"),
            )

    adapter = CapturingAdapter()
    TemplateApplicationService(storage, adapter=adapter).apply(
        template.id,
        tmp_path / "source.mp4",
        tmp_path / "rendered.mp4",
    )

    font_path = adapter.kwargs["overlay_font_paths"][asset.id]
    assert Path(font_path).read_bytes() == payload


def test_adapter_rejects_custom_caption_anchors_instead_of_ignoring_them():
    recipe = TemplateRecipe.model_validate({
        "captions": {"enabled": True, "anchor_x": 0.4},
    })

    with pytest.raises(RendererCompatibilityError, match="unsupported"):
        PythonFFmpegAdapter().preflight(recipe)


def test_adapter_marks_nondefault_caption_line_count_as_approximate():
    recipe = TemplateRecipe.model_validate({
        "captions": {"enabled": True, "max_lines": 3},
    })

    report = PythonFFmpegAdapter().preflight(recipe)

    assert report.status == "partial"
    assert [item.feature for item in report.approximate] == ["captions"]
