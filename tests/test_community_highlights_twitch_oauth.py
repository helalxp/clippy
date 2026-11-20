import asyncio
import functools
import time

import httpx
import pytest



def run_async(test_function):
    @functools.wraps(test_function)
    def wrapper(*args, **kwargs):
        return asyncio.run(test_function(*args, **kwargs))
    return wrapper

from community_highlights import twitch_oauth


class FakeStore:
    def __init__(self):
        self.saved = {}

    def save(self, provider, bundle):
        self.saved[provider] = bundle


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def post(self, url, data):
        self.requests.append(("POST", url, data))
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

    async def get(self, url, headers=None):
        self.requests.append(("GET", url, headers))
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload, request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def reset_flows(monkeypatch):
    twitch_oauth._flows.clear()
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "public-client-id")
    monkeypatch.setattr(twitch_oauth, "WindowsCredentialStore", lambda: FakeStore())


@run_async
async def test_start_flow_returns_prefilled_browser_url_but_never_device_code():
    client = FakeClient([(
        200,
        {
            "device_code": "server-only-device-code",
            "expires_in": 1800,
            "interval": 5,
            "verification_uri": "https://www.twitch.tv/activate?public=true&device-code=USERCODE",
        },
    )])

    result = await twitch_oauth.start_twitch_flow(client)

    assert result["verification_url"].startswith("https://www.twitch.tv/activate?")
    assert "device_code" not in result
    assert "server-only-device-code" not in repr(result)
    assert client.requests[0][2] == {"client_id": "public-client-id", "scopes": "chat:read"}


@run_async
async def test_start_flow_rejects_non_twitch_activation_urls():
    client = FakeClient([(
        200,
        {
            "device_code": "secret",
            "expires_in": 1800,
            "interval": 5,
            "verification_uri": "https://attacker.example/collect",
        },
    )])

    with pytest.raises(twitch_oauth.TwitchOAuthError, match="unexpected activation URL"):
        await twitch_oauth.start_twitch_flow(client)


@run_async
async def test_poll_flow_waits_for_authorization_without_exposing_device_code():
    client = FakeClient([
        (400, {"message": "authorization_pending"}),
    ])
    twitch_oauth._flows["opaque-flow-id-012345678901234567890123456789"] = {
        "device_code": "never-return-this",
        "client_id": "public-client-id",
        "expires_at": time.monotonic() + 600,
        "interval": 5,
        "next_poll": 0,
        "status": "pending",
        "message": "Waiting",
    }

    result = await twitch_oauth.poll_twitch_flow(
        "opaque-flow-id-012345678901234567890123456789", client=client
    )

    assert result["status"] == "pending"
    assert "never-return-this" not in repr(result)


@run_async
async def test_poll_flow_validates_client_and_scope_before_persisting_credentials():
    flow_id = "opaque-flow-id-012345678901234567890123456789"
    twitch_oauth._flows[flow_id] = {
        "device_code": "server-only",
        "client_id": "public-client-id",
        "expires_at": time.monotonic() + 600,
        "interval": 5,
        "next_poll": 0,
        "status": "pending",
        "message": "Waiting",
    }
    client = FakeClient([
        (200, {
            "access_token": "access-value",
            "refresh_token": "refresh-value",
            "expires_in": 14400,
        }),
        (200, {
            "client_id": "public-client-id",
            "user_id": "1234",
            "login": "viewer",
            "scopes": ["chat:read"],
        }),
    ])
    store = FakeStore()

    result = await twitch_oauth.poll_twitch_flow(
        flow_id, client=client, store_factory=lambda: store
    )

    assert result["status"] == "connected"
    assert store.saved["twitch"]["access_token"] == "access-value"
    assert store.saved["twitch"]["refresh_token"] == "refresh-value"
    assert "device_code" not in twitch_oauth._flows[flow_id]


@run_async
async def test_poll_flow_rejects_token_for_wrong_client():
    flow_id = "opaque-flow-id-012345678901234567890123456789"
    twitch_oauth._flows[flow_id] = {
        "device_code": "server-only",
        "client_id": "public-client-id",
        "expires_at": time.monotonic() + 600,
        "interval": 5,
        "next_poll": 0,
        "status": "pending",
        "message": "Waiting",
    }
    client = FakeClient([
        (200, {"access_token": "access-value", "refresh_token": "refresh-value"}),
        (200, {"client_id": "another-client", "scopes": ["chat:read"]}),
    ])
    store = FakeStore()

    result = await twitch_oauth.poll_twitch_flow(
        flow_id, client=client, store_factory=lambda: store
    )

    assert result["status"] == "error"
    assert store.saved == {}


@run_async
async def test_cancel_flow_discards_device_code():
    flow_id = "opaque-flow-id-012345678901234567890123456789"
    twitch_oauth._flows[flow_id] = {"device_code": "secret", "status": "pending"}

    assert await twitch_oauth.cancel_twitch_flow(flow_id) is True
    assert flow_id not in twitch_oauth._flows
