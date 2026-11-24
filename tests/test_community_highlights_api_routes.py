import logging

from fastapi.testclient import TestClient

import app as backend_app
import community_highlights.api as community_api
from community_highlights.twitch_oauth import TwitchOAuthError
from community_highlights.credentials import CredentialStoreError


class FakeCredentialStore:
    def __init__(self):
        self.bundle = None

    def load(self, _provider):
        return self.bundle


def _client(monkeypatch, *, credential_store_factory=FakeCredentialStore):
    monkeypatch.setattr(backend_app, "_DESKTOP_API_TOKEN", "test-desktop-session-token")
    monkeypatch.setattr(community_api, "WindowsCredentialStore", credential_store_factory)
    monkeypatch.setattr(community_api, "twitch_authorization_available", lambda: True)
    monkeypatch.setattr(community_api, "google_authorization_available", lambda: True)
    # Do not enter TestClient as a context manager: these route tests must not
    # start the application's long-running lifespan workers.
    return TestClient(backend_app.app, raise_server_exceptions=True)


def _headers():
    return {"X-Clippy-Token": "test-desktop-session-token"}


def test_connections_route_is_registered_and_requires_desktop_session(monkeypatch, caplog):
    client = _client(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="clippy.community_highlights"):
        denied = client.get("/api/community-highlights/connections")
    assert denied.status_code == 401
    assert "route=/api/community-highlights/connections" in caplog.text

    response = client.get("/api/community-highlights/connections", headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["credential_storage_available"] is True
    assert payload["providers"]["twitch"]["authorization_available"] is True
    assert payload["providers"]["youtube"]["authorization_available"] is True


def test_community_highlights_fails_closed_when_desktop_token_is_missing(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(backend_app, "_DESKTOP_API_TOKEN", "")

    response = client.get(
        "/api/community-highlights/connections",
        headers={"X-Clippy-Token": "caller-supplied-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "This local Clippy API requires its active desktop session token."


def test_twitch_authorization_start_status_cancel_routes(monkeypatch):
    flow_id = "t" * 40

    async def start():
        return {"flow_id": flow_id, "verification_uri": "https://example.test/activate"}

    async def status(_flow_id):
        return {"status": "pending"}

    async def cancel(_flow_id):
        return True

    monkeypatch.setattr(community_api, "start_twitch_flow", start)
    monkeypatch.setattr(community_api, "poll_twitch_flow", status)
    monkeypatch.setattr(community_api, "cancel_twitch_flow", cancel)
    client = _client(monkeypatch)

    started = client.post("/api/community-highlights/twitch/authorize", headers=_headers())
    assert started.status_code == 200
    assert started.json()["flow_id"] == flow_id
    assert client.get(f"/api/community-highlights/twitch/authorize/{flow_id}", headers=_headers()).json() == {"status": "pending"}
    stopped = client.delete(f"/api/community-highlights/twitch/authorize/{flow_id}", headers=_headers())
    assert stopped.status_code == 200
    assert stopped.json() == {"cancelled": True}


def test_google_authorization_start_status_cancel_routes(monkeypatch):
    flow_id = "g" * 40

    async def start():
        return {"flow_id": flow_id, "status": "pending"}

    async def status(_flow_id):
        return {"status": "pending"}

    async def cancel(_flow_id):
        return False

    monkeypatch.setattr(community_api, "start_google_flow", start)
    monkeypatch.setattr(community_api, "google_flow_status", status)
    monkeypatch.setattr(community_api, "cancel_google_flow", cancel)
    client = _client(monkeypatch)

    started = client.post("/api/community-highlights/youtube/authorize", headers=_headers())
    assert started.status_code == 200
    assert started.json()["flow_id"] == flow_id
    assert client.get(f"/api/community-highlights/youtube/authorize/{flow_id}", headers=_headers()).json() == {"status": "pending"}
    stopped = client.delete(f"/api/community-highlights/youtube/authorize/{flow_id}", headers=_headers())
    assert stopped.status_code == 200
    assert stopped.json() == {"cancelled": False}


def test_start_chat_session_returns_actionable_validation_error_without_logging_stream_url(monkeypatch, caplog):
    stream_url = "https://www.youtube.com/@private_creator"

    async def reject_stream(_stream_url):
        raise ValueError("Use a YouTube live or video URL, not a channel or playlist URL.")

    monkeypatch.setattr(community_api.chat_sessions, "start", reject_stream)
    client = _client(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="clippy.community_highlights"):
        response = client.post(
            "/api/community-highlights/sessions",
            headers=_headers(),
            json={"stream_url": stream_url},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Use a YouTube live or video URL, not a channel or playlist URL."
    assert "route=/api/community-highlights/sessions" in caplog.text
    assert stream_url not in caplog.text
    assert stream_url not in response.text


def test_google_authorization_flow_invalidated_by_backend_restart_is_reported_as_expired(monkeypatch):
    from community_highlights import google_oauth

    # OAuth state and its loopback listener are intentionally process-local.
    # A backend restart clears them; the next poll must report expiry, not
    # leave the frontend stuck in a pending authorization state.
    google_oauth._GOOGLE_FLOWS.clear()
    flow_id = "g" * 40
    client = _client(monkeypatch)

    response = client.get(
        f"/api/community-highlights/youtube/authorize/{flow_id}",
        headers=_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "This sign-in attempt has expired. Start again."


def test_not_found_diagnostics_use_route_template_and_never_log_flow_ids_or_query(monkeypatch, caplog):
    flow_id = "private-flow-id-" + ("x" * 32)

    async def missing(_flow_id):
        raise TwitchOAuthError("Sign-in attempt not found.")

    monkeypatch.setattr(community_api, "poll_twitch_flow", missing)
    client = _client(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="clippy.community_highlights"):
        response = client.get(
            f"/api/community-highlights/twitch/authorize/{flow_id}?code=do-not-log-this",
            headers=_headers(),
        )

    assert response.status_code == 404
    assert "route=/api/community-highlights/twitch/authorize/{flow_id}" in caplog.text
    assert flow_id not in caplog.text
    assert "do-not-log-this" not in caplog.text
    assert "test-desktop-session-token" not in caplog.text


def test_unknown_community_highlights_route_returns_404_and_logs_redacted_path(monkeypatch, caplog):
    client = _client(monkeypatch)
    unknown_id = "z" * 40

    with caplog.at_level(logging.WARNING, logger="clippy.community_highlights"):
        response = client.get(
            f"/api/community-highlights/unknown/{unknown_id}?access_token=never-log",
            headers=_headers(),
        )

    assert response.status_code == 404
    assert "/<id>" in caplog.text
    assert unknown_id not in caplog.text
    assert "never-log" not in caplog.text


def test_unknown_route_diagnostic_strips_log_line_breaks(monkeypatch, caplog):
    client = _client(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="clippy.community_highlights"):
        response = client.get(
            "/api/community-highlights/unknown/%0d%0aFORGED-LOG-LINE",
            headers=_headers(),
        )
    assert response.status_code == 404
    assert "FORGED-LOG-LINE" in caplog.text
    assert "\\nFORGED-LOG-LINE" not in caplog.text
    assert "\\r" not in caplog.text


def test_candidate_delete_route_reports_success_and_missing_candidate(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(community_api.capture_sessions, "delete_candidate", lambda _candidate_id: True)
    response = client.delete(
        "/api/community-highlights/candidates/candidate-123",
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json() == {"deleted": True}

    monkeypatch.setattr(community_api.capture_sessions, "delete_candidate", lambda _candidate_id: False)
    missing = client.delete(
        "/api/community-highlights/candidates/missing",
        headers=_headers(),
    )
    assert missing.status_code == 404


def test_candidate_delete_route_reports_conflict_when_media_cannot_be_removed(monkeypatch):
    client = _client(monkeypatch)

    def locked(_candidate_id):
        raise PermissionError("private filesystem detail")

    monkeypatch.setattr(community_api.capture_sessions, "delete_candidate", locked)
    response = client.delete(
        "/api/community-highlights/candidates/candidate-locked",
        headers=_headers(),
    )
    assert response.status_code == 409
    assert "private filesystem detail" not in response.text


def test_twitch_disconnect_stops_chat_and_removes_local_credentials_after_confirmed_revoke(monkeypatch):
    store = FakeCredentialStore()
    store.bundle = {
        "client_id": "twitch-client",
        "access_token": "twitch-access-secret",
        "refresh_token": "twitch-refresh-secret",
    }
    store.delete = lambda provider: setattr(store, "bundle", None)
    events = []

    async def begin(provider):
        events.append(("begin", provider))

    async def finish(provider):
        events.append(("finish", provider))

    async def revoke(bundle):
        assert bundle["access_token"] == "twitch-access-secret"
        events.append(("revoke", "twitch"))
        return True

    monkeypatch.setattr(community_api.chat_sessions, "begin_provider_disconnect", begin)
    monkeypatch.setattr(community_api.chat_sessions, "end_provider_disconnect", finish)
    monkeypatch.setattr(community_api, "revoke_twitch_credentials", revoke)
    client = _client(monkeypatch, credential_store_factory=lambda: store)

    response = client.delete("/api/community-highlights/connections/twitch", headers=_headers())

    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["revocation_status"] == "revoked"
    assert store.bundle is None
    assert events == [("begin", "twitch"), ("revoke", "twitch"), ("finish", "twitch")]
    assert "twitch-access-secret" not in response.text


def test_google_disconnect_is_local_even_when_remote_revocation_cannot_be_confirmed(monkeypatch):
    store = FakeCredentialStore()
    store.bundle = {
        "client_id": "google-client",
        "access_token": "google-access-secret",
        "refresh_token": "google-refresh-secret",
    }
    store.delete = lambda provider: setattr(store, "bundle", None)
    events = []

    async def begin(provider):
        events.append(("begin", provider))

    async def finish(provider):
        events.append(("finish", provider))

    async def revoke(_bundle):
        events.append(("revoke", "youtube"))
        return False

    monkeypatch.setattr(community_api.chat_sessions, "begin_provider_disconnect", begin)
    monkeypatch.setattr(community_api.chat_sessions, "end_provider_disconnect", finish)
    monkeypatch.setattr(community_api, "revoke_google_credentials", revoke)
    client = _client(monkeypatch, credential_store_factory=lambda: store)

    response = client.delete("/api/community-highlights/connections/youtube", headers=_headers())

    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["revocation_status"] == "not_confirmed"
    assert "did not confirm revocation" in response.json()["message"]
    assert store.bundle is None
    assert events == [("begin", "youtube"), ("revoke", "youtube"), ("finish", "youtube")]
    assert "google-refresh-secret" not in response.text


def test_disconnect_preserves_local_credentials_when_credential_manager_delete_fails(monkeypatch):
    store = FakeCredentialStore()
    store.bundle = {"access_token": "still-saved"}
    store.delete = lambda _provider: (_ for _ in ()).throw(CredentialStoreError("storage unavailable"))
    events = []

    async def no_sessions(_provider):
        events.append("begin")

    async def end_sessions(_provider):
        events.append("end")

    async def revoke(_bundle):
        return True

    monkeypatch.setattr(community_api.chat_sessions, "begin_provider_disconnect", no_sessions)
    monkeypatch.setattr(community_api.chat_sessions, "end_provider_disconnect", end_sessions)
    monkeypatch.setattr(community_api, "revoke_twitch_credentials", revoke)
    client = _client(monkeypatch, credential_store_factory=lambda: store)

    response = client.delete("/api/community-highlights/connections/twitch", headers=_headers())

    assert response.status_code == 503
    assert store.bundle["access_token"] == "still-saved"
    assert events == ["begin", "end"]

def test_candidate_file_route_serves_browser_preview_mp4(monkeypatch, tmp_path):
    candidate_id = "candidate-preview-123"
    media = tmp_path / "candidate-preview.mp4"
    media.write_bytes(b"browser-preview")
    monkeypatch.setattr(
        community_api.capture_sessions,
        "get_candidate",
        lambda requested_id: (
            {"candidate_id": requested_id, "status": "ready"},
            media,
        ) if requested_id == candidate_id else None,
    )
    client = _client(monkeypatch)

    response = client.get(
        f"/api/community-highlights/candidates/{candidate_id}/file",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["content-disposition"].endswith('.mp4"')
    assert response.content == b"browser-preview"
