"""Atomic, credential-free durable state for Community Highlights.

Provider access/refresh tokens are deliberately excluded. They remain in
Windows Credential Manager through the provider credential adapter.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)
STATE_SCHEMA_VERSION = 1
_MAX_STATE_BYTES = 2 * 1024 * 1024
_SECTIONS = {"trigger_settings", "capture_sessions", "candidates"}
class StateStoreError(RuntimeError):
    """A safe, user-displayable local Community Highlights persistence failure."""


class CommunityHighlightsStateStore:
    """Store small metadata snapshots under the movable Clippy data directory.

    Writes use a same-directory temporary file, fsync, and atomic replace.
    The lock serializes threads in this backend process. The desktop supervisor
    owns one backend process, so no second writer/process lock is required.
    """

    def __init__(self, data_root: str | Path) -> None:
        raw_root = Path(data_root).expanduser()
        if raw_root.is_symlink():
            raise StateStoreError("The Clippy data directory cannot be a symbolic link.")
        self.data_root = raw_root.resolve()
        self.directory = self.data_root / "community-highlights"
        self.path = self.directory / "state.json"
        self._lock = threading.RLock()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "updated_at": None,
            "trigger_settings": None,
            "capture_sessions": [],
            "candidates": [],
        }

    def _ensure_directory(self) -> None:
        if self.data_root.is_symlink() or (self.data_root.exists() and not self.data_root.is_dir()):
            raise StateStoreError("The Clippy data location is not a trusted directory.")
        self.data_root.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink() or (self.directory.exists() and not self.directory.is_dir()):
            raise StateStoreError("The Community Highlights data location is not a trusted directory.")
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise StateStoreError("The Community Highlights state file is not a regular file.")

    def _quarantine_corrupt_file(self) -> None:
        backup = self.directory / f"state.corrupt-{time.time_ns()}.json"
        try:
            os.replace(self.path, backup)
        except OSError as error:
            raise StateStoreError(
                "Community Highlights state is corrupt and could not be preserved safely."
            ) from error
        _LOG.error(
            "Community Highlights state was invalid; preserved the original as %s",
            backup.name,
        )

    def _read_locked(self) -> dict[str, Any]:
        self._ensure_directory()
        if not self.path.exists():
            return self._empty_state()
        try:
            size = self.path.stat().st_size
            if size > _MAX_STATE_BYTES:
                raise ValueError("state file exceeds the size limit")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            self._quarantine_corrupt_file()
            return self._empty_state()

        if not isinstance(payload, dict):
            self._quarantine_corrupt_file()
            return self._empty_state()
        version = payload.get("schema_version")
        if type(version) is not int:
            self._quarantine_corrupt_file()
            return self._empty_state()
        if version > STATE_SCHEMA_VERSION:
            raise StateStoreError(
                "Community Highlights state was written by a newer Clippy version. "
                "Update Clippy before opening this data directory."
            )
        if version != STATE_SCHEMA_VERSION:
            self._quarantine_corrupt_file()
            return self._empty_state()

        for section in ("capture_sessions", "candidates"):
            if not isinstance(payload.get(section, []), list):
                self._quarantine_corrupt_file()
                return self._empty_state()
        trigger_settings = payload.get("trigger_settings")
        if trigger_settings is not None and not isinstance(trigger_settings, dict):
            self._quarantine_corrupt_file()
            return self._empty_state()

        state = self._empty_state()
        state.update({
            "updated_at": payload.get("updated_at"),
            "trigger_settings": trigger_settings,
            "capture_sessions": payload.get("capture_sessions", []),
            "candidates": payload.get("candidates", []),
        })
        return state

    def _write_locked(self, state: dict[str, Any]) -> None:
        self._ensure_directory()
        state["schema_version"] = STATE_SCHEMA_VERSION
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary_path: str | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".community-highlights-state-",
                suffix=".tmp",
                dir=str(self.directory),
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except (OSError, TypeError, ValueError) as error:
            raise StateStoreError("Clippy could not save Community Highlights state safely.") from error
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_locked()

    def read_section(self, section: str) -> Any:
        if section not in _SECTIONS:
            raise ValueError("Unknown Community Highlights state section.")
        return self.read()[section]

    def update_sections(self, **sections: Any) -> None:
        unknown = set(sections) - _SECTIONS
        if unknown:
            raise ValueError("Unknown Community Highlights state section.")
        for name, value in sections.items():
            if name == "trigger_settings" and value is not None and not isinstance(value, dict):
                raise ValueError("Trigger settings must be an object.")
            if name in {"capture_sessions", "candidates"} and not isinstance(value, list):
                raise ValueError(f"{name} must be a list.")
        with self._lock:
            state = self._read_locked()
            state.update(sections)
            self._write_locked(state)


_DEFAULT_STORE_LOCK = threading.RLock()
_DEFAULT_STORE: CommunityHighlightsStateStore | None = None


def get_state_store() -> CommunityHighlightsStateStore:
    """Resolve storage after dotenv/supervisor environment setup, not at import time."""
    global _DEFAULT_STORE
    raw_root = Path(
        os.environ.get("CLIPPY_DATA_DIR") or os.environ.get("OUTPUT_DIR", "output")
    ).expanduser()
    # Check the caller-supplied path before resolve() erases the symlink.
    if raw_root.is_symlink():
        raise StateStoreError("The Clippy data directory cannot be a symbolic link.")
    root = raw_root.resolve()
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None or _DEFAULT_STORE.data_root != root:
            _DEFAULT_STORE = CommunityHighlightsStateStore(raw_root)
        return _DEFAULT_STORE
