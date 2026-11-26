"""Lossless MP4 remuxing of selected MPEG-TS rolling segments."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

from .rolling_capture import SegmentRecord, RollingCaptureError
from .diagnostics import BoundedStderrTail, log_event, summarize_ffmpeg_stderr


def _concat_quote(path: Path) -> str:
    # FFmpeg concat-demuxer quoting: single quotes are escaped as '\'\''.
    value = path.resolve().as_posix()
    return "'" + value.replace("'", "'\\''") + "'"


def _run_ffmpeg(
    args: list[str],
    *,
    runner: Callable[..., Any] | None,
    timeout: int,
) -> tuple[int, dict[str, str]]:
    """Run FFmpeg while draining stderr into a fixed-size tail buffer."""
    kwargs = {
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
        "check": False,
    }
    if runner is not None:
        try:
            result = runner(args, **kwargs)
        except subprocess.TimeoutExpired as error:
            fields = summarize_ffmpeg_stderr(getattr(error, "stderr", None))
            log_event("candidate.assembly.ffmpeg_timeout", level=40, **fields)
            raise
        return (
            getattr(result, "returncode", 1),
            summarize_ffmpeg_stderr(getattr(result, "stderr", None)),
        )

    try:
        process = subprocess.Popen(
            args,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError:
        log_event(
            "candidate.assembly.ffmpeg_start_failed",
            level=40,
            failure_code="process_start_failed",
            error_type="OSError",
        )
        raise

    stderr_tail = BoundedStderrTail(process.stderr)
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        log_event(
            "candidate.assembly.ffmpeg_timeout",
            level=40,
            **stderr_tail.diagnostic_fields(),
        )
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return return_code, stderr_tail.diagnostic_fields()


def probe_media_duration_seconds(
    media_path: Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    runner: Callable[..., Any] | None = None,
) -> float | None:
    """Return a finite positive duration, or None when FFprobe is unavailable.

    Prefer FFPROBE_PATH when explicitly configured, then a sibling FFprobe next
    to the configured FFmpeg executable, and finally one available on PATH.
    This is a best-effort display metric: failure must never invalidate a video
    that FFmpeg has already assembled successfully.
    """
    try:
        media_path = Path(media_path)
        if not media_path.is_file() or media_path.stat().st_size <= 0:
            return None

        probe_path = os.environ.get("FFPROBE_PATH", "").strip()
        if not probe_path:
            ffmpeg_resolved = ffmpeg_path
            if not os.path.isabs(ffmpeg_resolved):
                ffmpeg_resolved = shutil.which(ffmpeg_resolved) or ""
                if not ffmpeg_resolved and Path(ffmpeg_path).is_file():
                    ffmpeg_resolved = str(Path(ffmpeg_path).resolve())

            if ffmpeg_resolved:
                sibling_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
                sibling = Path(ffmpeg_resolved).with_name(sibling_name)
                if sibling.is_file():
                    probe_path = str(sibling)

            if not probe_path:
                probe_path = shutil.which("ffprobe") or ("ffprobe.exe" if os.name == "nt" else "ffprobe")

        command = [
            probe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(media_path),
        ]
        execute = runner or subprocess.run
        result = execute(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
        if getattr(result, "returncode", 1) != 0:
            return None

        raw_duration = getattr(result, "stdout", b"")
        if isinstance(raw_duration, bytes):
            raw_duration = raw_duration.decode("ascii", errors="ignore")
        duration = float(str(raw_duration).strip())
        if not math.isfinite(duration) or duration <= 0:
            return None
        return duration
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError) as error:
        # Never log FFprobe stderr or media paths; they can contain local details.
        log_event(
            "candidate.duration.measure_failed",
            level=30,
            error_type=type(error).__name__,
        )
        return None


def assemble_segments(
    records: Sequence[SegmentRecord],
    output_path: Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    runner: Callable[..., Any] | None = None,
) -> Path:
    """Concatenate MPEG-TS segments into a browser-playable MP4 without re-encoding."""
    if not records:
        raise RollingCaptureError("There are no segments to assemble.")
    if output_path.suffix.lower() != ".mp4":
        raise RollingCaptureError("Highlight preview assembly requires an .mp4 output.")
    paths = [record.path.resolve() for record in records]
    root = paths[0].parent
    if any(path.parent != root or not path.is_file() for path in paths):
        raise RollingCaptureError("Selected segments must be existing files from one capture directory.")
    if len(set(paths)) != len(paths):
        raise RollingCaptureError("The selected segment list contains duplicates.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            suffix=".ffconcat",
            prefix="highlight-",
            dir=output_path.parent,
            delete=False,
        ) as manifest:
            manifest_path = Path(manifest.name)
            manifest.write("ffconcat version 1.0\n")
            for path in paths:
                manifest.write(f"file {_concat_quote(path)}\n")

        args = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "concat",
            "-safe", "0",
            "-i", str(manifest_path),
            # Keep only streams that belong in a browser-playable media file.
            "-map", "0:v?",
            "-map", "0:a?",
            "-c", "copy",
            "-movflags", "+faststart",
            "-f", "mp4",
            "-y",
            str(output_path),
        ]
        return_code, diagnostic_fields = _run_ffmpeg(args, runner=runner, timeout=120)
        output_missing = not output_path.is_file() or output_path.stat().st_size == 0
        if return_code != 0 or output_missing:
            if output_missing and return_code == 0:
                diagnostic_fields = {"failure_code": "output_missing"}
            elif not diagnostic_fields:
                diagnostic_fields = {"failure_code": "ffmpeg_unknown"}
            log_event(
                "candidate.assembly.ffmpeg_failed",
                level=40,
                return_code=return_code,
                **diagnostic_fields,
            )
            output_path.unlink(missing_ok=True)
            raise RollingCaptureError(
                "FFmpeg could not create a browser-playable MP4 from the selected highlight segments."
            )
        return output_path
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        raise RollingCaptureError("FFmpeg highlight assembly exceeded its time limit.") from None
    except OSError:
        output_path.unlink(missing_ok=True)
        raise RollingCaptureError("Clippy could not run FFmpeg to assemble the highlight.") from None
    finally:
        if manifest_path is not None:
            manifest_path.unlink(missing_ok=True)
