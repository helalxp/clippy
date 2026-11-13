"""Translate canonical caption recipes into the existing ASS subtitle engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from ..models import CanvasRecipe, CaptionRecipe


def write_caption_ass(
    caption: CaptionRecipe,
    canvas: CanvasRecipe,
    transcript: dict[str, Any],
    output_path: str | Path,
    *,
    split_ranges: Sequence[tuple[float, float]] | None = None,
) -> bool:
    """Write a clip-relative ASS caption file using Clippy's established generator.

    The canonical model uses canvas-height ratios; the existing ASS generator
    uses PlayResY=288 units. This adapter is the only place that converts
    between those coordinate systems.
    """
    if caption.position == "custom":
        raise ValueError("custom caption positioning is not supported by the first FFmpeg caption adapter")
    if not isinstance(transcript, dict) or not transcript.get("segments"):
        return False

    from subtitles import generate_ass

    fontsize = max(10, round(caption.font_size_ratio * 288))
    outline_width = round(caption.outline_ratio * 288)
    shadow = round(caption.shadow_ratio * 288)

    if caption.position == "top":
        margin_v = round(canvas.safe_top * 288)
    elif caption.position == "bottom":
        margin_v = round(canvas.safe_bottom * 288)
    else:
        margin_v = 0

    # The legacy generator groups spoken words by character budget and time.
    # Derive a stable budget from the canonical line count and normalized font
    # size. The renderer capability report calls out non-default line counts as
    # approximate because glyph widths and language scripts vary.
    max_chars = round(16 * caption.max_lines * 0.035 / caption.font_size_ratio)
    max_chars = max(6, min(40, max_chars))

    highlight_color = caption.highlight_color if caption.word_highlight else caption.font_color
    return generate_ass(
        transcript,
        0.0,
        24 * 60 * 60.0,
        str(output_path),
        max_chars=max_chars,
        max_duration=1.4,
        alignment=caption.position,
        fontsize=fontsize,
        font_name=caption.font_family,
        font_color=caption.font_color,
        border_color=caption.outline_color,
        border_width=outline_width,
        highlight_color=highlight_color,
        effect="pop" if caption.word_highlight else "none",
        base_opacity=1.0,
        uppercase=caption.uppercase,
        margin_v=margin_v,
        split_ranges=split_ranges,
        reveal=caption.reveal_by_word,
        shadow=shadow,
    )
