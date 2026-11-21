import asyncio
import functools

from community_highlights.token_manager import ensure_access_token


def run_async(test_function):
    @functools.wraps(test_function)
    def wrapper(*args, **kwargs):
        return asyncio.run(test_function(*args, **kwargs))
    return wrapper


class FakeStore:
    def __init__(self, bundle):
        self.bundle = bundle
        self.saved = None

    def load(self, provider):
        return self.bundle

    def save(self, provider, bundle):
        self.saved = bundle


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, data):
        self.calls.append(("POST", url, data))
        status, payload = self.responses.pop(0)
        from httpx import Request, Response
        return Response(status, json=payload, request=Request("POST", url))

    async def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, headers, params))
        status, payload = self.responses.pop(0)
        from httpx import Request, Response
        return Response(status, json=payload, request=Request("GET", url))


@run_async
async def test_twitch_refresh_persists_rotated_refresh_token_before_returning_access(monkeypatch):
    monkeypatch.setenv("CLIPPY_TWITCH_CLIENT_ID", "twitch-client")
    store = FakeStore({
        "client_id": "twitch-client",
        "refresh_token": "old-refresh",
        "expires_at": 0,
        "scopes": ["chat:read"],
    })
    client = FakeClient([
        (200, {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 14400}),
        (200, {"client_id": "twitch-client", "scopes": ["chat:read"], "user_id": "1", "login": "viewer"}),
    ])

    token = await ensure_access_token("twitch", store_factory=lambda: store, client=client)

    assert token == "new-access"
    assert store.saved["refresh_token"] == "new-refresh"
    assert store.saved["access_token"] == "new-access"


@run_async
async def test_google_refresh_preserves_existing_refresh_token(monkeypatch):
    monkeypatch.setenv("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    store = FakeStore({
        "client_id": "google-client",
        "refresh_token": "existing-refresh",
        "expires_at": 0,
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
    })
    client = FakeClient([
        (200, {"access_token": "new-access", "expires_in": 3600}),
        (200, {"aud": "google-client", "azp": "google-client", "scope": "https://www.googleapis.com/auth/youtube.readonly"}),
    ])

    token = await ensure_access_token("youtube", store_factory=lambda: store, client=client)

    assert token == "new-access"
    assert store.saved["refresh_token"] == "existing-refresh"
    assert store.saved["access_token"] == "new-access"


@run_async
async def test_google_refresh_rejects_missing_authorized_party(monkeypatch):
    import pytest
    from community_highlights.token_manager import ProviderTokenError

    monkeypatch.setenv("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    store = FakeStore({
        "client_id": "google-client",
        "refresh_token": "existing-refresh",
        "expires_at": 0,
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
    })
    client = FakeClient([
        (200, {"access_token": "new-access", "expires_in": 3600}),
        (200, {"aud": "google-client", "scope": "https://www.googleapis.com/auth/youtube.readonly"}),
    ])

    with pytest.raises(ProviderTokenError):
        await ensure_access_token("youtube", store_factory=lambda: store, client=client)
    assert store.saved is None


@run_async
async def test_google_refresh_accepts_distinct_project_audience_with_matching_authorized_party(monkeypatch):
    monkeypatch.setenv("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    store = FakeStore({
        "client_id": "google-client",
        "refresh_token": "existing-refresh",
        "expires_at": 0,
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
    })
    client = FakeClient([
        (200, {"access_token": "new-access", "expires_in": 3600}),
        (200, {
            "aud": "another-client-in-same-project",
            "azp": "google-client",
            "scope": "https://www.googleapis.com/auth/youtube.readonly",
        }),
    ])

    token = await ensure_access_token("youtube", store_factory=lambda: store, client=client)

    assert token == "new-access"
    assert store.saved["client_id"] == "google-client"


@run_async
async def test_google_refresh_rejects_non_object_provider_responses(monkeypatch):
    import pytest
    from community_highlights.token_manager import ProviderTokenError

    monkeypatch.setenv("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    store = FakeStore({
        "client_id": "google-client",
        "refresh_token": "existing-refresh",
        "expires_at": 0,
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
    })
    client = FakeClient([
        (200, ["not", "an", "object"]),
    ])

    with pytest.raises(ProviderTokenError):
        await ensure_access_token("youtube", store_factory=lambda: store, client=client)
    assert store.saved is None
