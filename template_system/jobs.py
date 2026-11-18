"""Durable local workbench jobs for reference-video analysis.

The store persists job state outside OUTPUT_DIR so normal output retention cannot
delete in-progress or completed reference analyses. Analysis itself is executed
by the API worker in a background thread.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import (
    ReferenceAnalysisCancelled,
    ReferenceAnalysisError,
    analyze_reference_video,
)
from .providers.reference_video import (
    GeminiReferenceAnalyzer,
    GeminiReferenceAnalysisError,
)

_JOB_ID = re.compile(r"^tjob_[a-f0-9]{32}$")
_ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value: str) -> str:
    name = re.split(r"[\\/]", str(value or "reference.mp4"))[-1]
    name = re.sub(r"[\x00-\x1f]", "_", name)
    return (name.strip(" .") or "reference.mp4")[:240]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class AnalysisJobStore:
    """Atomic JSON job manifests plus per-job source and evidence directories."""

    def __init__(self, root: str | Path):
        raw = Path(root).expanduser()
        raw.mkdir(parents=True, exist_ok=True)
        if raw.is_symlink():
            raise ValueError("template analysis root cannot be a symbolic link")
        self.root = raw.resolve(strict=True)
        self.jobs_root = self.root / "jobs"
        self.incoming_root = self.root / ".incoming"
        self.jobs_root.mkdir(mode=0o700, exist_ok=True)
        self.incoming_root.mkdir(mode=0o700, exist_ok=True)
        for directory in (self.jobs_root, self.incoming_root):
            if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise ValueError("template analysis storage directory is unsafe")

    @classmethod
    def _lock(cls, key: str) -> threading.RLock:
        with _LOCKS_GUARD:
            return _LOCKS.setdefault(key, threading.RLock())

    def _job_dir(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError("invalid template analysis job id")
        path = self.jobs_root / job_id
        if path.is_symlink() or not path.resolve().is_relative_to(self.jobs_root):
            raise ValueError("template analysis job path is unsafe")
        return path

    def _manifest_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def new_upload_path(self, suffix: str) -> Path:
        suffix = str(suffix or "").lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise ValueError("unsupported reference video format")
        return self.incoming_root / f"upload_{uuid.uuid4().hex}{suffix}"

    def create(
        self,
        staged_path: str | Path,
        *,
        original_filename: str,
        name: str = "",
        category: str = "Uncategorized",
        gemini_consent: bool = False,
    ) -> dict[str, Any]:
        staged = Path(staged_path)
        if staged.is_symlink() or not staged.is_file():
            raise ValueError("staged reference upload is missing or unsafe")
        if staged.parent.resolve() != self.incoming_root.resolve():
            raise ValueError("staged reference upload is outside the incoming directory")
        suffix = staged.suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise ValueError("unsupported reference video format")
        size = staged.stat().st_size
        if size <= 0:
            raise ValueError("reference video is empty")

        job_id = f"tjob_{uuid.uuid4().hex}"
        directory = self._job_dir(job_id)
        directory.mkdir(mode=0o700)
        source_name = f"source{suffix}"
        source_target = directory / source_name
        try:
            os.replace(staged, source_target)
            payload = {
                "id": job_id,
                "schema_version": 1,
                "name": (str(name or "").strip()[:120] or Path(_safe_filename(original_filename)).stem or "Reference analysis"),
                "category": (str(category or "").strip()[:80] or "Uncategorized"),
                "original_filename": _safe_filename(original_filename),
                "source_file": source_name,
                "source_size_bytes": size,
                "source_sha256": _hash_file(source_target),
                "gemini_consent": bool(gemini_consent),
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "cancel_requested": False,
                "ai_status": "pending" if gemini_consent else "not_consented",
                "ai_error": None,
                "error": None,
                "created_at": _now(),
                "updated_at": _now(),
                "completed_at": None,
            }
            self._atomic_json(self._manifest_path(job_id), payload)
            return payload
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def get(self, job_id: str) -> dict[str, Any]:
        path = self._manifest_path(job_id)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(job_id)
        with self._lock(str(path)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("template analysis job manifest is corrupt") from exc
        if payload.get("id") != job_id:
            raise ValueError("template analysis job id does not match its manifest")
        return payload

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "status", "stage", "progress", "cancel_requested", "ai_status",
            "ai_error", "error", "completed_at",
        }
        if set(changes) - allowed:
            raise ValueError("unsupported template analysis job field")
        path = self._manifest_path(job_id)
        with self._lock(str(path)):
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(job_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.update(changes)
            payload["updated_at"] = _now()
            self._atomic_json(path, payload)
            return payload

    def save_report(self, job_id: str, report: dict[str, Any]) -> None:
        directory = self._job_dir(job_id)
        path = directory / "report.json"
        if path.is_symlink():
            raise ValueError("analysis report path cannot be a symbolic link")
        with self._lock(str(path)):
            self._atomic_json(path, report)

    def get_report(self, job_id: str) -> dict[str, Any] | None:
        path = self._job_dir(job_id) / "report.json"
        if path.is_symlink() or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("template analysis report is corrupt") from exc

    def source_path(self, job_id: str) -> Path:
        payload = self.get(job_id)
        path = self._job_dir(job_id) / payload["source_file"]
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("reference source is no longer available")
        return path

    def evidence_path(self, job_id: str, asset_id: str) -> Path:
        if not re.fullmatch(r"reference_frame_[0-9]{3}", str(asset_id or "")):
            raise ValueError("invalid reference evidence asset id")
        path = self._job_dir(job_id) / "evidence" / f"frame_{asset_id.rsplit('_', 1)[1]}_" 
        directory = path.parent
        if directory.is_symlink() or not directory.is_dir():
            raise FileNotFoundError(asset_id)
        matches = list(directory.glob(f"{path.name}*.png"))
        if len(matches) != 1 or matches[0].is_symlink() or not matches[0].is_file():
            raise FileNotFoundError(asset_id)
        return matches[0]

    def list(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for directory in self.jobs_root.iterdir():
            if directory.is_symlink() or not directory.is_dir() or not _JOB_ID.fullmatch(directory.name):
                continue
            try:
                jobs.append(self.get(directory.name))
            except (OSError, ValueError):
                continue
        return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)

    def delete(self, job_id: str) -> None:
        """Remove a terminal analysis job and all retained source/evidence assets."""
        directory = self._job_dir(job_id)
        with self._lock(str(directory)):
            if directory.is_symlink() or not directory.is_dir():
                raise FileNotFoundError(job_id)
            manifest = directory / "job.json"
            if manifest.is_symlink() or not manifest.is_file():
                raise ValueError("template analysis job manifest is missing or unsafe")
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("template analysis job manifest is corrupt") from exc
            if payload.get("id") != job_id:
                raise ValueError("template analysis job id does not match its directory")
            if payload.get("status") not in {"completed", "partial", "failed", "cancelled"}:
                raise ValueError("analysis jobs can only be deleted after they reach a terminal state")
            shutil.rmtree(directory)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        """Set cancellation under the same lock used by terminal finalization."""
        path = self._manifest_path(job_id)
        with self._lock(str(path)):
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(job_id)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("template analysis job manifest is corrupt") from exc
            if payload.get("id") != job_id:
                raise ValueError("template analysis job id does not match its manifest")
            if payload.get("status") in {"completed", "partial", "failed", "cancelled"}:
                return payload
            payload.update(
                cancel_requested=True,
                stage="cancelling",
                updated_at=_now(),
            )
            self._atomic_json(path, payload)
            return payload

    def finish(
        self,
        job_id: str,
        report: dict[str, Any],
        *,
        status: str,
        ai_status: str,
        ai_error: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist the final report and honor any concurrent cancel."""
        if status not in {"completed", "partial", "cancelled"}:
            raise ValueError("invalid terminal analysis status")
        if ai_status not in {"complete", "failed", "not_consented", "cancelled"}:
            raise ValueError("invalid terminal AI status")
        path = self._manifest_path(job_id)
        with self._lock(str(path)):
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(job_id)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("template analysis job manifest is corrupt") from exc
            if payload.get("id") != job_id:
                raise ValueError("template analysis job id does not match its manifest")

            final_report = dict(report)
            if payload.get("cancel_requested"):
                status = "cancelled"
                ai_status = "cancelled"
                ai_error = "Cancellation was requested while the analysis job was finalizing."
                final_report["ai_status"] = "cancelled"
                final_report["ai_error"] = ai_error
                final_report["ai_report"] = None
            else:
                final_report["ai_status"] = ai_status
                final_report["ai_error"] = ai_error
                if ai_status != "complete":
                    final_report["ai_report"] = None

            report_path = self._job_dir(job_id) / "report.json"
            if report_path.is_symlink():
                raise ValueError("analysis report path cannot be a symbolic link")
            self._atomic_json(report_path, final_report)

            payload.update(
                status=status,
                stage="cancelled" if status == "cancelled" else "complete",
                progress=100,
                ai_status=ai_status,
                ai_error=ai_error,
                error=None,
                completed_at=_now(),
                updated_at=_now(),
            )
            self._atomic_json(path, payload)
            return payload

    def is_cancel_requested(self, job_id: str) -> bool:
        return bool(self.get(job_id).get("cancel_requested"))

    def recover_interrupted(self) -> list[str]:
        """Re-queue interrupted work without resurrecting explicit cancellations."""
        resumed: list[str] = []
        for item in self.list():
            status = item.get("status")
            if status not in {"running", "queued"}:
                continue
            if item.get("cancel_requested"):
                report = self.get_report(item["id"])
                if report is not None:
                    report["ai_status"] = "cancelled"
                    report["ai_error"] = "The job was cancelled before the previous Clippy session shut down."
                    report["ai_report"] = None
                    self.save_report(item["id"], report)
                self.update(
                    item["id"],
                    status="cancelled",
                    stage="cancelled",
                    ai_status="cancelled",
                    ai_error="The job was cancelled before the previous Clippy session shut down.",
                    completed_at=_now(),
                )
                continue
            if status == "running":
                self.update(
                    item["id"], status="queued", stage="queued", progress=0,
                    cancel_requested=False,
                )
            resumed.append(item["id"])
        return resumed


