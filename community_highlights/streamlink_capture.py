"""Streamlink URL resolution for the Community Highlights capture pipeline.

Resolution is synchronous and must be called from a worker thread by async
callers. The returned stream keeps its Streamlink session alive until closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .models import ChatProvider
from .urls import parse_stream_url
from .diagnostics import log_event


_QUALITY = re.compile(r"^(?:best|worst|audio_only|\d{3,4}p\d*)$", re.IGNORECASE)


class StreamResolutionError(RuntimeError):
    """A live stream could not be resolved into a readable media stream."""


@dataclass
class ResolvedLiveStream:
    """An opened-on-demand Streamlink stream and the session that owns it."""

    session: Any
    stream: Any
    quality: str

    def open(self):
        """Open the selected media stream. This may perform blocking I/O."""
        try:
            return self.stream.open()
        except Exception as error:
            log_event("stream.open.failed", level=40, error_type=type(error).__name__)
            raise StreamResolutionError(
                "Clippy could not open the selected live stream. Check that it is live and try again."
            ) from None


def _canonical_stream_url(url: str) -> tuple[str, str]:
    reference = parse_stream_url(url)
    if reference.provider is ChatProvider.TWITCH:
        return f"https://www.twitch.tv/{reference.stream_id}", reference.provider.value
    return f"https://www.youtube.com/watch?v={reference.stream_id}", reference.provider.value


def resolve_live_stream(
    url: str,
    *,
    quality: str = "best",
    session_factory: Callable[[], Any] | None = None,
) -> ResolvedLiveStream:
    """Resolve a supported Twitch/YouTube URL using Streamlink's Python API.

    Only the normalized provider URL is passed to Streamlink. Query strings,
    fragments, credentials, and other user-supplied URL decorations are not
    forwarded to the provider plugin.
    """
    canonical_url, _provider = _canonical_stream_url(url)
    requested_quality = quality.strip().lower() if isinstance(quality, str) else ""
    if not _QUALITY.fullmatch(requested_quality):
        raise StreamResolutionError("Choose a supported stream quality.")

    log_event("stream.resolve.started", provider=_provider, quality=requested_quality)
    try:
        if session_factory is None:
            from streamlink import Streamlink

            session_factory = Streamlink
        session = session_factory()
        session.set_option("stream-timeout", 30)
        streams = session.streams(canonical_url)
    except ImportError:
        raise StreamResolutionError(
            "Live capture requires the Streamlink runtime dependency."
        ) from None
    except Exception as error:
        log_event("stream.resolve.failed", level=40, provider=_provider, error_type=type(error).__name__)
        raise StreamResolutionError(
            "Clippy could not resolve this live stream. Confirm the URL is live and supported."
        ) from None

    if not isinstance(streams, dict) or not streams:
        raise StreamResolutionError("No playable stream qualities were found.")

    selected = streams.get(requested_quality)
    if selected is None:
        raise StreamResolutionError(
            f"The requested stream quality ({requested_quality}) is not available."
        )
    log_event("stream.resolve.ready", provider=_provider, quality=requested_quality)
    return ResolvedLiveStream(session=session, stream=selected, quality=requested_quality)
