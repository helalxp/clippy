import asyncio
import functools
from urllib.parse import parse_qs, urlsplit

import pytest
import httpx

from community_highlights.credentials import CredentialStoreError



def run_async(test_function):
    @functools.wraps(test_function)
    def wrapper(*args, **kwargs):
        return asyncio.run(test_function(*args, **kwargs))
    return wrapper

from community_highlights import google_oauth


@pytest.fixture(autouse=True)
def reset_google_flows():
    google_oauth._GOOGLE_FLOWS.clear()
    yield
    for flow in google_oauth._GOOGLE_FLOWS.values():
        server = flow.get("server")
        if server:
            server.close()
    google_oauth._GOOGLE_FLOWS.clear()


@run_async
async def test_google_flow_uses_loopback_pkce_and_youtube_readonly_scope():
    result = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: object(),
    )

    query = parse_qs(urlsplit(result["authorization_url"]).query)
    flow = google_oauth._GOOGLE_FLOWS[result["flow_id"]]

    assert query["client_id"] == ["desktop-client-id"]
    assert query["redirect_uri"][0].startswith("http://127.0.0.1:")
    assert query["redirect_uri"][0].endswith(str(flow["server"].sockets[0].getsockname()[1]))
    assert query["scope"] == [google_oauth.GOOGLE_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] != [flow["verifier"]]
    assert query["state"] == [flow["state"]]
    assert "gmail" not in query["scope"][0].lower()

    await google_oauth.cancel_google_flow(result["flow_id"])


@run_async
async def test_google_callback_rejects_invalid_state():
    result = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: object(),
    )

    await google_oauth._complete_google_callback(
        result["flow_id"],
        {"state": ["attacker-state"], "code": ["authorization-code"]},
    )

    assert google_oauth._GOOGLE_FLOWS[result["flow_id"]]["status"] == "error"
    await google_oauth.cancel_google_flow(result["flow_id"])


@run_async
async def test_google_flow_status_expires_and_cancels_callback_listener():
    result = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: object(),
    )
    flow = google_oauth._GOOGLE_FLOWS[result["flow_id"]]
    flow["expires_at"] = 0

    status = await google_oauth.google_flow_status(result["flow_id"])

    assert status["status"] == "expired"
    assert await google_oauth.cancel_google_flow(result["flow_id"]) is True


def test_google_tokeninfo_requires_our_authorized_party_but_allows_project_audience():
    matches = google_oauth.google_token_info_matches_client

    # Google documents that aud may differ from azp for OAuth clients in the
    # same Cloud project. The requesting client (azp) is the binding we check.
    assert matches({"aud": "another-client.apps.googleusercontent.com", "azp": "desktop-client-id"}, "desktop-client-id")
    assert not matches({"aud": "desktop-client-id"}, "desktop-client-id")
    assert not matches({"aud": "desktop-client-id", "azp": "another-client"}, "desktop-client-id")
    assert not matches({"aud": "", "azp": "desktop-client-id"}, "desktop-client-id")
    assert not matches(None, "desktop-client-id")

class FakeCredentialStore:
    def __init__(self, *, fail_save=False):
        self.bundle = None
        self.saved = None
        self.fail_save = fail_save

    def load(self, provider):
        assert provider == "youtube"
        return self.bundle

    def save(self, provider, bundle):
        assert provider == "youtube"
        if self.fail_save:
            raise CredentialStoreError("Windows Credential Manager could not save the provider credentials.")
        self.saved = dict(bundle)
        self.bundle = dict(bundle)


def mock_google_token_exchange(monkeypatch, payload, *, status_code=200):
    requests = []
    transport = httpx.MockTransport(
        lambda request: (
            requests.append(request)
            or httpx.Response(status_code, json=payload, request=request)
        )
    )
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        google_oauth.httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_async_client(*args, transport=transport, **kwargs),
    )
    return requests


