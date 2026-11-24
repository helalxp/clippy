import asyncio
import functools
import time

import httpx
import pytest

from community_highlights.credential_lifecycle import (
    provider_disconnect_lock,
    provider_is_disconnecting,
)
from community_highlights.token_manager import ensure_access_token
from community_highlights import google_oauth, twitch_oauth


def run_async(test_function):
    @functools.wraps(test_function)
    def wrapper(*args, **kwargs):
        return asyncio.run(test_function(*args, **kwargs))
    return wrapper


class MemoryStore:
    def __init__(self, bundle=None):
        self.bundle = bundle
        self.saved = None

    def load(self, _provider):
        return self.bundle

    def save(self, _provider, bundle):
        self.saved = bundle
        self.bundle = bundle

    def delete(self, _provider):
        self.bundle = None


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "provider error",
                request=httpx.Request("GET", "https://provider.example"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self.payload


@run_async
async def test_disconnect_waits_for_token_refresh_before_deleting_rotated_credentials(monkeypatch):
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "twitch-client")
    store = MemoryStore({
        "client_id": "twitch-client",
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "expires_at": 0,
        "scopes": ["chat:read"],
    })
    refresh_started = asyncio.Event()
    allow_refresh = asyncio.Event()

    class RefreshClient:
        async def post(self, _url, data):
            assert data["refresh_token"] == "old-refresh"
            refresh_started.set()
            await allow_refresh.wait()
            return Response({
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 14400,
            })

        async def get(self, _url, headers=None, params=None):
            assert headers["Authorization"] == "OAuth new-access"
            return Response({
                "client_id": "twitch-client",
                "scopes": ["chat:read"],
                "user_id": "123",
                "login": "viewer",
            })

    refresh_task = asyncio.create_task(
        ensure_access_token("twitch", store_factory=lambda: store, client=RefreshClient())
    )
    await asyncio.wait_for(refresh_started.wait(), timeout=10)

    disconnect_entered = asyncio.Event()

    async def disconnect():
        async with provider_disconnect_lock("twitch"):
            assert provider_is_disconnecting("twitch")
            disconnect_entered.set()
            store.delete("twitch")

    disconnect_task = asyncio.create_task(disconnect())
    await asyncio.sleep(0)
    assert not disconnect_entered.is_set()

    allow_refresh.set()
    assert await refresh_task == "new-access"
    await disconnect_task

    assert store.bundle is None
    assert store.saved["refresh_token"] == "new-refresh"
    assert not provider_is_disconnecting("twitch")


@run_async
async def test_disconnect_waits_for_inflight_twitch_device_exchange_then_removes_saved_tokens():
    flow_id = "race-twitch-flow-012345678901234567890123456789"
    store = MemoryStore()
    validation_started = asyncio.Event()
    allow_validation = asyncio.Event()

    class OAuthClient:
        async def post(self, _url, data):
            assert data["device_code"] == "device-code"
            return Response({
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 14400,
            })

        async def get(self, _url, headers=None):
            validation_started.set()
            await allow_validation.wait()
            return Response({
                "client_id": "twitch-client",
                "scopes": ["chat:read"],
                "user_id": "123",
                "login": "viewer",
            })

    twitch_oauth._flows[flow_id] = {
        "device_code": "device-code",
        "client_id": "twitch-client",
        "expires_at": time.monotonic() + 600,
        "interval": 5,
        "next_poll": 0,
        "status": "pending",
        "message": "Waiting",
    }
    polling = asyncio.create_task(
        twitch_oauth.poll_twitch_flow(
            flow_id,
            client=OAuthClient(),
            store_factory=lambda: store,
        )
    )
    await asyncio.wait_for(validation_started.wait(), timeout=10)

    disconnect_entered = asyncio.Event()

    async def disconnect():
        async with provider_disconnect_lock("twitch"):
            disconnect_entered.set()
            assert await twitch_oauth.cancel_all_twitch_flows() == 1
            store.delete("twitch")

    disconnect_task = asyncio.create_task(disconnect())
    await asyncio.sleep(0)
    assert not disconnect_entered.is_set()

    allow_validation.set()
    result = await polling
    await disconnect_task

    assert result["status"] == "connected"
    assert store.saved["refresh_token"] == "new-refresh"
    assert store.bundle is None
    assert flow_id not in twitch_oauth._flows


