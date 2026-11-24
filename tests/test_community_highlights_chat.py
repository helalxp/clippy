import asyncio
from datetime import datetime, timezone

from community_highlights.chat import (
    ChatSession,
    ChatSessionManager,
    ChatTerminalError,
    _check_youtube_response,
    _parse_twitch_message,
    _parse_youtube_message,
    _split_twitch_irc_frame,
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


def test_provider_disconnect_stops_existing_chat_and_blocks_inflight_start():
    async def scenario():
        token_entered = asyncio.Event()
        release_token = asyncio.Event()

        async def token_provider(_provider):
            token_entered.set()
            await release_token.wait()
            return "token"

        manager = ChatSessionManager(token_provider=token_provider)
        running = asyncio.create_task(asyncio.Event().wait())
        active = ChatSession(
            session_id="active-twitch",
            reference=StreamReference(ChatProvider.TWITCH, "channel"),
            status="connected",
            task=running,
        )
        manager._sessions[active.session_id] = active

        starting = asyncio.create_task(manager.start("https://www.twitch.tv/another_channel"))
        await asyncio.wait_for(token_entered.wait(), timeout=10)
        await manager.begin_provider_disconnect("twitch")

        assert manager._sessions == {}
        assert active.stop_event.is_set()
        assert running.cancelled()

        release_token.set()
        try:
            await starting
        except ValueError as error:
            assert "being disconnected" in str(error)
        else:
            raise AssertionError("A chat session started while provider disconnect was in progress.")

        await manager.end_provider_disconnect("twitch")
        assert "twitch" not in manager._disconnecting_providers

    asyncio.run(scenario())


def test_twitch_websocket_frame_splits_every_crlf_delimited_irc_message():
    frame = (
        "PING :tmi.twitch.tv\r\n"
        "@display-name=First;id=message-1;user-id=1 "
        ":first!first@first.tmi.twitch.tv PRIVMSG #channel :first message\r\n"
        "@display-name=Second;id=message-2;user-id=2 "
        ":second!second@second.tmi.twitch.tv PRIVMSG #channel :second message\r\n"
    )

    lines = _split_twitch_irc_frame(frame)
    messages = [_parse_twitch_message(line, "channel") for line in lines]

    assert lines[0] == "PING :tmi.twitch.tv"
    assert [item.text for item in messages if item is not None] == [
        "first message",
        "second message",
    ]


def test_twitch_websocket_frame_accepts_bytes():
    frame = b":tmi.twitch.tv 001 bot :Welcome\r\nPING :tmi.twitch.tv\r\n"
    assert _split_twitch_irc_frame(frame) == [
        ":tmi.twitch.tv 001 bot :Welcome",
        "PING :tmi.twitch.tv",
    ]


def test_youtube_rate_limit_is_retryable_but_ended_chat_is_terminal():
    import httpx

    request = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/liveChat/messages")
    rate_limited = httpx.Response(
        403,
        request=request,
        json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
    )
    ended = httpx.Response(
        403,
        request=request,
        json={"error": {"errors": [{"reason": "liveChatEnded"}]}},
    )

    try:
        _check_youtube_response(rate_limited)
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("rateLimitExceeded should be retried, not treated as success")

    try:
        _check_youtube_response(ended)
    except ChatTerminalError as error:
        assert error.status == "ended"
        assert "ended" in str(error).lower()
    else:
        raise AssertionError("an ended YouTube live chat should be terminal")


def test_twitch_transport_processes_batched_frame_and_waits_for_join_confirmation(monkeypatch):
    async def scenario():
        from community_highlights import chat as chat_module

        class Store:
            def load(self, _provider):
                return {"login": "bot"}

        class Socket:
            def __init__(self):
                self.sent = []
                self.frames = [
                    "PING :tmi.twitch.tv\r\n"
                    ":tmi.twitch.tv 001 bot :Welcome\r\n"
                    ":tmi.twitch.tv 366 bot #channel :End of NAMES\r\n"
                    "@display-name=Viewer;id=1;user-id=10 "
                    ":viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #channel :hello\r\n"
                    "@display-name=Viewer2;id=2;user-id=20 "
                    ":viewer2!viewer2@viewer2.tmi.twitch.tv PRIVMSG #channel :clip it\r\n"
                ]

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def send(self, message):
                self.sent.append(message)

            async def recv(self):
                if self.frames:
                    return self.frames.pop(0)
                await asyncio.Event().wait()

        socket = Socket()
        monkeypatch.setattr(chat_module, "WindowsCredentialStore", Store)
        monkeypatch.setattr(chat_module.websockets, "connect", lambda *_args, **_kwargs: socket)
        manager = ChatSessionManager(token_provider=lambda *_args, **_kwargs: asyncio.sleep(0, result="token"))
        session = ChatSession(
            session_id="session",
            reference=StreamReference(ChatProvider.TWITCH, "channel"),
        )

        task = asyncio.create_task(manager._run_twitch(session))
        try:
            for _ in range(20):
                if len(session.messages) == 2:
                    break
                await asyncio.sleep(0)
            assert session.status == "connected"
            assert [message.text for message in session.messages] == ["hello", "clip it"]
            assert socket.sent[:4] == [
                "PASS oauth:token",
                "NICK bot",
                "CAP REQ :twitch.tv/tags twitch.tv/commands",
                "JOIN #channel",
            ]
            assert "PONG :tmi.twitch.tv" in socket.sent
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(scenario())


def test_start_replaces_error_session_and_reclaims_its_slot():
    async def scenario():
        async def token_provider(_provider):
            return "token"

        manager = ChatSessionManager(token_provider=token_provider)

        async def no_op(_session):
            return None

        manager._run = no_op
        for index, status in enumerate(("error", "ended")):
            session = ChatSession(
                session_id=f"terminal-{index}",
                reference=StreamReference(ChatProvider.TWITCH, f"old-{index}"),
                status=status,
            )
            manager._sessions[session.session_id] = session

        started = await manager.start("https://www.twitch.tv/newchannel")
        await manager._sessions[started["session_id"]].task

        assert started["status"] == "connecting"
        assert set(manager._sessions) == {started["session_id"]}

    asyncio.run(scenario())


def test_youtube_backlog_is_visible_but_does_not_trigger_old_chat(monkeypatch):
    async def scenario():
        from datetime import timedelta
        import httpx
        from community_highlights import chat as chat_module

        now = datetime.now(timezone.utc)
        seen_by_trigger = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **_kwargs):
                if url.endswith("/videos"):
                    return httpx.Response(200, json={
                        "items": [{
                            "liveStreamingDetails": {"activeLiveChatId": "live-chat-id"},
                        }],
                    })
                session.stop_event.set()
                return httpx.Response(200, json={
                    "items": [
                        {
                            "id": "old-message",
                            "snippet": {
                                "publishedAt": (now - timedelta(seconds=30)).isoformat(),
                                "displayMessage": "clip it",
                            },
                            "authorDetails": {"channelId": "old-user", "displayName": "Old"},
                        },
                        {
                            "id": "new-message",
                            "snippet": {
                                "publishedAt": now.isoformat(),
                                "displayMessage": "hello",
                            },
                            "authorDetails": {"channelId": "new-user", "displayName": "New"},
                        },
                    ],
                    "pollingIntervalMillis": 1000,
                })

        monkeypatch.setattr(chat_module.httpx, "AsyncClient", FakeClient)
        original_sleep = asyncio.sleep
        async def no_wait(_seconds):
            await original_sleep(0)
        monkeypatch.setattr(chat_module.asyncio, "sleep", no_wait)

        manager = ChatSessionManager(
            token_provider=lambda *_args, **_kwargs: original_sleep(0, result="token"),
            message_callback=seen_by_trigger.append,
        )
        # The monitor was started shortly before these polls began. The old
        # "clip it" message is part of YouTube's initial backlog, not a new cue.
        session = ChatSession(
            session_id="youtube-session",
            reference=StreamReference(ChatProvider.YOUTUBE, "abcdefghijk"),
            started_at=now - timedelta(seconds=1),
        )

        await manager._run_youtube(session)

        assert [message.message_id for message in session.messages] == ["old-message", "new-message"]
        assert [message.message_id for message in seen_by_trigger] == ["new-message"]

    asyncio.run(scenario())


