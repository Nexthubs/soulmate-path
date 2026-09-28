"""Exact-identifier, allowlisted support case lookup (DEV-SPEC §14, §19–20)."""

from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.errors import ValidationError as DomainValidationError
from app.db.base import utc_now
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.soulmate.domain.identity import validate_and_normalize_email
from app.soulmate.domain.support_lookup_models import (
    SupportArtifactStatus,
    SupportJobStatus,
    SupportLookupRequest,
    SupportLookupResult,
    SupportPaymentStatus,
    SupportSessionStatus,
    SupportSubscriptionStatus,
    SupportTimelineEvent,
)


class AmbiguousSupportEmailError(Exception):
    """Raised when an email maps to more than one session and cannot identify one case."""


class InvalidSupportEmailError(Exception):
    """Raised without echoing an invalid email identifier."""


class SupportLookupService:
    """Resolve exactly one case and return status-only data for that session."""

    @classmethod
    async def lookup(
        cls,
        db: AsyncSession,
        query: SupportLookupRequest,
    ) -> Optional[SupportLookupResult]:
        session_id = await cls._resolve_session_id(db, query)
        if session_id is None:
            return None

        session = (
            await db.execute(
                select(SoulmateSession)
                .options(
                    load_only(
                        SoulmateSession.id,
                        SoulmateSession.public_id,
                        SoulmateSession.status,
                        SoulmateSession.current_step,
                        SoulmateSession.created_at,
                        SoulmateSession.updated_at,
                        SoulmateSession.quiz_completed_at,
                        SoulmateSession.email_captured_at,
                        SoulmateSession.subscription_success_at,
                    )
                )
                .where(SoulmateSession.id == session_id)
            )
        ).scalars().first()
        if session is None:
            return None

        subscriptions = (
            await db.execute(
                select(Subscription)
                .options(
                    load_only(
                        Subscription.id,
                        Subscription.session_id,
                        Subscription.provider_subscription_id,
                        Subscription.provider_status,
                        Subscription.currency,
                        Subscription.first_payment_at,
                        Subscription.next_billing_at,
                        Subscription.paid_through_at,
                        Subscription.cancelled_at,
                        Subscription.suspended_at,
                        Subscription.expired_at,
                        Subscription.failed_payments_count,
                        Subscription.billing_issue_detected_at,
                        Subscription.provider_status_updated_at,
                        Subscription.created_at,
                        Subscription.updated_at,
                    )
                )
                .where(Subscription.session_id == session.id)
                .order_by(Subscription.created_at.asc(), Subscription.id.asc())
            )
        ).scalars().all()
        subscription_ids = [row.id for row in subscriptions]
        payments = []
        if subscription_ids:
            payments = (
                await db.execute(
                    select(SubscriptionPayment)
                    .options(
                        load_only(
                            SubscriptionPayment.id,
                            SubscriptionPayment.subscription_id,
                            SubscriptionPayment.provider_payment_id,
                            SubscriptionPayment.cycle_no,
                            SubscriptionPayment.amount,
                            SubscriptionPayment.currency,
                            SubscriptionPayment.status,
                            SubscriptionPayment.paid_at,
                            SubscriptionPayment.refunded_at,
                            SubscriptionPayment.created_at,
                        )
                    )
                    .where(SubscriptionPayment.subscription_id.in_(subscription_ids))
                    .order_by(SubscriptionPayment.created_at.asc(), SubscriptionPayment.id.asc())
                )
            ).scalars().all()

        artifacts = (
            await db.execute(
                select(SoulmateArtifact)
                .options(
                    load_only(
                        SoulmateArtifact.id,
                        SoulmateArtifact.session_id,
                        SoulmateArtifact.artifact_type,
                        SoulmateArtifact.generation_status,
                        SoulmateArtifact.attempt_count,
                        SoulmateArtifact.created_at,
                        SoulmateArtifact.generation_started_at,
                        SoulmateArtifact.completed_at,
                        SoulmateArtifact.updated_at,
                    )
                )
                .where(SoulmateArtifact.session_id == session.id)
                .order_by(SoulmateArtifact.created_at.asc(), SoulmateArtifact.id.asc())
            )
        ).scalars().all()
        artifact_ids = [row.id for row in artifacts]
        jobs = []
        if artifact_ids:
            jobs = (
                await db.execute(
                    select(AIGenerationJob)
                    .options(
                        load_only(
                            AIGenerationJob.id,
                            AIGenerationJob.artifact_id,
                            AIGenerationJob.job_type,
                            AIGenerationJob.status,
                            AIGenerationJob.attempt,
                            AIGenerationJob.run_after,
                            AIGenerationJob.locked_at,
                            AIGenerationJob.created_at,
                            AIGenerationJob.updated_at,
                        )
                    )
                    .where(AIGenerationJob.artifact_id.in_(artifact_ids))
                    .order_by(AIGenerationJob.created_at.asc(), AIGenerationJob.id.asc())
                )
            ).scalars().all()

        timeline: list[SupportTimelineEvent] = []

        def add_event(
            occurred_at,
            event_type: str,
            entity_type: str,
            entity_id: uuid.UUID,
            status: Optional[str] = None,
            status_context: Optional[str] = None,
        ) -> None:
            if occurred_at is not None:
                timeline.append(
                    SupportTimelineEvent(
                        occurred_at=occurred_at,
                        event_type=event_type,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        status=status,
                        status_context=status_context,
                    )
                )

        add_event(session.created_at, "session_created", "session", session.id)
        add_event(session.quiz_completed_at, "quiz_completed", "session", session.id)
        add_event(session.email_captured_at, "email_captured", "session", session.id)
        add_event(session.subscription_success_at, "payment_confirmed", "session", session.id)

        for row in subscriptions:
            add_event(row.created_at, "subscription_created", "subscription", row.id)
            add_event(
                row.provider_status_updated_at,
                "subscription_status",
                "subscription",
                row.id,
                row.provider_status,
                "at_event",
            )
            add_event(row.first_payment_at, "first_payment", "subscription", row.id)
            add_event(row.next_billing_at, "next_billing_scheduled", "subscription", row.id)
            add_event(row.paid_through_at, "paid_through", "subscription", row.id)
            add_event(
                row.cancelled_at,
                "subscription_cancelled",
                "subscription",
                row.id,
                "CANCELLED",
                "at_event",
            )
            add_event(
                row.suspended_at,
                "subscription_suspended",
                "subscription",
                row.id,
                "SUSPENDED",
                "at_event",
            )
            add_event(row.expired_at, "subscription_expired", "subscription", row.id, "EXPIRED", "at_event")
            add_event(row.billing_issue_detected_at, "billing_issue", "subscription", row.id)

        for row in payments:
            add_event(row.created_at, "payment_recorded", "payment", row.id)
            add_event(row.paid_at, "payment_paid", "payment", row.id, "COMPLETED", "at_event")
            add_event(row.refunded_at, "payment_refunded", "payment", row.id)

        for row in artifacts:
            add_event(row.created_at, "artifact_created", "artifact", row.id)
            add_event(row.generation_started_at, "generation_started", "artifact", row.id)
            add_event(row.completed_at, "artifact_completed", "artifact", row.id, "COMPLETED", "at_event")

        for row in jobs:
            add_event(row.created_at, "generation_job_created", "job", row.id)

        # The domain tables retain current status, but do not retain every
        # transition. Publish those values as an explicitly current snapshot
        # instead of attaching them to older creation/update timestamps.
        snapshot_at = utc_now()
        add_event(
            snapshot_at,
            "current_status_snapshot",
            "session",
            session.id,
            session.status,
            "current_snapshot",
        )
        for row in subscriptions:
            add_event(
                snapshot_at,
                "current_status_snapshot",
                "subscription",
                row.id,
                row.provider_status,
                "current_snapshot",
            )
        for row in payments:
            add_event(
                snapshot_at,
                "current_status_snapshot",
                "payment",
                row.id,
                row.status,
                "current_snapshot",
            )
        for row in artifacts:
            add_event(
                snapshot_at,
                "current_status_snapshot",
                "artifact",
                row.id,
                row.generation_status,
                "current_snapshot",
            )
        for row in jobs:
            add_event(snapshot_at, "current_status_snapshot", "job", row.id, row.status, "current_snapshot")

        timeline.sort(
            key=lambda item: (
                item.occurred_at,
                item.entity_type,
                item.event_type,
                str(item.entity_id),
            )
        )

        return SupportLookupResult(
            session=SupportSessionStatus(
                id=session.id,
                public_id=session.public_id,
                status=session.status,
                current_step=session.current_step,
                created_at=session.created_at,
                updated_at=session.updated_at,
                quiz_completed_at=session.quiz_completed_at,
                email_captured_at=session.email_captured_at,
                subscription_success_at=session.subscription_success_at,
            ),
            subscriptions=[
                SupportSubscriptionStatus(
                    id=row.id,
                    paypal_subscription_id=row.provider_subscription_id,
                    provider_status=row.provider_status,
                    currency=row.currency,
                    first_payment_at=row.first_payment_at,
                    next_billing_at=row.next_billing_at,
                    paid_through_at=row.paid_through_at,
                    cancelled_at=row.cancelled_at,
                    suspended_at=row.suspended_at,
                    expired_at=row.expired_at,
                    failed_payments_count=row.failed_payments_count,
                    billing_issue_detected_at=row.billing_issue_detected_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in subscriptions
            ],
            payments=[
                SupportPaymentStatus(
                    id=row.id,
                    provider_payment_id=row.provider_payment_id,
                    cycle_no=row.cycle_no,
                    amount=row.amount,
                    currency=row.currency,
                    status=row.status,
                    paid_at=row.paid_at,
                    refunded_at=row.refunded_at,
                    created_at=row.created_at,
                )
                for row in payments
            ],
            artifacts=[
                SupportArtifactStatus(
                    id=row.id,
                    artifact_type=row.artifact_type,
                    generation_status=row.generation_status,
                    attempt_count=row.attempt_count,
                    created_at=row.created_at,
                    generation_started_at=row.generation_started_at,
                    completed_at=row.completed_at,
                    updated_at=row.updated_at,
                )
                for row in artifacts
            ],
            jobs=[
                SupportJobStatus(
                    id=row.id,
                    job_type=row.job_type,
                    status=row.status,
                    attempt=row.attempt,
                    run_after=row.run_after,
                    locked_at=row.locked_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in jobs
            ],
            timeline=timeline,
        )

    @classmethod
    async def _resolve_session_id(
        cls,
        db: AsyncSession,
        query: SupportLookupRequest,
    ) -> Optional[uuid.UUID]:
        if query.session_id is not None:
            try:
                parsed_id = uuid.UUID(query.session_id)
            except ValueError:
                parsed_id = None
            if parsed_id is not None:
                internal_match = (await db.execute(
                    select(SoulmateSession.id).where(SoulmateSession.id == parsed_id)
                )).scalar_one_or_none()
                if internal_match is not None:
                    return internal_match
            return (await db.execute(
                select(SoulmateSession.id).where(SoulmateSession.public_id == query.session_id)
            )).scalar_one_or_none()

        if query.email is not None:
            try:
                _, normalized_email = validate_and_normalize_email(query.email)
            except DomainValidationError as exc:
                raise InvalidSupportEmailError from exc
            matching_ids = (
                await db.execute(
                    select(SoulmateSession.id)
                    .where(SoulmateSession.email_normalized == normalized_email)
                    .order_by(SoulmateSession.created_at.asc(), SoulmateSession.id.asc())
                )
            ).scalars().all()
            if len(matching_ids) > 1:
                raise AmbiguousSupportEmailError
            return matching_ids[0] if matching_ids else None

        if query.paypal_subscription_id is not None:
            return (
                await db.execute(
                    select(Subscription.session_id).where(
                        Subscription.provider_subscription_id == query.paypal_subscription_id
                    )
                )
            ).scalar_one_or_none()

        if query.provider_payment_id is not None:
            return (
                await db.execute(
                    select(Subscription.session_id)
                    .join(SubscriptionPayment, SubscriptionPayment.subscription_id == Subscription.id)
                    .where(SubscriptionPayment.provider_payment_id == query.provider_payment_id)
                )
            ).scalar_one_or_none()

        return None
