import logging
from datetime import datetime, timedelta, timezone

from community_highlights.models import ChatMessage, ChatProvider
from community_highlights.state_store import StateStoreError
from community_highlights.rolling_capture import RollingCaptureError
from community_highlights.trigger_coordinator import TriggerCoordinator


class FakeCaptureManager:
    def __init__(self):
        self.calls = []

    def trigger(self, **kwargs):
        self.calls.append(kwargs)
        return {"candidate_id": "candidate"}


def message(text, message_id="m1", stamp=None, sender="u1", received_at=None):
    stamp = stamp or datetime.now(timezone.utc)
    return ChatMessage(
        provider=ChatProvider.TWITCH,
        stream_id="channel",
        message_id=message_id,
        provider_timestamp=stamp,
        received_at=received_at or stamp,
        sender_id=sender,
        sender_name=sender,
        text=text,
    )


def test_phrase_trigger_requests_capture_with_configured_window():
    manager = FakeCaptureManager()
    coordinator = TriggerCoordinator(manager)
    coordinator.configure(
        phrases=["clip it"],
        min_messages=10,
        min_unique_users=4,
        window_seconds=10,
        cooldown_seconds=30,
        pre_seconds=20,
        post_seconds=15,
    )

    coordinator.on_message(message("please CLIP IT", stamp=datetime.now(timezone.utc)))

    assert len(manager.calls) == 1
    assert manager.calls[0]["pre_seconds"] == 20
    assert manager.calls[0]["post_seconds"] == 15
    assert manager.calls[0]["reason"] == "phrase"


def test_message_volume_trigger_requires_unique_viewers():
    manager = FakeCaptureManager()
    coordinator = TriggerCoordinator(manager)
    coordinator.configure(
        phrases=[],
        min_messages=3,
        min_unique_users=2,
        window_seconds=10,
        cooldown_seconds=0,
        pre_seconds=5,
        post_seconds=5,
    )
    now = datetime.now(timezone.utc)
    coordinator.on_message(message("one", "1", now, "u1"))
    coordinator.on_message(message("two", "2", now, "u1"))
    coordinator.on_message(message("three", "3", now, "u2"))

    assert len(manager.calls) == 1
    assert manager.calls[0]["reason"] == "chat_volume"


def test_duplicate_message_does_not_trigger_twice():
    manager = FakeCaptureManager()
    coordinator = TriggerCoordinator(manager)
    now = datetime.now(timezone.utc)
    item = message("clip it", "same-id", now)
    coordinator.on_message(item)
    coordinator.on_message(item)
    assert len(manager.calls) == 1


def test_phrase_only_mode_does_not_trigger_on_chat_volume():
    manager = FakeCaptureManager()
    coordinator = TriggerCoordinator(manager)
    coordinator.configure(
        phrases=["clip it"],
        mode="phrases",
        min_messages=2,
        min_unique_users=2,
        window_seconds=10,
        cooldown_seconds=0,
        pre_seconds=5,
        post_seconds=5,
    )
    now = datetime.now(timezone.utc)
    coordinator.on_message(message("hello", "1", now, "u1"))
    coordinator.on_message(message("hello", "2", now + timedelta(seconds=1), "u2"))
    assert manager.calls == []
    coordinator.on_message(message("please clip it", "3", now + timedelta(seconds=2), "u3"))
    assert [call["reason"] for call in manager.calls] == ["phrase"]


def test_chat_volume_only_mode_does_not_trigger_on_phrase_alone():
    manager = FakeCaptureManager()
    coordinator = TriggerCoordinator(manager)
    coordinator.configure(
        phrases=["clip it"],
        mode="chat_volume",
        min_messages=3,
        min_unique_users=2,
        window_seconds=10,
        cooldown_seconds=0,
        pre_seconds=5,
        post_seconds=5,
    )
    now = datetime.now(timezone.utc)
    coordinator.on_message(message("clip it", "1", now, "u1"))
    assert manager.calls == []
    coordinator.on_message(message("hello", "2", now + timedelta(seconds=1), "u2"))
    assert [call["reason"] for call in manager.calls] == ["chat_volume"]