def test_youtube_rate_limit_retries_the_same_chat_without_resolving_video_again(monkeypatch):
    async def scenario():
        from datetime import timedelta
        import httpx
        from community_highlights import chat as chat_module

        now = datetime.now(timezone.utc)
        video_calls = []
        chat_calls = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **_kwargs):
                if url.endswith("/videos"):
                    video_calls.append(url)
                    return httpx.Response(200, json={
                        "items": [{
                            "liveStreamingDetails": {"activeLiveChatId": "live-chat-id"},
                        }],
                    })
                chat_calls.append(url)
                if len(chat_calls) == 1:
                    return httpx.Response(
                        403,
                        headers={"Retry-After": "1"},
                        json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
                    )
                session.stop_event.set()
                return httpx.Response(200, json={
                    "items": [{
                        "id": "new-message",
                        "snippet": {
                            "publishedAt": now.isoformat(),
                            "displayMessage": "hello",
                        },
                        "authorDetails": {"channelId": "user-1", "displayName": "Viewer"},
                    }],
                    "pollingIntervalMillis": 1000,
                })

        monkeypatch.setattr(chat_module.httpx, "AsyncClient", FakeClient)
        original_sleep = asyncio.sleep
        delays = []
        async def no_wait(seconds):
            delays.append(seconds)
            await original_sleep(0)
        monkeypatch.setattr(chat_module.asyncio, "sleep", no_wait)

        session = ChatSession(
            session_id="youtube-rate-limit",
            reference=StreamReference(ChatProvider.YOUTUBE, "abcdefghijk"),
            started_at=now - timedelta(seconds=1),
        )
        manager = ChatSessionManager(token_provider=lambda *_args, **_kwargs: original_sleep(0, result="token"))
        await manager._run_youtube(session)

        assert len(video_calls) == 1
        assert len(chat_calls) == 2
        assert delays[0] == 1.0
        assert [message.text for message in session.messages] == ["hello"]

    asyncio.run(scenario())
