"""Supervised lifecycle for Streamlink/FFmpeg rolling captures.

Capture workers own their blocking Streamlink and FFmpeg resources. The manager
owns worker threads, immutable per-session configuration snapshots, and safe
status reporting to the API.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import ChatProvider
from .rolling_capture import RollingCapture, RollingCaptureConfig, RollingCaptureError
from .urls import parse_stream_url


MAX_CAPTURE_SESSIONS = 2
STOP_JOIN_SECONDS = 12


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
        return config


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
        self._lock = threading.RLock()

    def start(
        self, stream_url: str, settings: CaptureSettings | None = None
    ) -> dict[str, Any]:
        reference = parse_stream_url(stream_url)
        settings = settings or CaptureSettings()
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
        with self._lock:
            self._prune_finished_locked()
            if len(self._sessions) >= self._max_sessions:
                raise ValueError(f"Clippy can record up to {self._max_sessions} live streams at a time.")
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
            session.status = "recording"
            session.capture.run(session.stop_event)
            if session.stop_event.is_set():
                session.status = "stopped"
            else:
                session.status = "ended"
        except RollingCaptureError as error:
            session.error = str(error)
            session.status = "error"
        except Exception:
            session.error = "Live capture failed unexpectedly. Check the stream and FFmpeg installation."
            session.status = "error"

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.snapshot() if session else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_finished_locked()
            return [session.snapshot() for session in self._sessions.values()]

    def _prune_finished_locked(self) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.status in {"stopped", "ended", "error"}:
                worker = session.worker
                if worker is None or not worker.is_alive():
                    # Retain terminal sessions for inspection until capacity is
                    # needed; a new capture then reclaims completed entries.
                    del self._sessions[session_id]

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

        if worker and worker.is_alive():
            await asyncio.to_thread(worker.join, STOP_JOIN_SECONDS)
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
        if workers:
            await asyncio.gather(
                *(asyncio.to_thread(worker.join, STOP_JOIN_SECONDS) for worker in workers)
            )
        with self._lock:
            for session in sessions:
                if session.worker and session.worker.is_alive():
                    session.status = "error"
                    session.error = "Capture did not stop within the shutdown timeout."
                elif session.status == "stopping":
                    session.status = "stopped"


capture_sessions = CaptureSessionManager()
