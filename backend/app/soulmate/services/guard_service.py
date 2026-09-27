"""Route Guard Evaluation Service (DEV-SPEC §3, §10, §20, Decisions: PAY-AUTH-01, TIME-01)."""

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import utc_now
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.soulmate.domain.guard import evaluate_route_guard, normalize_route_path
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.schema import RouteGuardResponse

logger = logging.getLogger(__name__)


class GuardService:
    """Service governing server-authoritative route access evaluation."""

    @classmethod
    async def evaluate_guard(
        cls,
        db: AsyncSession,
        target_route: str,
        session: Optional[SoulmateSession] = None,
        public_id: Optional[str] = None,
    ) -> RouteGuardResponse:
        """
        Evaluates whether the requested target route is permitted for the given session.

        Guarantees:
        - Server-authoritative state evaluation matching DEV-SPEC §3 table.
        - H-1: Quiz completion strictly requires quiz_completed_at or completed/captured status.
        - H-3 / PAY-AUTH-01: Payment entitlement strictly requires provider/server-confirmed
          first_payment_at; never falls back to created_at or unconfirmed provider status.
        - TIME-01: Server-persisted UTC timestamp is the authoritative clock for 12h/24h unlocks.
        - Client input is normalized and sanitized before evaluation.
        """
        server_time = utc_now()
        session_exists = session is not None
        resolved_public_id = session.public_id if session else public_id
        current_step = session.current_step if session else None

        quiz_completed = False
        email_captured = False
        is_paid = False
        first_payment_at: Optional[datetime] = None
        paid_through_at: Optional[datetime] = None
        provider_status: Optional[str] = None

        if session:
            # 1. Quiz completed evaluation (DEV-SPEC §3, H-1 remediation)
            quiz_completed = bool(
                session.quiz_completed_at is not None
                or session.status in [
                    SessionStatus.QUIZ_COMPLETED.value,
                    SessionStatus.EMAIL_CAPTURED.value,
                    SessionStatus.CHECKOUT_PENDING.value,
                    SessionStatus.SUBSCRIBED.value,
                ]
            )

            # 2. Email captured evaluation
            email_captured = bool(
                (session.email_normalized is not None and len(session.email_normalized.strip()) > 0)
                or (session.email is not None and len(session.email.strip()) > 0)
                or session.status in [
                    SessionStatus.EMAIL_CAPTURED.value,
                    SessionStatus.CHECKOUT_PENDING.value,
                    SessionStatus.SUBSCRIBED.value,
                ]
            )

            # 3. First payment confirmed evaluation (PAY-AUTH-01 & TIME-01, H-3 remediation)
            # Entitlement begins strictly from server/provider-confirmed first successful payment.
            # Provider status (such as ACTIVE) does NOT substitute for first_payment_at.
            # Never fallback to subscription.created_at or session.updated_at.
            sub_query = (
                select(Subscription)
                .where(
                    Subscription.session_id == session.id,
                    Subscription.first_payment_at.isnot(None),
                )
                .order_by(Subscription.first_payment_at.desc())
            )
            sub_res = await db.execute(sub_query)
            sub = sub_res.scalars().first()

            if sub is not None and sub.first_payment_at is not None:
                is_paid = True
                first_payment_at = sub.first_payment_at
                # PAID-THROUGH-01 (resolved 2026-09-27): paid entitlement runs to
                # the end of the already-paid cycle; the guard denies paid routes
                # only when this date is known and has passed on the server clock
                # and the provider does not report an ACTIVE subscription.
                paid_through_at = sub.paid_through_at
                provider_status = sub.provider_status
            else:
                is_paid = False
                first_payment_at = None

        # Pure domain evaluation
        verdict = evaluate_route_guard(
            target_route=target_route,
            session_exists=session_exists,
            current_step=current_step,
            quiz_completed=quiz_completed,
            email_captured=email_captured,
            is_paid=is_paid,
            first_payment_at=first_payment_at,
            paid_through_at=paid_through_at,
            provider_status=provider_status,
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
            session_id=resolved_public_id,
            quiz_completed=verdict["quiz_completed"],
            email_captured=verdict["email_captured"],
            is_paid=verdict["is_paid"],
            sketch_unlocked=verdict["sketch_unlocked"],
            report_unlocked=verdict["report_unlocked"],
            sketch_unlock_at=verdict["sketch_unlock_at"],
            report_unlock_at=verdict["report_unlock_at"],
        )
