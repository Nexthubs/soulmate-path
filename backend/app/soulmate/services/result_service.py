"""
Result aggregate service (DEV-SPEC §10.4, §15.8, Decision: TIME-01, SP-503).

Composes one authoritative response for the Result page: server time,
subscription state, and sketch/report countdown statuses — so the client
never merges multiple authority calls and never derives access from its own clock.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenOwnershipError
from app.db.base import utc_now
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.soulmate.domain.guard import is_paid_access_ended
from app.soulmate.schema import ResultAggregateResponse, ResultSubscriptionView
from app.soulmate.services.status_service import ArtifactStatusService
from app.soulmate.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class ResultService:
    @classmethod
    async def get_result_aggregate(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        now: Optional[datetime] = None,
    ) -> ResultAggregateResponse:
        """
        Build the Result aggregate for an entitled session.

        Gates:
        - PAY-AUTH-01: requires a server-confirmed entitlement (session.subscription_success_at,
          set transactionally with the first confirmed payment). Unentitled sessions get 403.
        - TIME-01: statuses derive only from persisted timestamps and the server clock.

        Self-heal (SP-501): if an entitled session is missing artifact placeholder rows,
        the SP-501 create/ensure runs here (idempotent) and statuses are re-derived.
        """
        effective_now = now or utc_now()

        if session.subscription_success_at is None:
            raise ForbiddenOwnershipError(
                "Result is available only after a confirmed first payment (PAY-AUTH-01)."
            )

        # Latest subscription for the session (same selection semantics as get_subscription_status)
        stmt = (
            select(Subscription)
            .where(Subscription.session_id == session.id)
            .order_by(Subscription.created_at.desc())
        )
        sub = (await db.execute(stmt)).scalars().first()

        # Reconcile a cached ACTIVE subscription at the cycle boundary. A
        # provider-confirmed later date preserves legitimate renewed access.
        if sub is not None:
            sub = await SubscriptionService.refresh_paid_access_at_boundary(
                db, sub, effective_now
            )
        if sub is not None and is_paid_access_ended(
            sub.paid_through_at, effective_now
        ):
            raise ForbiddenOwnershipError(
                "Paid access period has ended (PAID-THROUGH-01). Re-subscribe to regain access."
            )

        statuses = await ArtifactStatusService.get_artifact_statuses(
            db,
            session.id,
            now=effective_now,
        )

        # SP-501 self-heal: placeholder rows missing for an entitled session
        if (statuses.sketch.unlock_at is None or statuses.report.unlock_at is None) and sub is not None:
            if sub.first_payment_at is not None:
                logger.warning(
                    "Result aggregate triggered artifact self-heal for session %s (SP-501 ensure)",
                    session.public_id,
                )
                await SubscriptionService.ensure_artifacts_for_session(
                    session=session,
                    paid_at=session.subscription_success_at,
                    db=db,
                )
                statuses = await ArtifactStatusService.get_artifact_statuses(
                    db,
                    session.id,
                    now=effective_now,
                )

        subscription_view = None
        if sub is not None:
            subscription_view = ResultSubscriptionView(
                provider=sub.provider,
                provider_status=sub.provider_status,
                first_payment_at=sub.first_payment_at,
                next_billing_at=sub.next_billing_at,
            )

        return ResultAggregateResponse(
            server_time=statuses.server_time,
            subscription=subscription_view,
            sketch=statuses.sketch,
            report=statuses.report,
        )
