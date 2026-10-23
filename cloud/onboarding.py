"""Sign-up survey: where the user heard of us and what they came to make.

``signup_attribution`` records the referrer, and 94% of it is brand traffic
from the GitHub repo or a direct visit, which says nothing about *why*: a
creator who wants clips from a podcast and one who wants AI avatar ads land on
the same page. Three closed questions asked once, right after sign-up, answer
that. One screen, skippable; a skip is stored too so it is never asked twice
and the skip rate is itself measurable.

Closed lists so the answers can be counted; the only free text is the "other"
source, capped short. The row is user-owned and goes with the account.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import analytics, database
from .auth import get_current_user_required
from .models import OnboardingSurvey, User

router = APIRouter()

# Mirror the lists in dashboard/src/components/OnboardingSurvey.jsx.
SOURCES = (
    "google", "ai_assistant", "youtube", "tiktok_instagram", "x_twitter", "reddit",
    "github", "friend", "directory", "newsletter_blog", "other",
)
GOALS = (
    "clips_from_long_videos", "ai_avatar_videos", "autopilot_posting", "thumbnails",
    "subtitles", "dubbing", "api_agents", "self_host",
)
ROLES = (
    "creator", "podcaster", "streamer_gamer", "agency", "business_marketing",
    "educator", "developer", "other",
)

# Only accounts this young are asked. Everyone who signed up before the survey
# shipped would otherwise get it on their next visit, and a returning user's
# "how did you hear about us" is a memory, not an attribution.
SURVEY_MAX_ACCOUNT_AGE = timedelta(days=7)
OTHER_MAX = 120


class SurveyAnswer(BaseModel):
    skipped: bool = False
    source: Optional[str] = None
    source_other: Optional[str] = Field(default=None, max_length=OTHER_MAX)
    goals: List[str] = Field(default_factory=list, max_length=len(GOALS))
    role: Optional[str] = None


def _validate(a: SurveyAnswer):
    if a.skipped:
        return
    if a.source is not None and a.source not in SOURCES:
        raise HTTPException(status_code=422, detail="Unknown source.")
    if a.role is not None and a.role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown role.")
    if any(g not in GOALS for g in a.goals):
        raise HTTPException(status_code=422, detail="Unknown goal.")
    if not (a.source or a.goals or a.role):
        raise HTTPException(status_code=422, detail="Answer at least one question, or skip.")


def survey_pending(user_created_at: Optional[datetime], answered: bool) -> bool:
    """Whether /api/me should ask the dashboard to show the survey."""
    if answered or user_created_at is None:
        return False
    return datetime.now(timezone.utc) - user_created_at <= SURVEY_MAX_ACCOUNT_AGE


async def is_pending(session, user) -> bool:
    answered = (await session.execute(
        select(OnboardingSurvey.user_id).where(OnboardingSurvey.user_id == user.id)
    )).scalar_one_or_none() is not None
    created = (await session.execute(
        select(User.created_at).where(User.id == user.id)
    )).scalar_one_or_none()
    return survey_pending(created, answered)


@router.post("/api/onboarding/survey")
async def answer_survey(body: SurveyAnswer, request: Request):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    user = await get_current_user_required(request)
    _validate(body)
    goals = [] if body.skipped else list(dict.fromkeys(body.goals))
    source = None if body.skipped else body.source
    other = (body.source_other or "").strip()[:OTHER_MAX] or None
    if source != "other":
        other = None
    role = None if body.skipped else body.role
    async with database.session() as session:
        async with session.begin():
            # First answer wins: two tabs, or a double click, must not overwrite.
            await session.execute(pg_insert(OnboardingSurvey).values(
                user_id=user.id, skipped=body.skipped, source=source,
                source_other=other, goals=goals, role=role,
            ).on_conflict_do_nothing(index_elements=["user_id"]))

    if body.skipped:
        analytics.track("SignupSurveySkipped", user_id=user.id)
    else:
        # One flat prop per goal so OpenPanel can break the event down by each,
        # which it cannot do with a list.
        analytics.track("SignupSurveyAnswered", user_id=user.id, source=source,
                        role=role, goals=",".join(goals) or None,
                        **{f"goal_{g}": True for g in goals})
    return {"ok": True}
