"""Flow and Step Navigation Business Service (DEV-SPEC §1.1, §4, §5, §6, §15.3, SP-203)."""

from typing import Any, Dict, Optional, Set
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import InvalidFlowStateError, ValidationError
from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.domain.step_resolver import (
    ALL_FLOW_STEPS_SET,
    ALL_QUESTION_CODES,
    calculate_progress_percent,
    get_next_step,
    get_previous_step,
    get_step_type,
    resolve_transition_metadata,
    validate_can_advance_transition,
)
from app.soulmate.schema import FlowStateResponse, TransitionContinueResponse
from app.soulmate.services.profile_service import ProfileService


class FlowService:
    """Central domain service governing flow state progression, navigation, and transitions."""

    @classmethod
    async def get_flow_state(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
    ) -> FlowStateResponse:
        """
        Builds the authoritative flow state representation for the current session.
        Determines current step, type, next/previous step, progress percent,
        and dynamic metadata (e.g. for transition screens).
        """
        if "answers" in session.__dict__ and session.answers is not None:
            answers = session.answers
        else:
            ans_res = await db.execute(
                select(SoulmateAnswer).where(SoulmateAnswer.session_id == session.id)
            )
            answers = ans_res.scalars().all()

        answered_codes: Set[str] = {ans.question_code for ans in answers}
        answers_map: Dict[str, Any] = {
            ans.question_code: ans.answer_json for ans in answers if ans.answer_json
        }

        current_step = session.current_step
        step_type = get_step_type(current_step)
        next_step = get_next_step(current_step)
        previous_step = get_previous_step(current_step)
        progress = calculate_progress_percent(current_step)

        is_quiz_completed = (session.quiz_completed_at is not None) or all(
            q in answered_codes for q in ALL_QUESTION_CODES
        )

        step_metadata: Optional[Dict[str, Any]] = None
        if current_step.startswith("transition_"):
            step_metadata = resolve_transition_metadata(current_step, answers_map)

        return FlowStateResponse(
            session_id=session.public_id,
            current_step=current_step,
            step_type=step_type.value,
            next_step=next_step,
            previous_step=previous_step,
            progress_percent=progress,
            is_quiz_completed=is_quiz_completed,
            step_metadata=step_metadata,
        )

    @classmethod
    async def continue_transition(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        transition_code: str,
    ) -> TransitionContinueResponse:
        """
        Advances a transition screen to its subsequent step after validating prerequisites.
        Guarantees idempotency on network retries.
        """
        if transition_code not in ALL_FLOW_STEPS_SET or not transition_code.startswith("transition_"):
            raise ValidationError(f"Invalid transition code '{transition_code}'.")

        next_step = get_next_step(transition_code)
        if next_step is None:
            raise InvalidFlowStateError(f"Transition '{transition_code}' has no subsequent step.")

        # Idempotent return if already advanced
        if session.current_step == next_step:
            flow_state = await cls.get_flow_state(db, session)
            return TransitionContinueResponse(
                transition_code=transition_code,
                next_step=next_step,
                flow_state=flow_state,
            )

        # Ensure session is currently at this transition
        if session.current_step != transition_code:
            raise InvalidFlowStateError(
                f"Cannot continue '{transition_code}': current active step is '{session.current_step}'.",
                details={"current_step": session.current_step, "transition_code": transition_code},
            )

        # Verify prerequisite questions
        ans_res = await db.execute(
            select(SoulmateAnswer.question_code).where(SoulmateAnswer.session_id == session.id)
        )
        answered_codes = set(ans_res.scalars().all())
        validate_can_advance_transition(transition_code, answered_codes)

        # Advance step
        now = utc_now()
        session.current_step = next_step
        session.updated_at = now

        if transition_code == "transition_5":
            if session.quiz_completed_at is None:
                session.quiz_completed_at = now
            session.status = SessionStatus.QUIZ_COMPLETED.value
            await ProfileService.sync_profile_for_session(db, session, commit=False)
        elif session.status == SessionStatus.CREATED.value:
            session.status = SessionStatus.QUIZ_IN_PROGRESS.value

        await db.commit()
        await db.refresh(session)

        flow_state = await cls.get_flow_state(db, session)
        return TransitionContinueResponse(
            transition_code=transition_code,
            next_step=next_step,
            flow_state=flow_state,
        )

    @classmethod
    async def navigate_back(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
    ) -> FlowStateResponse:
        """
        Moves the session to the previous canonical step.
        Preserves all saved answers without loss or corruption.
        """
        previous_step = get_previous_step(session.current_step)
        if previous_step is None:
            raise InvalidFlowStateError("Cannot navigate back from initial step.")

        session.current_step = previous_step
        session.updated_at = utc_now()
        await db.commit()
        await db.refresh(session)

        return await cls.get_flow_state(db, session)
