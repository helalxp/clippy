import asyncio
import functools
from urllib.parse import parse_qs, urlsplit

import pytest



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
