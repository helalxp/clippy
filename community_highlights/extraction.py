"""Lossless assembly of selected MPEG-TS rolling segments."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

from .rolling_capture import SegmentRecord, RollingCaptureError


def _concat_quote(path: Path) -> str:
    # FFmpeg concat-demuxer quoting: single quotes are escaped as '\'\''.
    value = path.resolve().as_posix()
    return "'" + value.replace("'", "'\\''") + "'"


def assemble_segments(
    records: Sequence[SegmentRecord],
    output_path: Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    """Concatenate compatible MPEG-TS segments without re-encoding."""
    if not records:
        raise RollingCaptureError("There are no segments to assemble.")
    if output_path.suffix.lower() != ".ts":
        raise RollingCaptureError("Lossless rolling assembly currently requires a .ts output.")
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

        result = runner(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-i", str(manifest_path),
                "-map", "0",
                "-c", "copy",
                "-f", "mpegts",
                "-y",
                str(output_path),
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
        if getattr(result, "returncode", 1) != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise RollingCaptureError("FFmpeg could not assemble the selected highlight segments.")
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
