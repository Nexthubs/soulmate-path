"""Soulmate Identity and Email Binding Service (DEV-SPEC §8, §15.5, §20, SP-301)."""

import logging
from typing import Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.session import SoulmateSession
from app.soulmate.domain.identity import (
    derive_user_id_for_email,
    validate_and_normalize_email,
)
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.schema import EmailCaptureResponse

logger = logging.getLogger(__name__)


class IdentityService:
    """Encapsulates email validation, identity normalization, and session account binding."""

    @classmethod
    async def capture_and_bind_email(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        email_input: str,
    ) -> EmailCaptureResponse:
        """
        Validates and normalizes email, binds anonymous session to consistent user identity
        using the existing account model, preserves session ownership, and advances flow state.

        Guarantees:
        - Normalized email and derived/existing user_id are consistent for downstream one-email-one-sketch logic.
        - Session ownership is strictly preserved; cannot bind or corrupt another user's session.
        - No password or authentication framework is invented.
        - Idempotent on repeated submissions.
        - Raw email is treated as PII and excluded from structured analytics logs (DEV-SPEC §18.2, §20).
        """
        # 1. Validate and normalize email
        raw_email, email_normalized = validate_and_normalize_email(email_input)

        # 2. Identity binding using existing account model (SoulmateSession.user_id)
        now = utc_now()
        if session.user_id is None:
            # Check if a prior session with this normalized email already possesses an assigned user_id
            existing_user_query = (
                select(SoulmateSession.user_id)
                .where(
                    SoulmateSession.email_normalized == email_normalized,
                    SoulmateSession.user_id.isnot(None),
                )
                .limit(1)
            )
            result = await db.execute(existing_user_query)
            existing_user_id = result.scalar_one_or_none()

            if existing_user_id is not None:
                # Bind to existing user identity
                session.user_id = existing_user_id
            else:
                # Assign deterministic canonical user identity derived from normalized email
                session.user_id = derive_user_id_for_email(email_normalized)

        # 3. Update session email and audit fields
        session.email = raw_email
        session.email_normalized = email_normalized
        session.email_captured_at = now
        session.updated_at = now

        # 4. Advance status if prior to EMAIL_CAPTURED (do not overwrite later checkout/subscribed states)
        if session.status in (
            SessionStatus.CREATED.value,
            SessionStatus.QUIZ_IN_PROGRESS.value,
            SessionStatus.QUIZ_COMPLETED.value,
        ):
            session.status = SessionStatus.EMAIL_CAPTURED.value

        # 5. Advance flow step if currently at email step
        if session.current_step == "email":
            session.current_step = "subscribe"

        await db.commit()
        await db.refresh(session)

        # 6. Non-PII structured analytics event (DEV-SPEC §18.2, §20)
        logger.info(
            "Email captured and identity bound",
            extra={
                "event_type": "email_captured",
                "session_id": str(session.id),
                "public_id": session.public_id,
                "user_id": str(session.user_id),
                "status": session.status,
                "current_step": session.current_step,
            },
        )

        return EmailCaptureResponse(
            ok=True,
            next="/soulmate/subscribe",
        )
