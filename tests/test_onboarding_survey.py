"""Sign-up survey (cloud/onboarding.py): who gets asked, what is accepted, and
that the dashboard offers exactly the answers the server accepts."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from cloud import onboarding

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestWhoIsAsked:
    def test_a_new_account_is_asked(self):
        now = datetime.now(timezone.utc)
        assert onboarding.survey_pending(now - timedelta(minutes=2), answered=False)

    def test_an_answer_or_a_skip_ends_it(self):
        assert not onboarding.survey_pending(datetime.now(timezone.utc), answered=True)

    def test_accounts_from_before_the_window_are_left_alone(self):
        old = datetime.now(timezone.utc) - onboarding.SURVEY_MAX_ACCOUNT_AGE - timedelta(hours=1)
        assert not onboarding.survey_pending(old, answered=False)

    def test_unknown_creation_date_is_not_asked(self):
        assert not onboarding.survey_pending(None, answered=False)


class TestValidation:
    def test_a_skip_needs_nothing(self):
        onboarding._validate(onboarding.SurveyAnswer(skipped=True))

    def test_a_real_answer_passes(self):
        onboarding._validate(onboarding.SurveyAnswer(
            source="github", goals=["clips_from_long_videos", "ai_avatar_videos"], role="podcaster"))

    @pytest.mark.parametrize("kw", [
        {"source": "my cousin"}, {"role": "ceo"}, {"goals": ["world domination"]}, {},
    ])
    def test_off_list_or_empty_answers_are_refused(self, kw):
        with pytest.raises(HTTPException) as e:
            onboarding._validate(onboarding.SurveyAnswer(**kw))
        assert e.value.status_code == 422


class TestUiMatchesServer:
    @pytest.mark.parametrize("values", [onboarding.SOURCES, onboarding.GOALS, onboarding.ROLES])
    def test_every_accepted_value_is_offered(self, values):
        ui = open(os.path.join(REPO, "dashboard/src/components/OnboardingSurvey.jsx")).read()
        for value in values:
            assert f"'{value}'" in ui, f"{value} is accepted but never offered"
