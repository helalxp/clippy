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
    await refresh_started.wait()

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
    await validation_started.wait()

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
    tokeninfo_started = asyncio.Event()
    allow_tokeninfo = asyncio.Event()

    class OAuthClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, data):
            assert data["code_verifier"] == "pkce-verifier"
            return Response({
                "access_token": "google-access",
                "refresh_token": "google-refresh",
                "expires_in": 3600,
            })

        async def get(self, _url, params=None):
            tokeninfo_started.set()
            await allow_tokeninfo.wait()
            return Response({
                "aud": "another-client-in-same-project",
                "azp": "google-client",
                "scope": google_oauth.GOOGLE_SCOPE,
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
            {"state": ["expected-state"], "code": ["authorization-code"]},
        )
    )
    await tokeninfo_started.wait()

    disconnect_entered = asyncio.Event()

    async def disconnect():
        async with provider_disconnect_lock("youtube"):
            disconnect_entered.set()
            assert await google_oauth.cancel_all_google_flows() == 1
            store.delete("youtube")

    disconnect_task = asyncio.create_task(disconnect())
    await asyncio.sleep(0)
    assert not disconnect_entered.is_set()

    allow_tokeninfo.set()
    await callback
    await disconnect_task

    assert flow["status"] == "cancelled"
    assert store.saved["refresh_token"] == "google-refresh"
    assert store.bundle is None
    assert flow_id not in google_oauth._GOOGLE_FLOWS


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
