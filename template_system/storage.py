"""Safe, local-only persistence for versioned Clippy templates.

The storage layer owns filesystem boundaries and integrity checks. It does not
know about HTTP, jobs, AI providers, or renderer implementations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping

from .models import TemplateAsset, TemplateDocument

_TEMPLATE_ID = re.compile(r"^tpl_[A-Za-z0-9_-]{8,64}$")
_MANIFEST_NAME = "manifest.json"


class TemplateStorageError(RuntimeError):
    """Base class for safe template-library storage failures."""


class TemplateAlreadyExists(TemplateStorageError):
    pass


class TemplateNotFound(TemplateStorageError):
    pass


class TemplateRevisionConflict(TemplateStorageError):
    pass


class TemplateIntegrityError(TemplateStorageError):
    pass


class TemplateAssetNotFound(TemplateStorageError):
    pass


class TemplateAssetInUse(TemplateStorageError):
    pass


class LocalTemplateStorage:
    """Persist templates beneath one explicitly configured local directory.

    Asset bytes are supplied at create time and written beneath the template's
    own directory. Updating a document cannot silently replace or orphan assets;
    asset-inventory changes require a future explicit asset-management API.
    """

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise TemplateStorageError("template library root is not a directory")
        self._root_lock = threading.RLock()

    @classmethod
    def _lock_for(cls, key: str) -> threading.RLock:
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @contextmanager
    def _synchronized(self, key: str):
        """Serialize operations across threads and processes on this library root."""
        lock = self._lock_for(f"{self.root}:{key}")
        with lock:
            lock_dir = self.root / ".locks"
            if lock_dir.is_symlink():
                raise TemplateIntegrityError("template lock directory cannot be a symlink")
            lock_dir.mkdir(mode=0o700, exist_ok=True)
            lock_path = lock_dir / f"{key}.lock"
            if lock_path.is_symlink():
                raise TemplateIntegrityError("template lock file cannot be a symlink")
            with lock_path.open("a+b") as stream:
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _validate_id(template_id: str):
        if not isinstance(template_id, str) or not _TEMPLATE_ID.fullmatch(template_id):
            raise ValueError("invalid template id")
        return template_id

    def _template_dir(self, template_id: str) -> Path:
        template_id = self._validate_id(template_id)
        path = self.root / template_id
        if not path.resolve().is_relative_to(self.root):
            raise TemplateIntegrityError("template directory escapes library root")
        if path.is_symlink():
            raise TemplateIntegrityError("template directory cannot be a symlink")
        return path

    @staticmethod
    def _assert_no_symlink_components(base: Path, target: Path) -> None:
        try:
            relative = target.relative_to(base)
        except ValueError as exc:
            raise TemplateIntegrityError("asset path escapes template directory") from exc
        current = base
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise TemplateIntegrityError("template assets cannot traverse symlinks")

    def _asset_path(self, template_dir: Path, relative_path: str) -> Path:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise TemplateIntegrityError("asset path must be a safe relative path")
        target = template_dir.joinpath(*pure.parts)
        if not target.resolve().is_relative_to(template_dir.resolve()):
            raise TemplateIntegrityError("asset path escapes template directory")
        self._assert_no_symlink_components(template_dir, target)
        return target

    def _write_assets(
        self,
        template_dir: Path,
        document: TemplateDocument,
        asset_payloads: Mapping[str, bytes],
    ) -> None:
        expected_ids = {asset.id for asset in document.assets}
        if set(asset_payloads) != expected_ids:
            missing = sorted(expected_ids - set(asset_payloads))
            extra = sorted(set(asset_payloads) - expected_ids)
            raise TemplateIntegrityError(
                f"asset payload mismatch (missing={missing}, extra={extra})"
            )

        for asset in document.assets:
            payload = asset_payloads[asset.id]
            if not isinstance(payload, bytes):
                raise TypeError(f"asset {asset.id!r} payload must be bytes")
            if len(payload) != asset.size_bytes:
                raise TemplateIntegrityError(f"asset {asset.id!r} size does not match manifest")
            digest = hashlib.sha256(payload).hexdigest()
            if digest.lower() != asset.sha256.lower():
                raise TemplateIntegrityError(f"asset {asset.id!r} checksum does not match manifest")
            target = self._asset_path(template_dir, asset.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._assert_no_symlink_components(template_dir, target)
            try:
                with target.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError as exc:
                raise TemplateIntegrityError(f"asset path already exists: {asset.path}") from exc

    def _verify_assets(self, template_dir: Path, document: TemplateDocument) -> None:
        for asset in document.assets:
            path = self._asset_path(template_dir, asset.path)
            if not path.is_file():
                raise TemplateIntegrityError(f"template asset is missing: {asset.path}")
            if path.stat().st_size != asset.size_bytes:
                raise TemplateIntegrityError(f"template asset size mismatch: {asset.path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest.lower() != asset.sha256.lower():
                raise TemplateIntegrityError(f"template asset checksum mismatch: {asset.path}")

    @staticmethod
    def _atomic_write_manifest(template_dir: Path, document: TemplateDocument) -> None:
        payload = json.dumps(
            document.to_storage_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(
            prefix=".manifest-", suffix=".tmp", dir=template_dir
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, template_dir / _MANIFEST_NAME)
            # Best-effort directory sync on platforms that support opening dirs.
            if os.name != "nt":
                dir_fd = os.open(template_dir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_document(self, template_dir: Path) -> TemplateDocument:
        manifest = template_dir / _MANIFEST_NAME
        if manifest.is_symlink() or not manifest.is_file():
            raise TemplateIntegrityError("template manifest is missing or unsafe")
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            document = TemplateDocument.model_validate(raw)
        except Exception as exc:
            raise TemplateIntegrityError(f"template manifest is invalid: {exc}") from exc
        if document.id != template_dir.name:
            raise TemplateIntegrityError("manifest id does not match its directory")
        self._verify_assets(template_dir, document)
        return document

    def create(
        self,
        document: TemplateDocument,
        *,
        asset_payloads: Mapping[str, bytes] | None = None,
    ) -> TemplateDocument:
        template_dir = self._template_dir(document.id)
        with self._root_lock, self._synchronized("_library"), self._synchronized(document.id):
            if template_dir.exists():
                raise TemplateAlreadyExists(document.id)
            template_dir.mkdir(mode=0o700)
            try:
                self._write_assets(template_dir, document, asset_payloads or {})
                self._verify_assets(template_dir, document)
                self._atomic_write_manifest(template_dir, document)
            except Exception:
                shutil.rmtree(template_dir, ignore_errors=True)
                raise
        return document

    def get(self, template_id: str) -> TemplateDocument:
        template_dir = self._template_dir(template_id)
        with self._synchronized(template_id):
            if not template_dir.is_dir():
                raise TemplateNotFound(template_id)
            return self._read_document(template_dir)

    def list(self) -> list[TemplateDocument]:
        documents: list[TemplateDocument] = []
        with self._root_lock, self._synchronized("_library"):
            entries = sorted(self.root.iterdir(), key=lambda item: item.name.casefold())
            for entry in entries:
                if not _TEMPLATE_ID.fullmatch(entry.name):
                    continue
                if entry.is_symlink() or not entry.is_dir():
                    raise TemplateIntegrityError(f"unsafe template entry: {entry.name}")
                with self._synchronized(entry.name):
                    documents.append(self._read_document(entry))
        return documents

    def update(
        self,
        document: TemplateDocument,
        *,
        expected_revision: int,
    ) -> TemplateDocument:
        template_dir = self._template_dir(document.id)
        with self._synchronized(document.id):
            if not template_dir.is_dir():
                raise TemplateNotFound(document.id)
            current = self._read_document(template_dir)
            if current.revision != expected_revision:
                raise TemplateRevisionConflict(
                    f"expected revision {expected_revision}, found {current.revision}"
                )
            if document.revision != current.revision + 1:
                raise TemplateRevisionConflict("updated document revision must increment by one")
            if document.created_at != current.created_at:
                raise TemplateIntegrityError("created_at cannot change during an update")
            if document.updated_at < current.updated_at:
                raise TemplateIntegrityError("updated_at cannot move backwards")
            if document.assets != current.assets:
                raise TemplateIntegrityError(
                    "asset inventory changes require the explicit asset-management API"
                )
            self._verify_assets(template_dir, document)
            self._atomic_write_manifest(template_dir, document)
        return document

    def add_asset(
        self,
        template_id: str,
        asset: TemplateAsset,
        payload: bytes,
        *,
        expected_revision: int,
    ) -> TemplateDocument:
        """Add one validated asset and advance the template revision atomically."""
        if not isinstance(payload, bytes):
            raise TypeError("template asset payload must be bytes")
        if len(payload) != asset.size_bytes:
            raise TemplateIntegrityError("template asset size does not match manifest")
        if hashlib.sha256(payload).hexdigest().lower() != asset.sha256.lower():
            raise TemplateIntegrityError("template asset checksum does not match manifest")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")

        template_dir = self._template_dir(template_id)
        with self._root_lock, self._synchronized("_library"), self._synchronized(template_id):
            if not template_dir.is_dir():
                raise TemplateNotFound(template_id)
            current = self._read_document(template_dir)
            if current.revision != expected_revision:
                raise TemplateRevisionConflict(
                    f"expected revision {expected_revision}, found {current.revision}"
                )
            if any(existing.id == asset.id for existing in current.assets):
                raise TemplateIntegrityError("template asset id already exists")
            if any(existing.path == asset.path for existing in current.assets):
                raise TemplateIntegrityError("template asset path already exists")

            target = self._asset_path(template_dir, asset.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._assert_no_symlink_components(template_dir, target)
            try:
                with target.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())

                updated_data = current.model_dump(mode="python", by_alias=True)
                updated_data["assets"] = [*current.assets, asset]
                updated_data["revision"] = current.revision + 1
                updated_data["updated_at"] = datetime.now(timezone.utc)
                updated = TemplateDocument.model_validate(updated_data)
                self._atomic_write_manifest(template_dir, updated)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return updated

    def get_asset(self, template_id: str, asset_id: str) -> tuple[TemplateAsset, Path]:
        """Return a verified asset record and its path inside the template root."""
        template_dir = self._template_dir(template_id)
        with self._synchronized(template_id):
            if not template_dir.is_dir():
                raise TemplateNotFound(template_id)
            document = self._read_document(template_dir)
            asset = next((item for item in document.assets if item.id == asset_id), None)
            if asset is None:
                raise TemplateAssetNotFound(asset_id)
            return asset, self._asset_path(template_dir, asset.path)

    def remove_asset(
        self,
        template_id: str,
        asset_id: str,
        *,
        expected_revision: int,
    ) -> TemplateDocument:
        """Remove an unreferenced asset and advance the template revision."""
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        template_dir = self._template_dir(template_id)
        with self._root_lock, self._synchronized("_library"), self._synchronized(template_id):
            if not template_dir.is_dir():
                raise TemplateNotFound(template_id)
            current = self._read_document(template_dir)
            if current.revision != expected_revision:
                raise TemplateRevisionConflict(
                    f"expected revision {expected_revision}, found {current.revision}"
                )
            asset = next((item for item in current.assets if item.id == asset_id), None)
            if asset is None:
                raise TemplateAssetNotFound(asset_id)

            referenced_ids = {
                item.asset_id for item in current.recipe.overlays if item.asset_id
            }
            referenced_ids.update(
                item for item in (
                    current.recipe.captions.font_asset_id,
                    current.recipe.hook.font_asset_id,
                    *(overlay.font_asset_id for overlay in current.recipe.overlays),
                ) if item
            )
            referenced_ids.update(
                item.asset_id for item in current.analysis.evidence if item.asset_id
            )
            if current.interpretation is not None:
                referenced_ids.update(
                    evidence.asset_id
                    for claim in current.interpretation.claims
                    for evidence in claim.evidence
                )
            if asset_id in referenced_ids:
                raise TemplateAssetInUse(
                    "asset is referenced by the recipe or template evidence"
                )

            updated_data = current.model_dump(mode="python", by_alias=True)
            updated_data["assets"] = [
                item for item in current.assets if item.id != asset_id
            ]
            updated_data["revision"] = current.revision + 1
            updated_data["updated_at"] = datetime.now(timezone.utc)
            updated = TemplateDocument.model_validate(updated_data)
            self._atomic_write_manifest(template_dir, updated)

            # The manifest no longer references this file. A failed unlink leaves
            # only an orphaned file, never a manifest that points at missing bytes.
            asset_path = self._asset_path(template_dir, asset.path)
            try:
                asset_path.unlink(missing_ok=True)
            except OSError:
                pass
            return updated

    def delete(
        self,
        template_id: str,
        *,
        expected_revision: int | None = None,
    ) -> None:
        """Delete a template, optionally requiring the caller's observed revision."""
        template_dir = self._template_dir(template_id)
        with self._root_lock, self._synchronized("_library"), self._synchronized(template_id):
            if not template_dir.exists():
                raise TemplateNotFound(template_id)
            if template_dir.is_symlink() or not template_dir.is_dir():
                raise TemplateIntegrityError("refusing to delete an unsafe template path")
            if expected_revision is not None:
                current = self._read_document(template_dir)
                if current.revision != expected_revision:
                    raise TemplateRevisionConflict(
                        f"expected revision {expected_revision}, found {current.revision}"
                    )
            shutil.rmtree(template_dir)
