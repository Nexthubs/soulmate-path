"""Answer Submission and Upsert Domain Service (DEV-SPEC §4, §14, §15.3, SP-202)."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import ValidationError
from app.db.base import utc_now
from app.db.models.quiz import SoulmateQuizVersion
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.quiz.constants import CANONICAL_QUIZ_VERSION
from app.quiz.loader import get_cached_quiz_config
from app.quiz.schema import QuestionType, QuizConfig, QuizQuestion
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.domain.step_resolver import (
    resolve_next_step_for_question,
    validate_can_submit_question,
)
from app.soulmate.domain.zodiac import get_zodiac_for_date
from app.soulmate.schema import AnswerSubmitRequest, AnswerSubmitResponse
from app.soulmate.services.profile_service import ProfileService




class AnswerService:
    """Handles question answer validation, atomic upsert, and flow step progression."""

    @classmethod
    async def submit_answer(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        question_code: str,
        req: AnswerSubmitRequest,
    ) -> AnswerSubmitResponse:
        """
        Validates answer payload against session's quiz version and atomically
        persists answer row into soulmate_answers (DEV-SPEC §15.3).
        """
        # 1. Retrieve quiz configuration matching the session's pinned version
        config = await cls._get_quiz_config(db, session.quiz_version)

        # 2. Locate question definition
        question = next((q for q in config.questions if q.code == question_code), None)
        if question is None:
            raise ValidationError(
                f"Question '{question_code}' does not exist in quiz version '{session.quiz_version}'."
            )

        # 2.5 Flow step & skip prevention guard (DEV-SPEC §15.3, SP-203)
        ans_stmt = select(SoulmateAnswer.question_code).where(SoulmateAnswer.session_id == session.id)
        ans_res = await db.execute(ans_stmt)
        answered_codes = set(ans_res.scalars().all())
        validate_can_submit_question(question_code, session.current_step, answered_codes)

        # 3. Validate type-specific payload and option membership
        answer_payload = cls._validate_payload(question, req)


        # 4. Atomic PostgreSQL upsert to prevent duplicates from rapid double-taps
        now = utc_now()
        stmt = pg_insert(SoulmateAnswer).values(
            session_id=session.id,
            question_code=question_code,
            answer_json=answer_payload,
            duration_ms=req.duration_ms,
            answered_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_soulmate_answers_session_question",
            set_={
                "answer_json": stmt.excluded.answer_json,
                "duration_ms": stmt.excluded.duration_ms,
                "updated_at": now,
            },
        )
        await db.execute(stmt)

        # 5. Advance session state and step
        next_step = resolve_next_step_for_question(question_code)
        session.current_step = next_step
        if session.status == SessionStatus.CREATED.value:
            session.status = SessionStatus.QUIZ_IN_PROGRESS.value
        session.updated_at = now

        # 6. If quiz was already completed, recalculate normalized profile (DEV-SPEC §7)
        if session.quiz_completed_at is not None:
            await ProfileService.sync_profile_for_session(db, session, commit=False)

        await db.commit()

        zodiac_resp = None
        if question_code == "q08" and "zodiac_sign" in answer_payload:
            zodiac_resp = {
                "sign": answer_payload["zodiac_sign"],
                "label": answer_payload["zodiac_label"],
            }

        return AnswerSubmitResponse(
            saved=True,
            question_code=question_code,
            next_step=next_step,
            zodiac=zodiac_resp,
        )


    @classmethod
    async def _get_quiz_config(cls, db: AsyncSession, quiz_version: str) -> QuizConfig:
        """Loads quiz configuration pinned to the given version from cache or DB."""
        if quiz_version == CANONICAL_QUIZ_VERSION:
            return get_cached_quiz_config()

        # Query immutable quiz version record from DB (DEV-SPEC §4.5, §15.2)
        stmt = select(SoulmateQuizVersion).where(SoulmateQuizVersion.version == quiz_version)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        if record and record.config_json:
            return QuizConfig.model_validate(record.config_json)

        raise ValidationError(f"Unknown or unseeded quiz version: '{quiz_version}'.")

    @classmethod
    def _validate_payload(
        cls,
        question: QuizQuestion,
        req: AnswerSubmitRequest,
    ) -> Dict[str, Any]:
        """
        Strictly validates answer value(s) against question type, options, and boundaries.
        Returns the sanitized dictionary to be stored in answer_json.
        """
        if question.type == QuestionType.SINGLE:
            return cls._validate_single(question, req)
        elif question.type == QuestionType.DATE:
            return cls._validate_date(question, req)
        elif question.type == QuestionType.MULTI:
            return cls._validate_multi(question, req)
        else:
            raise ValidationError(f"Unsupported question type '{question.type}'.")

    @staticmethod
    def _validate_single(question: QuizQuestion, req: AnswerSubmitRequest) -> Dict[str, Any]:
        if req.values is not None:
            raise ValidationError(
                f"Single-choice question '{question.code}' does not accept 'values' array."
            )
        if not req.value or not req.value.strip():
            raise ValidationError(
                f"Missing required 'value' for single-choice question '{question.code}'."
            )

        cleaned_value = req.value.strip()
        valid_options = {opt.code for opt in (question.options or [])}
        if cleaned_value not in valid_options:
            raise ValidationError(
                f"Invalid option code '{cleaned_value}' for question '{question.code}'."
            )

        return {"value": cleaned_value}

    @staticmethod
    def _validate_date(question: QuizQuestion, req: AnswerSubmitRequest) -> Dict[str, Any]:
        if req.values is not None:
            raise ValidationError(
                f"Date question '{question.code}' does not accept 'values' array."
            )
        if not req.value or not req.value.strip():
            raise ValidationError(
                f"Missing required 'value' for date question '{question.code}'."
            )

        cleaned_date_str = req.value.strip()
        try:
            parsed_date = datetime.strptime(cleaned_date_str, "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError(
                f"Invalid date format '{cleaned_date_str}' for question '{question.code}'. Expected YYYY-MM-DD."
            )

        # Real calendar date & non-future check (DEV-SPEC §4.4, DECISIONS.md AGE-01: no unapproved age floor invented)
        if parsed_date > date.today():
            raise ValidationError("Birth date cannot be in the future.")

        # Compute server-authoritative zodiac (DEV-SPEC §4.4, §5.5, SP-204)
        zodiac = get_zodiac_for_date(parsed_date)

        return {
            "value": cleaned_date_str,
            "zodiac_sign": zodiac.name,
            "zodiac_label": zodiac.sun_label,
            "zodiac_element": zodiac.element,
        }


    @staticmethod
    def _validate_multi(question: QuizQuestion, req: AnswerSubmitRequest) -> Dict[str, Any]:
        if req.value is not None:
            raise ValidationError(
                f"Multi-choice question '{question.code}' does not accept single 'value'."
            )
        if req.values is None:
            raise ValidationError(
                f"Missing required 'values' array for multi-choice question '{question.code}'."
            )

        # Deduplicate while preserving order (Acceptance criteria)
        deduped_values: List[str] = list(dict.fromkeys(v.strip() for v in req.values if isinstance(v, str) and v.strip()))

        min_select = question.min_select or 1
        if len(deduped_values) < min_select:
            raise ValidationError(
                f"Question '{question.code}' requires at least {min_select} selection(s), received {len(deduped_values)}."
            )

        if question.max_select and len(deduped_values) > question.max_select:
            raise ValidationError(
                f"Question '{question.code}' accepts at most {question.max_select} selection(s), received {len(deduped_values)}."
            )

        valid_options = {opt.code for opt in (question.options or [])}
        invalid_codes = [c for c in deduped_values if c not in valid_options]
        if invalid_codes:
            raise ValidationError(
                f"Invalid option code(s) {invalid_codes} for question '{question.code}'."
            )

        return {"values": deduped_values}
