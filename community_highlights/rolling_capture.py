"""FFmpeg rolling-segment capture worker for Community Highlights.

Run `capture.run(stop_event)` in a dedicated worker thread. Streamlink reads
and FFmpeg stdin writes are blocking operations; this module never belongs on
the FastAPI event loop.
"""
from __future__ import annotations

import csv
import math
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .streamlink_capture import ResolvedLiveStream, resolve_live_stream


class RollingCaptureError(RuntimeError):
    """A live stream could not be recorded into rolling segments."""


@dataclass(frozen=True)
class SegmentRecord:
    """One completed segment and its media-timeline presentation interval."""

    path: Path
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class RollingCaptureConfig:
    output_dir: Path
    segment_seconds: int = 4
    retention_seconds: int = 180
    max_buffer_size_mb: int = 512
    quality: str = "best"
    ffmpeg_path: str = field(default_factory=lambda: os.environ.get("FFMPEG_PATH", "ffmpeg"))

    def validate(self) -> None:
        if not isinstance(self.segment_seconds, int) or not 1 <= self.segment_seconds <= 60:
            raise ValueError("segment_seconds must be between 1 and 60.")
        if not isinstance(self.retention_seconds, int) or self.retention_seconds < self.segment_seconds * 2:
            raise ValueError("retention_seconds must cover at least two segments.")
        if not isinstance(self.max_buffer_size_mb, int) or self.max_buffer_size_mb < 16:
            raise ValueError("max_buffer_size_mb must be at least 16.")
        if not isinstance(self.output_dir, Path):
            raise ValueError("output_dir must be a pathlib Path.")
        if not isinstance(self.ffmpeg_path, str) or not self.ffmpeg_path.strip():
            raise ValueError("ffmpeg_path must be a non-empty executable path.")


def build_ffmpeg_segment_args(config: RollingCaptureConfig) -> list[str]:
    """Build a no-shell, stream-copy FFmpeg command writing MPEG-TS segments."""
    config.validate()
    pattern = str(config.output_dir / "segment-%08d.ts")
    index_path = config.output_dir / "segments.csv"
    index_size = max(2, math.ceil(config.retention_seconds / config.segment_seconds) + 2)
    return [
        config.ffmpeg_path,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-i", "pipe:0",
        "-map", "0:v?",
        "-map", "0:a?",
        "-c", "copy",
        "-f", "segment",
        "-segment_format", "mpegts",
        "-segment_time", str(config.segment_seconds),
        "-reset_timestamps", "1",
        "-segment_start_number", "0",
        "-segment_list", str(index_path),
        "-segment_list_type", "csv",
        "-segment_list_size", str(index_size),
        pattern,
    ]


