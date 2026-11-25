"""Safe, timestamped Community Highlights diagnostics.

Only fixed event labels, bounded enum-like fields, exception types, and hashed
opaque references are written. Never pass credentials, chat text, URLs, or
raw provider/channel identifiers here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

_LOG = logging.getLogger("clippy.community_highlights")
_ID_FIELDS = {
    "candidate_id",
    "session_id",
    "job_id",
    "flow_id",
    "stream_id",
    "channel_id",
    "user_id",
    "account_id",
}
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SAFE_STRING_FIELDS = {"provider", "outcome", "status", "reason", "method", "route", "error_type", "quality", "phase"}
_SAFE_REASONS = {"phrase", "chat_volume", "manual", "chat_trigger"}


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
