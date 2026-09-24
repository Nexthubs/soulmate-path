"""
Route Guard Service (DEV-SPEC §3, §10, §20, Decisions: PAY-AUTH-01, TIME-01).
Evaluates server-persisted truth to authorize route transitions and prevent invalid skips.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import utc_now
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.soulmate.domain.guard import evaluate_route_guard
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.schema import RouteGuardResponse


class GuardService:
    """Service evaluating authoritative server state for route guard enforcement."""

    @classmethod
    async def evaluate_guard(
        cls,
        db: AsyncSession,
        target_route: str,
        session: Optional[SoulmateSession],
        current_time: Optional[datetime] = None,
    ) -> RouteGuardResponse:
        """
        Evaluates minimum route prerequisites per DEV-SPEC §3 table.
        Server-side state is the final authority.
        """
        server_time = current_time or utc_now()
        session_exists = session is not None
        current_step = session.current_step if session else None
        public_id = session.public_id if session else None

        quiz_completed = False
        email_captured = False
        is_paid = False
        first_payment_at: Optional[datetime] = None

        if session:
            # 1. Quiz completed evaluation
            quiz_completed = bool(
                session.quiz_completed_at is not None
                or session.status in [
                    SessionStatus.QUIZ_COMPLETED.value,
                    SessionStatus.EMAIL_CAPTURED.value,
                    SessionStatus.CHECKOUT_PENDING.value,
                    SessionStatus.SUBSCRIBED.value,
                ]
                or session.current_step in [
                    "transition_5",
                    "spiritual_person",
                    "familiar_psychic_artistry",
                    "warning_response",
                    "email",
                    "subscribe",
                    "result",
                ]
            )

            # 2. Email captured evaluation
            email_captured = bool(
                (session.email is not None and len(session.email.strip()) > 0)
                or (session.email_normalized is not None and len(session.email_normalized.strip()) > 0)
                or session.status in [
                    SessionStatus.EMAIL_CAPTURED.value,
                    SessionStatus.CHECKOUT_PENDING.value,
                    SessionStatus.SUBSCRIBED.value,
                ]
            )

            # 3. First payment confirmed evaluation (PAY-AUTH-01: server/provider authority)
            sub_res = await db.execute(
                select(Subscription).where(Subscription.session_id == session.id)
            )
            sub = sub_res.scalars().first()

            if sub:
                if sub.first_payment_at is not None or sub.provider_status.upper() in [
                    "ACTIVE",
                    "CANCELLED",
                    "SUSPENDED",
                ]:
                    is_paid = True
                    first_payment_at = sub.first_payment_at or sub.created_at
            elif session.status == SessionStatus.SUBSCRIBED.value:
                is_paid = True
                first_payment_at = session.updated_at

        # Pure domain evaluation
        verdict = evaluate_route_guard(
            target_route=target_route,
            session_exists=session_exists,
            current_step=current_step,
            quiz_completed=quiz_completed,
            email_captured=email_captured,
            is_paid=is_paid,
            first_payment_at=first_payment_at,
            server_time=server_time,
            sketch_hours=settings.soulmate_sketch_unlock_hours,
            report_hours=settings.soulmate_report_unlock_hours,
        )

        return RouteGuardResponse(
            allowed=verdict["allowed"],
            target_route=verdict["target_route"],
            redirect_to=verdict["redirect_to"],
            reason=verdict["reason"],
            server_time=verdict["server_time"],
            session_id=public_id,
            quiz_completed=verdict["quiz_completed"],
            email_captured=verdict["email_captured"],
            is_paid=verdict["is_paid"],
            sketch_unlocked=verdict["sketch_unlocked"],
            report_unlocked=verdict["report_unlocked"],
            sketch_unlock_at=verdict["sketch_unlock_at"],
            report_unlock_at=verdict["report_unlock_at"],
        )
