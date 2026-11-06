"""Local, reference-derived template storage and deterministic analysis.

This deliberately does not ask an LLM to describe a style.  It records the
measurable editing characteristics of a reference once, next to its source
video, so subsequent projects can reuse the saved blueprint without spending
another model call.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROOT = "reference_templates"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def root() -> Path:
    path = Path(os.environ.get("REFERENCE_TEMPLATES_DIR", DEFAULT_ROOT))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fps(rate: str | None) -> float:
    try:
        numerator, denominator = str(rate or "0/1").split("/", 1)
        return float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        return 0


def _aspect(width: int, height: int) -> str:
    if not width or not height:
        return "unknown"
    ratio = width / height
    if abs(ratio - 9 / 16) < 0.04:
        return "vertical"
    if abs(ratio - 1) < 0.04:
        return "square"
    if abs(ratio - 16 / 9) < 0.04:
        return "horizontal"
    return "custom"


def _scene_times(video_path: Path, duration: float) -> list[float]:
    """Return hard-cut timestamps using FFmpeg's deterministic scene score.

    The analysis is capped to prevent a long reference upload from monopolising
    the local renderer.  A partial result remains useful for pacing and carries
    its coverage explicitly in the manifest.
    """
    limit = max(30, int(os.environ.get("REFERENCE_TEMPLATE_ANALYSIS_SECONDS", "600")))
    covered = min(duration, float(limit)) if duration else float(limit)
    try:
        result = _run([
            "ffmpeg", "-hide_banner", "-t", f"{covered:.3f}", "-i", str(video_path),
            "-filter:v", "select='gt(scene,0.35)',showinfo", "-an", "-f", "null", "-",
        ], timeout=max(120, int(covered / 2) + 60))
    except (OSError, subprocess.SubprocessError):
        return []
    return [float(value) for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)]


def _poster(video_path: Path, duration: float, output_path: Path) -> bool:
    at = max(0, duration * 0.2)
    try:
        result = _run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}",
            "-i", str(video_path), "-frames:v", "1", "-vf", "scale='min(640,iw)':-2",
            str(output_path),
        ])
        return result.returncode == 0 and output_path.is_file()
    except (OSError, subprocess.SubprocessError):
        return False


def analyze(video_path: Path) -> dict[str, Any]:
    """Create the no-model portion of a reusable style blueprint."""
    try:
        probe = _run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height,avg_frame_rate", "-of", "json", str(video_path),
        ])
        data = json.loads(probe.stdout or "{}") if probe.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        data = {}

    streams = data.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    duration = _number((data.get("format") or {}).get("duration"))
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    fps = round(_fps(video.get("avg_frame_rate")), 3)
    scene_times = _scene_times(video_path, duration)
    coverage = min(duration, float(max(30, int(os.environ.get("REFERENCE_TEMPLATE_ANALYSIS_SECONDS", "600"))))) if duration else 0
    intervals = [b - a for a, b in zip([0.0, *scene_times], [*scene_times, coverage]) if b - a > 0.08]
    average_cut = round(sum(intervals) / len(intervals), 3) if intervals else None
    pacing = "unknown" if average_cut is None else "fast" if average_cut < 2 else "medium" if average_cut < 5 else "slow"

    return {
        "technical": {
            "duration_seconds": round(duration, 3), "width": width, "height": height,
            "fps": fps, "aspect_ratio": _aspect(width, height), "has_audio": has_audio,
        },
        "pacing": {
            "analysis_coverage_seconds": round(coverage, 3), "hard_cut_count": len(scene_times),
            "hard_cut_times_seconds": [round(value, 3) for value in scene_times],
            "average_shot_seconds": average_cut, "classification": pacing,
            "source": "detected",
        },
        "style": {
            "framing": {"value": "not_analyzed", "source": "pending"},
            "captions": {"value": "not_analyzed", "source": "pending"},
            "background": {"value": "not_analyzed", "source": "pending"},
            "watermark": {"value": "not_analyzed", "source": "pending"},
            "transitions": {"value": "hard_cuts_detected", "source": "detected"},
        },
    }


def create(video_path: Path, original_name: str, name: str | None = None, category: str | None = None) -> dict[str, Any]:
    suffix = video_path.suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError("Unsupported reference video format")
    template_id = f"ref_{uuid.uuid4().hex}"
    directory = root() / template_id
    directory.mkdir(parents=True, exist_ok=False)
    reference_name = f"reference{suffix}"
    target = directory / reference_name
    video_path.replace(target)
    analysis = analyze(target)
    poster_name = "poster.jpg"
    poster_ready = _poster(target, analysis["technical"]["duration_seconds"], directory / poster_name)
    now = datetime.now(timezone.utc).isoformat()
    label = (name or "").strip() or Path(original_name).stem or "Reference style"
    manifest = {
        "id": template_id,
        "name": label[:120],
        "category": (category or "Uncategorized").strip()[:80],
        "created_at": now,
        "updated_at": now,
        "reference": {"original_name": original_name, "video": reference_name, "poster": poster_name if poster_ready else None},
        "analysis": analysis,
        "overrides": {},
        "version": 1,
    }
    save(manifest)
    return manifest


def manifest_path(template_id: str) -> Path:
    if not re.fullmatch(r"ref_[a-f0-9]{32}", template_id or ""):
        raise ValueError("Invalid reference template id")
    return root() / template_id / "manifest.json"


def save(manifest: dict[str, Any]) -> None:
    path = manifest_path(str(manifest.get("id") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def get(template_id: str) -> dict[str, Any]:
    path = manifest_path(template_id)
    if not path.is_file():
        raise FileNotFoundError(template_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_all() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for path in root().glob("ref_*/manifest.json"):
        try:
            templates.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(templates, key=lambda item: item.get("updated_at", ""), reverse=True)

