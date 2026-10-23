"""Password sign-in for the app-directory review account: off unless both env
vars are set, and never a way in for any other email. The database-backed
success path is exercised against prod after deploy."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cloud import auth


def _client():
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def test_disabled_without_both_env_vars(monkeypatch):
    monkeypatch.delenv("REVIEW_LOGIN_EMAIL", raising=False)
    monkeypatch.setenv("REVIEW_LOGIN_PASSWORD", "pw")
    assert not auth.review_login_enabled()
    r = _client().post("/api/auth/review-login", json={"email": "a@b.com", "password": "pw"})
    assert r.status_code == 401


def test_wrong_email_or_password_is_refused(monkeypatch):
    monkeypatch.setenv("REVIEW_LOGIN_EMAIL", "Review@Example.com")
    monkeypatch.setenv("REVIEW_LOGIN_PASSWORD", "correct-horse")
    c = _client()
    assert c.post("/api/auth/review-login",
                  json={"email": "other@example.com", "password": "correct-horse"}).status_code == 401
    assert c.post("/api/auth/review-login",
                  json={"email": "review@example.com", "password": "wrong"}).status_code == 401
