"""Safe FFmpeg drawtext translation for canonical text overlays."""
from __future__ import annotations

import re
from pathlib import Path

from ffmpeg_utils import escape_filter_value

from ..models import CanvasRecipe, OverlayRecipe


def _color(value: str, opacity: float) -> str:
    return f"0x{value.lstrip('#').upper()}@{opacity:.4f}"


def write_text_overlay(
    overlay: OverlayRecipe,
    canvas: CanvasRecipe,
    text_path: str | Path,
    *,
    font_path: str | Path | None = None,
) -> str:
    """Write literal UTF-8 copy to disk and return a bounded drawtext filter.

    Explicit newlines define line breaks. Text is read with expansion disabled,
    so user content is never interpreted as an FFmpeg expression.
    """
    if overlay.kind != "text":
        raise ValueError("write_text_overlay requires a text overlay")

    text = (overlay.text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("text overlays require non-empty text")
    if len(text.split("\n")) > overlay.max_lines:
        raise ValueError("text overlay exceeds its configured max_lines")

    path = Path(text_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if "'" in str(path):
        raise ValueError("text overlay paths cannot contain apostrophes")
    text_value = escape_filter_value(str(path.resolve()))

    parts = ["drawtext", f"textfile='{text_value}'", "expansion=none"]
    if font_path is not None:
        font = Path(font_path).expanduser().resolve(strict=True)
        if not font.is_file():
            raise ValueError("text overlay font asset is not a regular file")
        if "'" in str(font):
            raise ValueError("text overlay font paths cannot contain apostrophes")
        parts.append(f"fontfile='{escape_filter_value(str(font))}'")
    else:
        family = re.sub(r"[^A-Za-z0-9 _-]", "", overlay.font_family).strip() or "Arial"
        parts.append(f"font='{family}'")

    font_size = max(12, round(overlay.font_size_ratio * canvas.height))
    box_width = max(2, round(overlay.text_box_width_ratio * canvas.width))
    box_height = max(2, round(overlay.text_box_height_ratio * canvas.height))
    x = round(overlay.text_anchor_x * canvas.width - box_width / 2)
    y = round(overlay.text_anchor_y * canvas.height - box_height / 2)
    outline_width = round(overlay.outline_ratio * canvas.height)
    line_spacing = round(overlay.line_spacing_ratio * canvas.height)
    align = {
        "left": "left+middle",
        "center": "center+middle",
        "right": "right+middle",
    }[overlay.text_align]

    parts.extend([
        f"fontsize={font_size}",
        f"fontcolor={_color(overlay.font_color, overlay.opacity)}",
        f"boxw={box_width}",
        f"boxh={box_height}",
        f"text_align={align}",
        f"x={x}",
        f"y={y}",
        f"line_spacing={line_spacing}",
        f"borderw={outline_width}",
        f"bordercolor={_color(overlay.outline_color, overlay.opacity)}",
        "fix_bounds=1",
    ])
    if overlay.background_color:
        parts.extend([
            "box=1",
            f"boxcolor={_color(overlay.background_color, overlay.opacity)}",
            f"boxborderw={max(2, round(font_size * 0.2))}",
        ])
    else:
        parts.append("box=0")

    return "," + ":".join(parts)
