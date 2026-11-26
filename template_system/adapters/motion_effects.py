"""Deterministic FFmpeg filter builders for canonical motion and color effects.

These helpers translate only the explicitly supported recipe semantics. They do
not inspect media or infer motion from source pixels.
"""
from __future__ import annotations

from ..models import EffectSegment, MotionRecipe


def build_motion_filter(
    motions: list[MotionRecipe],
    *,
    width: int,
    height: int,
    fps: float,
) -> str | None:
    """Build one frame-accurate zoompan filter for ordered, non-overlapping motions.

    punch_in ramps to its target zoom over the first 20% then holds.
    slow_zoom interpolates linearly across the full interval.
    pan uses a constant zoom and moves the crop center from canvas center to
    the configured normalized target.
    Every motion returns to the unmodified frame outside its time interval.
    """
    if not motions:
        return None

    zoom_expr = "1"
    center_x_expr = "0.5"
    center_y_expr = "0.5"
    for motion in reversed(motions):
        start = round(motion.start_seconds * fps)
        end = round(motion.end_seconds * fps)
        duration = max(1, end - start)
        progress = f"((on-{start})/{duration})"
        active = f"between(on,{start},{end})"

        if motion.kind == "punch_in":
            amount = (
                f"if(lt({progress},0.2),"
                f"{progress}/0.2,1)"
            )
            target_zoom = f"(1+{motion.intensity:.8f}*{amount})"
            center_x = f"{motion.center_x:.8f}"
            center_y = f"{motion.center_y:.8f}"
        elif motion.kind == "slow_zoom":
            target_zoom = f"(1+{motion.intensity:.8f}*{progress})"
            center_x = f"{motion.center_x:.8f}"
            center_y = f"{motion.center_y:.8f}"
        elif motion.kind == "pan":
            target_zoom = f"(1+{motion.intensity:.8f})"
            center_x = f"(0.5+({motion.center_x:.8f}-0.5)*{progress})"
            center_y = f"(0.5+({motion.center_y:.8f}-0.5)*{progress})"
        else:  # Defensive: the canonical model currently constrains this Literal.
            raise ValueError(f"unsupported motion kind: {motion.kind}")

        zoom_expr = f"if({active},{target_zoom},{zoom_expr})"
        center_x_expr = f"if({active},{center_x},{center_x_expr})"
        center_y_expr = f"if({active},{center_y},{center_y_expr})"

    x_expr = f"(iw-iw/zoom)*({center_x_expr})"
    y_expr = f"(ih-ih/zoom)*({center_y_expr})"
    return (
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
        f"d=1:s={width}x{height}:fps={fps:.6f}"
    )


def build_effect_filters(effects: list[EffectSegment]) -> list[str]:
    """Build color-only EQ filters for each canonical effect interval.

    EffectSegment.zoom and center coordinates are intentionally handled by the
    separate motion recipe for now; the capability registry rejects non-default
    values rather than silently ignoring them.
    """
    filters: list[str] = []
    for effect in effects:
        start = f"{effect.start_seconds:.6f}".rstrip("0").rstrip(".")
        end = f"{effect.end_seconds:.6f}".rstrip("0").rstrip(".")
        brightness = effect.brightness - 1.0
        filters.append(
            "eq="
            f"brightness={brightness:.6f}:"
            f"contrast={effect.contrast:.6f}:"
            f"saturation={effect.saturation:.6f}:"
            f"enable='between(t,{start},{end})'"
        )
    return filters
