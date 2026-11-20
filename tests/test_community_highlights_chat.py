from datetime import datetime, timezone

from community_highlights.chat import (
    ChatSession,
    _parse_twitch_message,
    _parse_youtube_message,
)
from community_highlights.models import ChatProvider, StreamReference


def test_twitch_irc_message_is_normalized_with_provider_identity_and_timestamp():
    line = (
        "@badge-info=;badges=;display-name=Viewer;id=message-123;"
        "tmi-sent-ts=1763596800000;user-id=9988 "
        ":viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #somechannel :clip it"
    )

    message = _parse_twitch_message(line, "somechannel")

    assert message is not None
    assert message.provider is ChatProvider.TWITCH
    assert message.stream_id == "somechannel"
    assert message.message_id == "message-123"
    assert message.sender_id == "9988"
    assert message.sender_name == "Viewer"
    assert message.text == "clip it"
    assert message.provider_timestamp.tzinfo is not None
    assert message.received_at.tzinfo is not None


def test_twitch_irc_non_message_and_missing_identity_are_ignored():
    assert _parse_twitch_message("PING :tmi.twitch.tv", "channel") is None
    assert _parse_twitch_message(
        "@display-name=Viewer :viewer!viewer@host PRIVMSG #channel :hello",
        "channel",
    ) is None


def test_chat_session_snapshot_contains_only_normalized_messages_and_safe_metadata():
    session = ChatSession(
        session_id="session-id",
        reference=StreamReference(ChatProvider.YOUTUBE, "abcdefghijk"),
        status="connected",
    )

    snapshot = session.snapshot()

    assert snapshot["provider"] == "youtube"
    assert snapshot["stream_id"] == "abcdefghijk"
    assert snapshot["status"] == "connected"
    assert snapshot["messages"] == []
    assert "access_token" not in repr(snapshot)
    assert "refresh_token" not in repr(snapshot)



def test_youtube_chat_message_is_normalized_from_api_payload():
    message = _parse_youtube_message(
        {
            "id": "yt-message-1",
            "snippet": {
                "publishedAt": "2026-11-20T10:15:30Z",
                "displayMessage": "clip it!",
            },
            "authorDetails": {
                "channelId": "channel-123",
                "displayName": "Live Viewer",
            },
        },
        "abcdefghijk",
    )

    assert message is not None
    assert message.provider is ChatProvider.YOUTUBE
    assert message.stream_id == "abcdefghijk"
    assert message.message_id == "yt-message-1"
    assert message.sender_id == "channel-123"
    assert message.sender_name == "Live Viewer"
    assert message.text == "clip it!"
    assert message.provider_timestamp.tzinfo is not None


def test_youtube_chat_message_without_required_identity_is_ignored():
    assert _parse_youtube_message(
        {"id": "message", "snippet": {"displayMessage": "hello"}},
        "abcdefghijk",
    ) is None
