import asyncio
import functools
from urllib.parse import parse_qs, urlencode, urlsplit

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
    assert query["prompt"] == ["consent"]
    assert "gmail" not in query["scope"][0].lower()

    await google_oauth.cancel_google_flow(result["flow_id"])


@run_async
async def test_google_loopback_callback_rejects_invalid_requests_then_completes_valid_pkce_flow(monkeypatch):
    store = FakeCredentialStore()
    requests = mock_google_token_exchange(monkeypatch, {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": google_oauth.GOOGLE_SCOPE,
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]
    server = flow["server"]
    port = server.sockets[0].getsockname()[1]

    async def callback_response(parameters):
        query = urlencode(parameters)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = (
            f"GET /?{query} HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response.split(b"\r\n", 1)[0]

    invalid_callbacks = [
        [("state", "attacker-state"), ("iss", google_oauth.GOOGLE_ISSUER), ("code", "bad-code")],
        [("state", flow["state"]), ("iss", "https://attacker.example"), ("code", "bad-code")],
        [("state", flow["state"]), ("state", "duplicate-state"), ("iss", google_oauth.GOOGLE_ISSUER), ("code", "bad-code")],
        [("state", flow["state"]), ("iss", google_oauth.GOOGLE_ISSUER), ("code", "first-code"), ("code", "second-code")],
        [("state", flow["state"]), ("iss", google_oauth.GOOGLE_ISSUER), ("code", "bad-code"), ("error", "access_denied")],
    ]
    for parameters in invalid_callbacks:
        response_line = await callback_response(parameters)
        assert response_line.startswith(b"HTTP/1.1 400")
        assert (await google_oauth.google_flow_status(started["flow_id"]))["status"] == "pending"
        assert server.is_serving() is True

    expected_verifier = flow["verifier"]
    response_line = await callback_response([
        ("state", flow["state"]),
        ("iss", google_oauth.GOOGLE_ISSUER),
        ("code", "test-authorization-code"),
    ])
    assert response_line.startswith(b"HTTP/1.1 200")
    assert (await google_oauth.google_flow_status(started["flow_id"]))["status"] == "connected"
    assert store.saved is not None
    assert store.saved["access_token"] == "test-access-token"
    assert store.saved["refresh_token"] == "test-refresh-token"
    assert store.saved["client_id"] == "desktop-client-id"
    assert store.saved["scopes"] == [google_oauth.GOOGLE_SCOPE]
    assert len(requests) == 1
    assert requests[0].method == "POST"
    fields = parse_qs(requests[0].content.decode("ascii"))
    assert fields["client_id"] == ["desktop-client-id"]
    assert fields["code"] == ["test-authorization-code"]
    assert fields["code_verifier"] == [expected_verifier]
    assert fields["redirect_uri"] == [flow["redirect_uri"]]
    assert server.is_serving() is False


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
    assert flow["server"].is_serving() is False
    assert await google_oauth.cancel_google_flow(result["flow_id"]) is False


class FakeCredentialStore:
    def __init__(self, *, fail_save=False, bundle=None):
        self.bundle = bundle
        self.saved = None
        self.fail_save = fail_save

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
async def test_google_initial_authorization_does_not_reuse_previous_refresh_token(monkeypatch):
    store = FakeCredentialStore(bundle={
        "client_id": "desktop-client-id",
        "refresh_token": "old-account-refresh-token",
    })
    mock_google_token_exchange(monkeypatch, {
        "access_token": "new-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": google_oauth.GOOGLE_SCOPE,
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]

    await google_oauth._complete_google_callback(
        started["flow_id"],
        {"state": [flow["state"]], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["new-authorization-code"]},
    )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "error"
    assert store.saved is None
    assert store.bundle["refresh_token"] == "old-account-refresh-token"
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
            {"state": [flow["state"]], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["secret-authorization-code"]},
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
        "token_type": "Bearer",
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
            {"state": [flow["state"]], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["secret-authorization-code"]},
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
        "token_type": "Bearer",
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
            {"state": [flow["state"]], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["test-authorization-code"]},
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
        "token_type": "Bearer",
        "expires_in": 3600,
    })
    started = await google_oauth.start_google_flow(
        client_id="desktop-client-id",
        store_factory=lambda: store,
    )
    flow = google_oauth._GOOGLE_FLOWS[started["flow_id"]]

    await google_oauth._complete_google_callback(
        started["flow_id"],
        {"state": [flow["state"]], "iss": [google_oauth.GOOGLE_ISSUER], "code": ["test-authorization-code"]},
    )

    status = await google_oauth.google_flow_status(started["flow_id"])
    assert status["status"] == "connected"
    assert store.saved["scopes"] == [google_oauth.GOOGLE_SCOPE]

    await google_oauth.cancel_google_flow(started["flow_id"])