def test_saving_settings_preserves_message_deduplication_and_cooldown():
    manager = FakeCaptureManager()
    coordinator = TriggerCoordinator(manager)
    now = datetime.now(timezone.utc)
    settings = {
        "phrases": ["clip it"],
        "mode": "phrases",
        "min_messages": 10,
        "min_unique_users": 2,
        "window_seconds": 10,
        "cooldown_seconds": 30,
        "pre_seconds": 5,
        "post_seconds": 5,
    }
    coordinator.configure(**settings)
    duplicate = message("clip it", "same-id", now)
    coordinator.on_message(duplicate)
    coordinator.configure(**settings)
    coordinator.on_message(duplicate)
    coordinator.on_message(message("clip it", "within-cooldown", now + timedelta(seconds=5)))
    assert len(manager.calls) == 1
    coordinator.on_message(message("clip it", "after-cooldown", now + timedelta(seconds=31)))
    assert len(manager.calls) == 2


def test_rejects_invalid_trigger_configuration():
    coordinator = TriggerCoordinator(FakeCaptureManager())
    try:
        coordinator.configure(
            phrases=["x" * 81],
            min_messages=10,
            min_unique_users=2,
            window_seconds=10,
            cooldown_seconds=30,
            pre_seconds=45,
            post_seconds=45,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid phrase should be rejected")


def test_trigger_creation_failure_is_logged_without_chat_content_or_identity(caplog):
    manager = FakeCaptureManager()

    def reject(**_kwargs):
        raise ValueError("The rolling buffer does not contain the full pre-trigger window yet.")

    manager.trigger = reject
    coordinator = TriggerCoordinator(manager)
    private_text = "private viewer says clip it"
    private_message_id = "private-message-id"
    item = message(private_text, private_message_id)

    with caplog.at_level(logging.WARNING, logger="community_highlights.trigger_coordinator"):
        coordinator.on_message(item)

    assert "trigger was not captured" in caplog.text
    assert "provider=twitch" in caplog.text
    assert "reason=phrase" in caplog.text
    assert "ValueError" in caplog.text
    assert '"failure_code":"capture_window_unavailable"' in caplog.text
    assert private_text not in caplog.text
    assert private_message_id not in caplog.text
    assert item.stream_id not in caplog.text

def test_trigger_failures_include_stable_diagnostic_outcomes(caplog):
    cases = [
        (
            ValueError("Increase rolling-buffer retention to cover the requested highlight window."),
            "retention_too_short",
        ),
        (
            ValueError("The highlight queue is full. Delete an existing candidate before creating another."),
            "candidate_queue_full",
        ),
        (
            RollingCaptureError("The requested highlight window exceeds the configured protected-segment storage budget."),
            "protected_buffer_limit",
        ),
    ]
    for error, expected_code in cases:
        manager = FakeCaptureManager()

        def reject(_error=error, **_kwargs):
            raise _error

        manager.trigger = reject
        coordinator = TriggerCoordinator(manager)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="community_highlights.trigger_coordinator"):
            coordinator.on_message(message("please clip it"))

        assert f'"failure_code":"{expected_code}"' in caplog.text


def test_state_store_trigger_failure_is_logged_safely(caplog):
    manager = FakeCaptureManager()

    def fail_trigger(**_kwargs):
        raise StateStoreError("private data-directory path")

    manager.trigger = fail_trigger
    coordinator = TriggerCoordinator(manager)
    private_text = "private viewer says clip it"
    with caplog.at_level(logging.WARNING, logger="community_highlights.trigger_coordinator"):
        coordinator.on_message(message(private_text, "private-trigger-id"))

    assert "trigger was not captured" in caplog.text
    assert "provider=twitch" in caplog.text
    assert "reason=phrase" in caplog.text
    assert "StateStoreError" in caplog.text
    assert '"failure_code":"state_store_error"' in caplog.text
    assert private_text not in caplog.text
    assert "private-trigger-id" not in caplog.text
    assert "private data-directory path" not in caplog.text
