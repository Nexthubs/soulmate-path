"""
Payment Ledger Service (DEV-SPEC §9.4–9.7, §14, Decision: PAY-AUTH-01, SP-407).
Authoritative service for recording, querying, and auditing subscription payments,
deduplicating provider payment IDs, and supporting customer reconciliation.
"""

from datetime import datetime
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_event
from app.db.base import utc_now
from app.db.models.billing import Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.core.errors import ForbiddenOwnershipError
from app.soulmate.analytics import track_funnel_event
from app.soulmate.services.payment_consistency import payment_lock
from app.soulmate.domain.ledger_models import (
    LedgerSearchQuery,
    LedgerSearchResult,
    PaymentLedgerRecord,
    PaymentLedgerSummary,
    PaymentRecordCreate,
)

logger = logging.getLogger(__name__)


class PaymentLedgerService:
    """Service handling durable payment ledger operations and customer support reconciliation."""

    @classmethod
    async def record_payment(
        cls,
        db: AsyncSession,
        create_data: PaymentRecordCreate,
    ) -> Tuple[SubscriptionPayment, bool]:
        """
        Record a provider payment in the durable ledger idempotently (DEV-SPEC §9.6, §14).

        Guarantees:
        - If `provider_payment_id` already exists, returns (existing_payment, False).
        - If new, derives cycle context if not provided (cycle_no = count + 1).
        - Persists durable provider payment ID, amount, currency, paid time, subscription link, cycle.
        - Emits structured audit log.
        """
        pay_id = create_data.provider_payment_id.strip()
        if not pay_id:
            raise ValueError("provider_payment_id must not be empty")

        await payment_lock(db, "ledger-subscription", create_data.subscription_id)
        await payment_lock(db, "ledger-payment", pay_id)

        # 1. Idempotency Check: O(1) lookup on unique provider_payment_id
        stmt = select(SubscriptionPayment).where(SubscriptionPayment.provider_payment_id == pay_id).execution_options(populate_existing=True)
        existing = (await db.execute(stmt)).scalars().first()
        if existing is not None:
            if existing.subscription_id != create_data.subscription_id:
                raise ForbiddenOwnershipError("Payment already belongs to a different subscription.")
            logger.info(
                "PaymentLedger: duplicate provider_payment_id %s ignored idempotently (already exists on sub %s)",
                pay_id,
                existing.subscription_id,
            )
            return existing, False

        # 2. Derive billing cycle context if not explicitly passed
        cycle_no = create_data.cycle_no
        if cycle_no is None:
            count_stmt = select(func.count(SubscriptionPayment.id)).where(
                SubscriptionPayment.subscription_id == create_data.subscription_id
            )
            count = (await db.execute(count_stmt)).scalar() or 0
            cycle_no = count + 1

        # 3. Create durable ledger entry
        payment = SubscriptionPayment(
            subscription_id=create_data.subscription_id,
            provider_payment_id=pay_id,
            provider_event_id=create_data.provider_event_id,
            cycle_no=cycle_no,
            amount=create_data.amount,
            currency=create_data.currency.upper(),
            status=create_data.status.upper(),
            paid_at=create_data.paid_at,
            raw_json=create_data.raw_json,
        )
        db.add(payment)
        await db.flush()

        log_event(
            event_type="payment_ledger_recorded",
            message=f"Recorded payment ledger entry {pay_id} ({payment.status}) cycle {cycle_no}",
            level=logging.INFO,
            extra_data={
                "payment_id": str(payment.id),
                "provider_payment_id": pay_id,
                "subscription_id": str(payment.subscription_id),
                "cycle_no": cycle_no,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "provider_event_id": payment.provider_event_id,
            },
        )
        # §18.1 `soulmate_payment_confirmed` fires exactly once per subscription:
        # the first durably recorded COMPLETED payment (cycle 1). Both the webhook
        # path and provider reconciliation converge here, so webhook retries can
        # never duplicate the event (provider_payment_id idempotency above).
        if payment.status == "COMPLETED" and payment.cycle_no == 1:
            session_row = (await db.execute(
                select(Subscription.session_id).where(Subscription.id == payment.subscription_id)
            )).scalar_one_or_none()
            track_funnel_event(
                "soulmate_payment_confirmed",
                session_id=str(session_row) if session_row is not None else None,
                properties={"amount": str(payment.amount), "currency": payment.currency},
            )
        return payment, True

    @classmethod
    async def record_refund(
        cls,
        db: AsyncSession,
        provider_payment_id: str,
        refunded_at: Optional[datetime] = None,
        status: str = "REFUNDED",
        raw_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[SubscriptionPayment]:
        """
        Record a refund or reversal on an existing payment (DEV-SPEC §9.5).
        """
        pay_id = provider_payment_id.strip()
        await payment_lock(db, "ledger-payment", pay_id)
        stmt = select(SubscriptionPayment).where(SubscriptionPayment.provider_payment_id == pay_id).execution_options(populate_existing=True)
        payment = (await db.execute(stmt)).scalars().first()
        if not payment:
            logger.warning("PaymentLedger: Cannot record refund for unknown payment %s", pay_id)
            return None

        if payment.refunded_at is not None and refunded_at is not None and refunded_at <= payment.refunded_at:
            return payment
        payment.status = status.upper()
        payment.refunded_at = refunded_at or utc_now()
        if raw_json and payment.raw_json is not None:
            updated_raw = dict(payment.raw_json)
            updated_raw["refund_event"] = raw_json
            payment.raw_json = updated_raw

        await db.flush()

        log_event(
            event_type="payment_ledger_refunded",
            message=f"Payment {pay_id} updated to status {payment.status}",
            level=logging.INFO,
            extra_data={
                "payment_id": str(payment.id),
                "provider_payment_id": pay_id,
                "status": payment.status,
                "refunded_at": payment.refunded_at.isoformat() if payment.refunded_at else None,
            },
        )
        return payment

    @classmethod
    def _to_record_dto(
        cls,
        payment: SubscriptionPayment,
        sub: Optional[Subscription] = None,
        session: Optional[SoulmateSession] = None,
    ) -> PaymentLedgerRecord:
        """Helper to build a rich PaymentLedgerRecord DTO."""
        return PaymentLedgerRecord(
            id=payment.id,
            subscription_id=payment.subscription_id,
            provider_payment_id=payment.provider_payment_id,
            provider_event_id=payment.provider_event_id,
            cycle_no=payment.cycle_no,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status,
            paid_at=payment.paid_at,
            refunded_at=payment.refunded_at,
            created_at=payment.created_at,
            raw_json=payment.raw_json,
            provider_subscription_id=sub.provider_subscription_id if sub else None,
            session_id=session.id if session else (sub.session_id if sub else None),
            session_public_id=session.public_id if session else None,
            customer_email=session.email_normalized if session else None,
        )

    @classmethod
    async def get_payment_by_provider_payment_id(
        cls,
        db: AsyncSession,
        provider_payment_id: str,
    ) -> Optional[PaymentLedgerRecord]:
        """Lookup payment by provider payment ID for customer support & reconciliation."""
        stmt = (
            select(SubscriptionPayment, Subscription, SoulmateSession)
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .outerjoin(SoulmateSession, Subscription.session_id == SoulmateSession.id)
            .where(SubscriptionPayment.provider_payment_id == provider_payment_id.strip())
        )
        res = (await db.execute(stmt)).first()
        if not res:
            return None
        payment, sub, session = res
        return cls._to_record_dto(payment, sub, session)

    @classmethod
    async def get_payments_by_subscription_id(
        cls,
        db: AsyncSession,
        subscription_id: uuid.UUID,
    ) -> List[PaymentLedgerRecord]:
        """Fetch all payments for a given internal subscription UUID in cycle order."""
        stmt = (
            select(SubscriptionPayment, Subscription, SoulmateSession)
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .outerjoin(SoulmateSession, Subscription.session_id == SoulmateSession.id)
            .where(SubscriptionPayment.subscription_id == subscription_id)
            .order_by(SubscriptionPayment.cycle_no.asc().nulls_last(), SubscriptionPayment.created_at.asc())
        )
        rows = (await db.execute(stmt)).all()
        return [cls._to_record_dto(payment, sub, session) for payment, sub, session in rows]

    @classmethod
    async def get_payments_by_provider_subscription_id(
        cls,
        db: AsyncSession,
        provider_sub_id: str,
    ) -> List[PaymentLedgerRecord]:
        """Fetch all payments for a given PayPal subscription ID (e.g. I-...)."""
        stmt = (
            select(SubscriptionPayment, Subscription, SoulmateSession)
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .outerjoin(SoulmateSession, Subscription.session_id == SoulmateSession.id)
            .where(Subscription.provider_subscription_id == provider_sub_id.strip())
            .order_by(SubscriptionPayment.cycle_no.asc().nulls_last(), SubscriptionPayment.created_at.asc())
        )
        rows = (await db.execute(stmt)).all()
        return [cls._to_record_dto(payment, sub, session) for payment, sub, session in rows]

    @classmethod
    async def get_payments_by_session_public_id(
        cls,
        db: AsyncSession,
        public_id: str,
    ) -> List[PaymentLedgerRecord]:
        """Fetch all payments associated with a session public ID."""
        stmt = (
            select(SubscriptionPayment, Subscription, SoulmateSession)
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .join(SoulmateSession, Subscription.session_id == SoulmateSession.id)
            .where(SoulmateSession.public_id == public_id.strip())
            .order_by(SubscriptionPayment.created_at.desc())
        )
        rows = (await db.execute(stmt)).all()
        return [cls._to_record_dto(payment, sub, session) for payment, sub, session in rows]

    @classmethod
    async def get_payments_by_email(
        cls,
        db: AsyncSession,
        email: str,
    ) -> List[PaymentLedgerRecord]:
        """Lookup payment history by customer normalized email."""
        norm_email = email.strip().lower()
        stmt = (
            select(SubscriptionPayment, Subscription, SoulmateSession)
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .join(SoulmateSession, Subscription.session_id == SoulmateSession.id)
            .where(SoulmateSession.email_normalized == norm_email)
            .order_by(SubscriptionPayment.created_at.desc())
        )
        rows = (await db.execute(stmt)).all()
        return [cls._to_record_dto(payment, sub, session) for payment, sub, session in rows]

    @classmethod
    async def search_payments(
        cls,
        db: AsyncSession,
        query: LedgerSearchQuery,
    ) -> LedgerSearchResult:
        """
        Search payment ledger with flexible filters for customer support and reconciliation.
        Supports pagination, filtering by provider_payment_id, provider_sub_id, email, status, date range.
        """
        stmt = (
            select(SubscriptionPayment, Subscription, SoulmateSession)
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .outerjoin(SoulmateSession, Subscription.session_id == SoulmateSession.id)
        )
        count_stmt = (
            select(func.count(SubscriptionPayment.id))
            .join(Subscription, SubscriptionPayment.subscription_id == Subscription.id)
            .outerjoin(SoulmateSession, Subscription.session_id == SoulmateSession.id)
        )

        conditions = []
        if query.provider_payment_id:
            conditions.append(SubscriptionPayment.provider_payment_id == query.provider_payment_id.strip())
        if query.provider_subscription_id:
            conditions.append(Subscription.provider_subscription_id == query.provider_subscription_id.strip())
        if query.subscription_id:
            conditions.append(SubscriptionPayment.subscription_id == query.subscription_id)
        if query.session_public_id:
            conditions.append(SoulmateSession.public_id == query.session_public_id.strip())
        if query.email:
            conditions.append(SoulmateSession.email_normalized == query.email.strip().lower())
        if query.status:
            conditions.append(SubscriptionPayment.status == query.status.strip().upper())
        if query.start_date:
            conditions.append(SubscriptionPayment.created_at >= query.start_date)
        if query.end_date:
            conditions.append(SubscriptionPayment.created_at <= query.end_date)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(SubscriptionPayment.created_at.desc()).offset(query.offset).limit(query.limit)
        rows = (await db.execute(stmt)).all()

        items = [cls._to_record_dto(payment, sub, session) for payment, sub, session in rows]
        return LedgerSearchResult(
            items=items,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    @classmethod
    async def get_subscription_ledger_summary(
        cls,
        db: AsyncSession,
        subscription_id: uuid.UUID,
    ) -> Optional[PaymentLedgerSummary]:
        """Compute aggregate billing summary for a subscription."""
        sub_stmt = (
            select(Subscription, SoulmateSession)
            .outerjoin(SoulmateSession, Subscription.session_id == SoulmateSession.id)
            .where(Subscription.id == subscription_id)
        )
        res = (await db.execute(sub_stmt)).first()
        if not res:
            return None
        sub, session = res

        payments_stmt = (
            select(SubscriptionPayment)
            .where(SubscriptionPayment.subscription_id == subscription_id)
            .order_by(SubscriptionPayment.created_at.asc())
        )
        payments = (await db.execute(payments_stmt)).scalars().all()

        total_count = len(payments)
        completed_count = sum(1 for p in payments if p.status == "COMPLETED")
        failed_count = sum(1 for p in payments if p.status == "FAILED")
        refunded_count = sum(1 for p in payments if p.status in ("REFUNDED", "REVERSED"))
        total_amount = sum((p.amount for p in payments if p.status == "COMPLETED"), Decimal("0.00"))

        first_payment = next((p.paid_at for p in payments if p.status == "COMPLETED" and p.paid_at), None)
        latest_payment = next((p.paid_at for p in reversed(payments) if p.status == "COMPLETED" and p.paid_at), None)
        latest_status = payments[-1].status if payments else "NONE"

        return PaymentLedgerSummary(
            subscription_id=sub.id,
            provider_subscription_id=sub.provider_subscription_id,
            session_public_id=session.public_id if session else None,
            customer_email=session.email_normalized if session else None,
            currency=sub.currency,
            total_payments_count=total_count,
            completed_payments_count=completed_count,
            failed_payments_count=failed_count,
            refunded_payments_count=refunded_count,
            total_amount_paid=total_amount,
            first_payment_at=first_payment,
            latest_payment_at=latest_payment,
            latest_status=latest_status,
        )