@run_async
async def test_google_callback_uses_token_response_scope_and_saves_credentials(monkeypatch):
    store = FakeCredentialStore()
    requests = mock_google_token_exchange(monkeypatch, {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_in": 3600,
        "scope": google_oauth.GOOGLE_SCOPE,
        "token_type": "Bearer",
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]
    expected_verifier = flow["verifier"]

    await google_oauth._complete_google_callback(
        started["flow_id"],
        {"state": [flow["state"]], "code": ["test-authorization-code"]},
    )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "connected"
    assert store.saved is not None
    assert store.saved["access_token"] == "test-access-token"
    assert store.saved["refresh_token"] == "test-refresh-token"
    assert store.saved["client_id"] == "desktop-client-id"
    assert store.saved["scopes"] == [google_oauth.GOOGLE_SCOPE]
    # Initial authorization is completed by the PKCE-bound token exchange;
    # it no longer makes a second tokeninfo request.
    assert len(requests) == 1
    assert requests[0].method == "POST"
    fields = parse_qs(requests[0].content.decode("ascii"))
    assert fields["client_id"] == ["desktop-client-id"]
    assert fields["code"] == ["test-authorization-code"]
    assert fields["code_verifier"] == [expected_verifier]
    assert fields["redirect_uri"] == [flow["redirect_uri"]]

    await google_oauth.cancel_google_flow(started["flow_id"])



@run_async
async def test_google_callback_logs_safe_provider_error_description(monkeypatch, caplog):
    store = FakeCredentialStore()
    mock_google_token_exchange(
        monkeypatch,
        {
            "error": "invalid_request",
            "error_description": "Missing required parameter: code_verifier",
        },
        status_code=400,
    )
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]

    with caplog.at_level("WARNING", logger=google_oauth.__name__):
        await google_oauth._complete_google_callback(
            started["flow_id"],
            {"state": [flow["state"]], "code": ["secret-authorization-code"]},
        )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "error"
    assert "phase=authorization_code_exchange" in caplog.text
    assert "provider_error=invalid_request" in caplog.text
    assert "provider_error_description=Missing required parameter: code_verifier" in caplog.text
    assert "secret-authorization-code" not in caplog.text
    assert store.saved is None

    await google_oauth.cancel_google_flow(started["flow_id"])

@run_async
async def test_google_callback_reports_safe_credential_save_diagnostic(monkeypatch, caplog):
    store = FakeCredentialStore(fail_save=True)
    mock_google_token_exchange(monkeypatch, {
        "access_token": "secret-access-value",
        "refresh_token": "secret-refresh-value",
        "expires_in": 3600,
        "scope": google_oauth.GOOGLE_SCOPE,
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]

    with caplog.at_level("WARNING", logger=google_oauth.__name__):
        await google_oauth._complete_google_callback(
            started["flow_id"],
            {"state": [flow["state"]], "code": ["secret-authorization-code"]},
        )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "error"
    assert "phase=credential_store_save" in caplog.text
    assert "Windows Credential Manager could not save" in caplog.text
    assert "secret-access-value" not in caplog.text
    assert "secret-refresh-value" not in caplog.text
    assert "secret-authorization-code" not in caplog.text
    assert store.saved is None

    await google_oauth.cancel_google_flow(started["flow_id"])


@run_async
async def test_google_callback_rejects_token_response_without_youtube_scope(monkeypatch, caplog):
    store = FakeCredentialStore()
    mock_google_token_exchange(monkeypatch, {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_in": 3600,
        "scope": "openid",
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]

    with caplog.at_level("WARNING", logger=google_oauth.__name__):
        await google_oauth._complete_google_callback(
            started["flow_id"],
            {"state": [flow["state"]], "code": ["test-authorization-code"]},
        )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "error"
    assert "phase=scope_validation" in caplog.text
    assert store.saved is None

    await google_oauth.cancel_google_flow(started["flow_id"])

@run_async
async def test_google_callback_accepts_omitted_scope_when_it_matches_requested_scope(monkeypatch):
    store = FakeCredentialStore()
    mock_google_token_exchange(monkeypatch, {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_in": 3600,
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]

    await google_oauth._complete_google_callback(
        started["flow_id"],
        {"state": [flow["state"]], "code": ["test-authorization-code"]},
    )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "connected"
    assert store.saved["scopes"] == [google_oauth.GOOGLE_SCOPE]

    await google_oauth.cancel_google_flow(started["flow_id"])

