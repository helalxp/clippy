"""In-app cancellation: ask why, ask for a review, then cancel.

Cancelling used to happen only inside the Stripe Customer Portal, so the one
moment a paying customer tells us what went wrong produced nothing but a
"🔻 Subscription canceled" alert with no reason in it. This endpoint is the
dashboard's cancel flow: the reason (closed list, so it can be counted), an
optional free-text detail, a 1-5 rating and an optional review, stored in
``cancellation_feedback`` and then passed on to Stripe as
``cancellation_details`` so the Stripe dashboard shows the same reason.

The cancel is ``cancel_at_period_end``, never immediate: they paid for the
period and keep it. The portal stays available and can still cancel without
this form; the webhook alert carries Stripe's own ``cancellation_details`` for
those.

Before the cancel, the last step offers the retention coupon (the portal's
"Stay with us: 50% off for 3 months", ``RETENTION_COUPON``). Cancelling was
turned off in the portal on 2026-09-28 so this flow, with its offer, is the only
way out. The offer is made once per subscription (``retention_offer`` in its
Stripe metadata), only on a live monthly plan with no discount on it: on a
yearly plan it would halve a whole year. Taking it stores the same feedback row
with ``outcome="retained"``. ``/api/billing/resume`` undoes a scheduled cancel,
since the portal's "renew" goes with its cancel feature.

Unlike ``account.DELETION_REASONS``, free text is fine here: these rows belong
to the user (``account.USER_OWNED_TABLES``) and go with the account. What must
not happen is the text reaching Telegram (see ``alerts.user_ref``), so the
alert says how long the review is, never what it says.
"""
import asyncio
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import analytics, database
from .auth import get_current_user_required
from .models import CancellationFeedback, Subscription

router = APIRouter()

# Mirrors the REASONS list in dashboard/src/components/CancelPlanModal.jsx.
# Each maps to the closest value of Stripe's own cancellation_details.feedback
# enum, so the reason also shows up on the subscription in Stripe.
CANCEL_REASONS = {
    "too_expensive": "too_expensive",
    "not_using_it": "unused",
    "clip_quality": "low_quality",
    "missing_feature": "missing_features",
    "found_alternative": "switched_service",
    "too_complex": "too_complex",
    "support": "customer_service",
    "one_off_project": "unused",
    "other": "other",
}

# States in which there is a renewal to stop. past_due is included: a customer
# whose card failed and who wants out should not have to fix the card first.
CANCELLABLE_STATES = ("active", "trialing", "past_due")

MAX_TEXT = 2000

# The Stripe coupon offered before a cancel (env, like every coupon id; see
# CLAUDE.md). Unset turns the offer off and the flow is reason -> review -> cancel.
RETENTION_COUPON = os.environ.get("RETENTION_COUPON_ID", "").strip()


class CancelRequest(BaseModel):
    reason: str
    details: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    review: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    review_public_ok: bool = False


def _stripe_cancel_at_period_end(subscription_id: str, feedback: str, comment: str):
    # Imported here so the module (and its tests) load where stripe is not
    # installed, as in CI.
    import stripe
    stripe.Subscription.modify(
        subscription_id,
        cancel_at_period_end=True,
        cancellation_details={"feedback": feedback, "comment": comment},
    )


def _stripe_offer_blocked(subscription_id: str) -> bool:
    """True when this subscription already has a discount or had the offer."""
    import stripe
    live = stripe.Subscription.retrieve(subscription_id)
    return bool(live.get("discounts") or live.get("discount")
                or (live.get("metadata") or {}).get("retention_offer"))


_coupon_terms = {}


def _stripe_coupon_terms(coupon_id: str) -> dict:
    if coupon_id not in _coupon_terms:
        import stripe
        c = stripe.Coupon.retrieve(coupon_id)
        if not c.get("valid") or not c.get("percent_off"):
            return {}
        _coupon_terms[coupon_id] = {"percent_off": int(c["percent_off"]),
                                    "months": c.get("duration_in_months")}
    return _coupon_terms[coupon_id]


def _stripe_apply_retention(subscription_id: str, coupon_id: str):
    import stripe
    stripe.Subscription.modify(
        subscription_id,
        discounts=[{"coupon": coupon_id}],
        metadata={"retention_offer": "accepted"},
    )


def _stripe_resume(subscription_id: str):
    import stripe
    stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)


def _clean(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None


async def _renewing_sub(user_id) -> Subscription:
    """The user's subscription, if it is live and still set to renew."""
    async with database.session() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )).scalar_one_or_none()
    if not sub or sub.status not in CANCELLABLE_STATES:
        raise HTTPException(status_code=409, detail="There is no active subscription to cancel.")
    if sub.cancel_at_period_end:
        raise HTTPException(status_code=409, detail="Your subscription is already set to cancel.")
    return sub


async def _offer_for(sub) -> Optional[dict]:
    """The retention offer's terms for this subscription, or None."""
    if not RETENTION_COUPON or sub.status != "active" or sub.interval != "month":
        return None
    try:
        if await asyncio.to_thread(_stripe_offer_blocked, sub.stripe_subscription_id):
            return None
        return await asyncio.to_thread(_stripe_coupon_terms, RETENTION_COUPON) or None
    except Exception as e:
        # No offer is better than a cancel flow that cannot reach its last step.
        print(f"⚠️  Retention offer check failed for {sub.stripe_subscription_id}: {e}")
        return None


@router.get("/api/billing/retention-offer")
async def retention_offer(request: Request):
    user = await get_current_user_required(request)
    sub = await _renewing_sub(user.id)
    offer = await _offer_for(sub)
    return {"eligible": bool(offer), **(offer or {})}


