"""Deterministic FFmpeg adapter for the supported template recipe subset.

Unsupported recipe features are rejected in preflight rather than silently
ignored. Captions and hook/title layers are translated through isolated adapters.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..analysis import ReferenceAnalysisError, _local_video_path, probe_media
from ..capabilities import CompatibilityReport, check_compatibility
from ..models import OverlayRecipe, TemplateRecipe


class RenderAdapterError(RuntimeError):
    pass


class RenderCancelledError(RenderAdapterError):
    pass


class RendererCompatibilityError(RenderAdapterError):
    def __init__(self, report: CompatibilityReport):
        self.report = report
        unsupported = ", ".join(item.feature for item in report.unsupported) or "none"
        approximate = ", ".join(item.feature for item in report.approximate) or "none"
        super().__init__(
            f"python_ffmpeg cannot safely apply this recipe "
            f"(unsupported: {unsupported}; approximate: {approximate})"
        )


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    source_fingerprint: str
    output_fingerprint: str
    duration_seconds: float
    width: int
    height: int
    frame_rate: float | None
    has_audio: bool
    compatibility: CompatibilityReport


class PythonFFmpegAdapter:
    def __init__(
        self,
        *,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        timeout_seconds: int = 1800,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.timeout_seconds = timeout_seconds

    def preflight(self, recipe: TemplateRecipe) -> CompatibilityReport:
        report = check_compatibility(recipe, "python_ffmpeg")
        if report.status == "incompatible":
            raise RendererCompatibilityError(report)
        return report

    @staticmethod
    def _filter_graph(
        recipe: TemplateRecipe,
        *,
        ass_path: str | Path | None = None,
        fonts_dir: str | Path | None = None,
        hook_filter: str | None = None,
        overlay_inputs: list[tuple[OverlayRecipe, int]] | None = None,
    ) -> str:
        width, height = recipe.canvas.width, recipe.canvas.height
        caption_filter = ""
        if ass_path is not None:
            if fonts_dir is None:
                raise RenderAdapterError("caption font directory is required")
            from subtitles import _escape_ffmpeg_filter_value
            ass_value = _escape_ffmpeg_filter_value(str(ass_path))
            fonts_value = _escape_ffmpeg_filter_value(str(fonts_dir))
            if "'" in str(ass_path) or "'" in str(fonts_dir):
                raise RenderAdapterError("caption paths cannot contain apostrophes")
            caption_filter = f",ass=filename='{ass_value}':fontsdir='{fonts_value}'"

        fps = f"{recipe.canvas.fps:.6f}".rstrip("0").rstrip(".")
        mode = recipe.framing.mode
        background = recipe.background.mode
        if mode == "auto":
            mode = "cover" if background == "original" else "contain"

        if mode in {"cover", "manual"}:
            x = f"(iw-ow)*{recipe.framing.anchor_x:.6f}"
            y = f"(ih-oh)*{recipe.framing.anchor_y:.6f}"
            base_graph = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height}:x='{x}':y='{y}',"
                f"fps={fps},setsar=1,format=yuv420p[base0]"
            )
        elif background == "blur":
            radius = max(1, min(50, round(min(width, height) * recipe.background.blur_radius_ratio)))
            base_graph = (
                f"[0:v]split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height},boxblur=luma_radius={radius}:luma_power=2[bg];"
                f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                f"fps={fps},setsar=1,format=yuv420p[base0]"
            )
        else:
            pad_color = recipe.background.color if background == "solid" else "#000000"
            pad_color = "0x" + pad_color.lstrip("#")
            base_graph = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color},"
                f"fps={fps},setsar=1,format=yuv420p[base0]"
            )

        filters = [base_graph]
        current_label = "base0"
        for index, (overlay, input_index) in enumerate(overlay_inputs or []):
            if overlay.kind == "text":
                raise RenderAdapterError("text overlays are not supported by the first overlay adapter")
            overlay_width = max(2, round(width * overlay.width_ratio))
            overlay_label = f"template_overlay_{index}"
            transforms = [
                f"[{input_index}:v]scale={overlay_width}:-1:flags=lanczos",
                "format=rgba",
                f"colorchannelmixer=aa={overlay.opacity:.6f}",
            ]
            if overlay.rotation_degrees:
                radians = overlay.rotation_degrees * 3.141592653589793 / 180.0
                transforms.append(
                    f"rotate={radians:.8f}:ow=rotw(iw):oh=roth(ih):c=none"
                )
            filters.append(",".join(transforms) + f"[{overlay_label}]")
            next_label = f"base{index + 1}"
            x = f"W*{overlay.anchor_x:.6f}-w/2"
            y = f"H*{overlay.anchor_y:.6f}-h/2"
            filters.append(
                f"[{current_label}][{overlay_label}]"
                f"overlay=x='{x}':y='{y}':eof_action=repeat[{next_label}]"
            )
            current_label = next_label

        final_filters = ",".join(
            value.lstrip(",")
            for value in (caption_filter, hook_filter or "")
            if value
        ) or "null"
        filters.append(f"[{current_label}]{final_filters}[v]")
        return ";".join(filters)

    @staticmethod
    def _terminate(process: subprocess.Popen, grace_seconds: float = 3.0) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def render(
        self,
        source_path: str | Path,
        output_path: str | Path,
        recipe: TemplateRecipe,
        *,
        allow_approximate: bool = False,
        progress_callback: Callable[[str, float], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        caption_transcript: dict | None = None,
        caption_split_ranges: list[tuple[float, float]] | None = None,
        font_path: str | Path | None = None,
        hook_font_path: str | Path | None = None,
        overlay_asset_paths: Mapping[str, str | Path] | None = None,
    ) -> RenderResult:
        report = self.preflight(recipe)
        if report.status == "partial" and not allow_approximate:
            raise RendererCompatibilityError(report)
        if cancel_check is not None and cancel_check():
            raise RenderCancelledError("render was cancelled before starting")

        try:
            source = _local_video_path(source_path)
            source_probe = probe_media(source, ffprobe_bin=self.ffprobe_bin)
        except ReferenceAnalysisError as exc:
            raise RenderAdapterError(str(exc)) from exc
        if source_probe.video_stream_count != 1:
            raise RenderAdapterError("the first FFmpeg adapter requires exactly one video stream")
        if source_probe.other_stream_types:
            stream_types = ", ".join(source_probe.other_stream_types)
            raise RenderAdapterError(
                f"the first FFmpeg adapter cannot preserve these source stream types: {stream_types}"
            )

        destination_input = Path(output_path).expanduser()
        if destination_input.suffix.lower() != ".mp4":
            raise RenderAdapterError("PythonFFmpegAdapter currently writes MP4 output only")
        if destination_input.is_symlink():
            raise RenderAdapterError("render output must not be a symbolic link")
        destination_input.parent.mkdir(parents=True, exist_ok=True)
        parent = destination_input.parent.resolve(strict=True)
        if not parent.is_dir():
            raise RenderAdapterError("render output parent is not a directory")
        destination = parent / destination_input.name
        if destination.exists() and destination.is_dir():
            raise RenderAdapterError("render output path is a directory")
        if destination.is_symlink():
            raise RenderAdapterError("render output must not be a symbolic link")
        try:
            if os.path.samefile(source, destination):
                raise RenderAdapterError("render output must not overwrite its clean source")
        except FileNotFoundError:
            pass

        temporary = parent / f".{destination.stem}.{uuid.uuid4().hex}.tmp.mp4"
        render_temp_dir = None
        ass_path = None
        fonts_dir = None
        hook_filter = None
        overlay_inputs: list[tuple[OverlayRecipe, int, Path]] = []
        if recipe.captions.enabled or recipe.hook.enabled or recipe.overlays:
            render_temp_dir = tempfile.mkdtemp(prefix="clippy_template_render_")
        try:
            for index, overlay in enumerate(recipe.overlays):
                if overlay.kind == "text":
                    raise RenderAdapterError("text overlays are not supported by the first overlay adapter")
                if not overlay.asset_id or overlay_asset_paths is None or overlay.asset_id not in overlay_asset_paths:
                    raise RenderAdapterError(
                        f"template overlay {overlay.id!r} is missing its resolved image asset"
                    )
                original_asset_path = Path(overlay_asset_paths[overlay.asset_id]).expanduser()
                if original_asset_path.is_symlink():
                    raise RenderAdapterError("template overlay assets must not be symbolic links")
                original_asset_path = original_asset_path.resolve(strict=True)
                if not original_asset_path.is_file():
                    raise RenderAdapterError("template overlay asset is not a regular file")
                suffix = original_asset_path.suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise RenderAdapterError("template overlay asset has an unsupported image extension")
                staged_asset_path = Path(render_temp_dir) / f"overlay_{index}{suffix}"
                shutil.copyfile(original_asset_path, staged_asset_path)
                overlay_inputs.append((overlay, index + 1, staged_asset_path))

            if recipe.captions.enabled:
                if caption_transcript is None:
                    raise RenderAdapterError(
                        "template captions are enabled, but no clip-relative transcript was supplied"
                    )
                ass_path = Path(render_temp_dir) / f"subs_template_{uuid.uuid4().hex}.ass"
                if font_path is not None:
                    source_font = Path(font_path).expanduser().resolve(strict=True)
                    if not source_font.is_file():
                        raise RenderAdapterError("template caption font asset is not a regular file")
                    fonts_dir = Path(render_temp_dir) / "caption_fonts"
                    fonts_dir.mkdir()
                    shutil.copyfile(source_font, fonts_dir / source_font.name)
                else:
                    import subtitles
                    fonts_dir = Path(subtitles.__file__).resolve().parent / "fonts"
                from .captions import write_caption_ass
                if not write_caption_ass(
                    recipe.captions,
                    recipe.canvas,
                    caption_transcript,
                    ass_path,
                    split_ranges=caption_split_ranges,
                ):
                    raise RenderAdapterError("template caption transcript contains no usable words")
                if "'" in str(ass_path) or "'" in str(fonts_dir):
                    raise RenderAdapterError("caption paths cannot contain apostrophes")

            if recipe.hook.enabled:
                if recipe.hook.start_seconds >= source_probe.duration_seconds:
                    raise RenderAdapterError("template hook starts after the source clip ends")
                hook_text_path = Path(render_temp_dir) / f"hook_{uuid.uuid4().hex}.txt"
                staged_hook_font = None
                if hook_font_path is not None:
                    source_font = Path(hook_font_path).expanduser().resolve(strict=True)
                    if not source_font.is_file():
                        raise RenderAdapterError("template hook font asset is not a regular file")
                    staged_hook_font = Path(render_temp_dir) / f"hook_font{source_font.suffix.lower()}"
                    shutil.copyfile(source_font, staged_hook_font)
                from .hooks import write_hook_text
                hook_filter = write_hook_text(
                    recipe.hook,
                    recipe.canvas,
                    hook_text_path,
                    font_path=staged_hook_font,
                )
                if hook_filter is None:
                    raise RenderAdapterError("enabled template hook did not produce a render layer")
        except Exception as exc:
            if render_temp_dir:
                shutil.rmtree(render_temp_dir, ignore_errors=True)
            if isinstance(exc, RenderAdapterError):
                raise
            raise RenderAdapterError(f"could not prepare template render assets: {exc}") from exc

        try:
            filter_graph = self._filter_graph(
                recipe,
                ass_path=ass_path,
                fonts_dir=fonts_dir,
                hook_filter=hook_filter,
                overlay_inputs=[(overlay, input_index) for overlay, input_index, _ in overlay_inputs],
            )
        except Exception:
            if render_temp_dir:
                shutil.rmtree(render_temp_dir, ignore_errors=True)
            raise

        command = [
            self.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
            "-loglevel", "error", "-progress", "pipe:1",
            "-i", str(source),
        ]
        for _, _, overlay_path in overlay_inputs:
            command.extend(["-i", str(overlay_path)])
        command.extend([
            "-filter_complex", filter_graph,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(temporary),
        ])

        process = None
        stderr_tail: deque[str] = deque(maxlen=120)
        stderr_thread = None
        started = time.monotonic()
        try:
            if progress_callback is not None:
                progress_callback("rendering", 0.0)
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            def drain_stderr() -> None:
                assert process is not None and process.stderr is not None
                for line in process.stderr:
                    stderr_tail.append(line.rstrip())

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
            current_time = 0.0
            assert process.stdout is not None
            for line in process.stdout:
                if time.monotonic() - started > self.timeout_seconds:
                    self._terminate(process)
                    raise RenderAdapterError("FFmpeg render exceeded its timeout")
                if cancel_check is not None and cancel_check():
                    self._terminate(process)
                    raise RenderCancelledError("render was cancelled")
                if "=" not in line:
                    continue
                key, value = line.strip().split("=", 1)
                if key == "out_time_ms":
                    try:
                        current_time = max(0.0, int(value) / 1_000_000)
                    except ValueError:
                        continue
                    if progress_callback is not None:
                        fraction = min(0.9, 0.9 * current_time / source_probe.duration_seconds)
                        progress_callback("rendering", fraction)
            process.wait(timeout=5)
            if stderr_thread is not None:
                stderr_thread.join(timeout=5)
            if process.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                detail = "\n".join(stderr_tail)[-6000:]
                raise RenderAdapterError(
                    f"FFmpeg render failed with exit code {process.returncode}: {detail}"
                )

            if progress_callback is not None:
                progress_callback("verifying", 0.92)
            output_probe = probe_media(temporary, ffprobe_bin=self.ffprobe_bin)
            if (output_probe.width, output_probe.height) != (
                recipe.canvas.width, recipe.canvas.height
            ):
                raise RenderAdapterError(
                    f"render dimensions mismatch: expected {recipe.canvas.width}x{recipe.canvas.height}, "
                    f"got {output_probe.width}x{output_probe.height}"
                )
            if output_probe.frame_rate is None or abs(output_probe.frame_rate - recipe.canvas.fps) > 0.15:
                raise RenderAdapterError(
                    f"render frame rate mismatch: expected {recipe.canvas.fps}, "
                    f"got {output_probe.frame_rate}"
                )
            duration_delta = abs(output_probe.duration_seconds - source_probe.duration_seconds)
            if duration_delta > max(0.25, source_probe.duration_seconds * 0.02):
                raise RenderAdapterError(
                    f"render duration changed unexpectedly by {duration_delta:.3f}s"
                )
            if output_probe.has_audio != source_probe.has_audio:
                raise RenderAdapterError("render did not preserve source audio presence")
            if output_probe.audio_stream_count != source_probe.audio_stream_count:
                raise RenderAdapterError("render did not preserve all source audio streams")
            if output_probe.video_stream_count != 1:
                raise RenderAdapterError("render output contains an unexpected video stream count")

            os.replace(temporary, destination)
            result = RenderResult(
                output_path=destination,
                source_fingerprint=source_probe.source_fingerprint,
                output_fingerprint=output_probe.source_fingerprint,
                duration_seconds=output_probe.duration_seconds,
                width=output_probe.width,
                height=output_probe.height,
                frame_rate=output_probe.frame_rate,
                has_audio=output_probe.has_audio,
                compatibility=report,
            )
            if progress_callback is not None:
                try:
                    progress_callback("complete", 1.0)
                except Exception:
                    pass
            return result
        except Exception:
            if process is not None:
                self._terminate(process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=2)
            temporary.unlink(missing_ok=True)
            raise
        finally:
            if render_temp_dir:
                shutil.rmtree(render_temp_dir, ignore_errors=True)
