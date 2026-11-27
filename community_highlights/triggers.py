"""Deterministic chat trigger evaluation; no network or media dependencies."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import unicodedata

from .models import ChatMessage


@dataclass(frozen=True, slots=True)
class TriggerRule:
    rule_id: str
    phrases: tuple[str, ...] = ()
    min_messages: int | None = None
    min_unique_users: int = 1
    window_seconds: float = 10.0
    cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        normalized = tuple(p.strip() for p in self.phrases if p.strip())
        object.__setattr__(self, "phrases", normalized)
        if not normalized and self.min_messages is None:
            raise ValueError("a rule needs at least one phrase or a message threshold")
        if self.min_messages is not None and self.min_messages < 1:
            raise ValueError("min_messages must be at least 1")
        if self.min_unique_users < 1:
            raise ValueError("min_unique_users must be at least 1")
        if self.window_seconds <= 0 or self.cooldown_seconds < 0:
            raise ValueError("window_seconds must be positive and cooldown_seconds non-negative")


@dataclass(frozen=True, slots=True)
class TriggerMatch:
    rule_id: str
    provider: str
    stream_id: str
    triggered_at: datetime
    reason: str
    message_count: int
    unique_user_count: int


def _normalise(text: str) -> str:
    """Normalize Unicode and punctuation so phrases match as whole words."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalise(text)
    normalized_phrase = _normalise(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


class TriggerEngine:
    """Evaluate phrase and chat-volume rules with bounded deduplication and cooldowns.

    Provider event timestamps determine how close chat messages occurred. Local
    receipt timestamps are retained for trigger-to-capture coordination, because
    the rolling media timeline uses the same local host clock.
    """

    def __init__(self, rules: tuple[TriggerRule, ...] | list[TriggerRule], *, max_messages: int = 5000):
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self._max_messages = max_messages
        self._rules: tuple[TriggerRule, ...] = ()
        self._messages: dict[tuple[str, str], deque[ChatMessage]] = {}
        self._seen: dict[tuple[str, str], set[str]] = {}
        self._seen_order: dict[tuple[str, str], deque[str]] = {}
        self._last_trigger: dict[tuple[str, str], datetime] = {}
        self._latest_event_at: dict[tuple[str, str], datetime] = {}
        self.set_rules(rules)

    @staticmethod
    def _validated_rules(rules: tuple[TriggerRule, ...] | list[TriggerRule]) -> tuple[TriggerRule, ...]:
        validated = tuple(rules)
        ids = [rule.rule_id for rule in validated]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id values must be unique")
        return validated

    def set_rules(self, rules: tuple[TriggerRule, ...] | list[TriggerRule]) -> None:
        """Replace rules without discarding message deduplication or cooldown state."""
        self._rules = self._validated_rules(rules)

    def add(self, message: ChatMessage) -> list[TriggerMatch]:
        key = (message.provider.value, message.stream_id)
        history = self._messages.setdefault(key, deque(maxlen=self._max_messages))
        seen = self._seen.setdefault(key, set())
        seen_order = self._seen_order.setdefault(key, deque())
        if message.message_id in seen:
            return []

        seen.add(message.message_id)
        seen_order.append(message.message_id)
        while len(seen_order) > self._max_messages:
            seen.discard(seen_order.popleft())

        event_at = message.provider_timestamp.astimezone(timezone.utc)
        latest_event_at = self._latest_event_at.get(key)
        # Providers normally deliver chronological chat. A late event must not
        # rewind the rule clock or fire a phrase from an old reconnect backlog.
        if latest_event_at is not None and event_at < latest_event_at:
            return []
        self._latest_event_at[key] = event_at

        history.append(message)
        max_window = max((rule.window_seconds for rule in self._rules), default=0)
        global_cutoff = event_at - timedelta(seconds=max_window)
        history = deque(
            (
                item for item in history
                if global_cutoff <= item.provider_timestamp.astimezone(timezone.utc) <= event_at
            ),
            maxlen=self._max_messages,
        )
        self._messages[key] = history

        matches: list[TriggerMatch] = []
        for rule in self._rules:
            cutoff = event_at - timedelta(seconds=rule.window_seconds)
            recent = [
                item for item in history
                if cutoff <= item.provider_timestamp.astimezone(timezone.utc) <= event_at
            ]
            phrase_hit = any(_contains_phrase(message.text, phrase) for phrase in rule.phrases)
            users = {item.sender_id for item in recent}
            volume_hit = (
                rule.min_messages is not None
                and len(recent) >= rule.min_messages
                and len(users) >= rule.min_unique_users
            )
            if not phrase_hit and not volume_hit:
                continue

            cooldown_key = (key[0] + ":" + key[1], rule.rule_id)
            last = self._last_trigger.get(cooldown_key)
            if last is not None and (event_at - last).total_seconds() < rule.cooldown_seconds:
                continue

            reason = "phrase" if phrase_hit else "chat_volume"
            matches.append(TriggerMatch(
                rule_id=rule.rule_id,
                provider=message.provider.value,
                stream_id=message.stream_id,
                # Candidate capture uses the local receipt clock, not provider time.
                triggered_at=message.received_at,
                reason=reason,
                message_count=len(recent),
                unique_user_count=len(users),
            ))
            self._last_trigger[cooldown_key] = event_at
        return matches
