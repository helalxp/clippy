from __future__ import annotations

import struct

import pytest

from template_system.assets import inspect_font_payload


def make_sfnt(signature=b"\x00\x01\x00\x00"):
    tags = ["head", "maxp", "name", "cmap", "glyf", "loca"]
    if signature == b"OTTO":
        tags = ["head", "maxp", "name", "cmap", "CFF "]
    directory_end = 12 + len(tags) * 16
    payload = bytearray(directory_end)
    payload[:12] = struct.pack(">IHHHH", int.from_bytes(signature, "big"), len(tags), 0, 0, 0)
    cursor = directory_end
    for tag in tags:
        size = {"head": 54, "maxp": 6, "name": 6, "cmap": 4}.get(tag, 8)
        payload.extend(b"\0" * size)
        record = tag.encode("ascii") + struct.pack(">III", 0, cursor, size)
        start = 12 + tags.index(tag) * 16
        payload[start:start + 16] = record
        cursor += size
    return bytes(payload)


def test_accepts_true_type_sfnt():
    assert inspect_font_payload(make_sfnt()) == ("font/ttf", "ttf")


def test_accepts_open_type_cff_sfnt():
    assert inspect_font_payload(make_sfnt(b"OTTO")) == ("font/otf", "otf")


@pytest.mark.parametrize("payload", [b"", b"not-a-font", b"wOFF" + b"\0" * 40])
def test_rejects_unsupported_or_truncated_font(payload):
    with pytest.raises(ValueError):
        inspect_font_payload(payload)


def test_rejects_zero_or_excessive_table_count():
    payload = bytearray(make_sfnt())
    payload[4:6] = (0).to_bytes(2, "big")
    with pytest.raises(ValueError, match="table count"):
        inspect_font_payload(bytes(payload))


def test_rejects_truncated_table_directory():
    with pytest.raises(ValueError, match="directory is truncated"):
        inspect_font_payload(b"\x00\x01\x00\x00" + (2).to_bytes(2, "big") + b"\0" * 6 + b"\0" * 16)


def test_rejects_missing_required_table():
    payload = bytearray(make_sfnt())
    # Change the final table tag from loca to Loca, preserving a valid directory.
    payload[12 + 2 * 16:12 + 2 * 16 + 4] = b"Name"
    with pytest.raises(ValueError, match="missing required"):
        inspect_font_payload(bytes(payload))


def test_rejects_table_outside_file():
    payload = bytearray(make_sfnt())
    record = 12
    payload[record + 8:record + 12] = (len(payload) + 10).to_bytes(4, "big")
    with pytest.raises(ValueError, match="outside the file"):
        inspect_font_payload(bytes(payload))


def test_rejects_overlapping_tables():
    payload = bytearray(make_sfnt())
    first = 12
    second = 12 + 16
    payload[second + 8:second + 12] = payload[first + 8:first + 12]
    with pytest.raises(ValueError, match="overlap"):
        inspect_font_payload(bytes(payload))


def test_rejects_payload_above_size_limit():
    with pytest.raises(ValueError, match="25 MB"):
        inspect_font_payload(b"\x00\x01\x00\x00" + b"\0" * (25 * 1024 * 1024))
