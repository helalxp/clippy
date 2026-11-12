"""Deterministic, bounded analysis primitives for local reference videos.

This module measures media facts and captures timestamped frame evidence. It
does not use an AI model and never claims to detect style properties it has
not measured.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Sequence


class ReferenceAnalysisError(RuntimeError):
    """A reference source could not be safely probed or sampled."""


@dataclass(frozen=True)
class MediaProbe:
    source_name: str
    source_fingerprint: str
    file_size_bytes: int
    duration_seconds: float
    width: int
    height: int
    frame_rate: float | None
    pixel_aspect_ratio: float | None
    video_codec: str
    pixel_format: str | None
    has_audio: bool
    audio_codec: str | None
    audio_channels: int | None
    audio_sample_rate: int | None
    rotation_degrees: int

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_fingerprint": f"sha256:{self.source_fingerprint}",
            "file_size_bytes": self.file_size_bytes,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "video_codec": self.video_codec,
            "pixel_format": self.pixel_format,
            "has_audio": self.has_audio,
            "audio_codec": self.audio_codec,
            "audio_channels": self.audio_channels,
            "rotation_degrees": self.rotation_degrees,
        }


@dataclass(frozen=True)
class FrameSample:
    timestamp_ms: int
    relative_path: str
    sha256: str
    size_bytes: int
    width: int
    height: int

    def to_dict(self) -> dict:
        return {
            "timestamp_ms": self.timestamp_ms,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ReferenceAnalysisResult:
    probe: MediaProbe
    scene_boundaries_seconds: tuple[float, ...]
    samples: tuple[FrameSample, ...]
    coverage: dict[str, float]
    limitations: tuple[str, ...]
    status: str


def _local_video_path(path: str | Path) -> Path:
    source = Path(path).expanduser()
    if source.is_symlink():
        raise ReferenceAnalysisError("reference video must not be a symbolic link")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise ReferenceAnalysisError(f"reference video is unavailable: {exc}") from exc
    if not resolved.is_file():
        raise ReferenceAnalysisError("reference video path is not a regular file")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_frame_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return rate if math.isfinite(rate) and 0 < rate <= 1000 else None


def _parse_aspect_ratio(value: str | None) -> float | None:
    if not value or value in {"0:1", "N/A"}:
        return None
    try:
        ratio = float(Fraction(value.replace(":", "/")))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return ratio if math.isfinite(ratio) and 0 < ratio <= 100 else None


def probe_media(
    video_path: str | Path,
    *,
    ffprobe_bin: str = "ffprobe",
    timeout_seconds: int = 30,
    max_file_size_bytes: int = 2 * 1024 * 1024 * 1024,
    max_duration_seconds: float = 7200,
) -> MediaProbe:
    """Probe one local file and return measured stream facts plus SHA-256."""
    source = _local_video_path(video_path)
    size = source.stat().st_size
    if size <= 0:
        raise ReferenceAnalysisError("reference video is empty")
    if size > max_file_size_bytes:
        raise ReferenceAnalysisError("reference video exceeds the configured size limit")

    command = [
        ffprobe_bin, "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(source),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_seconds, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceAnalysisError(f"ffprobe could not inspect the reference video: {exc}") from exc
    if result.returncode != 0:
        raise ReferenceAnalysisError(
            f"ffprobe failed: {(result.stderr or '').strip()[-1200:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReferenceAnalysisError("ffprobe returned invalid JSON") from exc

    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video:
        raise ReferenceAnalysisError("reference file contains no video stream")

    format_info = payload.get("format") or {}
    raw_duration = format_info.get("duration") or video.get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise ReferenceAnalysisError("video duration is missing or invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ReferenceAnalysisError("video duration must be a positive finite value")
    if duration > max_duration_seconds:
        raise ReferenceAnalysisError("reference video exceeds the configured duration limit")

    try:
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise ReferenceAnalysisError("video dimensions are invalid") from exc
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ReferenceAnalysisError("video dimensions are missing or outside supported limits")

    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    rotation = 0
    for side_data in video.get("side_data_list") or []:
        try:
            rotation = int(round(float(side_data.get("rotation", 0))))
            break
        except (TypeError, ValueError):
            continue
    if not rotation:
        try:
            rotation = int(round(float((video.get("tags") or {}).get("rotate", 0))))
        except (TypeError, ValueError):
            rotation = 0

    try:
        audio_channels = int(audio["channels"]) if audio and audio.get("channels") is not None else None
    except (TypeError, ValueError):
        audio_channels = None
    try:
        audio_sample_rate = int(audio["sample_rate"]) if audio and audio.get("sample_rate") is not None else None
    except (TypeError, ValueError):
        audio_sample_rate = None

    return MediaProbe(
        source_name=source.name,
        source_fingerprint=_sha256_file(source),
        file_size_bytes=size,
        duration_seconds=duration,
        width=width,
        height=height,
        frame_rate=_parse_frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        pixel_aspect_ratio=_parse_aspect_ratio(video.get("sample_aspect_ratio")),
        video_codec=str(video.get("codec_name") or "unknown"),
        pixel_format=video.get("pix_fmt"),
        has_audio=audio is not None,
        audio_codec=(str(audio.get("codec_name") or "unknown") if audio else None),
        audio_channels=audio_channels,
        audio_sample_rate=audio_sample_rate,
        rotation_degrees=rotation,
    )


def detect_scene_boundaries(
    video_path: str | Path,
    duration_seconds: float,
    *,
    ffmpeg_bin: str = "ffmpeg",
    threshold: float = 0.35,
    timeout_seconds: int = 300,
    max_boundaries: int = 500,
) -> list[float]:
    """Use FFmpeg's scene score to return bounded, timestamped cut candidates."""
    source = _local_video_path(video_path)
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive and finite")
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError("scene threshold must be between 0 and 1")
    if not 1 <= max_boundaries <= 5000:
        raise ValueError("max_boundaries must be between 1 and 5000")

    command = [
        ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(source),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_seconds, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceAnalysisError(f"ffmpeg scene detection could not run: {exc}") from exc
    if result.returncode != 0:
        raise ReferenceAnalysisError(
            f"ffmpeg scene detection failed: {(result.stderr or '').strip()[-1200:]}"
        )

    timestamps: list[float] = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr or ""):
        value = float(match.group(1))
        if 0 < value < duration_seconds:
            if not timestamps or value - timestamps[-1] > 0.05:
                timestamps.append(value)
        if len(timestamps) >= max_boundaries:
            break
    return timestamps


