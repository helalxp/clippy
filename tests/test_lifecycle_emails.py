"""Lifecycle emails (cloud/lifecycle.py) and the commercial-email guard.

Until 28-sep-2026 a free sign-up got no email between the magic link and the
out-of-minutes upsell, and an abandoned Stripe Checkout (1,011 of 1,126
sessions) was never followed up.
"""
import asyncio
from types import SimpleNamespace

import pytest

from cloud import emails, lifecycle, marketing, metering


def run(coro):
    return asyncio.run(coro)


class TestAmountLabel:
    def test_usd(self):
        assert lifecycle.amount_label({"amount_total": 1200, "currency": "usd"}) == "$12.00"

    def test_other_currency(self):
        assert lifecycle.amount_label({"amount_total": 990, "currency": "eur"}) == "9.90 EUR"

    def test_missing(self):
        assert lifecycle.amount_label({}) == ""
        assert lifecycle.amount_label({"amount_total": 0, "currency": "usd"}) == ""


class TestPromo:
    def test_unset(self, monkeypatch):
        monkeypatch.delenv("WINBACK_PROMO_CODE", raising=False)
        monkeypatch.setenv("WINBACK_PROMO_LABEL", "50% off")
        assert lifecycle.promo() == ("", "")

    def test_set(self, monkeypatch):
        monkeypatch.setenv("WINBACK_PROMO_CODE", " CODE ")
        monkeypatch.setenv("WINBACK_PROMO_LABEL", "50% off your first month")
        assert lifecycle.promo() == ("CODE", "50% off your first month")


def _expired(url="https://checkout.stripe.com/r/x", user_id="u1", amount=1200):
    return {"after_expiration": {"recovery": {"url": url} if url else None},
            "client_reference_id": user_id, "amount_total": amount, "currency": "usd"}


@pytest.fixture()
def recovery(monkeypatch):
    monkeypatch.delenv("LIFECYCLE_EMAILS_DISABLED", raising=False)
    state = {"claims": set(), "sent": [], "target": SimpleNamespace(id="u1", email="a@b.co")}

    async def _target(user_id):
        return state["target"]

    async def _claim(user_id, kind):
        if (user_id, kind) in state["claims"]:
            return False
        state["claims"].add((user_id, kind))
        return True

    async def _send(user_id, email, url, amount_label=""):
        state["sent"].append((email, url, amount_label))
        return True

    monkeypatch.setattr(lifecycle, "_recovery_target", _target)
    monkeypatch.setattr(lifecycle, "claim", _claim)
    monkeypatch.setattr(emails, "send_checkout_recovery_email", _send)
    return state


class TestCheckoutRecovery:
    def test_sends_the_recovery_url_once(self, recovery):
        assert run(lifecycle.on_checkout_expired(_expired())) is True
        assert recovery["sent"] == [("a@b.co", "https://checkout.stripe.com/r/x", "$12.00")]
        # A second abandoned session does not mail again.
        assert run(lifecycle.on_checkout_expired(_expired())) is False
        assert len(recovery["sent"]) == 1

    def test_no_recovery_url_no_email(self, recovery):
        assert run(lifecycle.on_checkout_expired(_expired(url=None))) is False
        assert recovery["sent"] == []

    def test_no_user_no_email(self, recovery):
        assert run(lifecycle.on_checkout_expired(_expired(user_id=None))) is False
        recovery["target"] = None  # gone, or already paying
        assert run(lifecycle.on_checkout_expired(_expired())) is False
        assert recovery["sent"] == []

    def test_kill_switch(self, recovery, monkeypatch):
        monkeypatch.setenv("LIFECYCLE_EMAILS_DISABLED", "1")
        assert run(lifecycle.on_checkout_expired(_expired())) is False
        assert recovery["sent"] == []

    def test_webhook_dispatches_and_swallows_errors(self, monkeypatch):
        billing = pytest.importorskip("cloud.billing")  # needs the stripe SDK
        seen = []

        async def _boom(obj):
            seen.append(obj)
            raise RuntimeError("smtp down")
        monkeypatch.setattr(lifecycle, "on_checkout_expired", _boom)
        event = {"type": "checkout.session.expired", "created": 1790000000,
                 "data": {"object": {"id": "cs_1"}}}
        run(billing.handle_event(event))  # must not raise: Stripe would retry
        assert seen == [{"id": "cs_1"}]


