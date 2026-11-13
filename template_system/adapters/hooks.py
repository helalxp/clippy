"""Deterministic FFmpeg drawtext translation for canonical template hooks."""
from __future__ import annotations

import re
from pathlib import Path

from ffmpeg_utils import escape_filter_value

from ..models import CanvasRecipe, HookRecipe


def _number(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"


def _color(value: str) -> str:
    return "0x" + value.lstrip("#").upper()


def write_hook_text(
    hook: HookRecipe,
    canvas: CanvasRecipe,
    text_path: str | Path,
    *,
    font_path: str | Path | None = None,
) -> str | None:
    """Write hook copy to a text file and return its FFmpeg drawtext filter.

    Text is passed through drawtext's textfile option, never interpolated into
    filter syntax. The returned filter is appended after framing and captions,
    making the title the top visual layer.
    """
    if not hook.enabled:
        return None

    text = hook.text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    if not text:
        raise ValueError("an enabled template hook must contain text")

    path = Path(text_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if "'" in str(path):
        raise ValueError("template hook paths cannot contain apostrophes")
    text_value = escape_filter_value(str(path.resolve()))

    parts = ["drawtext", f"textfile='{text_value}'", "expansion=none"]
    if font_path is not None:
        font = Path(font_path).expanduser().resolve(strict=True)
        if not font.is_file():
            raise ValueError("template hook font asset is not a regular file")
        if "'" in str(font):
            raise ValueError("template hook font paths cannot contain apostrophes")
        parts.append(f"fontfile='{escape_filter_value(str(font))}'")
    else:
        # drawtext's font option is a fontconfig family name, not a path.
        family = re.sub(r"[^A-Za-z0-9 _-]", "", hook.font_family).strip() or "Arial"
        parts.append(f"font='{family}'")

    base_size = max(12, round(hook.font_size_ratio * canvas.height))
    size_expression = str(base_size)
    if hook.entrance == "pop":
        elapsed = f"max(0\\,t-{_number(hook.start_seconds)})"
        size_expression = (
            f"{base_size}*(0.82+0.18*min(1\\,max(0\\,{elapsed}/0.18)))"
        )
    elif hook.entrance == "spring":
        elapsed = f"max(0\\,t-{_number(hook.start_seconds)})"
        size_expression = (
            f"{base_size}*(1+0.16*exp(-9*{elapsed})*sin(20*{elapsed}))"
        )
    parts.extend([
        f"fontsize='{size_expression}'",
        f"fontcolor={_color(hook.color)}",
        "borderw=0",
    ])

    if hook.background_color:
        parts.extend([
            "box=1",
            f"boxcolor={_color(hook.background_color)}@1.0",
            f"boxborderw={max(6, round(base_size * 0.28))}",
        ])
    else:
        parts.append("box=0")

    if hook.position == "custom":
        x = f"(w-text_w)*{_number(hook.anchor_x)}"
        y = f"(h-text_h)*{_number(hook.anchor_y)}"
    else:
        x = "(w-text_w)*0.5"
        if hook.position == "top":
            y = f"h*{_number(canvas.safe_top)}"
        elif hook.position == "bottom":
            y = f"h*(1-{_number(canvas.safe_bottom)})-text_h"
        else:
            y = "(h-text_h)*0.5"

    start = _number(hook.start_seconds)
    end = _number(hook.start_seconds + hook.duration_seconds)
    if hook.entrance == "slide_up":
        travel = _number(canvas.height * 0.07)
        elapsed = f"min(1\\,max(0\\,(t-{start})/0.32))"
        y = f"({y})+{travel}*(1-{elapsed})"
    parts.extend([
        f"x='{x}'",
        f"y='{y}'",
        f"enable='between(t,{start},{end})'",
    ])

    if hook.entrance == "fade":
        fade = _number(min(0.4, hook.duration_seconds / 3))
        parts.append(
            f"alpha='if(lt(t,{_number(hook.start_seconds + float(fade))}),"
            f"max(0\\,min(1\\,(t-{start})/{fade})),1)'"
        )

    return "," + ":".join(parts)
