"""Safe, timestamped Community Highlights diagnostics."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

_LOG = logging.getLogger("clippy.community_highlights")
_ID_FIELDS = {
    "candidate_id", "session_id", "job_id", "flow_id",
    "stream_id", "channel_id", "user_id", "account_id",
}
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SAFE_STRING_FIELDS = {
    "provider", "outcome", "status", "reason", "method", "route",
    "error_type", "quality", "phase", "failure_code", "ffmpeg_detail",
}
_SAFE_REASONS = {"phrase", "chat_volume", "manual", "chat_trigger"}
_SAFE_FAILURE_CODES = {
    "candidate_queue_full", "capture_io_error", "capture_storage_error",
    "capture_window_unavailable", "codec_error", "ffmpeg_unknown",
    "invalid_data", "invalid_trigger", "io_error", "muxer_error",
    "no_active_capture", "output_missing", "process_start_failed",
    "protected_buffer_limit", "retention_too_short", "segment_error",
    "state_store_error", "timestamp_error", "unexpected_error",
}
_URL_RE = re.compile(r"(?i)\b(?:https?|rtmps?|file)://[^\s'\"<>]+")
_SECRET_RE = re.compile(
    r"(?i)\b(?:authorization|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|api[_-]?key|password)\b\s*[:=]\s*"
    r"(?:bearer\s+)?[^\s,;]+|\bbearer\s+[A-Za-z0-9._~+/=-]+"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:[\\/]|\\\\)[^'\"<>|\r\n]+")
_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9:])/(?:[^\s'\"<>]+)")
_UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)
_LONG_HEX_RE = re.compile(r"(?i)\b[0-9a-f]{24,}\b")
_SAFE_DETAIL_CHARS = re.compile(r"[^A-Za-z0-9 .,:;_+()/#=\[\]-]")


def _sanitize_ffmpeg_detail(value: Any) -> str | None:
    """Keep useful FFmpeg error wording while stripping paths, URLs and secrets."""
    if not isinstance(value, str):
        return None
    cleaned = _SECRET_RE.sub("[redacted]", value)
    cleaned = _URL_RE.sub("[url]", cleaned)
    cleaned = _WINDOWS_PATH_RE.sub("[path]", cleaned)
    cleaned = _POSIX_PATH_RE.sub("[path]", cleaned)
    cleaned = _UUID_RE.sub("[id]", cleaned)
    cleaned = _LONG_HEX_RE.sub("[id]", cleaned)
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = _SAFE_DETAIL_CHARS.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned[:360] or None


def summarize_ffmpeg_stderr(stderr: bytes | str | None) -> dict[str, str]:
    """Return a stable failure class and a small, redacted tail excerpt."""
    if not stderr:
        return {"failure_code": "ffmpeg_unknown"}
    if isinstance(stderr, bytes):
        text = stderr[-4096:].decode("utf-8", "replace")
    else:
        text = str(stderr)[-4096:]
    lowered = text.lower()

    if any(term in lowered for term in ("invalid data found", "moov atom not found", "corrupt input")):
        code = "invalid_data"
    elif any(term in lowered for term in (
        "non-monotonous", "invalid pts", "invalid dts", "invalid timestamp", "timestamp discontinuity",
    )):
        code = "timestamp_error"
    elif any(term in lowered for term in (
        "could not write header", "error writing trailer", "muxer does not support",
        "could not write trailer",
    )):
        code = "muxer_error"
    elif any(term in lowered for term in (
        "unknown decoder", "decoder not found", "codec not found", "codec is not supported",
        "unsupported codec", "no decoder",
    )):
        code = "codec_error"
    elif "segment" in lowered and any(term in lowered for term in ("error", "failed", "invalid")):
        code = "segment_error"
    elif any(term in lowered for term in (
        "no such file or directory", "permission denied", "i/o error", "error opening input",
        "broken pipe", "input/output error",
    )):
        code = "io_error"
    else:
        code = "ffmpeg_unknown"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    detail_hints = {
        "invalid_data": ("invalid data found", "moov atom not found", "corrupt input"),
        "timestamp_error": (
            "non-monotonous", "invalid pts", "invalid dts",
            "invalid timestamp", "timestamp discontinuity",
        ),
        "muxer_error": (
            "could not write header", "error writing trailer",
            "muxer does not support", "could not write trailer",
        ),
        "codec_error": (
            "unknown decoder", "decoder not found", "codec not found",
            "codec is not supported", "unsupported codec", "no decoder",
        ),
        "segment_error": ("segment",),
        "io_error": (
            "no such file or directory", "permission denied", "i/o error",
            "error opening input", "broken pipe", "input/output error",
        ),
    }
    hints = detail_hints.get(code, ())
    relevant_lines = [
        line for line in lines
        if any(hint in line.lower() for hint in hints)
    ]
    # Keep the lines that explain the classified failure ahead of trailing
    # path/cleanup noise. Fall back to the last lines for unknown diagnostics.
    selected_lines = (relevant_lines or lines[-3:])[:3]
    excerpts = [
        detail for line in selected_lines
        if (detail := _sanitize_ffmpeg_detail(line)) is not None
    ]
    fields = {"failure_code": code}
    if excerpts:
        fields["ffmpeg_detail"] = " | ".join(excerpts)[-360:]
    return fields


class BoundedStderrTail:
    """Drain a child stderr pipe without blocking it, retaining only its last 4 KiB."""

    def __init__(self, stream: Any, *, max_bytes: int = 4096) -> None:
        self._stream = stream
        self._max_bytes = max(1, min(int(max_bytes), 16384))
        self._tail = bytearray()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        if stream is not None:
            self._thread = threading.Thread(
                target=self._drain,
                name="community-highlights-stderr",
                daemon=True,
            )
            self._thread.start()

    def _drain(self) -> None:
        try:
            while True:
                chunk = self._stream.read(1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", "replace")
                if not isinstance(chunk, bytes):
                    continue
                with self._lock:
                    self._tail.extend(chunk)
                    excess = len(self._tail) - self._max_bytes
                    if excess > 0:
                        del self._tail[:excess]
        except (OSError, ValueError):
            return

    def diagnostic_fields(self) -> dict[str, str]:
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            tail = bytes(self._tail)
        return summarize_ffmpeg_stderr(tail)


def _safe_value(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _ID_FIELDS:
        return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()[:12]
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, str):
        if name not in _SAFE_STRING_FIELDS:
            return None
        if name == "reason" and value not in _SAFE_REASONS:
            return None
        if name == "failure_code" and value not in _SAFE_FAILURE_CODES:
            return None
        if name == "ffmpeg_detail":
            return _sanitize_ffmpeg_detail(value)
        if name == "route" and not value.startswith("/api/community-highlights/"):
            return None
        return value.replace("\r", "").replace("\n", " ")[:120]
    return None


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Write one JSON event with an explicit UTC timestamp and redacted refs."""
    safe: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": re.sub(r"[^a-z0-9_.-]", "_", str(event).lower())[:80],
    }
    for name, value in fields.items():
        if not _FIELD_RE.fullmatch(name):
            continue
        cleaned = _safe_value(name, value)
        if cleaned is not None:
            safe[name + "_ref" if name in _ID_FIELDS else name] = cleaned
    _LOG.log(level, "community_highlights %s", json.dumps(safe, sort_keys=True, separators=(",", ":")))
