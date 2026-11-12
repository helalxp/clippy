"""Deterministic FFmpeg adapter for the supported template recipe subset.

This adapter intentionally implements canvas, crop/contain framing, and
original/blur/solid background treatment only. Unsupported recipe features are
rejected in preflight rather than silently ignored.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..analysis import ReferenceAnalysisError, _local_video_path, probe_media
from ..capabilities import CompatibilityReport, check_compatibility
from ..models import TemplateRecipe


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
    def _filter_graph(recipe: TemplateRecipe) -> str:
        width, height = recipe.canvas.width, recipe.canvas.height
        fps = f"{recipe.canvas.fps:.6f}".rstrip("0").rstrip(".")
        mode = recipe.framing.mode
        background = recipe.background.mode
        if mode == "auto":
            mode = "cover" if background == "original" else "contain"

        if mode in {"cover", "manual"}:
            x = f"(iw-ow)*{recipe.framing.anchor_x:.6f}"
            y = f"(ih-oh)*{recipe.framing.anchor_y:.6f}"
            return (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height}:x='{x}':y='{y}',"
                f"fps={fps},setsar=1,format=yuv420p[v]"
            )

        if background == "blur":
            radius = max(1, min(50, round(min(width, height) * recipe.background.blur_radius_ratio)))
            return (
                f"[0:v]split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height},boxblur=luma_radius={radius}:luma_power=2[bg];"
                f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                f"fps={fps},setsar=1,format=yuv420p[v]"
            )

        pad_color = recipe.background.color if background == "solid" else "#000000"
        pad_color = "0x" + pad_color.lstrip("#")
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color},"
            f"fps={fps},setsar=1,format=yuv420p[v]"
        )

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

        temporary = parent / f".{destination.stem}.{uuid.uuid4().hex}.tmp.mp4"
        command = [
            self.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
            "-loglevel", "error", "-progress", "pipe:1",
            "-i", str(source),
            "-filter_complex", self._filter_graph(recipe),
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(temporary),
        ]

        if progress_callback is not None:
            progress_callback("rendering", 0.0)
        process = None
        stderr_tail: deque[str] = deque(maxlen=120)
        stderr_thread = None
        started = time.monotonic()
        try:
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
