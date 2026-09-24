"""Session Business Service for Creation, Recovery, and State Formatting (DEV-SPEC §6, §15.1)."""

from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db.models.session import SoulmateSession
from app.quiz.constants import CANONICAL_QUIZ_VERSION
from app.soulmate.domain.session_state import INITIAL_SESSION_STATUS, INITIAL_STEP_CODE
from app.soulmate.schema import SessionCreateResponse, SessionCurrentResponse
from app.soulmate.security import generate_public_id, generate_session_token


class SessionService:
    """Encapsulates session creation, persistence, and state formatting."""

    @staticmethod
    async def create_session(
        db: AsyncSession,
        utm_json: Optional[Dict[str, Any]] = None,
        quiz_version: Optional[str] = None,
    ) -> Tuple[SoulmateSession, str]:
        """
        Creates an anonymous Soulmate session with irrevocably pinned quiz_version.
        Generates and returns (SoulmateSession, signed_session_token).
        """
        public_id = generate_public_id()
        version = quiz_version or CANONICAL_QUIZ_VERSION

        session = SoulmateSession(
            public_id=public_id,
            quiz_version=version,
            status=INITIAL_SESSION_STATUS.value,
            current_step=INITIAL_STEP_CODE,
            utm_json=utm_json or {},
        )

        db.add(session)
        await db.flush()
        await db.refresh(session)

        token = generate_session_token(public_id)
        return session, token

    @staticmethod
    async def get_session_by_public_id(
        db: AsyncSession,
        public_id: str,
    ) -> Optional[SoulmateSession]:
        """Loads a SoulmateSession by public_id eagerly fetching its answers."""
        query = (
            select(SoulmateSession)
            .options(selectinload(SoulmateSession.answers))
            .where(SoulmateSession.public_id == public_id)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def format_create_response(session: SoulmateSession) -> SessionCreateResponse:
        """Formats the initial session creation response per DEV-SPEC §15.1."""
        return SessionCreateResponse(
            session_id=session.public_id,
            quiz_version=session.quiz_version,
            current_step=session.current_step,
            status=session.status,
        )

    @staticmethod
    def format_current_response(session: SoulmateSession) -> SessionCurrentResponse:
        """
        Formats the full session response for recovery/refresh.
        Exposes current step, status, and saved answers for UI restoration.
        """
        answers_map: Dict[str, Dict[str, Any]] = {}
        for ans in session.answers or []:
            answer_payload = dict(ans.answer_json) if ans.answer_json else {}
            answers_map[ans.question_code] = {
                "question_code": ans.question_code,
                "answer": answer_payload,
                "value": answer_payload.get("value"),
                "values": answer_payload.get("values"),
                "duration_ms": ans.duration_ms,
                "answered_at": ans.answered_at.isoformat() if ans.answered_at else None,
            }

        return SessionCurrentResponse(
            session_id=session.public_id,
            quiz_version=session.quiz_version,
            status=session.status,
            current_step=session.current_step,
            email=session.email,
            quiz_completed_at=session.quiz_completed_at,
            answers=answers_map,
            saved_answers_count=len(answers_map),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
