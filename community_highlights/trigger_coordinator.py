"""Bridge normalized chat events into capture-window requests."""
from __future__ import annotations

import threading
from typing import Any

from .capture_sessions import capture_sessions
from .models import ChatMessage
from .triggers import TriggerEngine, TriggerRule


class TriggerCoordinator:
    def __init__(self, capture_manager=capture_sessions) -> None:
        self._capture_manager = capture_manager
        self._lock = threading.RLock()
        self._phrases = ("clip it", "clip that")
        self._min_messages = 12
        self._min_unique_users = 5
        self._window_seconds = 10.0
        self._cooldown_seconds = 60.0
        self._pre_seconds = 45
        self._post_seconds = 45
        self._engine = self._build_engine()

    def _build_engine(self) -> TriggerEngine:
        return TriggerEngine([
            TriggerRule(
                rule_id="community-default",
                phrases=self._phrases,
                min_messages=self._min_messages,
                min_unique_users=self._min_unique_users,
                window_seconds=self._window_seconds,
                cooldown_seconds=self._cooldown_seconds,
            )
        ])

    def settings(self) -> dict[str, Any]:
        with self._lock:
            return {
                "phrases": list(self._phrases),
                "min_messages": self._min_messages,
                "min_unique_users": self._min_unique_users,
                "window_seconds": self._window_seconds,
                "cooldown_seconds": self._cooldown_seconds,
                "pre_seconds": self._pre_seconds,
                "post_seconds": self._post_seconds,
            }

    def configure(
        self,
        *,
        phrases: list[str],
        min_messages: int,
        min_unique_users: int,
        window_seconds: float,
        cooldown_seconds: float,
        pre_seconds: int,
        post_seconds: int,
    ) -> dict[str, Any]:
        normalized = tuple(dict.fromkeys(
            phrase.strip() for phrase in phrases
            if isinstance(phrase, str) and phrase.strip()
        ))
        if len(normalized) > 30 or any(len(phrase) > 80 for phrase in normalized):
            raise ValueError("Use at most 30 trigger phrases, each no longer than 80 characters.")
        if min_messages < 2 or min_messages > 500:
            raise ValueError("Message threshold must be between 2 and 500.")
        if min_unique_users < 1 or min_unique_users > min_messages:
            raise ValueError("Unique-user threshold must be between 1 and the message threshold.")
        if not 1 <= window_seconds <= 120 or not 0 <= cooldown_seconds <= 3600:
            raise ValueError("Trigger window must be 1-120 seconds and cooldown 0-3600 seconds.")
        if not 0 <= pre_seconds <= 300 or not 0 <= post_seconds <= 300:
            raise ValueError("Highlight windows must be between 0 and 300 seconds.")
        if not normalized and min_messages < 2:
            raise ValueError("Configure at least one phrase or a message threshold.")
        with self._lock:
            self._phrases = normalized
            self._min_messages = min_messages
            self._min_unique_users = min_unique_users
            self._window_seconds = window_seconds
            self._cooldown_seconds = cooldown_seconds
            self._pre_seconds = pre_seconds
            self._post_seconds = post_seconds
            self._engine = self._build_engine()
        return self.settings()

    def on_message(self, message: ChatMessage) -> None:
        with self._lock:
            matches = self._engine.add(message)
            pre_seconds = self._pre_seconds
            post_seconds = self._post_seconds
        for match in matches:
            try:
                self._capture_manager.trigger(
                    provider=match.provider,
                    stream_id=match.stream_id,
                    triggered_at=match.triggered_at,
                    pre_seconds=pre_seconds,
                    post_seconds=post_seconds,
                    reason=match.reason,
                )
            except ValueError:
                # Keep chat transport alive; an undersized buffer is surfaced
                # through capture/candidate diagnostics rather than dropping chat.
                continue


trigger_coordinator = TriggerCoordinator()
