"""Safe local staging and cleanup for reference-video ingestion."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .analysis import ReferenceAnalysisCancelled, ReferenceAnalysisError, _local_video_path

_STAGE_ID = re.compile(r"^ref_[a-f0-9]{32}$")


@dataclass(frozen=True)
class StagedReference:
    id: str
    path: Path
    original_name: str
    size_bytes: int
    sha256: str


def stage_reference_video(
    source_path: str | Path,
    staging_root: str | Path,
    *,
    max_file_size_bytes: int = 2 * 1024 * 1024 * 1024,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> StagedReference:
    """Copy a local reference into an isolated staging directory atomically."""
    source = _local_video_path(source_path)
    if max_file_size_bytes <= 0:
        raise ValueError("max_file_size_bytes must be positive")
    source_size = source.stat().st_size
    if source_size <= 0:
        raise ReferenceAnalysisError("reference video is empty")
    if source_size > max_file_size_bytes:
        raise ReferenceAnalysisError("reference video exceeds the staging size limit")

    root_input = Path(staging_root).expanduser()
    if root_input.is_symlink():
        raise ReferenceAnalysisError("staging root must not be a symbolic link")
    root_input.mkdir(parents=True, exist_ok=True)
    root = root_input.resolve(strict=True)
    if not root.is_dir():
        raise ReferenceAnalysisError("staging root is not a directory")

    stage_id = f"ref_{uuid.uuid4().hex}"
    stage_dir = root / stage_id
    if not stage_dir.resolve().is_relative_to(root):
        raise ReferenceAnalysisError("staging directory escapes staging root")
    stage_dir.mkdir(mode=0o700)
    suffix = source.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".media"
    target = stage_dir / f"source{suffix}"
    fd, temp_name = tempfile.mkstemp(prefix=".source-", suffix=".tmp", dir=stage_dir)
    temporary = Path(temp_name)
    digest = hashlib.sha256()
    copied = 0
    try:
        if progress_callback is not None:
            progress_callback(0, source_size)
        with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
            while True:
                if cancel_check is not None and cancel_check():
                    raise ReferenceAnalysisCancelled("reference staging was cancelled")
                chunk = incoming.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > max_file_size_bytes:
                    raise ReferenceAnalysisError("reference video exceeds the staging size limit")
                digest.update(chunk)
                outgoing.write(chunk)
                if progress_callback is not None:
                    progress_callback(copied, source_size)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if copied != source_size:
            raise ReferenceAnalysisError("source file changed while it was being staged")
        os.replace(temporary, target)
        if progress_callback is not None:
            progress_callback(copied, source_size)
        return StagedReference(
            id=stage_id,
            path=target,
            original_name=source.name,
            size_bytes=copied,
            sha256=digest.hexdigest(),
        )
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_staged_reference(
    staged: StagedReference,
    staging_root: str | Path,
) -> None:
    """Delete only the exact generated staging directory owned by this record."""
    if not _STAGE_ID.fullmatch(staged.id):
        raise ValueError("invalid staging reference id")
    root_input = Path(staging_root).expanduser()
    if root_input.is_symlink():
        raise ReferenceAnalysisError("staging root must not be a symbolic link")
    root = root_input.resolve(strict=True)
    stage_dir = root / staged.id
    if stage_dir.is_symlink() or not stage_dir.is_dir():
        raise ReferenceAnalysisError("staged reference directory is missing or unsafe")
    if not stage_dir.resolve(strict=True).is_relative_to(root):
        raise ReferenceAnalysisError("staged reference directory escapes staging root")
    if staged.path.parent.resolve(strict=True) != stage_dir.resolve(strict=True):
        raise ReferenceAnalysisError("staged reference path does not belong to its staging directory")
    if staged.path.is_symlink() or not staged.path.is_file():
        raise ReferenceAnalysisError("staged reference media file is missing or unsafe")
    shutil.rmtree(stage_dir)