@run_async
async def test_disconnect_waits_for_google_callback_exchange_then_removes_saved_tokens(monkeypatch):
    flow_id = "race-google-flow-012345678901234567890123456789"
    store = MemoryStore()
    exchange_started = asyncio.Event()
    allow_exchange = asyncio.Event()

    class OAuthClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, data):
            assert data["code_verifier"] == "pkce-verifier"
            exchange_started.set()
            await allow_exchange.wait()
            return Response({
                "access_token": "google-access",
                "refresh_token": "google-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })

    monkeypatch.setattr(
        google_oauth.httpx,
        "AsyncClient",
        lambda **_kwargs: OAuthClient(),
    )
    flow = {
        "state": "expected-state",
        "verifier": "pkce-verifier",
        "client_id": "google-client",
        "status": "pending",
        "message": "Waiting",
        "expires_at": time.monotonic() + 600,
        "server": None,
        "redirect_uri": "http://127.0.0.1:54321",
        "store_factory": lambda: store,
    }
    google_oauth._GOOGLE_FLOWS[flow_id] = flow

    callback = asyncio.create_task(
        google_oauth._complete_google_callback(
            flow_id,
            {"state": ["expected-state"], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["authorization-code"]},
        )
    )
    await asyncio.wait_for(exchange_started.wait(), timeout=10)

    disconnect_entered = asyncio.Event()

    async def disconnect():
        async with provider_disconnect_lock("youtube"):
            disconnect_entered.set()
            assert await google_oauth.cancel_all_google_flows() == 1
            store.delete("youtube")

    disconnect_task = asyncio.create_task(disconnect())
    await asyncio.sleep(0)
    assert not disconnect_entered.is_set()

    allow_exchange.set()
    await callback
    await disconnect_task

    assert flow["status"] == "cancelled"
    assert store.saved["refresh_token"] == "google-refresh"
    assert store.bundle is None
    assert flow_id not in google_oauth._GOOGLE_FLOWS



@run_async
async def test_google_user_cancellation_waits_for_exchange_and_reports_lost_race(monkeypatch):
    flow_id = "cancel-google-flow-012345678901234567890123456789"
    store = MemoryStore()
    exchange_started = asyncio.Event()
    allow_exchange = asyncio.Event()

    class OAuthClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, data):
            assert data["code_verifier"] == "pkce-verifier"
            exchange_started.set()
            await allow_exchange.wait()
            return Response({
                "access_token": "google-access",
                "refresh_token": "google-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            })

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", lambda **_kwargs: OAuthClient())
    flow = {
        "state": "expected-state",
        "verifier": "pkce-verifier",
        "client_id": "google-client",
        "status": "pending",
        "message": "Waiting",
        "expires_at": time.monotonic() + 600,
        "server": None,
        "redirect_uri": "http://127.0.0.1:54321",
        "store_factory": lambda: store,
    }
    google_oauth._GOOGLE_FLOWS[flow_id] = flow

    callback = asyncio.create_task(google_oauth._complete_google_callback(
        flow_id,
        {"state": ["expected-state"], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["authorization-code"]},
    ))
    await asyncio.wait_for(exchange_started.wait(), timeout=10)
    cancellation = asyncio.create_task(google_oauth.cancel_google_flow(flow_id))
    await asyncio.sleep(0)
    assert cancellation.done() is False

    allow_exchange.set()
    assert await callback == "connected"
    assert await cancellation is False
    assert flow["status"] == "connected"
    assert store.saved["refresh_token"] == "google-refresh"


@run_async
async def test_twitch_user_cancellation_waits_for_device_exchange_and_reports_lost_race():
    flow_id = "cancel-twitch-flow-012345678901234567890123456789"
    store = MemoryStore()
    exchange_started = asyncio.Event()
    allow_exchange = asyncio.Event()

    class OAuthClient:
        async def post(self, _url, data):
            assert data["device_code"] == "device-code"
            exchange_started.set()
            await allow_exchange.wait()
            return Response({
                "access_token": "twitch-access",
                "refresh_token": "twitch-refresh",
                "expires_in": 14400,
            })

        async def get(self, _url, headers=None):
            assert headers["Authorization"] == "OAuth twitch-access"
            return Response({
                "client_id": "twitch-client",
                "scopes": ["chat:read"],
                "user_id": "123",
                "login": "viewer",
            })

    twitch_oauth._flows[flow_id] = {
        "device_code": "device-code",
        "client_id": "twitch-client",
        "expires_at": time.monotonic() + 600,
        "interval": 5,
        "next_poll": 0,
        "status": "pending",
        "message": "Waiting",
    }
    polling = asyncio.create_task(twitch_oauth.poll_twitch_flow(
        flow_id,
        client=OAuthClient(),
        store_factory=lambda: store,
    ))
    await asyncio.wait_for(exchange_started.wait(), timeout=10)
    cancellation = asyncio.create_task(twitch_oauth.cancel_twitch_flow(flow_id))
    await asyncio.sleep(0)
    assert cancellation.done() is False

    allow_exchange.set()
    result = await polling
    assert result["status"] == "connected"
    assert await cancellation is False
    assert twitch_oauth._flows[flow_id]["status"] == "connected"
    assert store.saved["refresh_token"] == "twitch-refresh"


@run_async
async def test_new_provider_oauth_flows_are_rejected_during_disconnect(monkeypatch):
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "twitch-client")
    monkeypatch.setattr(twitch_oauth, "WindowsCredentialStore", lambda: MemoryStore())

    async with provider_disconnect_lock("twitch"):
        with pytest.raises(twitch_oauth.TwitchOAuthError, match="being disconnected"):
            await twitch_oauth.start_twitch_flow(client=object())

    monkeypatch.setattr(google_oauth, "WindowsCredentialStore", lambda: MemoryStore())
    async with provider_disconnect_lock("youtube"):
        with pytest.raises(google_oauth.GoogleOAuthError, match="being disconnected"):
            await google_oauth.start_google_flow(
                client_id="google-client",
                store_factory=lambda: MemoryStore(),
            )


@run_async
async def test_twitch_device_request_started_before_disconnect_cannot_register_a_late_flow(monkeypatch):
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "twitch-client")
    monkeypatch.setattr(twitch_oauth, "WindowsCredentialStore", lambda: MemoryStore())
    request_started = asyncio.Event()
    release_response = asyncio.Event()

    class DeviceClient:
        async def post(self, _url, data):
            request_started.set()
            await release_response.wait()
            return Response({
                "device_code": "one-time-device-code",
                "expires_in": 1800,
                "interval": 5,
                "verification_uri": "https://www.twitch.tv/activate?device-code=USER",
            })

    start = asyncio.create_task(twitch_oauth.start_twitch_flow(client=DeviceClient()))
    await asyncio.wait_for(request_started.wait(), timeout=10)

    async with provider_disconnect_lock("twitch"):
        assert await twitch_oauth.cancel_all_twitch_flows() == 0
    release_response.set()

    with pytest.raises(twitch_oauth.TwitchOAuthError, match="superseded by a disconnect"):
        await start
    assert twitch_oauth._flows == {}


@run_async
async def test_google_listener_started_before_disconnect_cannot_register_a_late_flow(monkeypatch):
    listener_starting = asyncio.Event()
    release_listener = asyncio.Event()

    class FakeSocket:
        def getsockname(self):
            return ("127.0.0.1", 45678)

    class FakeServer:
        sockets = [FakeSocket()]

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    server = FakeServer()

    async def fake_start_server(*_args, **_kwargs):
        listener_starting.set()
        await release_listener.wait()
        return server

    monkeypatch.setattr(google_oauth.asyncio, "start_server", fake_start_server)
    start = asyncio.create_task(
        google_oauth.start_google_flow(
            client_id="google-client",
            store_factory=lambda: MemoryStore(),
        )
    )
    await asyncio.wait_for(listener_starting.wait(), timeout=10)

    async with provider_disconnect_lock("youtube"):
        assert await google_oauth.cancel_all_google_flows() == 0
    release_listener.set()

    with pytest.raises(google_oauth.GoogleOAuthError, match="superseded by a disconnect"):
        await start
    assert server.closed is True
    assert google_oauth._GOOGLE_FLOWS == {}
