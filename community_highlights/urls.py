"""Strict parsing of supported Twitch and YouTube live/video URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import ChatProvider, StreamReference


_TWITCH_CHANNEL = re.compile(r"^[A-Za-z0-9_]{1,25}$")
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class StreamUrlError(ValueError):
    """The supplied URL is not a supported Twitch or YouTube stream URL."""


def parse_stream_url(url: str) -> StreamReference:
    if not isinstance(url, str) or not url.strip():
        raise StreamUrlError("Paste a Twitch or YouTube stream URL.")

    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:
        raise StreamUrlError("The stream URL is malformed.") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise StreamUrlError("Use a full https:// Twitch or YouTube URL.")

    host = parsed.hostname.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]

    if host in {"twitch.tv", "m.twitch.tv"}:
        if len(parts) != 1 or not _TWITCH_CHANNEL.fullmatch(parts[0]):
            raise StreamUrlError("Use a Twitch channel URL, such as https://www.twitch.tv/channel.")
        reserved = {"directory", "downloads", "jobs", "p", "settings", "turbo", "wallet"}
        if parts[0].lower() in reserved:
            raise StreamUrlError("That Twitch URL is not a channel page.")
        return StreamReference(ChatProvider.TWITCH, parts[0].lower())

    if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
        video_id = None
        if host == "youtu.be":
            video_id = parts[0] if len(parts) == 1 else None
        elif parts and parts[0] in {"live", "watch", "shorts", "embed"}:
            if parts[0] == "watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            elif len(parts) == 2:
                video_id = parts[1]
        if not video_id or not _YOUTUBE_ID.fullmatch(video_id):
            raise StreamUrlError("Use a YouTube live or video URL, not a channel or playlist URL.")
        return StreamReference(ChatProvider.YOUTUBE, video_id)

    raise StreamUrlError("Only Twitch and YouTube URLs are supported.")
