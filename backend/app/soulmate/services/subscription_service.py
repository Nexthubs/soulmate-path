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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ForbiddenOwnershipError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import log_event
from app.db.base import utc_now
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.soulmate.domain.ledger_models import PaymentRecordCreate
from app.soulmate.schema import (
    PayPalConfirmResponse,
    SubscriptionCancelResponse,
    SubscriptionStatusResponse,
)
from app.soulmate.services.ledger_service import PaymentLedgerService
from app.soulmate.services.paypal_client import PayPalClient

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

        # 1. Idempotency & Cross-Session Hijack Prevention Check
        stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id_clean)
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

        # 3. Ownership & Session Binding Verification (C-1, DEV-SPEC §15.7)
        # Prevents claiming an unattached subscription belonging to another user/session
        remote_custom_id = sub_data.get("custom_id")
        remote_subscriber = sub_data.get("subscriber") or {}
        remote_subscriber_email = remote_subscriber.get("email_address")

        if remote_custom_id:
            if remote_custom_id.strip() != session.public_id:
                logger.warning(
                    "Cross-session subscription confirmation rejected: custom_id '%s' does not match session '%s'",
                    remote_custom_id,
                    session.public_id,
                )
                raise ForbiddenOwnershipError("PayPal subscription does not belong to this session.")
        elif remote_subscriber_email:
            session_email = (session.email_normalized or session.email or "").strip().lower()
            if not session_email or remote_subscriber_email.strip().lower() != session_email:
                logger.warning(
                    "Cross-session subscription confirmation rejected: subscriber email '%s' does not match session email '%s'",
                    remote_subscriber_email,
                    session_email,
                )
                raise ForbiddenOwnershipError("PayPal subscription subscriber does not match this session.")

        provider_plan_id = sub_data.get("plan_id")
        provider_status = sub_data.get("status", "APPROVAL_PENDING").upper()

        # 4. Validate Plan ID against allowed Soulmate plans (DEV-SPEC §15.7 step 3, fail-closed)
        allowed_plans: Set[str] = set()
        if settings.paypal_soulmate_intro_plan_id:
            allowed_plans.add(settings.paypal_soulmate_intro_plan_id)
        if settings.paypal_soulmate_standard_plan_id:
            allowed_plans.add(settings.paypal_soulmate_standard_plan_id)

        if not allowed_plans:
            logger.error("No Soulmate subscription plans configured; rejecting subscription confirmation (fail-closed)")
            raise ValidationError("Soulmate subscription plans are not configured.")

        if not provider_plan_id or provider_plan_id not in allowed_plans:
            logger.warning(
                "Subscription confirmation rejected: plan %s not in allowed plans %s",
                provider_plan_id,
                allowed_plans,
            )
            raise ValidationError(f"Subscription plan '{provider_plan_id}' does not match configured Soulmate plans.")

        # 5. Validate Provider Status (Reject terminal invalid states)
        if provider_status in {"CANCELLED", "EXPIRED", "SUSPENDED"}:
            raise ValidationError(f"PayPal subscription is in invalid status: '{provider_status}'.")

        # 6. Extract Details & Dates
        currency = settings.soulmate_currency or "USD"
        intro_price = settings.soulmate_intro_price
        regular_price = settings.soulmate_regular_price or Decimal("29.00")

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
        Initialize durable artifact rows for SKETCH (+12h) and REPORT (+24h) per Spec §10, TIME-01.
        Idempotent: skips if row already exists, enforces uq_soulmate_one_sketch_per_email.
        """
        sketch_unlock = paid_at + timedelta(hours=settings.soulmate_sketch_unlock_hours)
        report_unlock = paid_at + timedelta(hours=settings.soulmate_report_unlock_hours)
        email = session.email_normalized or session.email or ""

        # 1. Sketch Artifact (enforces uq_soulmate_one_sketch_per_email)
        sketch_cond = (SoulmateArtifact.session_id == session.id)
        if email:
            sketch_cond = sketch_cond | (SoulmateArtifact.email_normalized == email)
        stmt_sketch = select(SoulmateArtifact).where(
            sketch_cond,
            SoulmateArtifact.artifact_type == "SKETCH",
        )
        if not (await db.execute(stmt_sketch)).scalars().first():
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

        # 2. Report Artifact
        stmt_report = select(SoulmateArtifact).where(
            SoulmateArtifact.session_id == session.id,
            SoulmateArtifact.artifact_type == "REPORT",
            SoulmateArtifact.artifact_version == "v1",
        )
        if not (await db.execute(stmt_report)).scalars().first():
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

    @classmethod
    async def reconcile_subscription(
        cls,
        db: AsyncSession,
        provider_subscription_id: str,
        paypal_client: Optional[PayPalClient] = None,
    ) -> Optional[Subscription]:
        """
        Reconcile local subscription state against PayPal REST API (DEV-SPEC §9.4, §15.7–15.8, SP-408).
        Ensures:
        1. Monotonicity: never regresses terminal CANCELLED or EXPIRED states.
        2. First payment authority (PAY-AUTH-01): sets first_payment_at, subscription_success_at,
           and unlocks artifacts exactly once if confirmed by PayPal billing_info.last_payment.
        3. Never deletes already-owned generated artifacts upon cancellation or expiration.
        4. Reconciles next_billing_at and paid_through_at.
        5. Records ledger payment via PaymentLedgerService if missing.
        """
        sub_id = provider_subscription_id.strip()
        if not sub_id or not sub_id.startswith("I-"):
            return None

        stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id)
        sub = (await db.execute(stmt)).scalars().first()

        client = paypal_client or PayPalClient(
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            environment=settings.paypal_env,
        )

        try:
            remote_data = await client.get_subscription(sub_id)
        except Exception as e:
            logger.warning("Failed to fetch PayPal subscription %s during reconciliation: %s", sub_id, e)
            return sub

        if not remote_data:
            return sub

        remote_status = str(remote_data.get("status", "")).upper()
        billing_info = remote_data.get("billing_info", {})
        next_billing_str = billing_info.get("next_billing_time")
        next_billing_at = parse_iso_datetime(next_billing_str)
        status_update_time = parse_iso_datetime(remote_data.get("status_update_time")) or utc_now()

        last_payment = billing_info.get("last_payment", {})
        last_payment_time_str = last_payment.get("time")
        last_paid_at = parse_iso_datetime(last_payment_time_str)

        if sub is not None:
            # 1. Monotonicity rule: Do not regress CANCELLED or EXPIRED if local state is already terminal
            if sub.provider_status in ("CANCELLED", "EXPIRED") and remote_status in ("ACTIVE", "APPROVAL_PENDING", "APPROVED"):
                logger.info(
                    "Reconciliation skipped status regression for %s: local=%s, remote=%s",
                    sub_id,
                    sub.provider_status,
                    remote_status,
                )
            else:
                if remote_status:
                    sub.provider_status = remote_status
                if remote_status == "CANCELLED" and not sub.cancelled_at:
                    sub.cancelled_at = status_update_time
                elif remote_status == "SUSPENDED" and not sub.suspended_at:
                    sub.suspended_at = status_update_time
                elif remote_status == "EXPIRED" and not sub.expired_at:
                    sub.expired_at = status_update_time
                elif remote_status == "ACTIVE":
                    sub.suspended_at = None

            # 2. Reconcile next billing and paid-through dates
            if next_billing_at:
                sub.next_billing_at = next_billing_at
                if not sub.paid_through_at or next_billing_at > sub.paid_through_at:
                    sub.paid_through_at = next_billing_at

            # 3. First Payment & Entitlement Authority (PAY-AUTH-01, TIME-01)
            if last_paid_at is not None:
                if sub.first_payment_at is None:
                    sub.first_payment_at = last_paid_at
                    # Locate and activate session
                    sess_stmt = select(SoulmateSession).where(SoulmateSession.id == sub.session_id)
                    session = (await db.execute(sess_stmt)).scalars().first()
                    if session is not None and session.subscription_success_at is None:
                        session.subscription_success_at = last_paid_at
                        session.status = "paid"
                        session.current_step = "result"
                        await cls._ensure_artifacts_initialized(session=session, paid_at=last_paid_at, db=db)
                        log_event(
                            event_type="entitlement_activated",
                            message=f"Entitlement activated for session {session.public_id} via reconciliation",
                            level=logging.INFO,
                            extra_data={
                                "session_public_id": session.public_id,
                                "subscription_id": str(sub.id),
                                "provider_sub_id": sub_id,
                                "subscription_success_at": last_paid_at.isoformat(),
                            },
                        )

                    # Ensure payment ledger entry exists
                    amount_val = last_payment.get("amount", {}).get("value")
                    try:
                        amount = Decimal(str(amount_val)) if amount_val else (sub.intro_price or Decimal("19.00"))
                    except Exception:
                        amount = sub.intro_price or Decimal("19.00")
                    currency = last_payment.get("amount", {}).get("currency_code") or sub.currency or "USD"
                    pay_id = last_payment.get("id") or f"PAYPAL-LASTPAY-{sub.provider_subscription_id}"
                    await PaymentLedgerService.record_payment(
                        db=db,
                        create_data=PaymentRecordCreate(
                            subscription_id=sub.id,
                            provider_payment_id=pay_id,
                            amount=amount,
                            currency=currency,
                            status="COMPLETED",
                            paid_at=last_paid_at,
                            raw_json=remote_data,
                        ),
                    )

            await db.flush()
            return sub

        # If sub does not exist locally yet, validate plan and locate session via custom_id or subscriber email (C-2, DEV-SPEC §8.3)
        # 1. Validate Plan ID against allowed Soulmate plans (fail-closed)
        allowed_plans: Set[str] = set()
        if settings.paypal_soulmate_intro_plan_id:
            allowed_plans.add(settings.paypal_soulmate_intro_plan_id)
        if settings.paypal_soulmate_standard_plan_id:
            allowed_plans.add(settings.paypal_soulmate_standard_plan_id)

        remote_plan_id = remote_data.get("plan_id")
        if not allowed_plans or not remote_plan_id or remote_plan_id not in allowed_plans:
            logger.warning(
                "Reconciliation rejected for unknown subscription %s: plan '%s' is not in allowed Soulmate plans %s",
                sub_id,
                remote_plan_id,
                allowed_plans,
            )
            return None

        # 2. Prioritize session lookup via custom_id (matches session public_id)
        custom_id = remote_data.get("custom_id")
        session: Optional[SoulmateSession] = None
        if custom_id:
            sess_stmt = select(SoulmateSession).where(SoulmateSession.public_id == custom_id.strip())
            session = (await db.execute(sess_stmt)).scalars().first()
            if not session:
                logger.warning(
                    "Reconciliation: custom_id '%s' on subscription %s not found in sessions",
                    custom_id,
                    sub_id,
                )

        # 3. Fallback to subscriber email with ambiguity & safety checks
        if not session:
            subscriber_email = remote_data.get("subscriber", {}).get("email_address")
            if subscriber_email:
                clean_email = subscriber_email.strip().lower()
                sess_stmt = select(SoulmateSession).where(SoulmateSession.email_normalized == clean_email)
                matching_sessions = (await db.execute(sess_stmt)).scalars().all()

                if len(matching_sessions) == 1:
                    session = matching_sessions[0]
                    logger.warning(
                        "Reconciliation: bound unknown subscription %s to session %s via fallback subscriber email '%s' (custom_id missing)",
                        sub_id,
                        session.public_id,
                        clean_email,
                    )
                elif len(matching_sessions) > 1:
                    # Filter for candidates that haven't already had a subscription succeeded
                    unpaid_sessions = [
                        s for s in matching_sessions
                        if s.subscription_success_at is None and s.status != "paid"
                    ]
                    if len(unpaid_sessions) == 1:
                        session = unpaid_sessions[0]
                        logger.warning(
                            "Reconciliation: bound unknown subscription %s to unique unpaid session %s for email '%s'",
                            sub_id,
                            session.public_id,
                            clean_email,
                        )
                    else:
                        logger.error(
                            "Reconciliation rejected: ambiguous subscriber email '%s' for subscription %s matches %d sessions (unpaid=%d). Refusing automatic binding to prevent cross-session confusion.",
                            clean_email,
                            sub_id,
                            len(matching_sessions),
                            len(unpaid_sessions),
                        )
                        return None

        if session:
            sub = Subscription(
                session_id=session.id,
                user_id=session.user_id,
                provider="paypal",
                provider_subscription_id=sub_id,
                provider_plan_id=remote_data.get("plan_id", ""),
                provider_status=remote_status or "APPROVAL_PENDING",
                currency=settings.soulmate_currency or "USD",
                intro_price=settings.soulmate_intro_price,
                regular_price=settings.soulmate_regular_price or Decimal("29.00"),
                first_payment_at=last_paid_at,
                next_billing_at=next_billing_at,
                paid_through_at=next_billing_at,
                cancelled_at=status_update_time if remote_status == "CANCELLED" else None,
                suspended_at=status_update_time if remote_status == "SUSPENDED" else None,
                expired_at=status_update_time if remote_status == "EXPIRED" else None,
            )
            db.add(sub)
            await db.flush()

            if last_paid_at is not None:
                if session.subscription_success_at is None:
                    session.subscription_success_at = last_paid_at
                    session.status = "paid"
                    session.current_step = "result"
                    await cls._ensure_artifacts_initialized(session=session, paid_at=last_paid_at, db=db)

                amount_val = last_payment.get("amount", {}).get("value")
                try:
                    amount = Decimal(str(amount_val)) if amount_val else (sub.intro_price or Decimal("19.00"))
                except Exception:
                    amount = sub.intro_price or Decimal("19.00")
                currency = last_payment.get("amount", {}).get("currency_code") or sub.currency or "USD"
                pay_id = last_payment.get("id") or f"PAYPAL-LASTPAY-{sub.provider_subscription_id}"
                await PaymentLedgerService.record_payment(
                    db=db,
                    create_data=PaymentRecordCreate(
                        subscription_id=sub.id,
                        provider_payment_id=pay_id,
                        amount=amount,
                        currency=currency,
                        status="COMPLETED",
                        paid_at=last_paid_at,
                        raw_json=remote_data,
                    ),
                )
            return sub

        return None

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

        # If still in processing and auto_reconcile requested, reconcile against PayPal API
        if auto_reconcile and sub.first_payment_at is None and sub.provider_status not in ("CANCELLED", "EXPIRED"):
            reconciled = await cls.reconcile_subscription(
                db=db,
                provider_subscription_id=sub.provider_subscription_id,
                paypal_client=paypal_client,
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
            first_payment_at=sub.first_payment_at,
            next_billing_at=sub.next_billing_at,
            paid_through_at=sub.paid_through_at,
            cancelled_at=sub.cancelled_at,
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
            elif sub.first_payment_at:
                # Default to 30 days cycle from first payment if next billing time is unknown
                sub.paid_through_at = sub.first_payment_at + timedelta(days=30)

        # 2. Call PayPal cancel API (DEV-SPEC §9.8: POST /v1/billing/subscriptions/{id}/cancel, Acceptance #1)
        success = await client.cancel_subscription(
            subscription_id=sub.provider_subscription_id,
            reason=reason or "Customer request",
        )
        if not success:
            logger.error("PayPal API rejected cancellation for subscription %s", sub.provider_subscription_id)
            raise ValidationError("Failed to cancel subscription with PayPal. Please try again or contact support.")

        # 3. Update local state
        now = utc_now()
        sub.provider_status = "CANCELLED"
        sub.cancelled_at = now
        sub.next_billing_at = None

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

        return SubscriptionCancelResponse(
            status="CANCELLED",
            is_paid=sub.first_payment_at is not None,
            subscription_id=sub.provider_subscription_id,
            provider_status="CANCELLED",
            cancelled_at=sub.cancelled_at,
            paid_through_at=sub.paid_through_at,
            message="Subscription successfully cancelled. Access remains active through your current billing cycle.",
        )

