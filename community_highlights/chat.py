"""Provider chat transports and bounded session lifecycle for Community Highlights."""
from __future__ import annotations

import asyncio
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
import websockets

from .credentials import CredentialStoreError, WindowsCredentialStore
from .models import ChatMessage, ChatProvider, StreamReference
from .token_manager import ProviderTokenError, ensure_access_token
from .urls import StreamUrlError, parse_stream_url

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
TWITCH_IRC = "wss://irc-ws.chat.twitch.tv:443"
MAX_CHAT_SESSIONS = 2
MAX_SESSION_MESSAGES = 250


class ChatTerminalError(RuntimeError):
    """A provider refusal that will not be repaired by reconnecting the same grant."""

    def __init__(self, message: str, *, status: str = "error") -> None:
        super().__init__(message)
        self.status = status


def _split_twitch_irc_frame(frame: str | bytes) -> list[str]:
    """Twitch WebSocket frames may contain several CRLF-delimited IRC messages."""
    text = frame.decode("utf-8", "replace") if isinstance(frame, bytes) else str(frame)
    return [line for line in text.splitlines() if line]


def _youtube_api_error_reason(response: httpx.Response) -> str:
    """Extract only Google's stable error reason; never surface its raw description."""
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    errors = error.get("errors") if isinstance(error, dict) else None
    if isinstance(errors, list):
        for item in errors:
            reason = item.get("reason") if isinstance(item, dict) else None
            if isinstance(reason, str) and reason.isascii() and reason.replace("_", "").isalnum():
                return reason
    return ""


def _check_youtube_response(response: httpx.Response) -> None:
    if response.is_success:
        return
    reason = _youtube_api_error_reason(response)
    if response.status_code == 401:
        raise ChatTerminalError("Google authorization was rejected. Reconnect your Google account.")
    if reason == "liveChatDisabled":
        raise ChatTerminalError("Live chat is disabled for this YouTube broadcast.", status="ended")
    if reason == "liveChatEnded":
        raise ChatTerminalError("This YouTube live chat has ended.", status="ended")
    if reason == "liveChatNotFound":
        raise ChatTerminalError("YouTube could not find an active live chat for this video.")
    if reason == "forbidden":
        raise ChatTerminalError("The connected Google account is not permitted to read this live chat.")
    if reason in {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"}:
        raise ChatTerminalError("YouTube API quota is exhausted. Try monitoring again after the quota resets.")
    if response.status_code in {400, 403, 404} and reason != "rateLimitExceeded":
        raise ChatTerminalError("YouTube rejected this live-chat request. Check that the video is live and chat is enabled.")
    response.raise_for_status()


@dataclass
class ChatSession:
    session_id: str
    reference: StreamReference
    status: str = "connecting"
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages: deque[ChatMessage] = field(default_factory=lambda: deque(maxlen=MAX_SESSION_MESSAGES))
    task: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.reference.provider.value,
            "stream_id": self.reference.stream_id,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "message_count": len(self.messages),
            "messages": [
                {
                    "message_id": message.message_id,
                    "timestamp": message.provider_timestamp.isoformat(),
                    "sender_id": message.sender_id,
                    "sender_name": message.sender_name,
                    "text": message.text,
                }
                for message in list(self.messages)[-50:]
            ],
        }


def _parse_twitch_message(line: str, channel: str) -> ChatMessage | None:
    if not line.startswith("@") or " :" not in line:
        return None
    tags_part, rest = line[1:].split(" :", 1)
    prefix_and_command, separator, text = rest.partition(" :")
    prefix_parts = prefix_and_command.split()
    if not separator or len(prefix_parts) < 3 or prefix_parts[1] != "PRIVMSG":
        return None
    tags = {}
    for item in tags_part.split(";"):
        key, separator, value = item.partition("=")
        if separator:
            tags[key] = value.replace("\\s", " ").replace("\\:", ";").replace("\\\\", "\\")
    message_id = tags.get("id")
    sender_id = tags.get("user-id")
    if not message_id or not sender_id:
        return None
    try:
        stamp_ms = int(tags.get("tmi-sent-ts", "0"))
        timestamp = datetime.fromtimestamp(stamp_ms / 1000, tz=timezone.utc) if stamp_ms else datetime.now(timezone.utc)
    except (TypeError, ValueError, OSError):
        timestamp = datetime.now(timezone.utc)
    sender_name = tags.get("display-name") or prefix_parts[0].split("!", 1)[0].lstrip(":")
    return ChatMessage.now_received(
        provider=ChatProvider.TWITCH,
        stream_id=channel,
        message_id=message_id,
        provider_timestamp=timestamp,
        sender_id=sender_id,
        sender_name=sender_name or sender_id,
        text=text,
    )


