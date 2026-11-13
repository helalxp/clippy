"""Versioned, integrity-checked .clippy-template package import/export."""
from __future__ import annotations

import hashlib
import io
import json
import stat
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Final

from .models import TemplateDocument
from .storage import LocalTemplateStorage, TemplateAlreadyExists, TemplateIntegrityError

PACKAGE_FORMAT: Final = "clippy.template.package"
PACKAGE_VERSION: Final = 1
PACKAGE_MANIFEST: Final = "clippy-template-package.json"
MAX_ARCHIVE_BYTES: Final = 100 * 1024 * 1024
MAX_MANIFEST_BYTES: Final = 2 * 1024 * 1024
MAX_ENTRY_BYTES: Final = 50 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES: Final = 250 * 1024 * 1024
MAX_ARCHIVE_ENTRIES: Final = 257
MAX_COMPRESSION_RATIO: Final = 200


class TemplatePackageError(ValueError):
    """Invalid, unsafe, unsupported, or inconsistent template package."""


def _safe_archive_path(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise TemplatePackageError("package contains an invalid asset path")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or (path.parts and ":" in path.parts[0])
        or str(path) != name
    ):
        raise TemplatePackageError("package asset paths must be safe relative paths")
    return name


def export_template_package(
    storage: LocalTemplateStorage,
    template_id: str,
) -> bytes:
    """Build a deterministic ZIP package from one verified stored template."""
    document = storage.get(template_id)
    output = io.BytesIO()
    package_manifest = {
        "format": PACKAGE_FORMAT,
        "package_version": PACKAGE_VERSION,
        "template": document.to_storage_dict(),
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        manifest_info = zipfile.ZipInfo(PACKAGE_MANIFEST, date_time=(1980, 1, 1, 0, 0, 0))
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        manifest_info.external_attr = (stat.S_IFREG | 0o600) << 16
        archive.writestr(
            manifest_info,
            json.dumps(package_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        for asset in sorted(document.assets, key=lambda item: item.id):
            _safe_archive_path(asset.path)
            verified_asset, path = storage.get_asset(template_id, asset.id)
            if verified_asset != asset:
                raise TemplateIntegrityError("template asset inventory changed during export")
            asset_info = zipfile.ZipInfo(asset.path, date_time=(1980, 1, 1, 0, 0, 0))
            asset_info.compress_type = zipfile.ZIP_DEFLATED
            asset_info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(asset_info, path.read_bytes())

    result = output.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise TemplatePackageError("exported template package exceeds the 100 MB limit")
    return result


def import_template_package(
    storage: LocalTemplateStorage,
    payload: bytes,
) -> TemplateDocument:
    """Validate a bounded package, assign a fresh local ID, and persist atomically."""
    if not isinstance(payload, bytes):
        raise TypeError("template package payload must be bytes")
    if not payload:
        raise TemplatePackageError("template package is empty")
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise TemplatePackageError("template package exceeds the 100 MB limit")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise TemplatePackageError("uploaded file is not a valid ZIP template package") from exc

    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_ENTRIES:
            raise TemplatePackageError("package contains an unsupported number of entries")

        by_name: dict[str, zipfile.ZipInfo] = {}
        total_uncompressed = 0
        for info in infos:
            name = _safe_archive_path(info.filename)
            if info.is_dir():
                raise TemplatePackageError("directory entries are not allowed in template packages")
            if name in by_name:
                raise TemplatePackageError("package contains duplicate file paths")
            if info.flag_bits & 0x1:
                raise TemplatePackageError("encrypted ZIP entries are not supported")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise TemplatePackageError("package uses an unsupported ZIP compression method")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise TemplatePackageError("package contains a non-regular file entry")
            if info.file_size < 0 or info.compress_size < 0:
                raise TemplatePackageError("package contains invalid entry sizes")
            if name == PACKAGE_MANIFEST:
                if info.file_size > MAX_MANIFEST_BYTES:
                    raise TemplatePackageError("package manifest exceeds the 2 MB limit")
            elif info.file_size > MAX_ENTRY_BYTES:
                raise TemplatePackageError("a package asset exceeds the 50 MB limit")
            if info.file_size and (
                info.compress_size == 0
                or info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO
            ):
                raise TemplatePackageError("package entry has an unsafe compression ratio")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise TemplatePackageError("package expands beyond the 250 MB limit")
            by_name[name] = info

        manifest_info = by_name.get(PACKAGE_MANIFEST)
        if manifest_info is None:
            raise TemplatePackageError("package manifest is missing")

        try:
            package_data = json.loads(archive.read(manifest_info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RuntimeError, zipfile.BadZipFile) as exc:
            raise TemplatePackageError("package manifest is not valid UTF-8 JSON") from exc
        if not isinstance(package_data, dict):
            raise TemplatePackageError("package manifest must be a JSON object")
        if package_data.get("format") != PACKAGE_FORMAT:
            raise TemplatePackageError("file is not a Clippy template package")
        if package_data.get("package_version") != PACKAGE_VERSION:
            raise TemplatePackageError("template package version is not supported")
        raw_document = package_data.get("template")
        if not isinstance(raw_document, dict):
            raise TemplatePackageError("package template document is missing")

        try:
            original = TemplateDocument.model_validate(raw_document)
        except Exception as exc:
            raise TemplatePackageError(f"package template document is invalid: {exc}") from exc

        expected_paths = {PACKAGE_MANIFEST}
        for asset in original.assets:
            expected_paths.add(_safe_archive_path(asset.path))
        if set(by_name) != expected_paths:
            missing = sorted(expected_paths - set(by_name))
            extra = sorted(set(by_name) - expected_paths)
            raise TemplatePackageError(
                f"package files do not match the template asset inventory (missing={missing}, extra={extra})"
            )

        asset_payloads: dict[str, bytes] = {}
        for asset in original.assets:
            try:
                asset_bytes = archive.read(by_name[asset.path])
            except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
                raise TemplatePackageError(f"could not read package asset {asset.path!r}") from exc
            if len(asset_bytes) != asset.size_bytes:
                raise TemplatePackageError(f"package asset size mismatch: {asset.path}")
            if hashlib.sha256(asset_bytes).hexdigest().lower() != asset.sha256.lower():
                raise TemplatePackageError(f"package asset checksum mismatch: {asset.path}")
            asset_payloads[asset.id] = asset_bytes

    now = datetime.now(timezone.utc).isoformat()
    document_data = original.to_storage_dict()
    document_data["id"] = f"tpl_{uuid.uuid4().hex[:16]}"
    document_data["revision"] = 1
    document_data["created_at"] = now
    document_data["updated_at"] = now
    origin = dict(document_data.get("origin") or {})
    origin["kind"] = "imported"
    origin["source_name"] = origin.get("source_name") or f"{original.name}.clippy-template"
    document_data["origin"] = origin

    imported = TemplateDocument.model_validate(document_data)
    try:
        return storage.create(imported, asset_payloads=asset_payloads)
    except TemplateAlreadyExists as exc:
        raise TemplatePackageError("generated template ID already exists; retry the import") from exc
