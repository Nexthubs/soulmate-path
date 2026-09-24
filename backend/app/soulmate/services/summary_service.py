"""Email Capture Summary Business Service (DEV-SPEC §8.1, SP-302, Decisions: QUIZ-01)."""

import logging
from typing import Any, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session import SoulmateAnswer, SoulmateProfile, SoulmateSession
from app.soulmate.domain.email_summary import (
    build_email_summary,
    get_default_email_summary,
)
from app.soulmate.schema import EmailSummaryResponse

logger = logging.getLogger(__name__)


class SummaryService:
    """Service governing display-ready summary view model generation for Email Capture."""

    @classmethod
    async def get_email_summary_for_session(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
    ) -> EmailSummaryResponse:
        """
        Builds display-ready Email capture summary view model for the session.

        Strategy:
        1. If session has an associated SoulmateProfile row, read normalized profile fields.
        2. Else, inspect session.answers for q02, q03, q05, q06.
        3. If neither are present (e.g. uncompleted quiz preview), return standard demo fallback with is_sample_data=True.

        STRICT INVARIANT (QUIZ-01):
        Visual variant is always determined by preferred_partner_gender (Q03), NEVER by user_gender (Q02).
        """
        # 1. Check for persisted SoulmateProfile
        profile_query = (
            select(SoulmateProfile)
            .where(SoulmateProfile.session_id == session.id)
        )
        res = await db.execute(profile_query)
        profile_rec = res.scalar_one_or_none()

        if profile_rec is not None:
            return build_email_summary(
                preferred_partner_gender=profile_rec.preferred_partner_gender,
                preferred_partner_age_range=profile_rec.preferred_partner_age_range,
                preferred_partner_ethnicity=profile_rec.preferred_partner_ethnicity,
                user_gender=profile_rec.user_gender,
                is_sample_data=False,
            )

        # 2. Check for answers in session
        if "answers" in session.__dict__ and session.answers is not None:
            answers = session.answers
        else:
            ans_res = await db.execute(
                select(SoulmateAnswer).where(SoulmateAnswer.session_id == session.id)
            )
            answers = ans_res.scalars().all()

        answers_map: Dict[str, Any] = {}
        for ans in answers:
            if ans.answer_json and isinstance(ans.answer_json, dict):
                val = ans.answer_json.get("value")
                answers_map[ans.question_code] = val

        q03 = answers_map.get("q03")
        q05 = answers_map.get("q05")
        q06 = answers_map.get("q06")
        q02 = answers_map.get("q02")

        if q03 or q05 or q06:
            return build_email_summary(
                preferred_partner_gender=q03,
                preferred_partner_age_range=q05,
                preferred_partner_ethnicity=q06,
                user_gender=q02,
                is_sample_data=False,
            )

        # 3. Fallback sample demo summary
        return get_default_email_summary()