def _parse_youtube_message(item: dict[str, Any], video_id: str) -> ChatMessage | None:
    snippet = item.get("snippet") or {}
    author = item.get("authorDetails") or {}
    message_id = item.get("id")
    sender_id = author.get("channelId")
    text = snippet.get("displayMessage")
    if not message_id or not sender_id or not isinstance(text, str):
        return None
    published = snippet.get("publishedAt")
    try:
        timestamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError):
        timestamp = datetime.now(timezone.utc)
    return ChatMessage.now_received(
        provider=ChatProvider.YOUTUBE,
        stream_id=video_id,
        message_id=message_id,
        provider_timestamp=timestamp,
        sender_id=sender_id,
        sender_name=author.get("displayName") or sender_id,
        text=text,
    )


class ChatSessionManager:
    """Owns a small bounded set of provider chat tasks."""

    def __init__(self, *, token_provider=ensure_access_token, message_callback: Callable[[ChatMessage], None] | None = None):
        self._sessions: dict[str, ChatSession] = {}
        self._lock = asyncio.Lock()
        self._token_provider = token_provider
        self._message_callback = message_callback
        self._disconnecting_providers: set[str] = set()

    def _prune_terminal_sessions_locked(self) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.status in {"stopped", "ended", "error"}:
                self._sessions.pop(session_id, None)

    async def start(self, stream_url: str) -> dict[str, Any]:
        reference = parse_stream_url(stream_url)
        provider = reference.provider.value
        async with self._lock:
            if provider in self._disconnecting_providers:
                raise ValueError(f"{provider.title()} is being disconnected. Try again shortly.")
        try:
            await self._token_provider(provider)
        except ProviderTokenError as error:
            raise ValueError(str(error)) from None

        async with self._lock:
            # A disconnect can begin while token refresh is in flight. Check
            # again before registering a new background chat task. Reclaim
            # terminal sessions here so an errored stream can be restarted and
            # a failed session cannot consume one of the two active slots.
            if provider in self._disconnecting_providers:
                raise ValueError(f"{provider.title()} is being disconnected. Try again shortly.")
            self._prune_terminal_sessions_locked()
            for session in self._sessions.values():
                if session.reference == reference and session.status not in {"stopped", "ended", "error"}:
                    return session.snapshot()
            if len(self._sessions) >= MAX_CHAT_SESSIONS:
                raise ValueError("Clippy can monitor up to two live chats at a time.")
            session = ChatSession(secrets.token_urlsafe(18), reference)
            self._sessions[session.session_id] = session
            session.task = asyncio.create_task(self._run(session))
            return session.snapshot()

    async def stop(self, session_id: str) -> bool:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session.stop_event.set()
        if session.task:
            session.task.cancel()
            try:
                await session.task
            except asyncio.CancelledError:
                pass
        session.status = "stopped"
        return True

    async def begin_provider_disconnect(self, provider: str) -> None:
        """Block new sessions and stop every active chat task for a provider."""
        async with self._lock:
            self._disconnecting_providers.add(provider)
            sessions = [
                session for session in self._sessions.values()
                if session.reference.provider.value == provider
            ]
            for session in sessions:
                self._sessions.pop(session.session_id, None)
                session.stop_event.set()
                if session.task:
                    session.task.cancel()

        tasks = [session.task for session in sessions if session.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for session in sessions:
            session.status = "stopped"

    async def end_provider_disconnect(self, provider: str) -> None:
        """Allow new chat sessions after local credential cleanup has finished."""
        async with self._lock:
            self._disconnecting_providers.discard(provider)

    async def get(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            return session.snapshot() if session else None

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [session.snapshot() for session in self._sessions.values()]

    async def _run(self, session: ChatSession) -> None:
        delay = 1
        while not session.stop_event.is_set():
            try:
                if session.reference.provider == ChatProvider.TWITCH:
                    await self._run_twitch(session)
                else:
                    await self._run_youtube(session)
                if session.stop_event.is_set() or session.status in {"error", "ended"}:
                    break
                session.status = "reconnecting"
                session.error = "The chat connection ended. Reconnecting…"
            except asyncio.CancelledError:
                raise
            except (ProviderTokenError, CredentialStoreError):
                session.status = "error"
                session.error = "Provider authorization is unavailable. Reconnect the account."
                break
            except ChatTerminalError as error:
                session.status = error.status
                session.error = str(error)
                break
            except httpx.HTTPStatusError as error:
                # YouTube reports rateLimitExceeded as HTTP 403. This is
                # recoverable; permanent permission/chat/quota failures are
                # classified before raise_for_status() in _run_youtube().
                session.status = "reconnecting"
                session.error = "Chat connection interrupted. Clippy is retrying."
                if error.response.status_code == 403 and _youtube_api_error_reason(error.response) == "rateLimitExceeded":
                    delay = max(delay, 5)
            except Exception:
                session.status = "reconnecting"
                session.error = "Chat connection interrupted. Clippy is retrying."
            try:
                await asyncio.wait_for(session.stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 30)
        if session.status not in {"error", "stopped", "ended"}:
            session.status = "stopped"

    async def _run_twitch(self, session: ChatSession) -> None:
        channel = session.reference.stream_id
        store = WindowsCredentialStore()
        bundle = store.load("twitch") or {}
        token = await self._token_provider("twitch")
        login = bundle.get("login")
        if not isinstance(login, str) or not login:
            raise ProviderTokenError("Twitch account identity is missing. Sign in again.")

        async with websockets.connect(
            TWITCH_IRC, ping_interval=20, ping_timeout=20, close_timeout=5
        ) as socket:
            # PASS must precede NICK. The session remains "connecting" until
            # Twitch confirms that it joined the requested room.
            await socket.send(f"PASS oauth:{token}")
            await socket.send(f"NICK {login}")
            await socket.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            await socket.send(f"JOIN #{channel}")
            session.status = "connecting"
            session.error = None
            loop = asyncio.get_running_loop()
            next_validation = loop.time() + 300
            join_deadline = loop.time() + 20
            joined = False
            while not session.stop_event.is_set():
                next_deadline = min(next_validation, join_deadline) if not joined else next_validation
                timeout = max(0.1, next_deadline - loop.time())
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    raw = None

                now = loop.time()
                if not joined and now >= join_deadline:
                    raise ChatTerminalError(
                        "Twitch did not confirm that this channel joined. Check the channel name and Twitch chat access."
                    )
                if now >= next_validation:
                    await self._token_provider("twitch")
                    next_validation = loop.time() + 300
                if raw is None:
                    continue

                for line in _split_twitch_irc_frame(raw):
                    if line.startswith("PING"):
                        # Echo the server's exact ping payload as required by IRC.
                        await socket.send("PONG" + line[4:])
                        continue
                    if " NOTICE " in line and "Login authentication failed" in line:
                        raise ChatTerminalError(
                            "Twitch rejected the chat connection. Reconnect Twitch and confirm chat:read access."
                        )
                    if " NOTICE " in line and "msg_channel_suspended" in line:
                        raise ChatTerminalError("Twitch reports that this channel is unavailable.")

                    parts = line.split()
                    if len(parts) >= 4 and parts[1] == "366" and parts[3].casefold() == f"#{channel}".casefold():
                        joined = True
                        session.status = "connected"
                        session.error = None
                    elif (
                        line.casefold().startswith(f":{login.casefold()}!")
                        and f" JOIN #{channel.casefold()}" in line.casefold()
                    ):
                        joined = True
                        session.status = "connected"
                        session.error = None

                    message = _parse_twitch_message(line, channel)
                    if message:
                        session.messages.append(message)
                        if self._message_callback:
                            try:
                                self._message_callback(message)
                            except Exception:
                                # A trigger callback failure must not tear down
                                # the provider transport. The coordinator logs a
                                # safe diagnostic for its own failures.
                                pass

    async def _run_youtube(self, session: ChatSession) -> None:
        video_id = session.reference.stream_id
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            token = await self._token_provider("youtube")
            headers = {"Authorization": f"Bearer {token}"}
            video = await client.get(
                f"{YOUTUBE_API}/videos",
                params={"part": "liveStreamingDetails", "id": video_id},
                headers=headers,
            )
            if video.status_code == 401:
                token = await self._token_provider("youtube", force_refresh=True)
                headers = {"Authorization": f"Bearer {token}"}
                video = await client.get(
                    f"{YOUTUBE_API}/videos",
                    params={"part": "liveStreamingDetails", "id": video_id},
                    headers=headers,
                )
            _check_youtube_response(video)
            items = video.json().get("items") or []
            if not items:
                raise ValueError("YouTube video was not found or is unavailable.")
            live_chat_id = (items[0].get("liveStreamingDetails") or {}).get("activeLiveChatId")
            if not live_chat_id:
                session.status = "ended"
                session.error = "This video has no active live chat."
                return

            page_token = None
            rate_limit_delay = 5
            session.status = "connected"
            session.error = None
            while not session.stop_event.is_set():
                token = await self._token_provider("youtube")
                headers = {"Authorization": f"Bearer {token}"}
                params = {
                    "liveChatId": live_chat_id,
                    "part": "id,snippet,authorDetails",
                    "maxResults": 200,
                }
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    f"{YOUTUBE_API}/liveChat/messages",
                    params=params,
                    headers=headers,
                )
                if response.status_code == 401:
                    token = await self._token_provider("youtube", force_refresh=True)
                    headers = {"Authorization": f"Bearer {token}"}
                    response = await client.get(
                        f"{YOUTUBE_API}/liveChat/messages",
                        params=params,
                        headers=headers,
                    )
                if response.status_code == 400 and _youtube_api_error_reason(response) == "pageTokenInvalid":
                    # A stale continuation token should not kill an otherwise
                    # valid monitoring session. Restart from the current window.
                    page_token = None
                    continue
                if response.status_code == 403 and _youtube_api_error_reason(response) == "rateLimitExceeded":
                    # The live-chat list endpoint explicitly asks clients not to
                    # poll too quickly. Back off in place so we keep the current
                    # liveChatId/page token and do not spend extra quota resolving
                    # the video again on each retry.
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else rate_limit_delay
                    except ValueError:
                        delay = rate_limit_delay
                    await asyncio.sleep(min(30.0, max(1.0, delay)))
                    rate_limit_delay = min(rate_limit_delay * 2, 30)
                    continue
                _check_youtube_response(response)
                rate_limit_delay = 5
                payload = response.json()
                for item in payload.get("items") or []:
                    message = _parse_youtube_message(item, video_id)
                    if message:
                        session.messages.append(message)
                        # The first list response can contain recent chat history.
                        # Keep it visible in the monitor, but don't turn old chat
                        # into a fresh trigger at the moment monitoring starts.
                        if message.provider_timestamp >= session.started_at and self._message_callback:
                            try:
                                self._message_callback(message)
                            except Exception:
                                pass
                page_token = payload.get("nextPageToken")
                wait_ms = payload.get("pollingIntervalMillis", 5000)
                await asyncio.sleep(max(1000, min(int(wait_ms), 30000)) / 1000)


from .trigger_coordinator import trigger_coordinator

chat_sessions = ChatSessionManager(message_callback=trigger_coordinator.on_message)
