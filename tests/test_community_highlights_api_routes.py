import logging

from fastapi.testclient import TestClient

import app as backend_app
import community_highlights.api as community_api
from community_highlights.twitch_oauth import TwitchOAuthError


class FakeCredentialStore:
    def load(self, _provider):
        return None


def _client(monkeypatch):
    monkeypatch.setattr(backend_app, "_DESKTOP_API_TOKEN", "test-desktop-session-token")
    monkeypatch.setattr(community_api, "WindowsCredentialStore", FakeCredentialStore)
    monkeypatch.setattr(community_api, "twitch_authorization_available", lambda: True)
    monkeypatch.setattr(community_api, "google_authorization_available", lambda: True)
    # Do not enter TestClient as a context manager: these route tests must not
    # start the application's long-running lifespan workers.
    return TestClient(backend_app.app, raise_server_exceptions=False)


def _headers():
    return {"X-Clippy-Token": "test-desktop-session-token"}


def test_connections_route_is_registered_and_requires_desktop_session(monkeypatch):
    client = _client(monkeypatch)

    denied = client.get("/api/community-highlights/connections")
    assert denied.status_code == 401

    response = client.get("/api/community-highlights/connections", headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["credential_storage_available"] is True
    assert payload["providers"]["twitch"]["authorization_available"] is True
    assert payload["providers"]["youtube"]["authorization_available"] is True


def test_twitch_authorization_start_status_cancel_routes(monkeypatch):
    flow_id = "t" * 40

    async def start():
        return {"flow_id": flow_id, "verification_uri": "https://example.test/activate"}

    async def status(_flow_id):
        return {"status": "pending"}

    async def cancel(_flow_id):
        return None

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
        return None

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
    assert stopped.json() == {"cancelled": True}


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
