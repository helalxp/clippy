"""Invoice webhooks must find the subscription on current Stripe API versions.

Since API 2025-03-31 an invoice carries the subscription under
``parent.subscription_details.subscription``; reading the old top-level field
made ``invoice.payment_failed`` / ``invoice.paid`` silent no-ops.
"""
import asyncio
from datetime import datetime, timezone

import pytest

billing = pytest.importorskip("cloud.billing")  # needs the stripe SDK

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def _invoice(reason="subscription_cycle", legacy=False):
    inv = {"id": "in_1", "billing_reason": reason}
    if legacy:
        inv["subscription"] = "sub_1"
    else:
        inv["parent"] = {"type": "subscription_details",
                         "subscription_details": {"subscription": "sub_1"}}
    return inv


@pytest.fixture()
def calls(monkeypatch):
    seen = []

    async def fake(sub_obj, status, event_created, only_from=None):
        seen.append((sub_obj["id"], status, only_from))
    monkeypatch.setattr(billing, "_set_subscription_status", fake)
    return seen


@pytest.mark.parametrize("legacy", [False, True])
def test_subscription_id_read_from_new_and_legacy_shapes(legacy):
    assert billing._invoice_subscription_id(_invoice(legacy=legacy)) == "sub_1"


def test_subscription_id_missing_or_expanded():
    assert billing._invoice_subscription_id({"id": "in_1"}) is None
    assert billing._invoice_subscription_id({"subscription": {"id": "sub_9"}}) == "sub_9"


def test_failed_renewal_moves_live_subscription_to_past_due(calls):
    asyncio.run(billing._set_subscription_status_by_invoice(_invoice(), "past_due", NOW))
    assert calls == [("sub_1", "past_due", frozenset({"active", "trialing"}))]


def test_failed_first_charge_leaves_incomplete_row_alone(calls):
    # Otherwise the row reads past_due, which blocks the user's checkout retry.
    asyncio.run(billing._set_subscription_status_by_invoice(
        _invoice("subscription_create"), "past_due", NOW))
    assert calls == []


def test_paid_invoice_only_revives_dunning_states(calls):
    asyncio.run(billing._set_subscription_status_by_invoice(_invoice(), "active", NOW))
    assert calls == [("sub_1", "active", frozenset({"past_due", "unpaid"}))]
    assert "canceled" not in calls[0][2]
