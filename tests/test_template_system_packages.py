from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile

from PIL import Image

import pytest

from template_system.models import TemplateAsset, TemplateDocument
from template_system.packages import (
    PACKAGE_FORMAT,
    PACKAGE_MANIFEST,
    TemplatePackageError,
    export_template_package,
    import_template_package,
)
from template_system.storage import LocalTemplateStorage


def make_template(storage, template_id="tpl_package123"):
    image_buffer = io.BytesIO()
    Image.new("RGBA", (12, 8), (10, 20, 30, 255)).save(image_buffer, format="PNG")
    payload = image_buffer.getvalue()
    asset = TemplateAsset(
        id="asset_logo",
        path="assets/asset_logo.png",
        media_type="image/png",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        width=12,
        height=8,
    )
    document = TemplateDocument(
        id=template_id,
        name="Package fixture",
        assets=[asset],
    )
    storage.create(document, asset_payloads={asset.id: payload})
    return document, payload


def test_export_import_round_trip_preserves_recipe_and_asset_bytes(tmp_path):
    source = LocalTemplateStorage(tmp_path / "source")
    original, payload = make_template(source)

    package = export_template_package(source, original.id)
    imported_storage = LocalTemplateStorage(tmp_path / "imported")
    imported = import_template_package(imported_storage, package)

    assert imported.id != original.id
    assert imported.revision == 1
    assert imported.origin.kind == "imported"
    assert imported.name == original.name
    assert imported.recipe == original.recipe
    assert imported.assets == original.assets
    imported_asset, path = imported_storage.get_asset(imported.id, "asset_logo")
    assert imported_asset.sha256 == hashlib.sha256(payload).hexdigest()
    assert path.read_bytes() == payload


def test_export_is_deterministic_for_unchanged_template(tmp_path):
    storage = LocalTemplateStorage(tmp_path / "library")
    document, _ = make_template(storage)

    assert export_template_package(storage, document.id) == export_template_package(storage, document.id)


def _package_bytes(template_data, version=1, files=None, extra_entries=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            PACKAGE_MANIFEST,
            json.dumps({
                "format": PACKAGE_FORMAT,
                "package_version": version,
                "template": template_data,
            }),
        )
        for name, content in (files or {}).items():
            archive.writestr(name, content)
        for info, content in (extra_entries or []):
            archive.writestr(info, content)
    return buffer.getvalue()


def test_import_rejects_invalid_zip(tmp_path):
    with pytest.raises(TemplatePackageError, match="valid ZIP"):
        import_template_package(LocalTemplateStorage(tmp_path), b"not a zip")


def test_import_rejects_unsupported_package_version(tmp_path):
    document = TemplateDocument(id="tpl_packagever1", name="Version fixture")
    payload = _package_bytes(document.to_storage_dict(), version=99)
    with pytest.raises(TemplatePackageError, match="version"):
        import_template_package(LocalTemplateStorage(tmp_path), payload)


def test_import_rejects_path_traversal_entries(tmp_path):
    document = TemplateDocument(id="tpl_packagetrv1", name="Traversal fixture")
    payload = _package_bytes(document.to_storage_dict(), files={"../escape.txt": b"bad"})
    with pytest.raises(TemplatePackageError, match="safe relative"):
        import_template_package(LocalTemplateStorage(tmp_path), payload)


def test_import_rejects_unlisted_files(tmp_path):
    document = TemplateDocument(id="tpl_packageextra1", name="Extra fixture")
    payload = _package_bytes(document.to_storage_dict(), files={"extra.txt": b"not in manifest"})
    with pytest.raises(TemplatePackageError, match="do not match"):
        import_template_package(LocalTemplateStorage(tmp_path), payload)


