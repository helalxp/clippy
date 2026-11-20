"""Provider-neutral data contracts for Community Highlights."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ChatProvider(str, Enum):
    TWITCH = "twitch"
    YOUTUBE = "youtube"


@dataclass(frozen=True, slots=True)
class StreamReference:
    provider: ChatProvider
    stream_id: str
    channel_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChatMessage:
    provider: ChatProvider
    stream_id: str
    message_id: str
    provider_timestamp: datetime
    received_at: datetime
    sender_id: str
    sender_name: str
    text: str

    def __post_init__(self) -> None:
        for field_name in ("stream_id", "message_id", "sender_id", "sender_name"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not isinstance(self.provider_timestamp, datetime):
            raise TypeError("provider_timestamp must be a datetime")
        if not isinstance(self.received_at, datetime):
            raise TypeError("received_at must be a datetime")
        if self.provider_timestamp.tzinfo is None or self.provider_timestamp.utcoffset() is None:
            raise ValueError("provider_timestamp must be timezone-aware")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")

    @classmethod
    def now_received(
        cls,
        *,
        provider: ChatProvider,
        stream_id: str,
        message_id: str,
        provider_timestamp: datetime,
        sender_id: str,
        sender_name: str,
        text: str,
    ) -> "ChatMessage":
        return cls(
            provider=provider,
            stream_id=stream_id,
            message_id=message_id,
            provider_timestamp=provider_timestamp,
            received_at=datetime.now(timezone.utc),
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
        )