@router.post("/api/billing/retention-offer/accept")
async def accept_retention_offer(body: CancelRequest, request: Request):
    user = await get_current_user_required(request)
    if body.reason not in CANCEL_REASONS:
        raise HTTPException(status_code=422, detail="Pick a reason from the list.")
    sub = await _renewing_sub(user.id)
    offer = await _offer_for(sub)
    if not offer:
        raise HTTPException(status_code=409, detail="This offer is no longer available.")
    try:
        await asyncio.to_thread(_stripe_apply_retention, sub.stripe_subscription_id,
                                RETENTION_COUPON)
    except Exception as e:
        print(f"⚠️  Retention coupon failed for {user.id}: {e}")
        raise HTTPException(status_code=502, detail=(
            "We couldn't apply the discount right now. Please try again, "
            "or email info@openshorts.app."))

    details, review = _clean(body.details), _clean(body.review)
    async with database.session() as session:
        async with session.begin():
            session.add(CancellationFeedback(
                user_id=user.id,
                stripe_subscription_id=sub.stripe_subscription_id,
                plan=sub.plan, interval=sub.interval,
                reason=body.reason, details=details,
                rating=body.rating, review=review,
                review_public_ok=bool(body.review_public_ok and review),
                outcome="retained",
            ))

    analytics.track("RetentionOfferAccepted", user_id=user.id, plan=sub.plan,
                    reason=body.reason, rating=body.rating)

    from .alerts import send_admin_alert, user_ref
    term = f" for {offer['months']} months" if offer.get("months") else ""
    await send_admin_alert(
        "🛟 Cancel saved",
        f"{user_ref(user.id)} was about to cancel the {sub.plan} plan "
        f"(reason: {body.reason}) and took {offer['percent_off']}% off{term}.",
    )
    return {"ok": True, **offer}


@router.post("/api/billing/resume")
async def resume_subscription(request: Request):
    user = await get_current_user_required(request)
    async with database.session() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )).scalar_one_or_none()
    if not sub or sub.status not in CANCELLABLE_STATES or not sub.cancel_at_period_end:
        raise HTTPException(status_code=409, detail="There is no scheduled cancellation to undo.")
    try:
        await asyncio.to_thread(_stripe_resume, sub.stripe_subscription_id)
    except Exception as e:
        print(f"⚠️  Stripe resume failed for {user.id}: {e}")
        raise HTTPException(status_code=502, detail=(
            "We couldn't resume your subscription right now. Please try again, "
            "or email info@openshorts.app."))
    async with database.session() as session:
        async with session.begin():
            row = (await session.execute(
                select(Subscription).where(Subscription.id == sub.id).with_for_update()
            )).scalar_one_or_none()
            if row is not None:
                row.cancel_at_period_end = False
    analytics.track("SubscriptionResumed", user_id=user.id, plan=sub.plan)
    from .alerts import send_admin_alert, user_ref
    await send_admin_alert("🔺 Cancel undone",
                           f"{user_ref(user.id)} resumed the {sub.plan} plan.")
    return {"ok": True}


@router.post("/api/billing/cancel")
async def cancel_subscription(body: CancelRequest, request: Request):
    user = await get_current_user_required(request)
    if body.reason not in CANCEL_REASONS:
        raise HTTPException(status_code=422, detail="Pick a reason from the list.")
    sub = await _renewing_sub(user.id)

    details, review = _clean(body.details), _clean(body.review)
    # Stripe caps the comment at 5000 chars; ours are 2000 each.
    comment = " | ".join(x for x in (details, review) if x) or None
    try:
        await asyncio.to_thread(
            _stripe_cancel_at_period_end, sub.stripe_subscription_id,
            CANCEL_REASONS[body.reason], comment or "")
    except Exception as e:
        print(f"⚠️  Stripe cancel failed for {user.id}: {e}")
        raise HTTPException(status_code=502, detail=(
            "We couldn't cancel your subscription right now. Please try again, "
            "or email info@openshorts.app."))

    # Written after Stripe accepted the cancel, so a failed call leaves no
    # feedback row claiming a cancellation that never happened. Flipping
    # cancel_at_period_end here (instead of waiting for the webhook) makes the
    # account page show it at once, and makes the webhook see no False -> True
    # transition, so the generic churn alert does not fire on top of this one.
    async with database.session() as session:
        async with session.begin():
            session.add(CancellationFeedback(
                user_id=user.id,
                stripe_subscription_id=sub.stripe_subscription_id,
                plan=sub.plan, interval=sub.interval,
                reason=body.reason, details=details,
                rating=body.rating, review=review,
                review_public_ok=bool(body.review_public_ok and review),
                outcome="canceled",
            ))
            row = (await session.execute(
                select(Subscription).where(Subscription.id == sub.id).with_for_update()
            )).scalar_one_or_none()
            if row is not None:
                row.cancel_at_period_end = True

    analytics.track("SubscriptionCanceled", user_id=user.id, plan=sub.plan,
                    interval=sub.interval, reason=body.reason, rating=body.rating,
                    has_review=bool(review))

    from .alerts import send_admin_alert, user_ref
    stars = f"{body.rating}/5" if body.rating else "no rating"
    written = []
    if details:
        written.append(f"detail {len(details)} chars")
    if review:
        written.append(f"review {len(review)} chars"
                       + (", OK to quote" if body.review_public_ok else ""))
    await send_admin_alert(
        "🔻 Subscription canceled",
        f"{user_ref(user.id)} canceled the {sub.plan} ({sub.interval}) plan.\n"
        f"Reason: {body.reason}. Rating: {stars}.\n"
        f"{'; '.join(written) or 'No written feedback'} (cancellation_feedback table).\n"
        f"Access continues until {sub.current_period_end:%Y-%m-%d}.",
    )
    return {"ok": True, "period_end": sub.current_period_end.isoformat()}
