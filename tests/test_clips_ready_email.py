"""The clips-ready email goes to dashboard jobs only (``app._notify_clips_ready``).

A job sent with an osk_ key (REST, MCP, OAuth clients) is followed by polling
or the webhook, so mailing its owner on every run is noise."""
import asyncio
from types import SimpleNamespace

import app


def _req(headers):
    return SimpleNamespace(headers=headers)


def test_api_key_detection():
    assert app.request_uses_api_key(_req({"Authorization": "Bearer osk_abc"}))
    assert app.request_uses_api_key(_req({"X-API-Key": "osk_abc"}))
    assert not app.request_uses_api_key(_req({"Authorization": "Bearer eyJhbGciOi"}))
    assert not app.request_uses_api_key(_req({}))


def test_api_job_sends_no_email(monkeypatch):
    monkeypatch.setattr(app, "BILLING_ENABLED", True)
    job = {"user_id": "u1", "status": "completed", "via_api_key": True,
           "result": {"clips": [{"title": "t"}]}}
    monkeypatch.setitem(app.jobs, "job-api", job)
    asyncio.run(app._notify_clips_ready("job-api"))
    assert not job.get("email_sent")
