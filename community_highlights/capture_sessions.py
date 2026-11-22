"""Supervised lifecycle for Streamlink/FFmpeg rolling captures.

Capture workers own their blocking Streamlink and FFmpeg resources. The manager
owns worker threads, immutable per-session configuration snapshots, and safe
status reporting to the API.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import ChatProvider
from .rolling_capture import RollingCapture, RollingCaptureConfig, RollingCaptureError
from .extraction import assemble_segments
from .timeline import segment_wall_interval, select_segments_for_window, validate_contiguous_window
from .urls import parse_stream_url


MAX_CAPTURE_SESSIONS = 2
STOP_JOIN_SECONDS = 45
MAX_HIGHLIGHT_CANDIDATES = 20


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

    def snapshot(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "capture_session_id": self.capture_session_id,
            "triggered_at": self.triggered_at.isoformat(),
            "pre_seconds": self.pre_seconds,
            "post_seconds": self.post_seconds,
            "reason": self.reason,
            "status": self.status,
            "review_status": self.review_status,
            "error": self.error,
            "file_name": self.output_path.name if self.output_path else None,
            "segment_count": self.segment_count,
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
    ) -> None:
        if not isinstance(max_sessions, int) or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer.")
        self._capture_factory = capture_factory
        self._output_root = output_root or Path(
            os.environ.get("CLIPPY_DATA_DIR", os.environ.get("OUTPUT_DIR", "output"))
        ) / "community-highlights"
        self._max_sessions = max_sessions
        self._sessions: dict[str, CaptureSession] = {}
        self._candidates: dict[str, HighlightCandidate] = {}
        self._lock = threading.RLock()

    def start(
        self, stream_url: str, settings: CaptureSettings | None = None
    ) -> dict[str, Any]:
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
                return existing.snapshot()
            if len(self._sessions) >= self._max_sessions:
                raise ValueError(f"Clippy can record up to {self._max_sessions} live streams at a time.")

            session_id = secrets.token_urlsafe(18)
            output_dir = (self._output_root / session_id).resolve()
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
                worker.start()
            except Exception:
                self._sessions.pop(session_id, None)
                raise
            return session.snapshot()

    def _run(self, session: CaptureSession) -> None:
        try:
            def mark_recording() -> None:
                with self._lock:
                    if not session.stop_event.is_set():
                        session.status = "recording"

            session.capture.run(session.stop_event, on_started=mark_recording)
            with self._lock:
                session.status = "stopped" if session.stop_event.is_set() else "ended"
        except RollingCaptureError as error:
            with self._lock:
                session.error = str(error)
                session.status = "error"
        except Exception:
            with self._lock:
                session.error = "Live capture failed unexpectedly. Check the stream and FFmpeg installation."
                session.status = "error"

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.snapshot() if session else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [session.snapshot() for session in self._sessions.values()]

    def _prune_finished_locked(self) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.status in {"stopped", "ended", "error"}:
                worker = session.worker
                if worker is None or not worker.is_alive():
                    # Retain terminal sessions for inspection until capacity is
                    # needed; a new capture then reclaims completed entries.
                    del self._sessions[session_id]


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
        if triggered_at.tzinfo is None or triggered_at.utcoffset() is None:
            raise ValueError("Trigger timestamp must be timezone-aware.")
        if not 0 <= pre_seconds <= 300 or not 0 <= post_seconds <= 300:
            raise ValueError("Highlight windows must be between 0 and 300 seconds.")
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
                return None
            if session.config.retention_seconds < pre_seconds + post_seconds + session.config.segment_seconds:
                raise ValueError("Increase rolling-buffer retention to cover the requested highlight window.")
            candidate_id = secrets.token_urlsafe(18)
            candidate = HighlightCandidate(
                candidate_id=candidate_id,
                capture_session_id=session.session_id,
                triggered_at=triggered_at,
                pre_seconds=pre_seconds,
                post_seconds=post_seconds,
                reason=reason,
            )
            if len(self._candidates) >= MAX_HIGHLIGHT_CANDIDATES:
                raise ValueError("The highlight queue is full. Delete an existing candidate before creating another.")
            pre_records = select_segments_for_window(
                session.capture.read_segment_index(),
                triggered_at=triggered_at,
                pre_seconds=pre_seconds,
                post_seconds=0,
            )
            protected = session.capture.protect_segments([item.path for item in pre_records])
            self._candidates[candidate_id] = candidate
            worker = threading.Thread(
                target=self._finish_candidate,
                args=(session, candidate, protected),
                name=f"community-highlight-candidate-{candidate_id[:8]}",
                daemon=True,
            )
            candidate.worker = worker
            try:
                worker.start()
            except Exception:
                self._candidates.pop(candidate_id, None)
                session.capture.release_segments(protected)
                raise
            return candidate.snapshot()

    def _finish_candidate(
        self,
        session: CaptureSession,
        candidate: HighlightCandidate,
        protected: list[Path],
    ) -> None:
        try:
            post_deadline = candidate.triggered_at.astimezone(timezone.utc).timestamp() + candidate.post_seconds
            flush_timeout = max(30, session.config.segment_seconds * 4)
            flush_deadline = post_deadline + flush_timeout
            while True:
                remaining = max(0.0, post_deadline - datetime.now(timezone.utc).timestamp())
                if remaining > 0 and session.stop_event.wait(min(remaining, 0.5)):
                    raise RollingCaptureError("The rolling capture stopped before the post-trigger window completed.")
                indexed = session.capture.read_segment_index()
                completed_end = 0.0
                for item in indexed:
                    try:
                        completed_end = max(completed_end, segment_wall_interval(item)[1].timestamp())
                    except (OSError, ValueError):
                        continue
                if completed_end >= post_deadline:
                    break
                if session.stop_event.is_set():
                    raise RollingCaptureError("The rolling capture stopped before the post-trigger window completed.")
                if datetime.now(timezone.utc).timestamp() >= flush_deadline:
                    raise RollingCaptureError("FFmpeg did not finalize a segment covering the post-trigger boundary in time.")
                session.stop_event.wait(0.25)

            records = select_segments_for_window(
                indexed,
                triggered_at=candidate.triggered_at,
                pre_seconds=candidate.pre_seconds,
                post_seconds=candidate.post_seconds,
            )
            already_protected = {Path(path).resolve() for path in protected}
            new_segments = [
                item.path for item in records
                if Path(item.path).resolve() not in already_protected
            ]
            additional = session.capture.protect_segments(new_segments) if new_segments else []
            protected = list(dict.fromkeys([*protected, *additional]))
            validate_contiguous_window(
                records,
                triggered_at=candidate.triggered_at,
                pre_seconds=candidate.pre_seconds,
                post_seconds=candidate.post_seconds,
            )
            output_path = session.config.output_dir / "highlights" / f"{candidate.candidate_id}.ts"
            assemble_segments(records, output_path, ffmpeg_path=session.config.ffmpeg_path)
            with self._lock:
                candidate.output_path = output_path
                candidate.segment_count = len(records)
                candidate.status = "ready"
        except (RollingCaptureError, ValueError, OSError) as error:
            with self._lock:
                candidate.error = str(error)
                candidate.status = "error"
        except Exception:
            with self._lock:
                candidate.error = "Clippy could not finish this highlight. Check the capture and FFmpeg logs."
                candidate.status = "error"
        finally:
            session.capture.release_segments(protected)

    def list_candidates(self, capture_session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._candidates.values())
            if capture_session_id is not None:
                items = [item for item in items if item.capture_session_id == capture_session_id]
            return [item.snapshot() for item in items]


    def decide_candidate(self, candidate_id: str, *, approved: bool) -> dict[str, Any] | None:
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return None
            if candidate.status != "ready":
                raise ValueError("Only completed highlight candidates can be reviewed.")
            if candidate.review_status == "rejected" and approved:
                raise ValueError("Rejected candidate media has been deleted and cannot be re-approved.")
            candidate.review_status = "approved" if approved else "rejected"
            if not approved and candidate.output_path is not None:
                try:
                    candidate.output_path.unlink(missing_ok=True)
                    candidate.output_path = None
                except OSError:
                    candidate.error = "Rejected, but Windows could not remove the file because it is still in use."
            return candidate.snapshot()

    def delete_candidate(self, candidate_id: str) -> bool:
        """Delete one completed candidate and its media on explicit user request.

        Candidate output paths are generated internally. Re-derive the only
        permitted location and verify its parent has not been redirected by a
        symlink before unlinking. Never remove a candidate while its worker is
        still writing or releasing capture segments.
        """
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return False
            if candidate.status == "capturing" or (
                candidate.worker is not None and candidate.worker.is_alive()
            ):
                raise ValueError("This highlight is still being created. Try deleting it when processing finishes.")

            output_path = candidate.output_path
            if output_path is not None:
                root = self._output_root.resolve()
                expected_parent = root / candidate.capture_session_id / "highlights"
                expected_file = expected_parent / f"{candidate.candidate_id}.ts"
                actual_file = Path(os.path.abspath(output_path))
                resolved_parent = expected_parent.resolve()
                if actual_file != expected_file or not resolved_parent.is_relative_to(root):
                    raise RuntimeError("Candidate output path failed its storage-boundary check.")
                if resolved_parent != expected_parent:
                    raise RuntimeError("Candidate output directory is not a trusted directory.")
                # If another process has the file open on Windows, unlink raises
                # and metadata remains available for a safe retry.
                output_path.unlink(missing_ok=True)

            del self._candidates[candidate_id]
            return True

    def get_candidate(self, candidate_id: str) -> tuple[dict[str, Any], Path | None] | None:
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                return None
            path = candidate.output_path if candidate.status == "ready" else None
            return candidate.snapshot(), path

    async def stop(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.status not in {"stopped", "ended", "error"}:
                session.status = "stopping"
                session.stop_event.set()
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
        return True

    async def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            for session in sessions:
                if session.status not in {"stopped", "ended", "error"}:
                    session.status = "stopping"
                    session.stop_event.set()
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


capture_sessions = CaptureSessionManager()
