import logging
import uuid
from typing import Any, Dict, Optional, Sequence, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateProfile, SoulmateSession
from app.quiz.schema import QuizConfig
from app.soulmate.domain.profile import (
    MissingRequiredAnswerError,
    ProfileValidationError,
    SoulmateProfileV1,
    build_soulmate_profile,
)

logger = logging.getLogger(__name__)


class ProfileService:
    """Service for building, persisting, and synchronizing normalized Soulmate profiles."""

    @classmethod
    def build_profile_from_answers(
        cls,
        answers: Union[Dict[str, Any], Sequence[Any]],
        quiz_config: Optional[QuizConfig] = None,
        strict: bool = True,
    ) -> SoulmateProfileV1:
        """Pure domain mapping from raw answers to canonical SoulmateProfileV1."""
        return build_soulmate_profile(
            answers=answers,
            quiz_config=quiz_config,
            strict=strict,
        )

    @classmethod
    async def get_profile_by_session_id(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> Optional[SoulmateProfile]:
        """Fetches the persisted SoulmateProfile row for a given session."""
        stmt = (
            select(SoulmateProfile)
            .where(SoulmateProfile.session_id == session_id)
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def sync_profile_for_session(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        commit: bool = True,
    ) -> Optional[SoulmateProfile]:
        """
        Compiles all saved answers for the session and synchronizes the SoulmateProfile row.
        If answers are incomplete, returns None without creating an incomplete row.
        If all required answers (q02-q18) exist, creates or updates the SoulmateProfile record.
        """
        # Fetch all answers for this session (populate_existing ensures identity map gets DB updates)
        ans_stmt = (
            select(SoulmateAnswer)
            .where(SoulmateAnswer.session_id == session.id)
            .execution_options(populate_existing=True)
        )
        ans_res = await db.execute(ans_stmt)
        saved_answers = ans_res.scalars().all()

        try:
            profile_data = build_soulmate_profile(answers=saved_answers, strict=True)
        except MissingRequiredAnswerError:
            # Quiz is incomplete, profile cannot be materialized yet
            return None
        except ProfileValidationError as exc:
            # Avoid breaking core transition/quiz flow on profile validation failure
            logger.warning(
                f"Profile synchronization skipped for session {session.id}: {exc}",
                extra={"event_type": "profile_sync_error", "session_id": str(session.id)},
            )
            return None

        # Check existing profile
        existing_profile = await cls.get_profile_by_session_id(db, session.id)
        now = utc_now()

        db_dict = profile_data.to_db_dict()

        if existing_profile:
            for k, v in db_dict.items():
                setattr(existing_profile, k, v)
            existing_profile.updated_at = now
            profile_row = existing_profile
        else:
            profile_row = SoulmateProfile(
                session_id=session.id,
                **db_dict,
            )
            profile_row.updated_at = now
            db.add(profile_row)

        if commit:
            await db.commit()
            await db.refresh(profile_row)

        return profile_row
