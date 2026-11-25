"""Bridge normalized chat events into capture-window requests."""
from __future__ import annotations

import logging
import threading
from typing import Any

from .capture_sessions import capture_sessions
from .models import ChatMessage
from .state_store import get_state_store
from .diagnostics import log_event
from .triggers import TriggerEngine, TriggerRule


_LOG = logging.getLogger(__name__)


class TriggerCoordinator:
    def __init__(self, capture_manager=capture_sessions, *, state_store=None) -> None:
        self._capture_manager = capture_manager
        self._state_store = state_store
        self._uses_default_store = state_store is None and capture_manager is capture_sessions
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

    def _get_state_store(self):
        if self._state_store is not None:
            return self._state_store
        return get_state_store() if self._uses_default_store else None

    @staticmethod
    def _validate_settings(
        *,
        phrases: list[str],
        min_messages: int,
        min_unique_users: int,
        window_seconds: float,
        cooldown_seconds: float,
        pre_seconds: int,
        post_seconds: int,
    ) -> dict[str, Any]:
        if not isinstance(phrases, (list, tuple)):
            raise ValueError("Trigger phrases must be provided as a list.")
        normalized = tuple(dict.fromkeys(
            phrase.strip() for phrase in phrases
            if isinstance(phrase, str) and phrase.strip()
        ))
        if len(normalized) > 30 or any(len(phrase) > 80 for phrase in normalized):
            raise ValueError("Use at most 30 trigger phrases, each no longer than 80 characters.")
        if type(min_messages) is not int or not 2 <= min_messages <= 500:
            raise ValueError("Message threshold must be between 2 and 500.")
        if type(min_unique_users) is not int or not 1 <= min_unique_users <= min_messages:
            raise ValueError("Unique-user threshold must be between 1 and the message threshold.")
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, (int, float)):
            raise ValueError("Trigger window must be numeric.")
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)):
            raise ValueError("Cooldown must be numeric.")
        if not 1 <= window_seconds <= 120 or not 0 <= cooldown_seconds <= 3600:
            raise ValueError("Trigger window must be 1-120 seconds and cooldown 0-3600 seconds.")
        if type(pre_seconds) is not int or type(post_seconds) is not int:
            raise ValueError("Highlight windows must be whole numbers of seconds.")
        if not 0 <= pre_seconds <= 300 or not 0 <= post_seconds <= 300:
            raise ValueError("Highlight windows must be between 0 and 300 seconds.")
        return {
            "phrases": normalized,
            "min_messages": min_messages,
            "min_unique_users": min_unique_users,
            "window_seconds": float(window_seconds),
            "cooldown_seconds": float(cooldown_seconds),
            "pre_seconds": pre_seconds,
            "post_seconds": post_seconds,
        }

    def _apply_settings_locked(self, settings: dict[str, Any]) -> None:
        self._phrases = settings["phrases"]
        self._min_messages = settings["min_messages"]
        self._min_unique_users = settings["min_unique_users"]
        self._window_seconds = settings["window_seconds"]
        self._cooldown_seconds = settings["cooldown_seconds"]
        self._pre_seconds = settings["pre_seconds"]
        self._post_seconds = settings["post_seconds"]
        self._engine = self._build_engine()

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
        persist: bool = True,
    ) -> dict[str, Any]:
        settings = self._validate_settings(
            phrases=phrases,
            min_messages=min_messages,
            min_unique_users=min_unique_users,
            window_seconds=window_seconds,
            cooldown_seconds=cooldown_seconds,
            pre_seconds=pre_seconds,
            post_seconds=post_seconds,
        )
        with self._lock:
            store = self._get_state_store() if persist else None
            if store is not None:
                store.update_sections(trigger_settings={
                    **settings,
                    "phrases": list(settings["phrases"]),
                })
            self._apply_settings_locked(settings)
        log_event("trigger.settings.updated", phrase_count=len(settings["phrases"]), pre_seconds=settings["pre_seconds"], post_seconds=settings["post_seconds"])
        return self.settings()

    def restore(self) -> None:
        """Load validated trigger settings before the API begins accepting requests."""
        store = self._get_state_store()
        if store is None:
            return
        settings = store.read_section("trigger_settings")
        if settings is None:
            return
        if not isinstance(settings, dict):
            _LOG.warning("Stored Community Highlights trigger settings were invalid; defaults remain active.")
            log_event("trigger.settings.restore_failed", level=logging.WARNING, outcome="invalid_shape")
            return
        try:
            self.configure(**settings, persist=False)
        except (TypeError, ValueError) as error:
            _LOG.warning("Stored Community Highlights trigger settings failed validation; defaults remain active.")
            log_event("trigger.settings.restore_failed", level=logging.WARNING, error_type=type(error).__name__)

    def on_message(self, message: ChatMessage) -> None:
        with self._lock:
            matches = self._engine.add(message)
            pre_seconds = self._pre_seconds
            post_seconds = self._post_seconds
        for match in matches:
            log_event("trigger.detected", provider=match.provider, reason=match.reason)
            try:
                self._capture_manager.trigger(
                    provider=match.provider,
                    stream_id=match.stream_id,
                    triggered_at=match.triggered_at,
                    pre_seconds=pre_seconds,
                    post_seconds=post_seconds,
                    reason=match.reason,
                )
            except Exception as error:
                # A failed trigger must not tear down chat, regardless of whether
                # it came from validation, capture I/O, or durable-state storage.
                # Log only fixed labels and the exception type, never chat content,
                # stream identifiers/URLs, or credential data.
                _LOG.warning(
                    "Community Highlights trigger was not captured (provider=%s, reason=%s, error_type=%s)",
                    match.provider,
                    match.reason,
                    type(error).__name__,
                )
                log_event(
                    "trigger.capture.failed",
                    level=logging.WARNING,
                    provider=match.provider,
                    reason=match.reason,
                    error_type=type(error).__name__,
                )


trigger_coordinator = TriggerCoordinator()