def choose_sample_timestamps(
    duration_seconds: float,
    scene_boundaries_seconds: Sequence[float],
    *,
    max_samples: int = 24,
) -> list[float]:
    """Choose reproducible scene-midpoint samples with bounded uniform coverage."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive and finite")
    if not 1 <= max_samples <= 64:
        raise ValueError("max_samples must be between 1 and 64")

    boundaries = sorted({
        float(value) for value in scene_boundaries_seconds
        if math.isfinite(float(value)) and 0 < float(value) < duration_seconds
    })
    if not boundaries:
        return [
            duration_seconds * (index + 0.5) / max_samples
            for index in range(max_samples)
        ]

    edges = [0.0, *boundaries, duration_seconds]
    midpoints = [(left + right) / 2 for left, right in zip(edges, edges[1:]) if right > left]
    uniform = [
        duration_seconds * (index + 0.5) / max_samples
        for index in range(max_samples)
    ]
    candidates = sorted(midpoints + uniform)
    unique: list[float] = []
    for value in candidates:
        if not unique or value - unique[-1] > 0.1:
            unique.append(value)
    if len(unique) <= max_samples:
        return unique
    if max_samples == 1:
        return [unique[len(unique) // 2]]
    indices = [
        round(index * (len(unique) - 1) / (max_samples - 1))
        for index in range(max_samples)
    ]
    return [unique[index] for index in indices]


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise ReferenceAnalysisError("ffmpeg did not return a valid PNG frame")
    width = int.from_bytes(payload[16:20], "big")
    height = int.from_bytes(payload[20:24], "big")
    if width <= 0 or height <= 0:
        raise ReferenceAnalysisError("sampled PNG has invalid dimensions")
    return width, height


def extract_sample_frames(
    video_path: str | Path,
    timestamps_seconds: Sequence[float],
    output_dir: str | Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    max_dimension: int = 640,
    max_frame_bytes: int = 12 * 1024 * 1024,
    timeout_seconds: int = 60,
) -> tuple[FrameSample, ...]:
    """Extract bounded PNG evidence frames into a caller-owned staging folder."""
    source = _local_video_path(video_path)
    if not 64 <= max_dimension <= 2048:
        raise ValueError("max_dimension must be between 64 and 2048")
    if not 1 <= len(timestamps_seconds) <= 64:
        raise ValueError("one to 64 frame timestamps are required")

    destination = Path(output_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve(strict=True)
    if not destination.is_dir():
        raise ReferenceAnalysisError("frame output path is not a directory")

    samples: list[FrameSample] = []
    for index, timestamp in enumerate(timestamps_seconds, start=1):
        if not math.isfinite(float(timestamp)) or float(timestamp) < 0:
            raise ValueError("frame timestamps must be finite and non-negative")
        timestamp = float(timestamp)
        command = [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{timestamp:.3f}", "-i", str(source),
            "-frames:v", "1",
            "-vf", f"scale={max_dimension}:{max_dimension}:force_original_aspect_ratio=decrease",
            "-f", "image2pipe", "-vcodec", "png", "pipe:1",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout_seconds, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReferenceAnalysisError(f"ffmpeg could not extract sample frame: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", errors="replace")
            raise ReferenceAnalysisError(f"frame extraction failed: {detail[-1000:]}")
        payload = result.stdout or b""
        if len(payload) > max_frame_bytes:
            raise ReferenceAnalysisError("sample frame exceeds the configured byte limit")
        width, height = _png_dimensions(payload)
        filename = f"frame_{index:03d}_{int(round(timestamp * 1000)):010d}ms.png"
        target = destination / filename
        if target.exists() or target.is_symlink():
            raise ReferenceAnalysisError(f"sample output already exists: {filename}")
        fd, temporary_name = tempfile.mkstemp(prefix=".frame-", suffix=".tmp", dir=destination)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        samples.append(FrameSample(
            timestamp_ms=int(round(timestamp * 1000)),
            relative_path=filename,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            width=width,
            height=height,
        ))
    return tuple(samples)


def analyze_reference_video(
    video_path: str | Path,
    output_dir: str | Path,
    *,
    max_samples: int = 24,
    scene_threshold: float = 0.35,
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
) -> ReferenceAnalysisResult:
    """Run probe → scene analysis → bounded frame sampling, retaining limits."""
    probe = probe_media(video_path, ffprobe_bin=ffprobe_bin)
    limitations: list[str] = []
    scene_ok = True
    try:
        boundaries = detect_scene_boundaries(
            video_path, probe.duration_seconds,
            ffmpeg_bin=ffmpeg_bin, threshold=scene_threshold,
        )
    except ReferenceAnalysisError as exc:
        boundaries = []
        scene_ok = False
        limitations.append(f"Scene detection unavailable; uniform sampling used: {exc}")

    timestamps = choose_sample_timestamps(
        probe.duration_seconds, boundaries, max_samples=max_samples
    )
    samples: list[FrameSample] = []
    sample_failures = 0
    for index, timestamp in enumerate(timestamps, start=1):
        try:
            extracted = extract_sample_frames(
                video_path, [timestamp], output_dir,
                ffmpeg_bin=ffmpeg_bin,
            )
            sample = extracted[0]
            # Give files a stable sequential name independent of the single-frame call.
            samples.append(sample)
        except ReferenceAnalysisError as exc:
            sample_failures += 1
            limitations.append(f"Frame sample at {timestamp:.3f}s failed: {exc}")

    if not samples:
        raise ReferenceAnalysisError("no reference frames could be sampled")
    coverage = {
        "media_probe": 1.0,
        "scene_detection": 1.0 if scene_ok else 0.0,
        "frame_sampling": len(samples) / len(timestamps),
    }
    status = "complete" if scene_ok and sample_failures == 0 else "partial"
    return ReferenceAnalysisResult(
        probe=probe,
        scene_boundaries_seconds=tuple(boundaries),
        samples=tuple(samples),
        coverage=coverage,
        limitations=tuple(limitations),
        status=status,
    )
