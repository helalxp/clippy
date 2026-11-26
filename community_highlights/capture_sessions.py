"""Supervised lifecycle for Streamlink/FFmpeg rolling captures.

Capture workers own their blocking Streamlink and FFmpeg resources. The manager
owns worker threads, immutable per-session configuration snapshots, and safe
status reporting to the API.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .models import ChatProvider
from .rolling_capture import RollingCapture, RollingCaptureConfig, RollingCaptureError
from .extraction import assemble_segments, probe_media_duration_seconds
from .timeline import segment_wall_interval, select_segments_for_interval, validate_contiguous_interval
from .urls import parse_stream_url
from .state_store import StateStoreError, get_state_store
from .diagnostics import log_event


MAX_CAPTURE_SESSIONS = 2
STOP_JOIN_SECONDS = 45
MAX_HIGHLIGHT_CANDIDATES = 20
_LOG = logging.getLogger(__name__)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_GENERATION_JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)
_GENERATION_STATES = {"not_started", "staging", "queued", "processing", "completed", "failed"}


@dataclass(frozen=True)
class CaptureSettings:
    segment_seconds: int = 4
    retention_seconds: int = 180
    max_buffer_size_mb: int = 512
    quality: str = "best"

    def snapshot(self, output_dir: Path) -> RollingCaptureConfig:
        config = RollingCaptureConfig(
            output_dir=output_dir,
            segment_seconds=self.segment_seconds,
            retention_seconds=self.retention_seconds,
            max_buffer_size_mb=self.max_buffer_size_mb,
            quality=self.quality,
        )
        config.validate()
        if not re.fullmatch(r"(?:best|worst|audio_only|[0-9]{3,4}p[0-9]*)", self.quality, re.IGNORECASE):
            raise ValueError("Choose a supported stream quality.")
        return config


@dataclass
class HighlightCandidate:
    candidate_id: str
    capture_session_id: str
    triggered_at: datetime
    pre_seconds: int
    post_seconds: int
    reason: str
    status: str = "capturing"
    review_status: str = "pending"
    error: str | None = None
    output_path: Path | None = None
    segment_count: int = 0
    worker: threading.Thread | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    merge_until: datetime | None = None
    trigger_count: int = 1
    actual_duration_seconds: float | None = None
    generation_status: str = "not_started"
    generation_job_id: str | None = None
    generation_error: str | None = None
    protected_segments: list[Path] = field(default_factory=list, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "capture_session_id": self.capture_session_id,
            "triggered_at": self.triggered_at.isoformat(),
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "pre_seconds": self.pre_seconds,
            "post_seconds": self.post_seconds,
            "actual_duration_seconds": self.actual_duration_seconds,
            "reason": self.reason,
            "status": self.status,
            "review_status": self.review_status,
            "error": self.error,
            "file_name": self.output_path.name if self.output_path else None,
            "segment_count": self.segment_count,
            "trigger_count": self.trigger_count,
            "generation_status": self.generation_status,
            "generation_job_id": self.generation_job_id,
            "generation_error": self.generation_error,
        }


@dataclass
class CaptureSession:
    session_id: str
    provider: ChatProvider
    stream_id: str
    config: RollingCaptureConfig
    capture: Any
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "starting"
    error: str | None = None
    worker: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    # Set only after RollingCapture.run() has closed Streamlink and FFmpeg.
    capture_finished: threading.Event = field(default_factory=threading.Event, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider.value,
            "stream_id": self.stream_id,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "segment_seconds": self.config.segment_seconds,
            "retention_seconds": self.config.retention_seconds,
            "max_buffer_size_mb": self.config.max_buffer_size_mb,
            "quality": self.config.quality,
        }


class CaptureSessionManager:
    """Own at most two capture workers and provide bounded shutdown."""

    def __init__(
        self,
        *,
        capture_factory: Callable[..., Any] = RollingCapture,
        output_root: Path | None = None,
        max_sessions: int = MAX_CAPTURE_SESSIONS,
        state_store=None,
    ) -> None:
        if not isinstance(max_sessions, int) or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer.")
        self._capture_factory = capture_factory
        self._custom_output_root = output_root is not None
        self._output_root = Path(output_root).expanduser().resolve() if output_root is not None else None
        self._state_store = state_store
        self._use_default_state_store = state_store is None and output_root is None
        self._max_sessions = max_sessions
        self._sessions: dict[str, CaptureSession] = {}
        self._candidates: dict[str, HighlightCandidate] = {}
        self._lock = threading.RLock()
        self._restored = False

    def _output_root_path(self) -> Path:
        if self._output_root is None:
            base = os.environ.get("CLIPPY_DATA_DIR", os.environ.get("OUTPUT_DIR", "output"))
            self._output_root = (Path(base).expanduser() / "community-highlights").resolve()
        return self._output_root

    def _get_state_store(self):
        if self._state_store is not None:
            return self._state_store
        if self._use_default_state_store:
            self._state_store = get_state_store()
        return self._state_store

    @staticmethod
    def _parse_saved_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or len(value) > 80:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    def _persist_locked(self, *, strict: bool = False) -> None:
        store = self._get_state_store()
        if store is None:
            return
        sessions = [
            {
                "session_id": item.session_id,
                "provider": item.provider.value,
                "stream_id": item.stream_id,
                "started_at": item.started_at.isoformat(),
                "status": item.status,
                "error": item.error,
                "segment_seconds": item.config.segment_seconds,
                "retention_seconds": item.config.retention_seconds,
                "max_buffer_size_mb": item.config.max_buffer_size_mb,
                "quality": item.config.quality,
            }
            for item in self._sessions.values()
        ]
        candidates = [
            {
                "candidate_id": item.candidate_id,
                "capture_session_id": item.capture_session_id,
                "triggered_at": item.triggered_at.isoformat(),
                "window_start": item.window_start.isoformat() if item.window_start else None,
                "window_end": item.window_end.isoformat() if item.window_end else None,
                "pre_seconds": item.pre_seconds,
                "post_seconds": item.post_seconds,
                "actual_duration_seconds": item.actual_duration_seconds,
                "reason": item.reason,
                "status": item.status,
                "review_status": item.review_status,
                "error": item.error,
                "segment_count": item.segment_count,
                "trigger_count": item.trigger_count,
                "generation_status": item.generation_status,
                "generation_job_id": item.generation_job_id,
                "generation_error": item.generation_error,
            }
            for item in self._candidates.values()
        ]
        try:
            store.update_sections(capture_sessions=sessions, candidates=candidates)
        except StateStoreError as error:
            if strict:
                raise
            _LOG.warning(
                "Community Highlights state snapshot could not be saved (error_type=%s)",
                type(error).__name__,
            )

    def _recover_pending_candidate_deletes(self, output_root: Path, state: dict[str, Any]) -> None:
        """Roll back an uncommitted media rename or finish a committed deletion."""
        saved_candidates = {
            (row.get("capture_session_id"), row.get("candidate_id"))
            for row in state.get("candidates", [])
            if isinstance(row, dict)
            and isinstance(row.get("capture_session_id"), str)
            and _SESSION_ID_RE.fullmatch(row["capture_session_id"])
            and isinstance(row.get("candidate_id"), str)
            and _SESSION_ID_RE.fullmatch(row["candidate_id"])
        }
        if not output_root.is_dir():
            return
        try:
            session_dirs = list(output_root.iterdir())
        except OSError:
            return

        suffix = ".delete-pending.mp4"
        for session_dir in session_dirs:
            if (
                session_dir.is_symlink()
                or not session_dir.is_dir()
                or not _SESSION_ID_RE.fullmatch(session_dir.name)
                or session_dir.resolve().parent != output_root
            ):
                continue
            highlights_dir = session_dir / "highlights"
            if (
                highlights_dir.is_symlink()
                or not highlights_dir.is_dir()
                or highlights_dir.resolve().parent != session_dir.resolve()
            ):
                continue
            for pending_path in highlights_dir.glob(f".*{suffix}"):
                if pending_path.is_symlink() or not pending_path.is_file():
                    continue
                candidate_id = pending_path.name[1:-len(suffix)]
                if not _SESSION_ID_RE.fullmatch(candidate_id):
                    continue
                media_path = highlights_dir / f"{candidate_id}.mp4"
                try:
                    if (session_dir.name, candidate_id) in saved_candidates:
                        # The metadata removal did not commit. Restore the
                        # original name so the candidate remains recoverable.
                        if media_path.is_symlink():
                            raise OSError("candidate media path is a symbolic link")
                        if media_path.exists():
                            if not media_path.is_file():
                                raise OSError("candidate media path is not a regular file")
                            pending_path.unlink(missing_ok=True)
                        else:
                            pending_path.replace(media_path)
                    else:
                        # Metadata removal committed. The remaining hidden file
                        # is only the second half of the completed deletion.
                        pending_path.unlink(missing_ok=True)
                except OSError as error:
                    _LOG.warning(
                        "A pending Community Highlights media deletion could not be reconciled (error_type=%s)",
                        type(error).__name__,
                    )

    def restore(self) -> None:
        """Restore durable metadata and mark non-resumable work interrupted."""
        with self._lock:
            if self._restored:
                return
            if not self._custom_output_root:
                self._output_root = None
            store = self._get_state_store()
            if store is None:
                self._restored = True
                return
            state = store.read()
            output_root = self._output_root_path().resolve()
            self._recover_pending_candidate_deletes(output_root, state)
            restored_sessions: dict[str, CaptureSession] = {}
            restored_candidates: dict[str, HighlightCandidate] = {}

            for row in state.get("capture_sessions", [])[-128:]:
                if not isinstance(row, dict):
                    continue
                session_id = row.get("session_id")
                stream_id = row.get("stream_id")
                if (
                    not isinstance(session_id, str)
                    or not _SESSION_ID_RE.fullmatch(session_id)
                    or not isinstance(stream_id, str)
                    or not stream_id
                    or len(stream_id) > 256
                    or any(ord(char) < 32 for char in stream_id)
                ):
                    continue
                try:
                    provider = ChatProvider(row.get("provider"))
                except (TypeError, ValueError):
                    continue
                output_dir = output_root / session_id
                if output_dir.is_symlink() or output_dir.resolve().parent != output_root:
                    _LOG.warning("Skipped an unsafe Community Highlights capture directory during recovery.")
                    continue

                try:
                    settings = CaptureSettings(
                        segment_seconds=row.get("segment_seconds", 4),
                        retention_seconds=row.get("retention_seconds", 180),
                        max_buffer_size_mb=row.get("max_buffer_size_mb", 512),
                        quality=row.get("quality", "best"),
                    )
                    config = settings.snapshot(output_dir)
                except (TypeError, ValueError):
                    config = CaptureSettings().snapshot(output_dir)
                    saved_error = "Saved capture settings were invalid; start a new rolling buffer."
                else:
                    saved_error = row.get("error") if isinstance(row.get("error"), str) else None

                started_at = self._parse_saved_datetime(row.get("started_at")) or datetime.now(timezone.utc)
                saved_status = row.get("status")
                if saved_status in {"starting", "recording", "stopping"}:
                    status = "interrupted"
                    error = "Clippy restarted while this rolling buffer was active. Start a new capture to continue."
                elif saved_status in {"stopped", "ended", "error", "interrupted"}:
                    status = saved_status
                    error = saved_error
                else:
                    status = "error"
                    error = "The saved capture status was invalid and could not be resumed."

                restored_session = CaptureSession(
                    session_id=session_id,
                    provider=provider,
                    stream_id=stream_id,
                    config=config,
                    capture=None,
                    started_at=started_at,
                    status=status,
                    error=error,
                )
                # No worker or external media reader survives a backend restart.
                restored_session.capture_finished.set()
                restored_sessions[session_id] = restored_session

            for row in state.get("candidates", [])[-MAX_HIGHLIGHT_CANDIDATES:]:
                if not isinstance(row, dict):
                    continue
                candidate_id = row.get("candidate_id")
                session_id = row.get("capture_session_id")
                triggered_at = self._parse_saved_datetime(row.get("triggered_at"))
                if (
                    not isinstance(candidate_id, str)
                    or not _SESSION_ID_RE.fullmatch(candidate_id)
                    or not isinstance(session_id, str)
                    or not _SESSION_ID_RE.fullmatch(session_id)
                    or triggered_at is None
                ):
                    continue
                reason = row.get("reason")
                if not isinstance(reason, str) or not reason or len(reason) > 40:
                    reason = "recovered"
                review_status = row.get("review_status")
                if review_status not in {"pending", "approved", "rejected"}:
                    review_status = "pending"
                saved_status = row.get("status")
                error = row.get("error") if isinstance(row.get("error"), str) else None
                candidate_dir = output_root / session_id
                highlights_dir = candidate_dir / "highlights"
                media_path = highlights_dir / f"{candidate_id}.mp4"
                try:
                    safe_media = (
                        not candidate_dir.is_symlink()
                        and not highlights_dir.is_symlink()
                        and not media_path.is_symlink()
                        and media_path.is_file()
                        and media_path.stat().st_size > 0
                        and media_path.resolve().parent == highlights_dir.resolve()
                        and highlights_dir.resolve().parent == candidate_dir.resolve()
                        and candidate_dir.resolve().parent == output_root
                    )
                except OSError:
                    safe_media = False
                output_path = media_path if safe_media else None
                if saved_status in {"capturing", "assembling"}:
                    status = "error"
                    error = "Clippy restarted before this highlight finished. The partial media was preserved for safe cleanup."
                elif saved_status == "ready" and output_path is None and review_status != "rejected":
                    status = "error"
                    error = "The saved highlight video is missing or failed its storage safety check."
                elif saved_status in {"ready", "error"}:
                    status = saved_status
                else:
                    status = "error"
                    error = "The saved highlight status was invalid and could not be resumed."

                pre_seconds = row.get("pre_seconds", 0)
                post_seconds = row.get("post_seconds", 0)
                window_start = self._parse_saved_datetime(row.get("window_start"))
                window_end = self._parse_saved_datetime(row.get("window_end"))
                actual_duration_seconds = row.get("actual_duration_seconds")
                if (
                    isinstance(actual_duration_seconds, bool)
                    or not isinstance(actual_duration_seconds, (int, float))
                    or not math.isfinite(actual_duration_seconds)
                    or actual_duration_seconds <= 0
                ):
                    actual_duration_seconds = None
                else:
                    actual_duration_seconds = float(actual_duration_seconds)
                if (
                    window_start is not None
                    and window_end is not None
                    and window_end < window_start
                ):
                    window_start = None
                    window_end = None
                segment_count = row.get("segment_count", 0)
                trigger_count = row.get("trigger_count", 1)
                generation_status = row.get("generation_status", "not_started")
                generation_job_id = row.get("generation_job_id")
                generation_error = row.get("generation_error")
                if generation_status not in _GENERATION_STATES:
                    generation_status = "failed" if generation_job_id else "not_started"
                    generation_error = "Saved generation state was invalid and must be retried."
                if generation_job_id is not None and (
                    not isinstance(generation_job_id, str)
                    or not _GENERATION_JOB_ID_RE.fullmatch(generation_job_id)
                ):
                    generation_job_id = None
                    generation_status = "failed"
                    generation_error = "Saved generation job reference was invalid and must be retried."
                if generation_job_id is None and generation_status in {"staging", "queued", "processing", "completed"}:
                    generation_status = "failed"
                    generation_error = "The saved generation job reference is missing."
                if not isinstance(generation_error, str):
                    generation_error = None
                else:
                    generation_error = generation_error.replace("\r", "").replace("\n", " ")[:500]
                if type(pre_seconds) is not int or not 0 <= pre_seconds <= 300:
                    pre_seconds = 0
                if type(post_seconds) is not int or not 0 <= post_seconds <= 300:
                    post_seconds = 0
                if type(segment_count) is not int or segment_count < 0:
                    segment_count = 0
                if type(trigger_count) is not int or trigger_count < 1:
                    trigger_count = 1
                restored_candidates[candidate_id] = HighlightCandidate(
                    candidate_id=candidate_id,
                    capture_session_id=session_id,
                    triggered_at=triggered_at,
                    pre_seconds=pre_seconds,
                    post_seconds=post_seconds,
                    reason=reason,
                    status=status,
                    review_status=review_status,
                    error=error,
                    output_path=output_path,
                    segment_count=segment_count,
                    trigger_count=trigger_count,
                    window_start=window_start,
                    window_end=window_end,
                    actual_duration_seconds=actual_duration_seconds,
                    generation_status=generation_status,
                    generation_job_id=generation_job_id,
                    generation_error=generation_error,
                )

            self._sessions = restored_sessions
            self._candidates = restored_candidates
            self._restored = True
            self._persist_locked()

            # No capture or candidate worker survives a backend restart. The
            # rolling source ring is therefore disposable; completed candidate
            # MP4s and interrupted partial MP4s remain available for review/delete.
            # Every restored session is terminal, even if it was already marked
            # stopped/ended/error before the process exited.
            cleanup_sessions = list(self._sessions.values())

        for session in cleanup_sessions:
            self._cleanup_rolling_segments_if_finished(session)

    def start(
        self, stream_url: str, settings: CaptureSettings | None = None
    ) -> dict[str, Any]:
        self.restore()
        reference = parse_stream_url(stream_url)
        settings = settings or CaptureSettings()
        with self._lock:
            self._prune_finished_locked()
            # A repeated start for the same provider stream is idempotent. This
            # prevents double-clicks/retries from spawning duplicate FFmpeg
            # workers for one live stream.
            existing = next(
                (
                    session for session in self._sessions.values()
                    if session.provider == reference.provider
                    and session.stream_id == reference.stream_id
                    and session.status not in {"stopped", "ended", "error"}
                ),
                None,
            )
            if existing is not None:
                log_event("capture.start.idempotent", provider=reference.provider.value, session_id=existing.session_id)
                return existing.snapshot()
            if len(self._sessions) >= self._max_sessions:
                raise ValueError(f"Clippy can record up to {self._max_sessions} live streams at a time.")

            session_id = secrets.token_urlsafe(18)
            output_dir = (self._output_root_path() / session_id).resolve()
            config = settings.snapshot(output_dir)
            capture = self._capture_factory(stream_url, config)
            session = CaptureSession(
                session_id=session_id,
                provider=reference.provider,
                stream_id=reference.stream_id,
                config=config,
                capture=capture,
            )
            self._sessions[session_id] = session
            worker = threading.Thread(
                target=self._run,
                args=(session,),
                name=f"community-highlight-{session_id[:8]}",
                daemon=True,
            )
            session.worker = worker
            try:
                self._persist_locked(strict=True)
                worker.start()
            except Exception as error:
                self._sessions.pop(session_id, None)
                self._persist_locked()
                log_event("capture.start.failed", level=logging.ERROR, provider=reference.provider.value, session_id=session_id, error_type=type(error).__name__)
                raise
            log_event("capture.start.accepted", provider=reference.provider.value, session_id=session_id, segment_seconds=config.segment_seconds, retention_seconds=config.retention_seconds, quality=config.quality)
            return session.snapshot()

    def _run(self, session: CaptureSession) -> None:
        try:
            def mark_recording() -> None:
                with self._lock:
                    if not session.stop_event.is_set():
                        session.status = "recording"
                        self._persist_locked()
                        log_event("capture.recording", provider=session.provider.value, session_id=session.session_id)

            session.capture.run(session.stop_event, on_started=mark_recording)
            with self._lock:
                session.status = "stopped" if session.stop_event.is_set() else "ended"
                self._persist_locked()
            log_event("capture.finished", provider=session.provider.value, session_id=session.session_id, outcome=session.status)
        except RollingCaptureError as error:
            with self._lock:
                session.error = str(error)
                session.status = "error"
                self._persist_locked()
            log_event("capture.failed", level=logging.ERROR, provider=session.provider.value, session_id=session.session_id, error_type=type(error).__name__)
        except Exception as error:
            with self._lock:
                session.error = "Live capture failed unexpectedly. Check the stream and FFmpeg installation."
                session.status = "error"
                self._persist_locked()
            log_event("capture.failed", level=logging.ERROR, provider=session.provider.value, session_id=session.session_id, error_type=type(error).__name__)
        finally:
            # A naturally ended/failed source cannot provide any more post-trigger
            # footage. Wake candidate workers so they fail promptly and release
            # their pins instead of leaving this session's ring on disk forever.
            # run() returns only after RollingCapture has closed its reader,
            # FFmpeg process, and resolved stream. Publish that fact before
            # waking candidate workers so cleanup has an unambiguous owner.
            session.capture_finished.set()
            session.stop_event.set()
            self._cleanup_rolling_segments_if_finished(session)

    def _cleanup_rolling_segments_if_finished(self, session: CaptureSession) -> None:
        """Remove source-ring files after the capture and all candidate readers finish.

        Approved/pending candidate MP4s live under the sibling highlights folder
        and are deliberately preserved. Only disposable rolling inputs and the
        FFmpeg index are removed.
        """
        with self._lock:
            if session.status not in {"stopped", "ended", "error", "interrupted"}:
                return
            current = threading.current_thread()
            capture_worker = session.worker
            if capture_worker is not None and capture_worker is not current and not session.capture_finished.is_set():
                # A stop request can time out while Streamlink/FFmpeg is still
                # closing. Never unlink its source files until run() has closed
                # the reader and process, even if the session is marked terminal.
                return
            for candidate in self._candidates.values():
                if (
                    candidate.capture_session_id == session.session_id
                    and candidate.status in {"capturing", "assembling"}
                ):
                    # Candidate status becomes terminal only after it has
                    # finished reading/assembling source segments. Thread
                    # liveness is not a safe cleanup signal: two finishing
                    # workers can otherwise observe each other alive and both
                    # skip the final cleanup pass.
                    return
            output_dir = session.config.output_dir

        if not output_dir.is_dir():
            return
        for segment in output_dir.glob("segment-*.ts"):
            try:
                segment.unlink(missing_ok=True)
            except OSError:
                # Leave an undeletable source in place for a later cleanup pass.
                continue
        for index_name in ("segments.csv", "segments.csv.tmp"):
            try:
                (output_dir / index_name).unlink(missing_ok=True)
            except OSError:
                continue
        highlights_dir = output_dir / "highlights"
        if highlights_dir.is_dir():
            # FFmpeg concat manifests are disposable extraction inputs. A normal
            # finally block deletes them; this is a second cleanup for a worker
            # that ended abnormally after capture has stopped.
            for manifest in highlights_dir.glob("highlight-*.ffconcat"):
                try:
                    manifest.unlink(missing_ok=True)
                except OSError:
                    continue
        # Keep candidate MP4s; remove only empty scaffolding.
        try:
            highlights_dir.rmdir()
        except OSError:
            pass
        try:
            output_dir.rmdir()
        except OSError:
            pass

    def get(self, session_id: str) -> dict[str, Any] | None:
        self.restore()
        with self._lock:
            session = self._sessions.get(session_id)
            return session.snapshot() if session else None

    def list(self) -> list[dict[str, Any]]:
        self.restore()
        with self._lock:
            return [session.snapshot() for session in self._sessions.values()]

    def _prune_finished_locked(self) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.status in {"stopped", "ended", "error", "interrupted"}:
                worker = session.worker
                if worker is None or not worker.is_alive():
                    # Retain terminal sessions for inspection until capacity is
                    # needed; a new capture then reclaims completed entries.
                    del self._sessions[session_id]


    def _protect_candidate_window_locked(
        self,
        session: CaptureSession,
        candidate: HighlightCandidate,
        indexed: list[Any],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        """Pin newly included segments while holding the candidate lifecycle lock."""
        records = select_segments_for_interval(
            indexed,
            window_start=window_start,
            window_end=window_end,
        )
        already_protected = {Path(path).resolve() for path in candidate.protected_segments}
        newly_included = [
            item.path for item in records
            if Path(item.path).resolve() not in already_protected
        ]
        if newly_included:
            additional = session.capture.protect_segments(newly_included)
            candidate.protected_segments.extend(additional)

    def trigger(
        self,
        *,
        provider: str,
        stream_id: str,
        triggered_at: datetime,
        pre_seconds: int = 45,
        post_seconds: int = 45,
        reason: str = "chat_trigger",
    ) -> dict[str, Any] | None:
        self.restore()
        if triggered_at.tzinfo is None or triggered_at.utcoffset() is None:
            raise ValueError("Trigger timestamp must be timezone-aware.")
        if not 0 <= pre_seconds <= 300 or not 0 <= post_seconds <= 300:
            raise ValueError("Highlight windows must be between 0 and 300 seconds.")

        trigger_utc = triggered_at.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        window_start = trigger_utc - timedelta(seconds=pre_seconds)
        window_end = trigger_utc + timedelta(seconds=post_seconds)

        with self._lock:
            session = next(
                (
                    item for item in self._sessions.values()
                    if item.provider.value == provider
                    and item.stream_id == stream_id
                    and item.status == "recording"
                ),
                None,
            )
            if session is None:
                log_event("candidate.trigger.ignored", level=logging.WARNING, provider=provider, outcome="no_active_capture", failure_code="no_active_capture")
                return None
            if session.config.retention_seconds < pre_seconds + post_seconds + session.config.segment_seconds:
                log_event("candidate.trigger.rejected", level=logging.WARNING, provider=provider, session_id=session.session_id, reason=reason, outcome="retention_too_short", failure_code="retention_too_short")
                raise ValueError("Increase rolling-buffer retention to cover the requested highlight window.")

            indexed = session.capture.read_segment_index()
            merge_gap = timedelta(seconds=session.config.segment_seconds)

            # Only merge candidates that have not been sealed for assembly. A
            # candidate remains mergeable through its pre-window plus one media
            # segment, allowing a later trigger's pre-window to overlap it.
            mergeable = []
            for existing in self._candidates.values():
                if (
                    existing.capture_session_id != session.session_id
                    or existing.status != "capturing"
                    or existing.window_start is None
                    or existing.window_end is None
                    or existing.merge_until is None
                    or now_utc > existing.merge_until
                ):
                    continue
                gap = max(
                    0.0,
                    (existing.window_start - window_end).total_seconds(),
                    (window_start - existing.window_end).total_seconds(),
                )
                if gap <= merge_gap.total_seconds():
                    merged_start = min(existing.window_start, window_start)
                    merged_end = max(existing.window_end, window_end)
                    merged_duration = (merged_end - merged_start).total_seconds()
                    # Use the configured rolling retention as a hard upper
                    # bound. Merging must not turn a bounded ring into an
                    # arbitrarily long pinned recording.
                    if merged_duration <= session.config.retention_seconds:
                        mergeable.append((gap, existing, merged_start, merged_end))

            if mergeable:
                _, candidate, merged_start, merged_end = min(
                    mergeable, key=lambda item: (item[0], item[1].triggered_at)
                )
                old_window_start = candidate.window_start
                old_window_end = candidate.window_end
                old_pre_seconds = candidate.pre_seconds
                old_post_seconds = candidate.post_seconds
                old_merge_until = candidate.merge_until
                old_trigger_count = candidate.trigger_count
                old_pin_count = len(candidate.protected_segments)
                # Pin the exact expanded union before publishing it. Pruning
                # uses the same RollingCapture lock, so newly included media
                # cannot disappear between selection and protection.
                self._protect_candidate_window_locked(
                    session, candidate, indexed, merged_start, merged_end
                )
                candidate.window_start = merged_start
                candidate.window_end = merged_end
                candidate.pre_seconds = max(
                    candidate.pre_seconds,
                    math.ceil((candidate.triggered_at.astimezone(timezone.utc) - merged_start).total_seconds()),
                )
                candidate.post_seconds = max(
                    candidate.post_seconds,
                    math.ceil((merged_end - candidate.triggered_at.astimezone(timezone.utc)).total_seconds()),
                )
                merge_pre_seconds = max(candidate.pre_seconds, pre_seconds)
                merge_grace = merge_pre_seconds + (
                    session.config.segment_seconds if merge_pre_seconds else 0
                )
                candidate.merge_until = max(
                    candidate.merge_until,
                    merged_end + timedelta(seconds=merge_grace),
                )
                candidate.trigger_count += 1
                try:
                    self._persist_locked(strict=True)
                except Exception:
                    candidate.window_start = old_window_start
                    candidate.window_end = old_window_end
                    candidate.pre_seconds = old_pre_seconds
                    candidate.post_seconds = old_post_seconds
                    candidate.merge_until = old_merge_until
                    candidate.trigger_count = old_trigger_count
                    new_pins = candidate.protected_segments[old_pin_count:]
                    del candidate.protected_segments[old_pin_count:]
                    session.capture.release_segments(new_pins)
                    raise
                log_event("candidate.trigger.merged", provider=provider, session_id=session.session_id, candidate_id=candidate.candidate_id, reason=reason, trigger_count=candidate.trigger_count)
                return candidate.snapshot()

            if len(self._candidates) >= MAX_HIGHLIGHT_CANDIDATES:
                raise ValueError("The highlight queue is full. Delete an existing candidate before creating another.")

            candidate_id = secrets.token_urlsafe(18)
            candidate = HighlightCandidate(
                candidate_id=candidate_id,
                capture_session_id=session.session_id,
                triggered_at=trigger_utc,
                pre_seconds=pre_seconds,
                post_seconds=post_seconds,
                reason=reason,
                window_start=window_start,
                window_end=window_end,
                merge_until=window_end + timedelta(
                    seconds=pre_seconds + (session.config.segment_seconds if pre_seconds else 0)
                ),
            )
            self._protect_candidate_window_locked(
                session, candidate, indexed, window_start, window_end
            )
            self._candidates[candidate_id] = candidate
            worker = threading.Thread(
                target=self._finish_candidate,
                args=(session, candidate),
                name=f"community-highlight-candidate-{candidate_id[:8]}",
                daemon=True,
            )
            candidate.worker = worker
            try:
                self._persist_locked(strict=True)
                worker.start()
            except Exception:
                self._candidates.pop(candidate_id, None)
                protected = list(candidate.protected_segments)
                candidate.protected_segments.clear()
                session.capture.release_segments(protected)
                self._persist_locked()
                raise
            log_event("candidate.created", provider=provider, session_id=session.session_id, candidate_id=candidate_id, reason=reason, segment_count=len(candidate.protected_segments))
            return candidate.snapshot()

    def _finish_candidate(
        self,
        session: CaptureSession,
        candidate: HighlightCandidate,
    ) -> None:
        try:
            log_event("candidate.assembly.waiting_for_window", provider=session.provider.value, session_id=session.session_id, candidate_id=candidate.candidate_id)
            flush_timeout = max(30, session.config.segment_seconds * 4)
            sealed_start = None
            sealed_end = None
            indexed = []
            while True:
                current_index = session.capture.read_segment_index()
                now = datetime.now(timezone.utc)
                with self._lock:
                    if candidate.status != "capturing":
                        return
                    window_start = candidate.window_start
                    window_end = candidate.window_end
                    merge_until = candidate.merge_until
                    if window_start is None or window_end is None or merge_until is None:
                        raise RollingCaptureError("The highlight window could not be resolved.")

                    self._protect_candidate_window_locked(
                        session, candidate, current_index, window_start, window_end
                    )
                    completed_end = 0.0
                    for item in current_index:
                        try:
                            completed_end = max(
                                completed_end,
                                segment_wall_interval(item)[1].timestamp(),
                            )
                        except (OSError, ValueError):
                            continue

                    window_complete = completed_end >= window_end.timestamp()
                    capture_stopped = session.stop_event.is_set()
                    if capture_stopped and not window_complete:
                        raise RollingCaptureError(
                            "The rolling capture stopped before the post-trigger window completed."
                        )
                    if window_complete and (capture_stopped or now >= merge_until):
                        # This state transition is the merge boundary. A new
                        # trigger can extend the window before this lock is
                        # acquired, but never while FFmpeg is assembling it.
                        candidate.status = "assembling"
                        self._persist_locked()
                        log_event("candidate.assembly.started", provider=session.provider.value, session_id=session.session_id, candidate_id=candidate.candidate_id, segment_count=len(current_index))
                        sealed_start = window_start
                        sealed_end = window_end
                        indexed = current_index
                        break
                    if (
                        not window_complete
                        and now.timestamp() >= window_end.timestamp() + flush_timeout
                    ):
                        raise RollingCaptureError(
                            "FFmpeg did not finalize a segment covering the post-trigger boundary in time."
                        )

                session.stop_event.wait(0.25)

            records = select_segments_for_interval(
                indexed,
                window_start=sealed_start,
                window_end=sealed_end,
            )
            validate_contiguous_interval(
                records,
                window_start=sealed_start,
                window_end=sealed_end,
            )
            output_path = session.config.output_dir / "highlights" / f"{candidate.candidate_id}.mp4"
            assemble_segments(records, output_path, ffmpeg_path=session.config.ffmpeg_path)
            # This measures the assembled file. It does not make the mtime-based
            # chat-to-media alignment or segment-boundary selection frame-accurate.
            actual_duration = probe_media_duration_seconds(
                output_path,
                ffmpeg_path=session.config.ffmpeg_path,
            )
            with self._lock:
                candidate.output_path = output_path
                candidate.segment_count = len(records)
                candidate.actual_duration_seconds = actual_duration
                candidate.status = "ready"
                # The preview must not become visible until its ready state is
                # durable. A crash after a best-effort write would restore this
                # completed MP4 as an interrupted assembly.
                self._persist_locked(strict=True)
            log_event("candidate.ready", provider=session.provider.value, session_id=session.session_id, candidate_id=candidate.candidate_id, segment_count=len(records))
        except StateStoreError as error:
            with self._lock:
                candidate.error = (
                    "The highlight video was created, but Clippy could not save its ready status. "
                    "It is unavailable until local storage is working again."
                )
                candidate.status = "error"
                self._persist_locked()
            log_event("candidate.ready_persist_failed", level=logging.ERROR, provider=session.provider.value, session_id=session.session_id, candidate_id=candidate.candidate_id, error_type=type(error).__name__)
        except (RollingCaptureError, ValueError, OSError) as error:
            with self._lock:
                candidate.error = str(error)
                candidate.status = "error"
                self._persist_locked()
            log_event("candidate.assembly.failed", level=logging.ERROR, provider=session.provider.value, session_id=session.session_id, candidate_id=candidate.candidate_id, error_type=type(error).__name__)
        except Exception as error:
            with self._lock:
                candidate.error = "Clippy could not finish this highlight. Check the capture and FFmpeg logs."
                candidate.status = "error"
                self._persist_locked()
            log_event("candidate.assembly.failed", level=logging.ERROR, provider=session.provider.value, session_id=session.session_id, candidate_id=candidate.candidate_id, error_type=type(error).__name__)
        finally:
            with self._lock:
                protected = list(candidate.protected_segments)
                candidate.protected_segments.clear()
            session.capture.release_segments(protected)
            self._cleanup_rolling_segments_if_finished(session)

    def list_candidates(self, capture_session_id: str | None = None) -> list[dict[str, Any]]:
        self.restore()
        with self._lock:
            items = list(self._candidates.values())
            if capture_session_id is not None:
                items = [item for item in items if item.capture_session_id == capture_session_id]
            return [item.snapshot() for item in items]


    def get_candidate_generation(self, candidate_id: str) -> dict[str, Any] | None:
        """Return durable generation/review state without exposing a media path."""
        self.restore()
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            return candidate.snapshot() if candidate is not None else None

    def _candidate_media_path_locked(self, candidate: HighlightCandidate) -> Path | None:
        if candidate.status != "ready" or candidate.review_status == "rejected" or candidate.output_path is None:
            return None
        try:
            root = self._output_root_path().resolve()
            expected_parent = root / candidate.capture_session_id / "highlights"
            expected_file = expected_parent / f"{candidate.candidate_id}.mp4"
            actual_file = Path(os.path.abspath(candidate.output_path))
            resolved_parent = expected_parent.resolve()
            if (
                actual_file == expected_file
                and expected_parent.is_dir()
                and not expected_parent.is_symlink()
                and resolved_parent == expected_parent
                and resolved_parent.is_relative_to(root)
                and not expected_file.is_symlink()
                and expected_file.is_file()
                and expected_file.resolve().parent == resolved_parent
                and expected_file.stat().st_size > 0
            ):
                return expected_file
        except OSError:
            return None
        return None

    def claim_candidate_generation(
        self, candidate_id: str, job_id: str
    ) -> tuple[dict[str, Any], Path | None, bool]:
        """Approve and atomically claim one normal Clippy job.

        Active/completed claims are idempotent. A failed attempt can be retried
        with a new job ID. Returns (snapshot, source_path, created).
        """
        self.restore()
        if not isinstance(job_id, str) or not _GENERATION_JOB_ID_RE.fullmatch(job_id):
            raise ValueError("The generation job identifier is invalid.")
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise KeyError("Highlight candidate not found.")
            if candidate.status != "ready":
                raise ValueError("Only completed highlight candidates can be generated.")
            if candidate.review_status == "rejected":
                raise ValueError("Rejected highlight candidates cannot be generated.")
            if candidate.generation_job_id and candidate.generation_status in {
                "staging", "queued", "processing", "completed"
            }:
                return candidate.snapshot(), None, False

            media_path = self._candidate_media_path_locked(candidate)
            if media_path is None:
                raise ValueError("The highlight MP4 is missing or failed its storage safety check.")

            previous = (
                candidate.review_status,
                candidate.generation_status,
                candidate.generation_job_id,
                candidate.generation_error,
            )
            candidate.review_status = "approved"
            candidate.generation_status = "staging"
            candidate.generation_job_id = job_id
            candidate.generation_error = None
            try:
                self._persist_locked(strict=True)
            except Exception:
                (
                    candidate.review_status,
                    candidate.generation_status,
                    candidate.generation_job_id,
                    candidate.generation_error,
                ) = previous
                raise

            log_event("generation.claimed", candidate_id=candidate_id, job_id=job_id, outcome="staging")
            return candidate.snapshot(), media_path, True

    def update_candidate_generation(
        self,
        candidate_id: str,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist a generation transition only for the candidate's claimed job."""
        if status not in _GENERATION_STATES - {"not_started"}:
            raise ValueError("The candidate generation status is invalid.")
        self.restore()
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None or candidate.generation_job_id != job_id:
                return None
            if candidate.generation_status == "completed" and status != "completed":
                log_event(
                    "generation.status.stale_transition_ignored",
                    level=logging.WARNING,
                    candidate_id=candidate_id,
                    job_id=job_id,
                    current_status="completed",
                    requested_status=status,
                )
                return candidate.snapshot()
            previous = (candidate.generation_status, candidate.generation_error)
            candidate.generation_status = status
            candidate.generation_error = (
                error.replace("\r", "").replace("\n", " ")[:500]
                if isinstance(error, str) and error else None
            )
            try:
                self._persist_locked(strict=True)
            except Exception:
                candidate.generation_status, candidate.generation_error = previous
                raise
            log_event(
                "generation.status",
                candidate_id=candidate_id,
                job_id=job_id,
                status=status,
                error_type="GenerationError" if error else None,
            )
            return candidate.snapshot()

    def decide_candidate(self, candidate_id: str, *, approved: bool) -> dict[str, Any] | None:
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return None
            if candidate.status != "ready":
                raise ValueError("Only completed highlight candidates can be reviewed.")
            if candidate.review_status == "rejected" and approved:
                raise ValueError("Rejected candidate media has been deleted and cannot be re-approved.")
            if not approved and candidate.generation_status in {"staging", "queued", "processing"}:
                raise ValueError("A candidate cannot be rejected while its generation job is active.")
            previous_review_status = candidate.review_status
            candidate.review_status = "approved" if approved else "rejected"
            try:
                # Commit the user decision before destructive media cleanup.
                # A failed state write must never delete media while leaving a
                # stale pending decision on disk.
                self._persist_locked(strict=True)
            except Exception:
                candidate.review_status = previous_review_status
                raise

            log_event("candidate.reviewed", candidate_id=candidate_id, outcome="approved" if approved else "rejected")
            if not approved and candidate.output_path is not None:
                try:
                    candidate.output_path.unlink(missing_ok=True)
                    candidate.output_path = None
                except OSError:
                    candidate.error = "Rejected, but Windows could not remove the file because it is still in use."
                self._persist_locked()
            return candidate.snapshot()

    def delete_candidate(self, candidate_id: str) -> bool:
        """Delete a completed candidate using a recoverable same-directory rename.

        Stage the media under a hidden pending-delete name, commit metadata
        removal, then unlink the staged file. Startup can distinguish a rename
        whose metadata commit failed from a deletion whose final unlink failed.
        """
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return False
            if candidate.status in {"capturing", "assembling"} or (
                candidate.worker is not None and candidate.worker.is_alive()
            ) or candidate.generation_status in {"staging", "queued", "processing"}:
                raise ValueError("This highlight is still being created. Try deleting it when processing finishes.")

            pending_path: Path | None = None
            output_path = candidate.output_path
            if output_path is not None:
                root = self._output_root_path().resolve()
                expected_parent = root / candidate.capture_session_id / "highlights"
                expected_file = expected_parent / f"{candidate.candidate_id}.mp4"
                pending_path = expected_parent / f".{candidate.candidate_id}.delete-pending.mp4"
                actual_file = Path(os.path.abspath(output_path))
                resolved_parent = expected_parent.resolve()
                if actual_file not in {expected_file, pending_path} or not resolved_parent.is_relative_to(root):
                    raise RuntimeError("Candidate output path failed its storage-boundary check.")
                if resolved_parent != expected_parent or expected_parent.is_symlink():
                    raise RuntimeError("Candidate output directory is not a trusted directory.")
                if output_path.is_symlink() or pending_path.is_symlink():
                    raise RuntimeError("Candidate output path failed its storage-boundary check.")
                if output_path.exists() and not output_path.is_file():
                    raise RuntimeError("Candidate output path is not a regular file.")
                if pending_path.exists() and not pending_path.is_file():
                    raise RuntimeError("Pending candidate deletion path is not a regular file.")

                if actual_file == expected_file:
                    if pending_path.exists():
                        if expected_file.exists() or expected_file.is_symlink():
                            raise RuntimeError("A pending candidate deletion already exists.")
                        # A previous rollback could not restore the original
                        # name. Reuse its staged file and complete the retry.
                    elif output_path.exists():
                        # Same-directory replace is atomic. If Windows refuses
                        # it because the preview is open, metadata is untouched.
                        output_path.replace(pending_path)
                elif expected_file.exists() or expected_file.is_symlink():
                    raise RuntimeError("A pending candidate deletion conflicts with the original media path.")

            del self._candidates[candidate_id]
            try:
                self._persist_locked(strict=True)
            except Exception:
                self._candidates[candidate_id] = candidate
                if (
                    pending_path is not None
                    and pending_path.exists()
                    and not (root / candidate.capture_session_id / "highlights" / f"{candidate.candidate_id}.mp4").exists()
                ):
                    try:
                        pending_path.replace(root / candidate.capture_session_id / "highlights" / f"{candidate.candidate_id}.mp4")
                    except OSError as rollback_error:
                        _LOG.warning(
                            "Candidate media rename rollback is pending (error_type=%s)",
                            type(rollback_error).__name__,
                        )
                raise

            if pending_path is not None and pending_path.exists():
                try:
                    pending_path.unlink(missing_ok=True)
                except OSError as error:
                    # The candidate is already durably removed. Leave only the
                    # hidden tombstone; startup retries this final unlink.
                    _LOG.warning(
                        "A committed Community Highlights deletion needs filesystem cleanup (error_type=%s)",
                        type(error).__name__,
                    )
            log_event("candidate.deleted", candidate_id=candidate_id)
            return True

    def get_candidate(self, candidate_id: str) -> tuple[dict[str, Any], Path | None] | None:
        self.restore()
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return None

            return candidate.snapshot(), self._candidate_media_path_locked(candidate)

    async def stop(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.status == "interrupted":
                session.status = "stopped"
                self._persist_locked()
            elif session.status not in {"stopped", "ended", "error"}:
                session.status = "stopping"
                session.stop_event.set()
                self._persist_locked()
                request_stop = getattr(session.capture, "request_stop", None)
                if callable(request_stop):
                    request_stop()
            worker = session.worker
            candidate_workers = [
                item.worker for item in self._candidates.values()
                if item.capture_session_id == session_id and item.worker and item.worker.is_alive()
            ]

        if worker and worker.is_alive():
            await asyncio.to_thread(worker.join, STOP_JOIN_SECONDS)
        if candidate_workers:
            await asyncio.gather(
                *(asyncio.to_thread(item.join, STOP_JOIN_SECONDS) for item in candidate_workers)
            )
        with self._lock:
            if worker and worker.is_alive():
                session.status = "error"
                session.error = "Capture did not stop within the shutdown timeout."
            elif session.status == "stopping":
                session.status = "stopped"
            self._persist_locked()
        self._cleanup_rolling_segments_if_finished(session)
        return True

    async def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            for session in sessions:
                if session.status not in {"stopped", "ended", "error", "interrupted"}:
                    session.status = "stopping"
                    session.stop_event.set()
                    self._persist_locked()
                    request_stop = getattr(session.capture, "request_stop", None)
                    if callable(request_stop):
                        request_stop()
        workers = [s.worker for s in sessions if s.worker and s.worker.is_alive()]
        candidate_workers = [
            item.worker for item in self._candidates.values()
            if item.worker and item.worker.is_alive()
        ]
        all_workers = [*workers, *candidate_workers]
        if all_workers:
            await asyncio.gather(
                *(asyncio.to_thread(worker.join, STOP_JOIN_SECONDS) for worker in all_workers)
            )
        with self._lock:
            for session in sessions:
                if session.worker and session.worker.is_alive():
                    session.status = "error"
                    session.error = "Capture did not stop within the shutdown timeout."
                elif session.status == "stopping":
                    session.status = "stopped"
            self._persist_locked()
        for session in sessions:
            self._cleanup_rolling_segments_if_finished(session)


capture_sessions = CaptureSessionManager()