class TestLoopSend:
    @pytest.fixture()
    def loop_state(self, monkeypatch):
        state = {"claims": [], "sent": []}

        async def _claim(user_id, kind):
            state["claims"].append(kind)
            return True

        async def _processed(user_id):
            return state.get("processed", False)

        def _mk(kind):
            async def _send(user_id, email, *args):
                state["sent"].append((kind, args))
                return True
            return _send

        monkeypatch.setattr(lifecycle, "claim", _claim)
        monkeypatch.setattr(metering, "has_processed_before", _processed)
        monkeypatch.setattr(metering, "free_plan_eligible", lambda u: u.eligible)
        monkeypatch.setattr(emails, "send_welcome_email", _mk("welcome"))
        monkeypatch.setattr(emails, "send_first_clip_email", _mk("first_clip"))
        monkeypatch.setattr(emails, "send_winback_email", _mk("winback"))
        monkeypatch.setattr(lifecycle.config, "FIRST_VIDEO_MAX_MINUTES", 60)
        return state

    def test_welcome_promises_the_first_video(self, loop_state):
        user = SimpleNamespace(id="u", email="e", eligible=True)
        assert run(lifecycle._send("welcome", user)) is True
        assert loop_state["sent"] == [("welcome", (60,))]

    def test_no_free_promise_after_a_processed_video(self, loop_state):
        loop_state["processed"] = True
        user = SimpleNamespace(id="u", email="e", eligible=True)
        run(lifecycle._send("welcome", user))
        assert loop_state["sent"] == [("welcome", (0,))]

    def test_ineligible_account_is_claimed_but_not_mailed(self, loop_state):
        user = SimpleNamespace(id="u", email="e", eligible=False)
        assert run(lifecycle._send("first_clip", user)) is False
        assert loop_state["claims"] == ["first_clip"]  # not picked up again
        assert loop_state["sent"] == []

    def test_winback_carries_the_promo_code(self, loop_state, monkeypatch):
        monkeypatch.setenv("WINBACK_PROMO_CODE", "CODE")
        monkeypatch.setenv("WINBACK_PROMO_LABEL", "50% off")
        user = SimpleNamespace(id="u", email="e", eligible=False)
        assert run(lifecycle._send("winback", user)) is True
        assert loop_state["sent"] == [("winback", ("CODE", "50% off"))]


class TestCommercialEmail:
    @pytest.fixture()
    def outbox(self, monkeypatch):
        sent = []

        async def _send(to, subject, html, headers=None):
            sent.append((to, subject, html, headers))
        monkeypatch.setattr(emails, "send_email", _send)
        monkeypatch.setattr(marketing, "unsubscribe_url", lambda uid: f"https://api/unsub?u={uid}")
        return sent

    def test_opted_out_account_gets_nothing(self, outbox, monkeypatch):
        async def _out(uid):
            return True
        monkeypatch.setattr(marketing, "is_opted_out", _out)
        assert run(emails.send_commercial_email("u1", "a@b.co", "s", "<p>x</p>")) is False
        assert outbox == []

    def test_footer_and_list_unsubscribe(self, outbox, monkeypatch):
        async def _in(uid):
            return False
        monkeypatch.setattr(marketing, "is_opted_out", _in)
        assert run(emails.send_commercial_email("u1", "a@b.co", "s", "<p>x</p>")) is True
        (to, _, html, headers), = outbox
        assert "https://api/unsub?u=u1" in html
        assert headers["List-Unsubscribe"] == "<https://api/unsub?u=u1>"
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
