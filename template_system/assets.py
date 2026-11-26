"""Bounded validation for uploaded OpenType/TrueType font containers.

This validates the SFNT directory and required structural tables before a font
is stored. It is not a font renderer or a substitute for renderer-side sandboxing.
"""
from __future__ import annotations

from typing import Final

MAX_FONT_BYTES: Final = 25 * 1024 * 1024
_SFNT_TTF_SIGNATURES = {b"\x00\x01\x00\x00", b"true"}
_SFNT_OTF_SIGNATURE = b"OTTO"
_REQUIRED_TABLES = {"head", "maxp", "name", "cmap"}
_MAX_TABLES = 128


def inspect_font_payload(payload: bytes) -> tuple[str, str]:
    """Return (media_type, extension) after validating a bounded SFNT font."""
    if not isinstance(payload, bytes):
        raise TypeError("font payload must be bytes")
    if len(payload) < 12:
        raise ValueError("font file is too small to contain an SFNT header")
    if len(payload) > MAX_FONT_BYTES:
        raise ValueError("font file exceeds the 25 MB limit")

    signature = payload[:4]
    if signature in _SFNT_TTF_SIGNATURES:
        media_type, extension = "font/ttf", "ttf"
        outline_tables = {"glyf", "loca"}
    elif signature == _SFNT_OTF_SIGNATURE:
        media_type, extension = "font/otf", "otf"
        outline_tables = {"CFF ", "CFF2"}
    else:
        raise ValueError("only TrueType (.ttf) and OpenType CFF (.otf) fonts are supported")

    table_count = int.from_bytes(payload[4:6], "big")
    if not 1 <= table_count <= _MAX_TABLES:
        raise ValueError("font table count is outside the supported range")

    directory_end = 12 + table_count * 16
    if directory_end > len(payload):
        raise ValueError("font table directory is truncated")

    tables: dict[str, tuple[int, int]] = {}
    ranges: list[tuple[int, int, str]] = []
    for index in range(table_count):
        start = 12 + index * 16
        record = payload[start:start + 16]
        try:
            tag = record[:4].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("font table tag is not valid ASCII") from exc
        if not tag.isprintable() or tag in tables:
            raise ValueError("font contains an invalid or duplicate table tag")

        offset = int.from_bytes(record[8:12], "big")
        length = int.from_bytes(record[12:16], "big")
        if length:
            end = offset + length
            if offset < directory_end or end > len(payload) or end < offset:
                raise ValueError(f"font table {tag!r} points outside the file")
            ranges.append((offset, end, tag))
        tables[tag] = (offset, length)

    missing = _REQUIRED_TABLES - tables.keys()
    if missing:
        raise ValueError(f"font is missing required tables: {', '.join(sorted(missing))}")

    if not (outline_tables & tables.keys()):
        raise ValueError("font is missing a supported outline table")

    minimum_lengths = {"head": 54, "maxp": 6, "name": 6, "cmap": 4}
    for tag, minimum in minimum_lengths.items():
        if tables[tag][1] < minimum:
            raise ValueError(f"font table {tag!r} is truncated")

    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise ValueError(
                f"font tables {previous[2]!r} and {current[2]!r} overlap"
            )

    return media_type, extension