class RollingCapture:
    """Pipe one resolved live stream into FFmpeg and retain a bounded segment ring."""

    def __init__(
        self,
        stream_url: str,
        config: RollingCaptureConfig,
        *,
        resolver: Callable[..., ResolvedLiveStream] = resolve_live_stream,
        popen: Callable[..., Any] = subprocess.Popen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        config.validate()
        self.stream_url = stream_url
        self.config = config
        self._resolver = resolver
        self._popen = popen
        self._clock = clock
        self._stop_requested = threading.Event()
        self._started_at: float | None = None
        # Each candidate owns one pin per segment. Reference counts prevent
        # one overlapping candidate from unpinning footage another still reads.
        self._protected_segments: dict[Path, int] = {}
        self._lock = threading.RLock()

    @property
    def segment_dir(self) -> Path:
        return self.config.output_dir

    def list_segments(self) -> list[Path]:
        """Return completed-looking segment files ordered by their sequence name."""
        if not self.segment_dir.exists():
            return []
        return sorted(
            (p for p in self.segment_dir.glob("segment-*.ts") if p.is_file()),
            key=lambda p: p.name,
        )

    def read_segment_index(self) -> list[SegmentRecord]:
        """Read FFmpeg's bounded CSV index, ignoring incomplete or pruned rows.

        FFmpeg's CSV start/end values are media-timeline seconds, not wall-clock
        timestamps. Chat-to-media clock alignment is intentionally a separate
        responsibility of the future trigger coordinator.
        """
        index_path = self.segment_dir / "segments.csv"
        if not index_path.is_file():
            return []
        root = self.segment_dir.resolve()
        records: list[SegmentRecord] = []
        try:
            with index_path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.reader(handle):
                    if len(row) != 3:
                        continue
                    try:
                        relative = Path(row[0])
                        path = (root / relative).resolve() if not relative.is_absolute() else relative.resolve()
                        start = float(row[1])
                        end = float(row[2])
                    except (OSError, TypeError, ValueError):
                        continue
                    if path.parent != root or not path.is_file():
                        continue
                    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                        continue
                    records.append(SegmentRecord(path, start, end))
        except OSError:
            return []
        return records

    def protect_segments(self, segments: list[Path]) -> list[Path]:
        """Acquire one pin per unique existing segment for this extraction owner."""
        root = self.segment_dir.resolve()
        with self._lock:
            requested: list[Path] = []
            seen: set[Path] = set()
            for candidate in segments:
                path = Path(candidate).resolve()
                if path in seen:
                    continue
                seen.add(path)
                if path.parent != root or path.suffix.lower() != ".ts" or not path.is_file():
                    continue
                requested.append(path)

            current = set(self._protected_segments)
            additions = [path for path in requested if path not in current]
            protected_bytes = sum(
                path.stat().st_size for path in current if path.is_file()
            )
            requested_bytes = sum(path.stat().st_size for path in additions)
            budget = self.config.max_buffer_size_mb * 1024 * 1024
            if protected_bytes + requested_bytes > budget:
                raise RollingCaptureError(
                    "The requested highlight window exceeds the configured protected-segment storage budget."
                )

            # Count each successful protect call as an independent owner. The
            # byte budget still counts each physical file only once.
            for path in requested:
                self._protected_segments[path] = self._protected_segments.get(path, 0) + 1
            return requested

    def release_segments(self, segments: list[Path]) -> None:
        """Release this owner's pins without unpinning concurrent readers."""
        with self._lock:
            for candidate in segments:
                path = Path(candidate).resolve()
                owners = self._protected_segments.get(path, 0)
                if owners <= 1:
                    self._protected_segments.pop(path, None)
                else:
                    self._protected_segments[path] = owners - 1

    def _prune_segments(self) -> None:
        """Enforce age and byte budgets without racing a concurrent pin operation."""
        with self._lock:
            segments = self.list_segments()
            if len(segments) <= 1:
                return

            now = self._clock()
            max_age = self.config.retention_seconds
            max_bytes = self.config.max_buffer_size_mb * 1024 * 1024
            try:
                sizes = {path: path.stat().st_size for path in segments}
            except FileNotFoundError:
                # A segment can be finalized or removed while the index is being
                # refreshed. The next recording iteration will retry pruning.
                return
            total = sum(sizes.values())

            # Keep the newest segment so FFmpeg can continue its sequence even
            # when every older segment has aged out or the byte cap is reached.
            for segment in segments[:-1]:
                resolved = segment.resolve()
                # Keep this final protected check and unlink under the same lock
                # used by protect_segments(); a trigger cannot pin a file after
                # this check but before the file is deleted.
                if resolved in self._protected_segments:
                    continue
                try:
                    stat = segment.stat()
                    age_expired = now - stat.st_mtime > max_age
                    size_expired = total > max_bytes
                    if age_expired or size_expired:
                        segment.unlink(missing_ok=True)
                        total -= sizes[segment]
                except FileNotFoundError:
                    continue

    def request_stop(self) -> None:
        self._stop_requested.set()

    def run(
        self,
        stop_event: threading.Event | None = None,
        *,
        on_started: Callable[[], None] | None = None,
    ) -> None:
        """Run until stopped or the source ends; call from a worker thread."""
        with self._lock:
            if self._started_at is not None:
                raise RollingCaptureError("This capture instance can only be run once.")
            self._started_at = self._clock()

        external_stop = stop_event or threading.Event()
        resolved: ResolvedLiveStream | None = None
        reader = None
        process = None
        try:
            self.segment_dir.mkdir(parents=True, exist_ok=True)
            ffmpeg = self.config.ffmpeg_path
            if not os.path.isabs(ffmpeg) and os.path.dirname(ffmpeg) == "":
                ffmpeg = shutil.which(ffmpeg) or ""
            if not ffmpeg:
                raise RollingCaptureError("FFmpeg was not found. Install FFmpeg or configure its executable path.")

            resolved = self._resolver(self.stream_url, quality=self.config.quality)
            reader = resolved.open()
            args = build_ffmpeg_segment_args(self.config)
            args[0] = ffmpeg
            try:
                process = self._popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    bufsize=0,
                )
            except OSError:
                raise RollingCaptureError("Clippy could not start FFmpeg. Check the configured FFmpeg executable.") from None

            if on_started is not None:
                on_started()

            while not self._stop_requested.is_set() and not external_stop.is_set():
                chunk = reader.read(256 * 1024)
                if not chunk:
                    break
                if process.poll() is not None:
                    raise RollingCaptureError("FFmpeg stopped unexpectedly while recording.")
                self._write_all(process.stdin, chunk)
                self._prune_segments()

            self._finish_process(process)
            process = None
            self._prune_segments()
        except RollingCaptureError:
            if process is not None:
                self._finish_process(process, force=True)
                process = None
            raise
        except Exception:
            if process is not None:
                self._finish_process(process, force=True)
                process = None
            raise RollingCaptureError("Live capture ended unexpectedly. Check the stream and FFmpeg installation.") from None
        finally:
            if process is not None:
                self._finish_process(process, force=True)
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
            if resolved is not None:
                close = getattr(resolved.stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

    @staticmethod
    def _write_all(pipe: Any, chunk: bytes) -> None:
        """Write every byte even when an unbuffered OS pipe accepts partial writes."""
        view = memoryview(chunk)
        offset = 0
        try:
            while offset < len(view):
                written = pipe.write(view[offset:])
                if not isinstance(written, int) or written <= 0:
                    raise BrokenPipeError("FFmpeg input pipe closed.")
                offset += written
        except (BrokenPipeError, OSError):
            raise RollingCaptureError("FFmpeg stopped accepting the live stream.") from None

    @staticmethod
    def _finish_process(process: Any, *, force: bool = False) -> None:
        """Close FFmpeg stdin for muxer finalization, then bound shutdown time."""
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except Exception:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except Exception:
                        pass
        if force and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass
