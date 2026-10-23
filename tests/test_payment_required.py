"""402s carry a link an AI agent can hand the user (``app.payment_required``).

MCP clients and SDKs often surface only ``message``, so the link travels both
as ``upgrade_url`` and inside the message text."""
from types import SimpleNamespace

import app


def _cfg(monkeypatch):
    monkeypatch.setattr(app, "_cloud_config", SimpleNamespace(
        settings=SimpleNamespace(frontend_url="https://example.test")))


def test_upgrade_url_opens_the_plan_checkout(monkeypatch):
    _cfg(monkeypatch)
    assert app.upgrade_url() == "https://example.test/#/pricing?plan=starter&src=api"


def test_402_has_link_in_field_and_message(monkeypatch):
    _cfg(monkeypatch)
    exc = app.payment_required("quota_exceeded", "Out of minutes.",
                               minutes_required=12, minutes_remaining=0)
    assert exc.status_code == 402
    d = exc.detail
    assert d["error"] == "quota_exceeded"
    assert d["upgrade_url"] == "https://example.test/#/pricing?plan=starter&src=api"
    assert d["upgrade_url"] in d["message"]
    assert d["minutes_required"] == 12 and d["minutes_remaining"] == 0


def test_no_plan_error_carries_the_link(monkeypatch):
    _cfg(monkeypatch)
    monkeypatch.setattr(app, "BILLING_ENABLED", True)
    d = app.gemini_missing_error().detail
    assert d["error"] == "no_plan" and d["upgrade_url"] in d["message"]
