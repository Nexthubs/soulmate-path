"""
Subscription Service (DEV-SPEC §9.3–9.4, §15.7–15.8, Decisions: PAY-AUTH-01).
Handles server-side validation and registration of approved PayPal subscriptions,
enforces session ownership (IDOR prevention), duplicate confirmation idempotency,
and strict separation between subscription confirmation and entitlement authority.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
import re
from typing import Any, Dict, Optional, Set
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ForbiddenOwnershipError,
    NotFoundError,
    ValidationError,
)
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.soulmate.schema import (
    PayPalConfirmResponse,
    SubscriptionStatusResponse,
)
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

        provider_plan_id = sub_data.get("plan_id")
        provider_status = sub_data.get("status", "APPROVAL_PENDING").upper()

        # 3. Validate Plan ID against allowed Soulmate plans (DEV-SPEC §15.7 step 3, fail-closed)
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

        # 4. Validate Provider Status (Reject terminal invalid states)
        if provider_status in {"CANCELLED", "EXPIRED", "SUSPENDED"}:
            raise ValidationError(f"PayPal subscription is in invalid status: '{provider_status}'.")

        # 5. Extract Details & Dates
        currency = settings.soulmate_currency or "USD"
        intro_price = settings.soulmate_intro_price
        regular_price = settings.soulmate_regular_price or Decimal("29.00")

        billing_info = sub_data.get("billing_info", {})
        next_billing_at = parse_iso_datetime(billing_info.get("next_billing_time"))

        # 6. Upsert Local Subscription Record
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
    async def get_subscription_status(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
    ) -> SubscriptionStatusResponse:
        """
        Query current subscription and entitlement status for the active session (DEV-SPEC §15.8).
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

        is_paid = sub.first_payment_at is not None
        status = "ACTIVE" if is_paid else (sub.provider_status if sub.provider_status in {"CANCELLED", "EXPIRED"} else "PROCESSING")

        return SubscriptionStatusResponse(
            status=status,
            is_paid=is_paid,
            subscription_id=sub.provider_subscription_id,
            plan_id=sub.provider_plan_id,
            provider_status=sub.provider_status,
            first_payment_at=sub.first_payment_at,
            next_billing_at=sub.next_billing_at,
        )