def execute_reference_analysis_job(
    store: AnalysisJobStore,
    job_id: str,
    *,
    analyzer_factory=None,
) -> None:
    """Run deterministic FFmpeg analysis then optional Gemini interpretation."""
    from .analysis import analyze_reference_video

    item = store.get(job_id)
    if item.get("cancel_requested"):
        store.update(job_id, status="cancelled", stage="cancelled", completed_at=_now())
        return
    source_path = store.source_path(job_id)
    evidence_dir = store._job_dir(job_id) / "evidence"
    evidence_dir.mkdir(mode=0o700, exist_ok=True)

    def cancelled() -> bool:
        return store.is_cancel_requested(job_id)

    def progress(stage: str, fraction: float) -> None:
        current = store.get(job_id)
        if current.get("cancel_requested"):
            raise ReferenceAnalysisCancelled("reference analysis was cancelled")
        store.update(
            job_id,
            status="running",
            stage=stage,
            progress=max(1, min(85, int(round(fraction * 85)))),
        )

    try:
        store.update(job_id, status="running", stage="probing", progress=1)
        analysis_result = analyze_reference_video(
            source_path,
            evidence_dir,
            progress_callback=progress,
            cancel_check=cancelled,
        )
        if cancelled():
            raise ReferenceAnalysisCancelled("reference analysis was cancelled")

        _, assets = analysis_result.to_template_parts()
        deterministic = {
            "technical": analysis_result.probe.to_dict(),
            "scene_boundaries_seconds": list(analysis_result.scene_boundaries_seconds),
            "scene_boundaries_ms": [
                int(round(value * 1000)) for value in analysis_result.scene_boundaries_seconds
            ],
            "samples": [
                {
                    "asset_id": asset.id,
                    "timestamp_ms": asset.source_timestamp_ms,
                    "width": asset.width,
                    "height": asset.height,
                    "sha256": asset.sha256,
                    "size_bytes": asset.size_bytes,
                }
                for asset in assets
            ],
            "visual_measurements": [
                measurement.to_dict() for measurement in analysis_result.visual_measurements
            ],
            "coverage": analysis_result.coverage,
            "status": analysis_result.status,
            "limitations": list(analysis_result.limitations) + (
                ["Audio content and audio-editing treatment are not analyzed in this visual-analysis milestone; only audio stream metadata is measured."]
                if getattr(analysis_result.probe, "has_audio", False) else []
            ),
        }

        ai_status = "pending" if item.get("gemini_consent") else "not_consented"
        ai_error = None
        report = {
            "schema_version": 1,
            "deterministic": deterministic,
            "ai_status": ai_status,
            "ai_error": None,
            "ai_report": None,
        }
        # Persist the deterministic work before making an optional network call.
        # Cancelling or losing Gemini must not discard the local analysis.
        store.save_report(job_id, report)

        if cancelled():
            report["ai_status"] = "cancelled"
            store.finish(
                job_id, report, status="cancelled", ai_status="cancelled",
                ai_error="Cancellation was requested before visual interpretation began.",
            )
            return

        ai_report = None
        if item.get("gemini_consent"):
            store.update(job_id, stage="gemini_interpretation", progress=88, ai_status="running")
            try:
                analyzer = (
                    analyzer_factory(consent_confirmed=True)
                    if analyzer_factory is not None
                    else GeminiReferenceAnalyzer(consent_confirmed=True)
                )
                ai_report = analyzer.analyze(analysis_result, str(evidence_dir)).model_dump(mode="json")
                ai_status = "complete"
            except Exception as exc:
                ai_status = "failed"
                ai_error = f"{type(exc).__name__}: {str(exc)[:1000]}"

        # finish() and request_cancel() serialize on the same manifest lock.
        # A cancel arriving during the provider request or finalization wins.
        final_status = "completed" if ai_status == "complete" else "partial"
        report["ai_status"] = ai_status
        report["ai_error"] = ai_error
        report["ai_report"] = ai_report if ai_status == "complete" else None
        store.finish(
            job_id, report, status=final_status,
            ai_status=ai_status, ai_error=ai_error,
        )
    except ReferenceAnalysisCancelled:
        store.update(job_id, status="cancelled", stage="cancelled", completed_at=_now())
    except Exception as exc:
        store.update(
            job_id, status="failed", stage="failed",
            error=f"{type(exc).__name__}: {str(exc)[:1500]}",
            completed_at=_now(),
        )
