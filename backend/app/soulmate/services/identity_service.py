"""Soulmate Identity and Email Binding Service (DEV-SPEC §8, §15.5, §20, SP-301)."""

import logging
from typing import Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidFlowStateError
from app.db.base import utc_now
from app.db.models.session import SoulmateSession
from app.soulmate.domain.identity import validate_and_normalize_email
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
        Validates and normalizes email, binds anonymous session contact email,
        preserves session ownership, and advances flow state.

        Guarantees:
        - DEV-SPEC §3 (H-1 remediation): Quiz must be completed before email capture.
        - DEV-SPEC §8.3 (H-2 remediation): Email capture email is a product contact/delivery
          field, not an authenticated login. Anonymous sessions do not inherit or bind to an
          existing user_id simply because an email is entered.
        - Session ownership is strictly preserved; cannot bind or corrupt another user's session.
        - No password or authentication framework is invented.
        - Idempotent on repeated submissions.
        - Raw email is treated as PII and excluded from structured analytics logs (DEV-SPEC §18.2, §20).
        """
        # 1. Validate and normalize email
        raw_email, email_normalized = validate_and_normalize_email(email_input)

        # 2. Enforce Quiz Completion Prerequisite (DEV-SPEC §3 Route Guard table, H-1 remediation)
        is_quiz_completed = (session.quiz_completed_at is not None) or session.status in (
            SessionStatus.QUIZ_COMPLETED.value,
            SessionStatus.EMAIL_CAPTURED.value,
            SessionStatus.CHECKOUT_PENDING.value,
            SessionStatus.SUBSCRIBED.value,
        )
        if not is_quiz_completed:
            raise InvalidFlowStateError(
                "Quiz must be completed before capturing email (DEV-SPEC §3).",
                details={
                    "current_step": session.current_step,
                    "status": session.status,
                    "required_prerequisite": "quiz_completed",
                },
            )

        # 3. Contact Email binding per DEV-SPEC §8.3 (H-2 remediation)
        # "若匿名，不得因为输入某个邮箱就授予该邮箱对应账户的访问权限。"
        # Verified user_id is only bound through trusted authentication flows.
        now = utc_now()
        session.email = raw_email
        session.email_normalized = email_normalized
        session.email_captured_at = now
        session.updated_at = now

        # 4. Advance status from QUIZ_COMPLETED to EMAIL_CAPTURED (do not overwrite later checkout/subscribed states)
        if session.status == SessionStatus.QUIZ_COMPLETED.value:
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
                "user_id": str(session.user_id) if session.user_id else None,
                "status": session.status,
                "current_step": session.current_step,
            },
        )

        return EmailCaptureResponse(
            ok=True,
            next="/soulmate/subscribe",
        )
