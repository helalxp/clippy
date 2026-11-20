from datetime import datetime, timezone

from community_highlights.models import ChatMessage, ChatProvider
from community_highlights.trigger_coordinator import TriggerCoordinator


class FakeCaptureManager:
    def __init__(self):
        self.calls = []

    def trigger(self, **kwargs):
        self.calls.append(kwargs)
        return {"candidate_id": "candidate"}


def message(text, message_id="m1", stamp=None, sender="u1"):
    stamp = stamp or datetime.now(timezone.utc)
    return ChatMessage(
        provider=ChatProvider.TWITCH,
        stream_id="channel",
        message_id=message_id,
        provider_timestamp=stamp,
        received_at=stamp,
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
