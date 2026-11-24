from datetime import datetime, timedelta, timezone

import pytest

from community_highlights.models import ChatMessage, ChatProvider
from community_highlights.triggers import TriggerEngine, TriggerRule
from community_highlights.urls import StreamUrlError, parse_stream_url


def message(message_id, text, sender="user-1", *, at=None, stream="channel"):
    timestamp = at or datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    return ChatMessage(
        provider=ChatProvider.TWITCH,
        stream_id=stream,
        message_id=message_id,
        provider_timestamp=timestamp,
        received_at=timestamp + timedelta(milliseconds=100),
        sender_id=sender,
        sender_name=sender,
        text=text,
    )


@pytest.mark.parametrize(
    ("url", "provider", "stream_id"),
    [
        ("https://www.twitch.tv/SomeChannel", ChatProvider.TWITCH, "somechannel"),
        ("https://youtube.com/live/abcdefghijk", ChatProvider.YOUTUBE, "abcdefghijk"),
        ("https://www.youtube.com/watch?v=abcdefghijk", ChatProvider.YOUTUBE, "abcdefghijk"),
        ("https://youtu.be/abcdefghijk?t=10", ChatProvider.YOUTUBE, "abcdefghijk"),
    ],
)
def test_parse_supported_stream_urls(url, provider, stream_id):
    result = parse_stream_url(url)
    assert result.provider is provider
    assert result.stream_id == stream_id


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://twitch.tv/",
        "https://twitch.tv/directory",
        "https://youtube.com/@creator",
        "https://youtube.com/playlist?list=abc",
        "https://youtube.com/live/not-an-id",
        "https://example.com/live/abcdefghijk",
        "file:///etc/passwd",
    ],
)
def test_reject_unsupported_or_non_stream_urls(url):
    with pytest.raises(StreamUrlError):
        parse_stream_url(url)


def test_chat_message_requires_timezone_aware_timestamps():
    timestamp = datetime(2026, 11, 20, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        message("m1", "hello", at=timestamp)


def test_phrase_trigger_matches_case_insensitively_and_deduplicates():
    engine = TriggerEngine([TriggerRule("clip", phrases=("clip it",), cooldown_seconds=0)])
    first = message("m1", "CLIP   IT!")
    assert [match.reason for match in engine.add(first)] == ["phrase"]
    assert engine.add(first) == []


def test_message_burst_requires_unique_users():
    engine = TriggerEngine([
        TriggerRule("crowd", min_messages=3, min_unique_users=2, window_seconds=5)
    ])
    at = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert engine.add(message("m1", "wow", "alice", at=at)) == []
    assert engine.add(message("m2", "wow", "alice", at=at + timedelta(seconds=1))) == []
    matches = engine.add(message("m3", "wow", "bob", at=at + timedelta(seconds=2)))
    assert len(matches) == 1
    assert matches[0].reason == "chat_volume"
    assert matches[0].message_count == 3
    assert matches[0].unique_user_count == 2


def test_old_messages_fall_out_of_detection_window():
    engine = TriggerEngine([
        TriggerRule("crowd", min_messages=2, min_unique_users=2, window_seconds=3)
    ])
    at = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    engine.add(message("m1", "wow", "alice", at=at))
    assert engine.add(message("m2", "wow", "bob", at=at + timedelta(seconds=4))) == []


def test_rule_windows_do_not_shrink_shared_history_for_later_rules():
    engine = TriggerEngine([
        TriggerRule("short", min_messages=10, window_seconds=2),
        TriggerRule("long", min_messages=3, min_unique_users=2, window_seconds=10),
    ])
    at = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    engine.add(message("m1", "one", "alice", at=at))
    engine.add(message("m2", "two", "bob", at=at + timedelta(seconds=1)))
    matches = engine.add(message("m3", "three", "carol", at=at + timedelta(seconds=3)))
    assert [match.rule_id for match in matches] == ["long"]


def test_cooldown_suppresses_repeated_phrase_triggers():
    engine = TriggerEngine([TriggerRule("clip", phrases=("clip it",), cooldown_seconds=10)])
    at = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert len(engine.add(message("m1", "clip it", at=at))) == 1
    assert engine.add(message("m2", "clip it", at=at + timedelta(seconds=5))) == []
    assert len(engine.add(message("m3", "clip it", at=at + timedelta(seconds=11)))) == 1


def test_trigger_volume_uses_local_receipt_clock_not_skewed_provider_time():
    engine = TriggerEngine([
        TriggerRule("crowd", min_messages=2, min_unique_users=2, window_seconds=5, cooldown_seconds=10)
    ])
    received = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    first = ChatMessage(
        provider=ChatProvider.TWITCH,
        stream_id="channel",
        message_id="future-provider-clock",
        provider_timestamp=datetime(2035, 1, 1, tzinfo=timezone.utc),
        received_at=received,
        sender_id="alice",
        sender_name="alice",
        text="hello",
    )
    second = ChatMessage(
        provider=ChatProvider.TWITCH,
        stream_id="channel",
        message_id="past-provider-clock",
        provider_timestamp=datetime(1995, 1, 1, tzinfo=timezone.utc),
        received_at=received + timedelta(seconds=1),
        sender_id="bob",
        sender_name="bob",
        text="hello",
    )

    assert engine.add(first) == []
    matches = engine.add(second)

    assert len(matches) == 1
    assert matches[0].triggered_at == second.received_at


def test_rule_validation_rejects_unusable_thresholds():
    with pytest.raises(ValueError):
        TriggerRule("empty")
    with pytest.raises(ValueError):
        TriggerRule("bad", min_messages=0)
