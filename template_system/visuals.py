"""Deterministic measurements of sampled reference frames.

These measurements describe pixels, not semantic content. Edge density and
inter-sample change must not be mislabeled as subject detection or optical flow.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence


class VisualMeasurementError(RuntimeError):
    pass


@dataclass(frozen=True)
class ColorShare:
    hex_color: str
    proportion: float

    def to_dict(self) -> dict:
        return {"hex_color": self.hex_color, "proportion": self.proportion}


@dataclass(frozen=True)
class FrameVisualMeasurement:
    timestamp_ms: int
    dominant_colors: tuple[ColorShare, ...]
    mean_luminance: float
    luminance_stddev: float
    mean_saturation: float
    edge_density: float
    inter_sample_visual_change: float | None

    def to_dict(self) -> dict:
        return {
            "timestamp_ms": self.timestamp_ms,
            "dominant_colors": [item.to_dict() for item in self.dominant_colors],
            "mean_luminance": self.mean_luminance,
            "luminance_stddev": self.luminance_stddev,
            "mean_saturation": self.mean_saturation,
            "edge_density": self.edge_density,
            "inter_sample_visual_change": self.inter_sample_visual_change,
        }


def measure_visual_samples(
    samples: Sequence,
    evidence_root: str | Path,
    *,
    max_frames: int = 64,
    analysis_dimension: int = 160,
    max_file_bytes: int = 12 * 1024 * 1024,
) -> tuple[FrameVisualMeasurement, ...]:
    """Measure bounded color, luminance, edge density, and sample-to-sample change."""
    if not 1 <= len(samples) <= max_frames <= 64:
        raise ValueError("sample count must be between 1 and max_frames (maximum 64)")
    if not 64 <= analysis_dimension <= 512:
        raise ValueError("analysis_dimension must be between 64 and 512")

    root_input = Path(evidence_root).expanduser()
    if root_input.is_symlink():
        raise VisualMeasurementError("evidence root must not be a symbolic link")
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise VisualMeasurementError(f"evidence root is unavailable: {exc}") from exc
    if not root.is_dir():
        raise VisualMeasurementError("evidence root is not a directory")

    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise VisualMeasurementError("Pillow is required for deterministic visual measurements") from exc

    measurements: list[FrameVisualMeasurement] = []
    previous_gray = None
    for sample in samples:
        pure = PurePosixPath(sample.relative_path)
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise VisualMeasurementError("evidence frame path is not a safe relative path")
        if "\\" in sample.relative_path:
            raise VisualMeasurementError("evidence frame paths must use forward slashes")
        path = root.joinpath(*pure.parts)
        try:
            if not path.resolve(strict=True).is_relative_to(root):
                raise VisualMeasurementError("evidence frame escapes the evidence root")
        except OSError as exc:
            raise VisualMeasurementError(f"evidence frame is unavailable: {sample.relative_path}") from exc
        current = root
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise VisualMeasurementError("evidence frame path cannot traverse symlinks")
        if not path.is_file() or path.stat().st_size > max_file_bytes:
            raise VisualMeasurementError("evidence frame is missing or exceeds the byte limit")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest().lower() != sample.sha256.lower():
            raise VisualMeasurementError("evidence frame checksum mismatch")

        try:
            with Image.open(path) as opened:
                if opened.format != "PNG":
                    raise VisualMeasurementError("evidence frame must be a PNG")
                opened.load()
                rgb = opened.convert("RGB")
        except VisualMeasurementError:
            raise
        except Exception as exc:
            raise VisualMeasurementError(f"evidence frame cannot be decoded: {sample.relative_path}") from exc

        rgb.thumbnail((analysis_dimension, analysis_dimension))
        quantized = rgb.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        color_counts = sorted(quantized.getcolors(maxcolors=256) or [], reverse=True)
        total_pixels = max(1, rgb.width * rgb.height)
        colors: list[ColorShare] = []
        for count, palette_index in color_counts[:5]:
            offset = palette_index * 3
            if offset + 2 >= len(palette):
                continue
            red, green, blue = palette[offset:offset + 3]
            colors.append(ColorShare(
                hex_color=f"#{red:02X}{green:02X}{blue:02X}",
                proportion=count / total_pixels,
            ))

        gray = rgb.convert("L")
        luminance = ImageStat.Stat(gray)
        hsv = rgb.convert("HSV")
        saturation = ImageStat.Stat(hsv).mean[1] / 255.0
        pixels = gray.tobytes()
        width, height = gray.size
        edge_count = 0
        edge_total = max(1, (width - 1) * (height - 1))
        for y in range(height - 1):
            row = y * width
            for x in range(width - 1):
                gradient = max(
                    abs(pixels[row + x + 1] - pixels[row + x]),
                    abs(pixels[row + x] - pixels[row + width + x]),
                )
                if gradient >= 24:
                    edge_count += 1

        small_gray = gray.resize((64, 64), Image.Resampling.BILINEAR)
        visual_change = None
        if previous_gray is not None:
            difference = ImageChops.difference(previous_gray, small_gray)
            visual_change = ImageStat.Stat(difference).mean[0] / 255.0
        previous_gray = small_gray.copy()

        values = (
            luminance.mean[0] / 255.0,
            luminance.stddev[0] / 255.0,
            saturation,
            edge_count / edge_total,
        )
        if any(not math.isfinite(value) for value in values):
            raise VisualMeasurementError("visual measurement produced a non-finite value")
        measurements.append(FrameVisualMeasurement(
            timestamp_ms=int(sample.timestamp_ms),
            dominant_colors=tuple(colors),
            mean_luminance=values[0],
            luminance_stddev=values[1],
            mean_saturation=values[2],
            edge_density=values[3],
            inter_sample_visual_change=visual_change,
        ))
    return tuple(measurements)
