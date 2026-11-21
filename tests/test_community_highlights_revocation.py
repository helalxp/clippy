import asyncio
import functools
import httpx

from community_highlights.revocation import (
    GOOGLE_REVOKE_URL,
    TWITCH_REVOKE_URL,
    revoke_google_credentials,
    revoke_twitch_credentials,
)


def run_async(test_function):
    @functools.wraps(test_function)
    def wrapper(*args, **kwargs):
        return asyncio.run(test_function(*args, **kwargs))
    return wrapper


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    def __init__(self, status_code=200, error=None):
        self.status_code = status_code
        self.error = error
        self.calls = []

    async def post(self, url, data):
        self.calls.append((url, data))
        if self.error:
            raise self.error
        return FakeResponse(self.status_code)


@run_async
async def test_google_revocation_posts_refresh_token_in_form_body_and_never_url(monkeypatch):
    monkeypatch.setenv("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    client = FakeClient()
    bundle = {
        "client_id": "google-client",
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
    }

    assert await revoke_google_credentials(bundle, client=client) is True
    assert client.calls == [(GOOGLE_REVOKE_URL, {"token": "refresh-secret"})]
    assert "refresh-secret" not in client.calls[0][0]


@run_async
async def test_twitch_revocation_uses_only_the_matching_public_client_and_access_token(monkeypatch):
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "twitch-client")
    client = FakeClient()
    bundle = {
        "client_id": "twitch-client",
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
    }

    assert await revoke_twitch_credentials(bundle, client=client) is True
    assert client.calls == [(
        TWITCH_REVOKE_URL,
        {"client_id": "twitch-client", "token": "access-secret"},
    )]
    assert "refresh-secret" not in repr(client.calls)


@run_async
async def test_provider_revoke_refusal_and_network_failure_are_not_reported_as_success(monkeypatch):
    monkeypatch.setenv("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    bundle = {"client_id": "google-client", "refresh_token": "refresh-secret"}

    assert await revoke_google_credentials(bundle, client=FakeClient(status_code=400)) is False
    assert await revoke_google_credentials(
        bundle,
        client=FakeClient(error=httpx.ConnectError("network detail")),
    ) is False


@run_async
async def test_revocation_refuses_bundle_from_another_oauth_client(monkeypatch):
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "twitch-client")
    client = FakeClient()

    assert await revoke_twitch_credentials(
        {"client_id": "different-client", "access_token": "access-secret"},
        client=client,
    ) is False
    assert client.calls == []
