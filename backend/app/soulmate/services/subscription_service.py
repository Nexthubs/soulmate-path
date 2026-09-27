"""
Subscription Service (DEV-SPEC §9.3–9.4, §15.7–15.8, Decisions: PAY-AUTH-01).
Handles server-side validation and registration of approved PayPal subscriptions,
enforces session ownership (IDOR prevention), duplicate confirmation idempotency,
and strict separation between subscription confirmation and entitlement authority.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import re
from typing import Any, Dict, Optional, Set
import uuid
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ForbiddenOwnershipError,
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from app.core.logging import log_event
from app.db.base import utc_now
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.soulmate.domain.ledger_models import PaymentRecordCreate
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.schema import (
    PayPalConfirmResponse,
    SubscriptionCancelResponse,
    SubscriptionStatusResponse,
)
from app.soulmate.services.ledger_service import PaymentLedgerService
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.offer_service import OfferService
from app.soulmate.services.payment_consistency import payment_lock, apply_provider_status, apply_billing_count

logger = logging.getLogger(__name__)

# PayPal Subscription ID format: starts with I- followed by alphanumeric characters
PAYPAL_SUB_ID_REGEX = re.compile(r"^I-[A-Z0-9]{8,32}$", re.IGNORECASE)


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO8601 string to timezone-aware UTC datetime."""
    if not dt_str:
        return None
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class SubscriptionService:
    """Business logic for subscription confirmation and status reporting."""

    @classmethod
    async def confirm_paypal_subscription(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        paypal_subscription_id: str,
        paypal_client: Optional[PayPalClient] = None,
    ) -> PayPalConfirmResponse:
        """
        Confirm and associate an approved PayPal subscription with the authenticated session (DEV-SPEC §15.7).
        Enforces:
        1. Provider subscription ID validation.
        2. Session ownership & IDOR prevention.
        3. Idempotent duplicate confirmations.
        4. Invariant PAY-AUTH-01: Does not grant entitlement client-side; first_payment_at stays None.
        """
        sub_id_clean = paypal_subscription_id.strip()
        if not sub_id_clean:
            raise ValidationError("PayPal subscription ID must not be empty.")

        await payment_lock(db, "subscription", sub_id_clean)

        # 1. Idempotency & Cross-Session Hijack Prevention Check
        stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id_clean).execution_options(populate_existing=True)
        res = await db.execute(stmt)
        existing_sub = res.scalars().first()

        if existing_sub:
            # Check ownership binding
            if existing_sub.session_id != session.id:
                # If session user matches existing user, ownership is valid; otherwise reject cross-session hijacking
                if not (session.user_id and existing_sub.user_id and session.user_id == existing_sub.user_id):
                    logger.warning(
                        "Cross-session subscription confirmation rejected: sub=%s, existing_session=%s, new_session=%s",
                        sub_id_clean,
                        existing_sub.session_id,
                        session.id,
                    )
                    raise ForbiddenOwnershipError("PayPal subscription is already bound to a different session.")

            # Idempotent repeat confirmation
            logger.info(
                "Idempotent duplicate subscription confirmation for session=%s, sub=%s",
                session.public_id,
                sub_id_clean,
            )
            is_paid = existing_sub.first_payment_at is not None
            return PayPalConfirmResponse(
                status="ACTIVE" if is_paid else "PROCESSING",
                is_paid=is_paid,
                provider_subscription_id=existing_sub.provider_subscription_id,
                provider_plan_id=existing_sub.provider_plan_id,
                provider_status=existing_sub.provider_status,
                session_id=session.public_id,
                created_at=existing_sub.created_at,
                message="Subscription confirmation already registered (idempotent duplicate request).",
            )

        # 2. Server-side Validation with Provider (PayPal REST API)
        client = paypal_client or PayPalClient()
        try:
            sub_data = await client.get_subscription(sub_id_clean)
        except Exception as e:
            logger.error("Failed to query PayPal subscription %s: %s", sub_id_clean, e)
            raise ValidationError(f"Unable to verify subscription with PayPal: {str(e)}")

        if not sub_data:
            raise NotFoundError(f"Subscription '{sub_id_clean}' was not found on PayPal.")

        # 3. Ownership & Session Binding Verification (C-1, DEV-SPEC §15.7, §20)
        # Prevents claiming an unattached subscription belonging to another user/session.
        # Front-end creates subscriptions with custom_id set to session.public_id.
        # Confirmation requires a strictly matching custom_id.
        # Subscriptions lacking custom_id, or with mismatched custom_id, are rejected fail-closed.
        # Fallback to unverified captured email or claiming orphan subscriptions is strictly forbidden.
        remote_custom_id = (sub_data.get("custom_id") or "").strip()
        if not remote_custom_id:
            logger.warning(
                "Subscription confirmation rejected: PayPal subscription %s lacks custom_id to bind to session %s",
                sub_id_clean,
                session.public_id,
            )
            raise ForbiddenOwnershipError("PayPal subscription lacks valid session binding (custom_id required).")

        if remote_custom_id != session.public_id:
            logger.warning(
                "Cross-session subscription confirmation rejected: custom_id '%s' does not match session '%s'",
                remote_custom_id,
                session.public_id,
            )
            raise ForbiddenOwnershipError("PayPal subscription does not belong to this session.")

        provider_plan_id = sub_data.get("plan_id")
        provider_status = sub_data.get("status", "APPROVAL_PENDING").upper()

        # Serialize eligibility decisions across subscriptions for the same contact/user.
        await cls._validate_new_subscription_plan(db, session, provider_plan_id)

        # 5. Validate Provider Status (Reject terminal invalid states)
        if provider_status in {"CANCELLED", "EXPIRED", "SUSPENDED"}:
            raise ValidationError(f"PayPal subscription is in invalid status: '{provider_status}'.")

        # 6. Extract Details & Dates
        currency = settings.soulmate_currency
        intro_price = settings.soulmate_intro_price
        regular_price = settings.soulmate_regular_price
        price_verified_at: Optional[datetime] = None

        # High-risk remediation (Wave 8 audit H-2): the displayed/quoted renewal
        # price must be a traceable provider snapshot, not local config. Fetch
        # the bound plan's pricing; only a successful snapshot marks the price
        # verified. Fail-open keeps binding usable, but the price then stays
        # provisional (price_verified_at=None) and the UI will not quote it in
        # the cancel confirmation.
        if provider_plan_id:
            try:
                plan_pricing = cls._extract_plan_regular_pricing(await client.get_plan(provider_plan_id))
                if plan_pricing is not None:
                    currency, regular_price = plan_pricing
                    price_verified_at = utc_now()
            except Exception as e:
                logger.warning(
                    "Could not verify PayPal plan pricing for %s at binding: %s",
                    provider_plan_id,
                    e,
                )

        if not currency or regular_price is None:
            raise ValidationError(
                "Soulmate plan pricing is unavailable: neither provider verification nor configured pricing succeeded."
            )

        billing_info = sub_data.get("billing_info", {})
        next_billing_at = parse_iso_datetime(billing_info.get("next_billing_time"))

        # 7. Upsert Local Subscription Record
        # HIGH-RISK INVARIANT (PAY-AUTH-01):
        # first_payment_at MUST remain None here. Entitlement is only granted upon
        # verified PAYMENT.SALE.COMPLETED webhook event.
        new_subscription = Subscription(
            session_id=session.id,
            user_id=session.user_id,
            provider="paypal",
            provider_subscription_id=sub_id_clean,
            provider_plan_id=provider_plan_id or "UNKNOWN",
            provider_status=provider_status,
            currency=currency,
            intro_price=intro_price,
            regular_price=regular_price,
            price_verified_at=price_verified_at,
            first_payment_at=None,
            next_billing_at=next_billing_at,
        )

        db.add(new_subscription)
        await db.commit()
        await db.refresh(new_subscription)

        logger.info(
            "Created local subscription for session=%s, provider_sub=%s, plan=%s, status=PROCESSING (PAY-AUTH-01)",
            session.public_id,
            sub_id_clean,
            provider_plan_id,
        )

        return PayPalConfirmResponse(
            status="PROCESSING",
            is_paid=False,
            provider_subscription_id=new_subscription.provider_subscription_id,
            provider_plan_id=new_subscription.provider_plan_id,
            provider_status=new_subscription.provider_status,
            session_id=session.public_id,
            created_at=new_subscription.created_at,
            message="Subscription registered successfully. Pending payment reconciliation (PAY-AUTH-01).",
        )

    @classmethod
    async def _ensure_artifacts_initialized(
        cls,
        session: SoulmateSession,
        paid_at: datetime,
        db: AsyncSession,
    ) -> None:
        """
        Create/ensure durable artifact rows for SKETCH (+12h) and REPORT (+24h) per Spec §10, TIME-01.
        Idempotent under repeated delivery; unlock timestamps of existing rows are never modified.
        Concurrent first-payment delivery (webhook + reconcile) is tolerated: uniqueness is enforced
        at DB level (uq_soulmate_artifacts_session_type_version, uq_soulmate_one_sketch_per_email)
        and a lost insert race rolls back to a savepoint instead of failing the whole webhook/reconcile
        transaction (SP-501).
        """
        sketch_unlock = paid_at + timedelta(hours=settings.soulmate_sketch_unlock_hours)
        report_unlock = paid_at + timedelta(hours=settings.soulmate_report_unlock_hours)
        email = session.email_normalized or session.email or ""

        # autoflush is disabled; flush pending outer-transaction changes so each savepoint
        # below contains only its own artifact INSERT.
        await db.flush()

        # 1. Sketch Artifact (enforces uq_soulmate_one_sketch_per_email)
        sketch_cond = (SoulmateArtifact.session_id == session.id)
        if email:
            sketch_cond = sketch_cond | (SoulmateArtifact.email_normalized == email)
        stmt_sketch = select(SoulmateArtifact).where(
            sketch_cond,
            SoulmateArtifact.artifact_type == "SKETCH",
        )
        if not (await db.execute(stmt_sketch)).scalars().first():
            try:
                async with db.begin_nested():
                    db.add(
                        SoulmateArtifact(
                            session_id=session.id,
                            email_normalized=email,
                            artifact_type="SKETCH",
                            artifact_version="v1",
                            unlock_at=sketch_unlock,
                            generation_status="NOT_STARTED",
                        )
                    )
                    await db.flush()
            except IntegrityError:
                # Concurrent writer inserted the row first — create/ensure semantics tolerate it.
                if not (await db.execute(stmt_sketch)).scalars().first():
                    raise

        # 2. Report Artifact (same create/ensure semantics)
        stmt_report = select(SoulmateArtifact).where(
            SoulmateArtifact.session_id == session.id,
            SoulmateArtifact.artifact_type == "REPORT",
            SoulmateArtifact.artifact_version == "v1",
        )
        if not (await db.execute(stmt_report)).scalars().first():
            try:
                async with db.begin_nested():
                    db.add(
                        SoulmateArtifact(
                            session_id=session.id,
                            email_normalized=email,
                            artifact_type="REPORT",
                            artifact_version="v1",
                            unlock_at=report_unlock,
                            generation_status="NOT_STARTED",
                        )
                    )
                    await db.flush()
            except IntegrityError:
                if not (await db.execute(stmt_report)).scalars().first():
                    raise

    @classmethod
    async def ensure_artifacts_for_session(
        cls,
        session: SoulmateSession,
        paid_at: datetime,
        db: AsyncSession,
    ) -> None:
        """Public create/ensure entry point for artifact placeholders (SP-501 self-heal; used by SP-503 read path)."""
        await payment_lock(db, "session", session.id)
        await db.refresh(session)
        paid_at = session.subscription_success_at or paid_at
        await cls._ensure_artifacts_initialized(session=session, paid_at=paid_at, db=db)

    @staticmethod
    def _extract_plan_regular_pricing(plan_data: Optional[Dict[str, Any]]) -> Optional[tuple[str, Decimal]]:
        """Extract (currency, regular renewal price) from a PayPal plan payload.

        The regular renewal price is the fixed price of the last REGULAR-tenure
        billing cycle (V1 plans: an intro TRIAL month followed by REGULAR
        months). Returns None when the payload lacks a usable regular price.
        """
        if not plan_data:
            return None
        regular_cycle = None
        for cycle in plan_data.get("billing_cycles") or []:
            if str(cycle.get("tenure_type", "")).upper() == "REGULAR":
                regular_cycle = cycle  # keep the last REGULAR cycle
        if regular_cycle is None:
            return None
        fixed = (regular_cycle.get("pricing_scheme") or {}).get("fixed_price") or {}
        value = fixed.get("value")
        currency = fixed.get("currency_code")
        if value is None or not currency:
            return None
        try:
            price = Decimal(str(value))
        except Exception:
            return None
        if not price.is_finite() or price <= 0:
            return None
        return str(currency).upper(), price

    @classmethod
    async def _validate_new_subscription_plan(
        cls, db: AsyncSession, session: SoulmateSession, provider_plan_id: Optional[str],
    ) -> None:        # This is policy enforcement, never email-based authorization. The same
        # policy evaluator feeds the offer UI and both server binding paths.
        allowed = {p for p in (settings.paypal_soulmate_intro_plan_id, settings.paypal_soulmate_standard_plan_id) if p}
        if not allowed:
            raise ValidationError("Soulmate subscription plans are not configured.")
        if provider_plan_id not in allowed:
            raise ValidationError("Subscription plan does not match configured Soulmate plans.")
        await payment_lock(db, "eligibility", session.email_normalized or session.id)
        if session.user_id:
            await payment_lock(db, "eligibility-user", session.user_id)
        offer = await OfferService.get_subscription_offer(db=db, session=session)
        if offer.eligibility.is_blocked or not offer.paypal_plan_id:
            raise ValidationError("Subscription checkout is blocked by the configured eligibility policy.")
        if provider_plan_id != offer.paypal_plan_id:
            raise ValidationError("Subscription plan does not match the server-selected Soulmate plan.")

    @classmethod
    async def lock_subscription(
        cls, db: AsyncSession, provider_subscription_id: str,
    ) -> Optional[Subscription]:
        await payment_lock(db, "subscription", provider_subscription_id)
        sub = (await db.execute(
            select(Subscription).where(Subscription.provider_subscription_id == provider_subscription_id)
            .execution_options(populate_existing=True)
        )).scalars().first()
        if sub is not None:
            await payment_lock(db, "session", sub.session_id)
        return sub

    @classmethod
    async def activate_from_payment(
        cls, db: AsyncSession, sub: Subscription, paid_at: datetime,
    ) -> None:
        """Serialize first-payment and artifact updates, including earlier evidence.

        Renewals never move an unlock forward. Delayed evidence of an earlier
        successful payment corrects the base atomically without replacing assets.
        """
        await payment_lock(db, "session", sub.session_id)
        session = (await db.execute(
            select(SoulmateSession).where(SoulmateSession.id == sub.session_id)
            .execution_options(populate_existing=True)
        )).scalars().first()
        if session is None:
            raise ProviderUnavailableError("Payment session is not available for reconciliation.")
        if sub.first_payment_at is None or paid_at < sub.first_payment_at:
            sub.first_payment_at = paid_at
        base = min(t for t in (sub.first_payment_at, session.subscription_success_at) if t is not None)
        previous = session.subscription_success_at
        session.subscription_success_at = base
        if previous is None:
            # Canonical post-payment status per DEV-SPEC §6.2 (RV-01/RV-02 M7).
            session.status = SessionStatus.SUBSCRIBED.value
            session.current_step = "result"
        if previous is not None and base < previous:
            artifacts = (await db.execute(select(SoulmateArtifact).where(
                SoulmateArtifact.session_id == session.id
            ))).scalars().all()
            for artifact in artifacts:
                hours = {"SKETCH": settings.soulmate_sketch_unlock_hours,
                         "REPORT": settings.soulmate_report_unlock_hours}.get(artifact.artifact_type)
                if hours is not None:
                    artifact.unlock_at = min(artifact.unlock_at, base + timedelta(hours=hours))
        await cls._ensure_artifacts_initialized(session=session, paid_at=base, db=db)
        if previous is None or base < previous:
            log_event(event_type="entitlement_activated" if previous is None else "entitlement_time_corrected",
                      message="Persisted transaction-backed entitlement time",
                      extra_data={"session_id": str(session.id), "subscription_id": str(sub.id),
                                  "first_payment_at": base.isoformat()})

    @classmethod
    async def _reconcile_subscription_payments(
        cls, sub: Subscription, remote_data: Dict[str, Any], client: PayPalClient, db: AsyncSession,
    ) -> Optional[datetime]:
        """Backfill real transactions BEFORE selecting the earliest successful time.

        last_payment is a latest-payment summary, not first-payment evidence.
        Failures propagate so a webhook cannot acknowledge an incomplete restore.
        """
        start = parse_iso_datetime(remote_data.get("create_time")) or sub.created_at
        if start is None:
            raise ProviderUnavailableError("Subscription creation time is unavailable.")
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        transactions = await client.list_subscription_transactions(
            sub.provider_subscription_id,
            start_time=(start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_time=(utc_now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        valid = []
        for tx in transactions:
            if str(tx.get("status", "")).upper() != "COMPLETED":
                continue
            pay_id = str(tx.get("id") or "").strip()
            paid_at = parse_iso_datetime(tx.get("time"))
            gross = tx.get("amount_with_breakdown", {}).get("gross_amount", {}) or tx.get("amount", {})
            try:
                amount = Decimal(str(gross.get("value")))
            except Exception:
                continue
            currency = gross.get("currency_code")
            if not pay_id or paid_at is None or not currency or not amount.is_finite() or amount <= 0:
                continue
            valid.append((paid_at, pay_id, amount, currency, tx))
        # Stable order also makes ledger context deterministic during backfills.
        for paid_at, pay_id, amount, currency, tx in sorted(valid, key=lambda row: (row[0], row[1])):
            await PaymentLedgerService.record_payment(db=db, create_data=PaymentRecordCreate(
                subscription_id=sub.id, provider_payment_id=pay_id, amount=amount,
                currency=currency, status="COMPLETED", paid_at=paid_at, raw_json=tx,
            ))
        await db.flush()
        return (await db.execute(select(func.min(SubscriptionPayment.paid_at)).where(
            SubscriptionPayment.subscription_id == sub.id,
            SubscriptionPayment.status.in_(["COMPLETED", "REFUNDED", "REVERSED"]),
        ))).scalar()

    @classmethod
    async def reconcile_subscription(
        cls, db: AsyncSession, provider_subscription_id: str,
        paypal_client: Optional[PayPalClient] = None,
        verify_price: bool = False,
    ) -> Optional[Subscription]:
        """Restore only a trustworthy binding and transaction-backed payment state.

        `verify_price` refreshes the provider plan pricing snapshot (Wave 8 audit
        H-2); it is opt-in so webhook-driven reconciliations do not add a plan
        fetch per event.
        """
        sub_id = provider_subscription_id.strip()
        if not sub_id or not sub_id.startswith("I-"):
            return None
        sub = await cls.lock_subscription(db, sub_id)
        client = paypal_client or PayPalClient()
        try:
            remote = await client.get_subscription(sub_id)
        except Exception as exc:
            raise ProviderUnavailableError("PayPal subscription reconciliation is temporarily unavailable.") from exc
        if not remote:
            return None
        billing = remote.get("billing_info", {})
        remote_status = str(remote.get("status", "")).upper()
        if sub is None:
            custom_id = str(remote.get("custom_id") or "").strip()
            if not custom_id:
                return None  # Contact/payer email is NEVER a binding credential.
            session = (await db.execute(select(SoulmateSession).where(
                SoulmateSession.public_id == custom_id
            ))).scalars().first()
            if session is None:
                return None
            try:
                await cls._validate_new_subscription_plan(db, session, remote.get("plan_id"))
            except ValidationError:
                return None
            sub = Subscription(
                session_id=session.id, user_id=session.user_id, provider="paypal",
                provider_subscription_id=sub_id, provider_plan_id=remote["plan_id"],
                provider_status="APPROVAL_PENDING", currency=settings.soulmate_currency,
                intro_price=settings.soulmate_intro_price, regular_price=settings.soulmate_regular_price,
            )
            db.add(sub)
            await db.flush()
        await payment_lock(db, "session", sub.session_id)
        status_time = parse_iso_datetime(remote.get("status_update_time"))
        # A fetched provider snapshot is current; use its event time when available.
        snapshot_time = utc_now()
        if remote_status:
            apply_provider_status(sub, remote_status, status_time or snapshot_time)
        next_at = parse_iso_datetime(billing.get("next_billing_time"))
        if next_at:
            if sub.provider_status not in ("CANCELLED", "EXPIRED"):
                sub.next_billing_at = next_at
            if sub.paid_through_at is None or next_at > sub.paid_through_at:
                sub.paid_through_at = next_at
        if billing.get("last_payment") or remote_status in ("ACTIVE", "CANCELLED", "SUSPENDED", "EXPIRED"):
            paid_at = await cls._reconcile_subscription_payments(sub, remote, client, db)
            if paid_at is not None:
                await cls.activate_from_payment(db, sub, paid_at)
        provider_count = billing.get("failed_payments_count")
        if provider_count is not None:
            apply_billing_count(sub, int(provider_count), snapshot_time)
        else:
            last_paid = parse_iso_datetime(billing.get("last_payment", {}).get("time"))
            if last_paid and sub.first_payment_at is not None:
                apply_billing_count(sub, 0, last_paid)
        if verify_price and sub.provider_plan_id and sub.provider_plan_id != "UNKNOWN":
            try:
                plan_pricing = cls._extract_plan_regular_pricing(await client.get_plan(sub.provider_plan_id))
                if plan_pricing is not None:
                    verified_currency, verified_price = plan_pricing
                    if sub.currency != verified_currency or sub.regular_price != verified_price:
                        logger.info(
                            "Provider plan pricing snapshot refreshed for subscription %s: %s %s -> %s %s",
                            sub.provider_subscription_id,
                            sub.currency,
                            sub.regular_price,
                            verified_currency,
                            verified_price,
                        )
                        sub.currency = verified_currency
                        sub.regular_price = verified_price
                    sub.price_verified_at = utc_now()
            except Exception as e:
                logger.warning(
                    "Plan price verification failed for %s during reconciliation: %s",
                    sub.provider_subscription_id,
                    e,
                )
        await db.flush()
        return sub

    @classmethod
    async def reconcile_session_subscription(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        paypal_client: Optional[PayPalClient] = None,
    ) -> SubscriptionStatusResponse:
        """
        Explicit reconciliation of session subscription against PayPal REST API (DEV-SPEC §9.4, SP-408).
        """
        stmt = (
            select(Subscription)
            .where(Subscription.session_id == session.id)
            .order_by(Subscription.created_at.desc())
        )
        sub = (await db.execute(stmt)).scalars().first()
        if not sub:
            return SubscriptionStatusResponse(status="NONE", is_paid=False)

        await cls.reconcile_subscription(
            db=db,
            provider_subscription_id=sub.provider_subscription_id,
            paypal_client=paypal_client,
        )
        await db.commit()

        return await cls.get_subscription_status(
            db=db,
            session=session,
            auto_reconcile=False,
            paypal_client=paypal_client,
        )

    @classmethod
    async def get_subscription_status(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        auto_reconcile: bool = False,
        paypal_client: Optional[PayPalClient] = None,
    ) -> SubscriptionStatusResponse:
        """
        Query current subscription and entitlement status for the active session (DEV-SPEC §15.8).
        Predictably maps failure, suspension, cancellation, and expiration states.
        """
        stmt = (
            select(Subscription)
            .where(Subscription.session_id == session.id)
            .order_by(Subscription.created_at.desc())
        )
        res = await db.execute(stmt)
        sub = res.scalars().first()

        if not sub:
            return SubscriptionStatusResponse(
                status="NONE",
                is_paid=False,
            )

        # Honor the explicit reconcile request for paid subscriptions too
        # (Wave 8 audit H-1): missed/delayed provider status and billing dates
        # must refresh when Settings opens, not only while unpaid. Terminal
        # provider states map monotonically locally and need no per-open
        # refresh. Price verification is included so quoted renewal prices
        # track the provider plan (audit H-2).
        if auto_reconcile and sub.provider_status not in ("CANCELLED", "EXPIRED"):
            reconciled = await cls.reconcile_subscription(
                db=db,
                provider_subscription_id=sub.provider_subscription_id,
                paypal_client=paypal_client,
                verify_price=True,
            )
            if reconciled:
                sub = reconciled

        is_paid = sub.first_payment_at is not None

        # Predictable state mapping (DEV-SPEC §9.4–9.8, §10, SP-408)
        if is_paid:
            if sub.provider_status in ("CANCELLED", "EXPIRED", "SUSPENDED"):
                status = sub.provider_status
            else:
                status = "ACTIVE"
        else:
            if sub.provider_status in ("CANCELLED", "EXPIRED", "SUSPENDED"):
                status = sub.provider_status
            else:
                status = "PROCESSING"

        return SubscriptionStatusResponse(
            status=status,
            is_paid=is_paid,
            subscription_id=sub.provider_subscription_id,
            plan_id=sub.provider_plan_id,
            provider_status=sub.provider_status,
            currency=sub.currency,
            regular_price=str(sub.regular_price) if sub.regular_price is not None else None,
            price_verified=sub.price_verified_at is not None,
            first_payment_at=sub.first_payment_at,
            next_billing_at=sub.next_billing_at,
            paid_through_at=sub.paid_through_at,
            cancelled_at=sub.cancelled_at,
            failed_payments_count=sub.failed_payments_count or 0,
            billing_issue_detected_at=sub.billing_issue_detected_at,
        )

    @classmethod
    async def cancel_subscription(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        reason: str = "Customer request",
        paypal_client: Optional[PayPalClient] = None,
    ) -> SubscriptionCancelResponse:
        """
        Cancel active PayPal subscription for the authenticated session (DEV-SPEC §9.8, §15.9, SP-409).

        Guarantees & Acceptance Criteria:
        1. Cancellation uses server-side provider API: POST /v1/billing/subscriptions/{id}/cancel.
        2. Preserves paid-through access: fetches billing_info.next_billing_time from PayPal before cancel
           and saves as local paid_through_at.
        3. Repeated cancel is safe and idempotent.
        4. Cancelled users retain previously generated artifacts (never deletes artifacts or ledger records).
        5. Future billing is cleared (next_billing_at = None).
        """
        stmt = (
            select(Subscription)
            .where(Subscription.session_id == session.id)
            .order_by(Subscription.created_at.desc())
        )
        res = await db.execute(stmt)
        sub = res.scalars().first()
        if not sub:
            raise NotFoundError("No subscription found for this session.")

        # Idempotency check: if already cancelled, return existing cancelled state safely (Acceptance #3)
        if sub.provider_status == "CANCELLED" or sub.cancelled_at is not None:
            logger.info(
                "Idempotent cancel request for session %s: subscription %s already cancelled at %s",
                session.public_id,
                sub.provider_subscription_id,
                sub.cancelled_at,
            )
            return SubscriptionCancelResponse(
                status="CANCELLED",
                is_paid=sub.first_payment_at is not None,
                subscription_id=sub.provider_subscription_id,
                provider_status="CANCELLED",
                cancelled_at=sub.cancelled_at or utc_now(),
                paid_through_at=sub.paid_through_at,
                message="Subscription is already cancelled (idempotent duplicate request).",
            )

        client = paypal_client or PayPalClient(
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            environment=settings.paypal_env,
        )

        # 1. Fetch provider latest status / next billing time before calling cancel (DEV-SPEC §9.8, §15.9)
        remote_data = None
        try:
            remote_data = await client.get_subscription(sub.provider_subscription_id)
        except Exception as e:
            logger.warning(
                "Failed to fetch PayPal subscription %s before cancellation: %s",
                sub.provider_subscription_id,
                e,
            )

        if remote_data:
            billing_info = remote_data.get("billing_info", {})
            next_billing_str = billing_info.get("next_billing_time")
            next_billing_at = parse_iso_datetime(next_billing_str)
            if next_billing_at:
                sub.paid_through_at = next_billing_at
                sub.next_billing_at = next_billing_at

        # Ensure paid_through_at is established if session has paid
        if not sub.paid_through_at:
            if sub.next_billing_at:
                sub.paid_through_at = sub.next_billing_at
            else:
                # H-4: Do NOT artificially default to 30 days (month lengths vary).
                # Leave unset or existing to be resolved accurately via provider/reconciliation.
                logger.warning(
                    "Subscription %s cancellation: PayPal did not provide next_billing_time and no paid_through_at exists locally; leaving paid_through_at unset for reconciliation.",
                    sub.provider_subscription_id,
                )

        # 2. Persist and commit paid_through_at before calling external PayPal API (DEV-SPEC §15.9 step 3, H-3)
        # Guarantees paid_through_at is safely committed to the database even if external call times out or fails.
        await db.commit()

        # 3. Call PayPal cancel API (DEV-SPEC §9.8: POST /v1/billing/subscriptions/{id}/cancel, Acceptance #1)
        success = await client.cancel_subscription(
            subscription_id=sub.provider_subscription_id,
            reason=reason or "Customer request",
        )
        if not success:
            logger.error("PayPal API rejected cancellation for subscription %s", sub.provider_subscription_id)
            raise ValidationError("Failed to cancel subscription with PayPal. Please try again or contact support.")

        # 3. Update local state
        now = utc_now()
        sub = await cls.lock_subscription(db, sub.provider_subscription_id)
        apply_provider_status(sub, "CANCELLED", now)

        # 4. Invariant: Retain existing artifacts (Acceptance #4, DEV-SPEC §9.8, ASSET-01)
        art_stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == session.id)
        artifacts = (await db.execute(art_stmt)).scalars().all()

        await db.commit()
        await db.refresh(sub)

        log_event(
            event_type="subscription_cancelled",
            message=f"Subscription {sub.provider_subscription_id} cancelled for session {session.public_id}",
            level=logging.INFO,
            extra_data={
                "session_public_id": session.public_id,
                "subscription_id": str(sub.id),
                "provider_subscription_id": sub.provider_subscription_id,
                "paid_through_at": sub.paid_through_at.isoformat() if sub.paid_through_at else None,
                "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
                "retained_artifacts_count": len(artifacts),
                "reason": reason,
            },
        )

        # State-aware success message (Wave 8 audit M-2): only promise
        # paid-cycle access when a confirmed payment AND a known access end
        # date exist; otherwise make no unsupported access claim.
        if sub.first_payment_at is not None:
            if sub.paid_through_at is not None:
                message = "Subscription successfully cancelled. Access remains active through your current billing cycle."
            else:
                message = "Subscription successfully cancelled. Your paid access end date will be confirmed by the provider shortly."
        else:
            message = "Subscription successfully cancelled. No further charges will occur."

        return SubscriptionCancelResponse(
            status="CANCELLED",
            is_paid=sub.first_payment_at is not None,
            subscription_id=sub.provider_subscription_id,
            provider_status="CANCELLED",
            cancelled_at=sub.cancelled_at,
            paid_through_at=sub.paid_through_at,
            message=message,
        )
