"""
PayPal Webhook Processing Service (DEV-SPEC §9.5–9.6, SP-404, Decisions: PAY-AUTH-01).

Preserves exact raw body bytes, extracts transmission headers, enforces signature verification gates,
guarantees unverified events never mutate business state, and implements idempotency and PayPal retry semantics.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, Optional, Protocol
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ValidationError, WebhookVerificationError
from app.core.logging import log_event
from app.db.base import utc_now
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import PayPalWebhookEvent, Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.soulmate.domain.ledger_models import PaymentRecordCreate
from app.soulmate.domain.webhook_models import (
    PayPalWebhookHeaders,
    PayPalWebhookRawRequest,
    PayPalWebhookResponse,
)
from app.soulmate.services.ledger_service import PaymentLedgerService
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


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


class WebhookVerifierProtocol(Protocol):
    """Protocol for pluggable PayPal signature verification (DEV-SPEC §9.6, SP-405)."""

    async def verify(
        self,
        raw_body: bytes,
        headers: PayPalWebhookHeaders,
        webhook_event: Optional[Dict[str, Any]] = None,
        webhook_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        ...


class PayPalWebhookService:
    """
    Orchestrates PayPal webhook ingestion, raw body preservation, verification gating,
    and idempotent database event recording.
    """

    @staticmethod
    def parse_raw_request(request: Request, raw_body: bytes) -> PayPalWebhookRawRequest:
        """
        Parse and validate incoming HTTP request into PayPalWebhookRawRequest container.
        Preserves raw_body exact byte sequence for signature calculation (Acceptance #1).
        Rejects empty or non-JSON payloads with HTTP 400.
        """
        # 1. Body emptiness validation
        if not raw_body or not raw_body.strip():
            log_event(
                event_type="paypal_webhook_rejected",
                message="Rejected empty webhook request body",
                level=logging.WARNING,
                error_code="VALIDATION_ERROR",
            )
            raise ValidationError(
                message="PayPal webhook request body must not be empty.",
                details={"reason": "empty_body"},
            )

        # 2. JSON syntax validation
        try:
            parsed_json = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log_event(
                event_type="paypal_webhook_rejected",
                message=f"Rejected malformed JSON webhook payload: {e}",
                level=logging.WARNING,
                error_code="VALIDATION_ERROR",
            )
            raise ValidationError(
                message="Malformed JSON in webhook payload.",
                details={"reason": "malformed_json", "error": str(e)},
            )

        if not isinstance(parsed_json, dict):
            raise ValidationError(
                message="Webhook payload must be a JSON object.",
                details={"reason": "non_object_json"},
            )

        # 3. Mandatory event identifier validation
        event_id = parsed_json.get("id")
        if not event_id or not isinstance(event_id, str) or not event_id.strip():
            raise ValidationError(
                message="Webhook payload missing required 'id' attribute.",
                details={"reason": "missing_event_id"},
            )

        event_type = parsed_json.get("event_type")
        if not event_type or not isinstance(event_type, str) or not event_type.strip():
            raise ValidationError(
                message="Webhook payload missing required 'event_type' attribute.",
                details={"reason": "missing_event_type"},
            )

        # 4. Extract transmission headers
        headers = PayPalWebhookHeaders.from_headers(request.headers)

        # 5. Extract optional resource attributes
        resource = parsed_json.get("resource")
        resource_id: Optional[str] = None
        if isinstance(resource, dict):
            resource_id = resource.get("id")

        return PayPalWebhookRawRequest(
            raw_body=raw_body,
            headers=headers,
            parsed_json=parsed_json,
            event_id=event_id.strip(),
            event_type=event_type.strip(),
            resource_id=resource_id,
            resource_type=parsed_json.get("resource_type"),
            summary=parsed_json.get("summary"),
            create_time=parsed_json.get("create_time"),
        )

    @classmethod
    async def process_webhook(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
        verifier: Optional[WebhookVerifierProtocol] = None,
        require_verification: bool = True,
        client: Optional[PayPalClient] = None,
    ) -> PayPalWebhookResponse:
        """
        Process parsed PayPal webhook request:
        1. Evaluates signature verification.
        2. High-Risk Invariant PAY-AUTH-01: Unverified events never mutate business state.
        3. Enforces idempotency via unique paypal_event_id DB constraint.
        4. Replays return 200 OK without re-executing business mutations (Acceptance #4).
        5. Atomic event dispatch with out-of-order state regression protection (SP-406).
        """
        event_id = raw_request.event_id
        event_type = raw_request.event_type

        # ----------------------------------------------------------------------
        # 1. Signature Verification Gate (PAY-AUTH-01, Acceptance #3)
        # ----------------------------------------------------------------------
        is_verified = False

        if require_verification:
            # Check for header presence
            if not raw_request.headers.is_complete():
                missing = raw_request.headers.missing_headers()
                log_event(
                    event_type="paypal_webhook_unverified",
                    message=f"Webhook event {event_id} missing required transmission headers: {missing}",
                    level=logging.WARNING,
                    error_code="VALIDATION_ERROR",
                    extra_data={"event_id": event_id, "event_type": event_type, "missing_headers": missing},
                )
                raise WebhookVerificationError(
                    message="Missing required PayPal transmission headers for signature verification.",
                    details={"missing_headers": missing},
                )

            if verifier is None:
                log_event(
                    event_type="paypal_webhook_unverified",
                    message=f"Webhook event {event_id} rejected: signature verifier is not provided (fail-closed)",
                    level=logging.ERROR,
                    error_code="VALIDATION_ERROR",
                    extra_data={"event_id": event_id, "event_type": event_type},
                )
                raise WebhookVerificationError(
                    message="Webhook signature verifier is not configured or provided.",
                    details={"event_id": event_id},
                )

            webhook_id = settings.paypal_webhook_id
            try:
                is_valid = await verifier.verify(
                    raw_body=raw_request.raw_body,
                    headers=raw_request.headers,
                    webhook_event=raw_request.parsed_json,
                    webhook_id=webhook_id,
                )
            except TypeError:
                is_valid = await verifier.verify(
                    raw_body=raw_request.raw_body,
                    headers=raw_request.headers,
                    webhook_id=webhook_id,
                )
            if not is_valid:
                log_event(
                    event_type="paypal_webhook_signature_failed",
                    message=f"Signature verification failed for webhook event {event_id}",
                    level=logging.WARNING,
                    error_code="VALIDATION_ERROR",
                    extra_data={"event_id": event_id, "event_type": event_type},
                )
                raise WebhookVerificationError(
                    message="PayPal webhook signature verification failed.",
                    details={"event_id": event_id},
                )
            is_verified = True
        else:
            is_verified = True

        # ----------------------------------------------------------------------
        # 2. Idempotency & Duplicate Event Check (DEV-SPEC §9.6 rules 4 & 5)
        # ----------------------------------------------------------------------
        stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event_id)
        existing_event = (await db.execute(stmt)).scalars().first()

        if existing_event is not None:
            # Already processed duplicate event -> return 200 OK so PayPal stops retrying
            log_event(
                event_type="paypal_webhook_duplicate",
                message=f"Duplicate PayPal webhook event {event_id} received. Returning success without mutations.",
                level=logging.INFO,
                extra_data={
                    "event_id": event_id,
                    "event_type": event_type,
                    "already_verified": existing_event.verified,
                },
            )
            return PayPalWebhookResponse(
                status="duplicate",
                event_id=event_id,
                event_type=event_type,
                duplicate=True,
            )

        # ----------------------------------------------------------------------
        # 3. Record verified event & dispatch business transitions in transaction
        # ----------------------------------------------------------------------
        new_event = PayPalWebhookEvent(
            paypal_event_id=event_id,
            event_type=event_type,
            resource_id=raw_request.resource_id,
            payload_json=raw_request.parsed_json,
            verified=is_verified,
            processed_at=datetime.now(timezone.utc),
        )
        db.add(new_event)
        await db.flush()

        try:
            await cls._dispatch_event(
                event_type=event_type,
                raw_request=raw_request,
                db=db,
                client=client,
            )
            await db.commit()
            await db.refresh(new_event)
        except Exception as e:
            await db.rollback()
            new_event.processing_error = str(e)
            db.add(new_event)
            await db.commit()
            logger.error("Error processing PayPal webhook %s (%s): %s", event_id, event_type, e, exc_info=True)
            raise

        log_event(
            event_type="paypal_webhook_recorded",
            message=f"Successfully recorded PayPal webhook event {event_id} ({event_type})",
            level=logging.INFO,
            extra_data={"event_id": event_id, "event_type": event_type, "verified": is_verified},
        )

        return PayPalWebhookResponse(
            status="received",
            event_id=event_id,
            event_type=event_type,
            duplicate=False,
        )

    @classmethod
    async def _dispatch_event(
        cls,
        event_type: str,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
        client: Optional[PayPalClient] = None,
    ) -> None:
        """Route webhook event to specialized state machine and ledger handlers (SP-406)."""
        if event_type == "PAYMENT.SALE.COMPLETED":
            await cls._handle_payment_sale_completed(raw_request, db, client)
        elif event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            await cls._handle_subscription_activated(raw_request, db, client)
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            await cls._handle_subscription_cancelled(raw_request, db)
        elif event_type == "BILLING.SUBSCRIPTION.SUSPENDED":
            await cls._handle_subscription_suspended(raw_request, db)
        elif event_type == "BILLING.SUBSCRIPTION.EXPIRED":
            await cls._handle_subscription_expired(raw_request, db)
        elif event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
            await cls._handle_payment_failed(raw_request, db)
        elif event_type in ("PAYMENT.SALE.REFUNDED", "PAYMENT.SALE.REVERSED"):
            await cls._handle_payment_refunded(raw_request, db)
        else:
            logger.info("No specific business handler required for webhook event_type %s", event_type)

    @classmethod
    async def _handle_payment_sale_completed(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
        client: Optional[PayPalClient] = None,
    ) -> None:
        """
        Handle PAYMENT.SALE.COMPLETED (DEV-SPEC §9.4, §10, §14, Decisions: PAY-AUTH-01, TIME-01).
        - Idempotently creates SubscriptionPayment ledger entry.
        - Activates first_payment_at and SoulmateSession.subscription_success_at if not set.
        - Does NOT regress provider_status if already CANCELLED or EXPIRED.
        - Replays of same event create zero duplicate ledger entries.
        """
        resource = raw_request.parsed_json.get("resource", {})
        pay_id = resource.get("id") or raw_request.resource_id
        provider_sub_id = resource.get("billing_agreement_id") or resource.get("custom")

        if not provider_sub_id:
            logger.warning("PAYMENT.SALE.COMPLETED event %s missing billing_agreement_id", raw_request.event_id)
            return

        stmt = select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
        sub = (await db.execute(stmt)).scalars().first()

        if sub is None:
            # Reconciliation path: check remote PayPal or create linked record if found
            sub = await cls.reconcile_subscription(provider_subscription_id=provider_sub_id, db=db, client=client)

        if sub is None:
            logger.warning("PAYMENT.SALE.COMPLETED: Subscription %s not found in local database", provider_sub_id)
            return

        paid_at = parse_iso_datetime(resource.get("create_time")) or parse_iso_datetime(raw_request.create_time) or utc_now()

        # Idempotently record payment in durable ledger via PaymentLedgerService (SP-407)
        if pay_id:
            amount_str = resource.get("amount", {}).get("total", "0.00")
            try:
                amount = Decimal(str(amount_str))
            except Exception:
                amount = Decimal("0.00")

            currency = resource.get("amount", {}).get("currency", sub.currency or "USD")

            payment, created = await PaymentLedgerService.record_payment(
                db=db,
                create_data=PaymentRecordCreate(
                    subscription_id=sub.id,
                    provider_payment_id=pay_id,
                    provider_event_id=raw_request.event_id,
                    amount=amount,
                    currency=currency,
                    status="COMPLETED",
                    paid_at=paid_at,
                    raw_json=resource,
                ),
            )
            if created:
                logger.info("Recorded payment ledger %s (cycle %d) for subscription %s", pay_id, payment.cycle_no or 1, provider_sub_id)
            else:
                logger.info("Payment %s already recorded for subscription %s (idempotent)", pay_id, provider_sub_id)

        # Update first_payment_at if initial payment
        if sub.first_payment_at is None:
            sub.first_payment_at = paid_at

        # Out-of-order protection: Do NOT regress provider_status if already CANCELLED or EXPIRED
        if sub.provider_status not in ("CANCELLED", "EXPIRED"):
            sub.provider_status = "ACTIVE"
            sub.suspended_at = None

        # Activate entitlement on SoulmateSession (PAY-AUTH-01, TIME-01)
        sess_stmt = select(SoulmateSession).where(SoulmateSession.id == sub.session_id)
        session = (await db.execute(sess_stmt)).scalars().first()

        if session is not None:
            if session.subscription_success_at is None:
                session.subscription_success_at = paid_at
                session.status = "paid"
                session.current_step = "result"
                log_event(
                    event_type="entitlement_activated",
                    message=f"Entitlement activated for session {session.public_id} via PAYMENT.SALE.COMPLETED",
                    level=logging.INFO,
                    extra_data={
                        "session_public_id": session.public_id,
                        "subscription_id": str(sub.id),
                        "provider_sub_id": provider_sub_id,
                        "subscription_success_at": paid_at.isoformat(),
                    },
                )
                await cls._ensure_artifacts_initialized(session=session, paid_at=paid_at, db=db)
            else:
                logger.info(
                    "Session %s already entitled at %s (invariant TIME-01 preserved)",
                    session.public_id,
                    session.subscription_success_at.isoformat(),
                )

    @classmethod
    async def _handle_subscription_activated(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
        client: Optional[PayPalClient] = None,
    ) -> None:
        """
        Handle BILLING.SUBSCRIPTION.ACTIVATED.
        Out-of-order rules:
        - Do not regress if already CANCELLED or EXPIRED.
        - Do not regress if event timestamp is older than existing status timestamp.
        """
        resource = raw_request.parsed_json.get("resource", {})
        provider_sub_id = resource.get("id") or raw_request.resource_id
        if not provider_sub_id:
            return

        stmt = select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
        sub = (await db.execute(stmt)).scalars().first()
        if not sub:
            sub = await cls.reconcile_subscription(provider_sub_id=provider_sub_id, db=db, client=client)
            if not sub:
                return

        event_time = parse_iso_datetime(raw_request.create_time) or utc_now()

        # Out-of-order check 1: Terminal states
        if sub.provider_status in ("CANCELLED", "EXPIRED"):
            logger.warning(
                "Ignoring stale/out-of-order BILLING.SUBSCRIPTION.ACTIVATED for %s; currently in terminal state %s",
                provider_sub_id,
                sub.provider_status,
            )
            return

        # Out-of-order check 2: Timestamp ordering vs cancelled_at / suspended_at
        if sub.cancelled_at and event_time <= sub.cancelled_at:
            logger.warning(
                "Ignoring stale BILLING.SUBSCRIPTION.ACTIVATED for %s (event_time %s <= cancelled_at %s)",
                provider_sub_id,
                event_time,
                sub.cancelled_at,
            )
            return

        if sub.suspended_at and event_time <= sub.suspended_at:
            logger.warning(
                "Ignoring stale BILLING.SUBSCRIPTION.ACTIVATED for %s (event_time %s <= suspended_at %s)",
                provider_sub_id,
                event_time,
                sub.suspended_at,
            )
            return

        # Valid transition
        sub.provider_status = "ACTIVE"
        sub.suspended_at = None
        logger.info("Subscription %s updated to ACTIVE from webhook", provider_sub_id)

    @classmethod
    async def _handle_subscription_cancelled(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
    ) -> None:
        """
        Handle BILLING.SUBSCRIPTION.CANCELLED.
        Marks provider_status = CANCELLED.
        Invariants (DEV-SPEC §9.8, PAY-AUTH-01):
        - Never deletes existing payments, session, or artifacts.
        - Preserves entitlement for paid_through_at period.
        """
        resource = raw_request.parsed_json.get("resource", {})
        provider_sub_id = resource.get("id") or raw_request.resource_id
        if not provider_sub_id:
            return

        stmt = select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
        sub = (await db.execute(stmt)).scalars().first()
        if not sub:
            return

        event_time = parse_iso_datetime(raw_request.create_time) or utc_now()

        sub.provider_status = "CANCELLED"
        if not sub.cancelled_at or event_time > sub.cancelled_at:
            sub.cancelled_at = event_time

        logger.info("Subscription %s cancelled at %s", provider_sub_id, sub.cancelled_at)

    @classmethod
    async def _handle_subscription_suspended(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
    ) -> None:
        """
        Handle BILLING.SUBSCRIPTION.SUSPENDED.
        Out-of-order rule: Do not regress if already CANCELLED or EXPIRED.
        """
        resource = raw_request.parsed_json.get("resource", {})
        provider_sub_id = resource.get("id") or raw_request.resource_id
        if not provider_sub_id:
            return

        stmt = select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
        sub = (await db.execute(stmt)).scalars().first()
        if not sub:
            return

        event_time = parse_iso_datetime(raw_request.create_time) or utc_now()

        if sub.provider_status in ("CANCELLED", "EXPIRED"):
            logger.warning(
                "Ignoring SUSPENDED event for %s; already in terminal state %s",
                provider_sub_id,
                sub.provider_status,
            )
            return

        if sub.cancelled_at and event_time <= sub.cancelled_at:
            return

        sub.provider_status = "SUSPENDED"
        if not sub.suspended_at or event_time > sub.suspended_at:
            sub.suspended_at = event_time

        logger.info("Subscription %s suspended at %s", provider_sub_id, sub.suspended_at)

    @classmethod
    async def _handle_subscription_expired(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
    ) -> None:
        """Handle BILLING.SUBSCRIPTION.EXPIRED. Terminal state."""
        resource = raw_request.parsed_json.get("resource", {})
        provider_sub_id = resource.get("id") or raw_request.resource_id
        if not provider_sub_id:
            return

        stmt = select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
        sub = (await db.execute(stmt)).scalars().first()
        if not sub:
            return

        event_time = parse_iso_datetime(raw_request.create_time) or utc_now()
        sub.provider_status = "EXPIRED"
        sub.expired_at = event_time
        logger.info("Subscription %s expired at %s", provider_sub_id, event_time)

    @classmethod
    async def _handle_payment_failed(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
    ) -> None:
        """
        Handle BILLING.SUBSCRIPTION.PAYMENT.FAILED (DEV-SPEC §9.7).
        Records failed payment ledger record without removing existing entitlement.
        """
        resource = raw_request.parsed_json.get("resource", {})
        provider_sub_id = resource.get("billing_agreement_id") or resource.get("id")
        if not provider_sub_id:
            return

        stmt = select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
        sub = (await db.execute(stmt)).scalars().first()
        if not sub:
            return

        payment_id = resource.get("id") or f"FAILED-{raw_request.event_id}"

        amount_str = resource.get("amount", {}).get("total", "0.00")
        try:
            amount = Decimal(str(amount_str))
        except Exception:
            amount = Decimal("0.00")
        currency = resource.get("amount", {}).get("currency", sub.currency or "USD")

        await PaymentLedgerService.record_payment(
            db=db,
            create_data=PaymentRecordCreate(
                subscription_id=sub.id,
                provider_payment_id=payment_id,
                provider_event_id=raw_request.event_id,
                amount=amount,
                currency=currency,
                status="FAILED",
                paid_at=None,
                raw_json=resource,
            ),
        )

        # Invariant checks:
        # If first payment never succeeded, ensure subscription_success_at remains None
        if sub.first_payment_at is None:
            sess_stmt = select(SoulmateSession).where(SoulmateSession.id == sub.session_id)
            session = (await db.execute(sess_stmt)).scalars().first()
            if session:
                session.subscription_success_at = None

    @classmethod
    async def _handle_payment_refunded(
        cls,
        raw_request: PayPalWebhookRawRequest,
        db: AsyncSession,
    ) -> None:
        """Handle PAYMENT.SALE.REFUNDED and PAYMENT.SALE.REVERSED."""
        resource = raw_request.parsed_json.get("resource", {})
        parent_id = resource.get("parent_payment") or resource.get("sale_id")
        if not parent_id:
            return

        status = "REFUNDED" if "REFUNDED" in raw_request.event_type else "REVERSED"
        refunded_at = parse_iso_datetime(resource.get("create_time")) or utc_now()
        await PaymentLedgerService.record_refund(
            db=db,
            provider_payment_id=parent_id,
            refunded_at=refunded_at,
            status=status,
            raw_json=resource,
        )

    @classmethod
    async def _ensure_artifacts_initialized(
        cls,
        session: SoulmateSession,
        paid_at: datetime,
        db: AsyncSession,
    ) -> None:
        """Initialize durable artifact rows via canonical SubscriptionService."""
        await SubscriptionService._ensure_artifacts_initialized(session=session, paid_at=paid_at, db=db)

    @classmethod
    async def reconcile_subscription(
        cls,
        provider_subscription_id: str,
        db: AsyncSession,
        client: Optional[PayPalClient] = None,
    ) -> Optional[Subscription]:
        """Reconcile subscription via canonical SubscriptionService (SP-408)."""
        return await SubscriptionService.reconcile_subscription(
            db=db,
            provider_subscription_id=provider_subscription_id,
            paypal_client=client,
        )