def test_import_rejects_symlink_entries(tmp_path):
    document = TemplateDocument(id="tpl_packagesym1", name="Symlink fixture")
    link = zipfile.ZipInfo("assets/link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    payload = _package_bytes(document.to_storage_dict(), extra_entries=[(link, b"target")])
    with pytest.raises(TemplatePackageError, match="non-regular"):
        import_template_package(LocalTemplateStorage(tmp_path), payload)


def test_import_rejects_duplicate_paths(tmp_path):
    document = TemplateDocument(id="tpl_packagedup1", name="Duplicate fixture")
    duplicate_manifest = zipfile.ZipInfo(PACKAGE_MANIFEST)
    payload = _package_bytes(
        document.to_storage_dict(),
        extra_entries=[(duplicate_manifest, b"{}")],
    )
    with pytest.raises(TemplatePackageError, match="duplicate"):
        import_template_package(LocalTemplateStorage(tmp_path), payload)


def test_import_rejects_missing_or_corrupt_asset(tmp_path):
    source = LocalTemplateStorage(tmp_path / "source")
    original, _ = make_template(source)
    package = export_template_package(source, original.id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package), "r") as source_zip:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
            for info in source_zip.infolist():
                content = source_zip.read(info.filename)
                if info.filename == "assets/asset_logo.png":
                    content = b"tampered"
                target_zip.writestr(info.filename, content)
    with pytest.raises(TemplatePackageError, match="size mismatch|checksum mismatch"):
        import_template_package(LocalTemplateStorage(tmp_path / "target"), buffer.getvalue())


def test_import_assigns_new_local_identity_and_keeps_source_identity(tmp_path):
    source = LocalTemplateStorage(tmp_path / "source")
    original, _ = make_template(source, "tpl_packageorig1")
    package = export_template_package(source, original.id)
    imported = import_template_package(LocalTemplateStorage(tmp_path / "target"), package)

    assert imported.id != original.id
    assert imported.origin.kind == "imported"


class _PackageUpload:
    def __init__(self, payload, content_type="application/zip"):
        self.payload = payload
        self.content_type = content_type
        self.filename = "untrusted-name.zip"
        self.closed = False

    async def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]

    async def close(self):
        self.closed = True


class _PackageRequest:
    def __init__(self, owner_id, form_data=None):
        self.owner_id = owner_id
        self.headers = {}
        self.query_params = {}
        self.form_data = form_data or {}

    async def form(self, **kwargs):
        assert kwargs == {"max_files": 1, "max_fields": 1}
        return self.form_data


async def _package_async_noop(*args, **kwargs):
    return None


async def _package_owner_id(request):
    return request.owner_id


def test_template_package_api_exports_and_imports_owner_scoped_template(tmp_path, monkeypatch):
    import asyncio

    import app as app_module

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _package_async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _package_owner_id)

    owner = _PackageRequest("package-owner")
    original = TemplateDocument(id="tpl_packageapi01", name="API package fixture")
    asyncio.run(app_module.create_template(original.to_storage_dict(), owner))

    exported = asyncio.run(app_module.export_template(original.id, owner))
    assert exported.media_type == "application/zip"
    assert exported.headers["content-disposition"].endswith(
        f'{original.id}.clippy-template.zip"'
    )

    upload = _PackageUpload(exported.body)
    import_request = _PackageRequest(
        "package-owner",
        {"file": upload},
    )
    response = asyncio.run(app_module.import_template(import_request))
    imported = response["template"]
    assert imported["id"] != original.id
    assert imported["name"] == original.name
    assert imported["origin"]["kind"] == "imported"
    assert upload.closed is True


def test_template_package_api_rejects_invalid_archive_without_creating_template(tmp_path, monkeypatch):
    import asyncio

    import app as app_module
    from fastapi import HTTPException

    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "TEMPLATE_LIBRARY_DIR", str(tmp_path / "libraries"))
    monkeypatch.setattr(app_module, "require_managed_entitlement", _package_async_noop)
    monkeypatch.setattr(app_module, "_owner_id", _package_owner_id)

    request = _PackageRequest(
        "package-owner",
        {"file": _PackageUpload(b"not a zip")},
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app_module.import_template(request))
    assert rejected.value.status_code == 422

    owner = _PackageRequest("package-owner")
    assert asyncio.run(app_module.list_templates(owner))["templates"] == []
