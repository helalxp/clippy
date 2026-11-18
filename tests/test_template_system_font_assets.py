from __future__ import annotations

import asyncio
import hashlib
import struct
from pathlib import Path
from types import SimpleNamespace

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


class FakeUpload:
    def __init__(self, payload, content_type):
        self.payload = payload
        self.content_type = content_type
        self.filename = "untrusted-font.bin"
        self.closed = False

    async def read(self, size=-1):
        return self.payload[:size]

    async def close(self):
        self.closed = True


class FakeRequest:
    def __init__(self, owner_id, form_data=None):
        self.owner_id = owner_id
        self.headers = {}
        self.query_params = {}
        self.form_data = form_data or {}

    async def form(self, **kwargs):
        assert kwargs == {"max_files": 1, "max_fields": 1}
        return self.form_data


async def async_noop(*args, **kwargs):
    return None


async def owner_id(request):
    return request.owner_id


def test_font_asset_upload_is_owner_scoped_and_revision_safe(tmp_path, monkeypatch):
    import app as app_module
    from template_system.models import TemplateDocument

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", async_noop)
    monkeypatch.setattr(app_module, "_owner_id", owner_id)

    document = TemplateDocument(id="tpl_font_upload01", name="Font upload fixture")
    owner = FakeRequest("font-owner")
    asyncio.run(app_module.create_template(document.to_storage_dict(), owner))

    payload = make_sfnt()
    upload = FakeUpload(payload, "font/ttf")
    request = FakeRequest(
        "font-owner",
        {"file": upload, "expected_revision": "1"},
    )
    result = asyncio.run(app_module.upload_template_asset(document.id, request))

    asset = result["asset"]
    assert asset["media_type"] == "font/ttf"
    assert asset["path"] == f"assets/{asset['id']}.ttf"
    assert asset["width"] is None and asset["height"] is None
    assert asset["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["template_revision"] == 2
    assert upload.closed is True

    scope = hashlib.sha256(b"font-owner").hexdigest()[:32]
    stored = tmp_path / "libraries" / scope / document.id / asset["path"]
    assert stored.read_bytes() == payload

    served = asyncio.run(app_module.get_template_asset(document.id, asset["id"], owner))
    assert Path(served.path) == stored
    assert served.media_type == "font/ttf"


def test_font_upload_rejects_mismatched_mime_without_mutating_template(tmp_path, monkeypatch):
    import app as app_module
    from fastapi import HTTPException
    from template_system.models import TemplateDocument

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", async_noop)
    monkeypatch.setattr(app_module, "_owner_id", owner_id)

    document = TemplateDocument(id="tpl_font_mime001", name="Font MIME fixture")
    owner = FakeRequest("font-owner")
    asyncio.run(app_module.create_template(document.to_storage_dict(), owner))

    request = FakeRequest(
        "font-owner",
        {
            "file": FakeUpload(make_sfnt(), "font/otf"),
            "expected_revision": "1",
        },
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.upload_template_asset(document.id, request))
    assert rejected.value.status_code == 415
    assert asyncio.run(app_module.get_template(document.id, owner))["template"]["assets"] == []
