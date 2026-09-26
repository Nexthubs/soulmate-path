"""
PayPal Webhook Processing Service (DEV-SPEC §9.5–9.6, SP-404, Decisions: PAY-AUTH-01).

Preserves exact raw body bytes, extracts transmission headers, enforces signature verification gates,
guarantees unverified events never mutate business state, and implements idempotency and PayPal retry semantics.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, Optional, Protocol
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ValidationError, WebhookVerificationError
from app.core.logging import log_event
from app.core.errors import ProviderUnavailableError
from app.soulmate.services.payment_consistency import payment_lock, apply_provider_status, apply_billing_count
from app.db.base import utc_now
from app.db.models.billing import PayPalWebhookEvent, Subscription
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

        # Serialize same-event deliveries, even before its DB row exists.
        await payment_lock(db, "event", event_id)
        event = (await db.execute(select(PayPalWebhookEvent).where(
            PayPalWebhookEvent.paypal_event_id == event_id
        ).execution_options(populate_existing=True))).scalars().first()
        if event is not None and event.processed_at is not None and event.processing_error is None:
            await db.commit()
            return PayPalWebhookResponse(status="duplicate", event_id=event_id,
                                         event_type=event_type, duplicate=True)
        retry = event is not None
        if event is None:
            event = PayPalWebhookEvent(
                paypal_event_id=event_id, event_type=event_type,
                resource_id=raw_request.resource_id, payload_json=raw_request.parsed_json,
                verified=is_verified,
            )
            db.add(event)
        await db.flush()
        try:
            # Keep the receipt outside the savepoint. On failure ALL business
            # changes roll back while the retryable receipt survives durably.
            async with db.begin_nested():
                await cls._dispatch_event(event_type, raw_request, db, client)
            event.processed_at = utc_now()
            event.processing_error = None
            await db.commit()
        except Exception as exc:
            event.processing_error = type(exc).__name__
            event.processed_at = None
            await db.commit()
            log_event(event_type="paypal_webhook_retry_required", message="Verified webhook business processing incomplete",
                      level=logging.WARNING, extra_data={"event_id": event_id, "event_type": event_type,
                                                        "error_type": type(exc).__name__})
            raise
        log_event(event_type="paypal_webhook_processed", message="Verified webhook business processing completed",
                  extra_data={"event_id": event_id, "event_type": event_type, "retry": retry})
        return PayPalWebhookResponse(status="success" if retry else "received",
                                     event_id=event_id, event_type=event_type, duplicate=False)

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
        elif event_type == "BILLING.SUBSCRIPTION.UPDATED":
            await cls._handle_subscription_updated(raw_request, db, client)
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
    async def _event_subscription(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession,
        client: Optional[PayPalClient] = None, *, sale: bool = False, reconcile_missing: bool = True,
    ) -> Subscription:
        resource = raw_request.parsed_json.get("resource", {})
        sub_id = (resource.get("billing_agreement_id") or resource.get("custom")) if sale else (resource.get("billing_agreement_id") or resource.get("id"))
        if not sub_id:
            raise ValidationError("Subscription identifier missing from payment event.")
        sub = await SubscriptionService.lock_subscription(db, sub_id)
        if sub is None and reconcile_missing:
            sub = await cls.reconcile_subscription(sub_id, db, client)
        if sub is None:
            raise ProviderUnavailableError("Webhook is waiting for a trusted subscription binding.")
        return sub

    @staticmethod
    def _event_time(raw_request: PayPalWebhookRawRequest) -> datetime:
        resource = raw_request.parsed_json.get("resource", {})
        at = parse_iso_datetime(resource.get("status_update_time")) or parse_iso_datetime(raw_request.create_time)
        if at is None:
            raise ValidationError("Provider event time is required.")
        return at

    @classmethod
    async def _handle_payment_sale_completed(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession, client: Optional[PayPalClient] = None,
    ) -> None:
        resource = raw_request.parsed_json.get("resource", {})
        sub = await cls._event_subscription(raw_request, db, client, sale=True)
        pay_id = resource.get("id")
        paid_at = parse_iso_datetime(resource.get("create_time")) or parse_iso_datetime(raw_request.create_time)
        try:
            amount = Decimal(str(resource.get("amount", {}).get("total")))
        except Exception as exc:
            raise ValidationError("Sale amount is required.") from exc
        currency = resource.get("amount", {}).get("currency")
        if not pay_id or paid_at is None or not currency or not amount.is_finite() or amount <= 0:
            raise ValidationError("Sale ID, positive amount, currency and provider payment time are required.")
        await PaymentLedgerService.record_payment(db, PaymentRecordCreate(
            subscription_id=sub.id, provider_payment_id=pay_id,
            provider_event_id=raw_request.event_id, amount=amount, currency=currency,
            status="COMPLETED", paid_at=paid_at, raw_json=resource,
        ))
        apply_provider_status(sub, "ACTIVE", paid_at)
        apply_billing_count(sub, 0, paid_at)
        await SubscriptionService.activate_from_payment(db, sub, paid_at)

    @classmethod
    async def _handle_subscription_activated(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession, client: Optional[PayPalClient] = None,
    ) -> None:
        sub = await cls._event_subscription(raw_request, db, client)
        at = cls._event_time(raw_request)
        apply_provider_status(sub, "ACTIVE", at)
        # Activation is not proof of payment, nor of a cleared billing issue.
        count = raw_request.parsed_json.get("resource", {}).get("billing_info", {}).get("failed_payments_count")
        if count is not None:
            apply_billing_count(sub, int(count), at)

    @classmethod
    async def _handle_subscription_updated(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession, client: Optional[PayPalClient] = None,
    ) -> None:
        sub = await cls._event_subscription(raw_request, db, client)
        resource = raw_request.parsed_json.get("resource", {})
        at = cls._event_time(raw_request)
        status = str(resource.get("status") or "").upper()
        accepted = bool(status) and apply_provider_status(sub, status, at)
        # Stale status snapshots must not update associated dates or counters.
        if not accepted:
            return
        billing = resource.get("billing_info", {})
        count = billing.get("failed_payments_count")
        if count is not None:
            apply_billing_count(sub, int(count), at)
        next_at = parse_iso_datetime(billing.get("next_billing_time"))
        if next_at:
            if sub.provider_status not in ("CANCELLED", "EXPIRED"):
                sub.next_billing_at = next_at
            if sub.paid_through_at is None or next_at > sub.paid_through_at:
                sub.paid_through_at = next_at

    @classmethod
    async def _handle_subscription_cancelled(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession,
    ) -> None:
        sub = await cls._event_subscription(raw_request, db, reconcile_missing=False)
        at = cls._event_time(raw_request)
        previous_next = sub.next_billing_at
        if not apply_provider_status(sub, "CANCELLED", at):
            return
        billing = raw_request.parsed_json.get("resource", {}).get("billing_info", {})
        paid_through = parse_iso_datetime(billing.get("next_billing_time")) or previous_next
        if paid_through and (sub.paid_through_at is None or paid_through > sub.paid_through_at):
            sub.paid_through_at = paid_through

    @classmethod
    async def _handle_subscription_suspended(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession,
    ) -> None:
        sub = await cls._event_subscription(raw_request, db, reconcile_missing=False)
        apply_provider_status(sub, "SUSPENDED", cls._event_time(raw_request))

    @classmethod
    async def _handle_subscription_expired(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession,
    ) -> None:
        sub = await cls._event_subscription(raw_request, db, reconcile_missing=False)
        apply_provider_status(sub, "EXPIRED", cls._event_time(raw_request))

    @classmethod
    async def _handle_payment_failed(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession,
    ) -> None:
        sub = await cls._event_subscription(raw_request, db, reconcile_missing=False)
        resource = raw_request.parsed_json.get("resource", {})
        at = cls._event_time(raw_request)
        # Failed subscription events identify the subscription, not a sale.
        # Use their event identity so two failed attempts do not collapse.
        amount_info = resource.get("amount", {})
        amount = Decimal(str(amount_info.get("total", "0.00")))
        await PaymentLedgerService.record_payment(db, PaymentRecordCreate(
            subscription_id=sub.id, provider_payment_id=f"FAILED-{raw_request.event_id}",
            provider_event_id=raw_request.event_id, amount=amount,
            currency=amount_info.get("currency", sub.currency), status="FAILED", raw_json=resource,
        ))
        count = resource.get("billing_info", {}).get("failed_payments_count")
        apply_billing_count(sub, int(count) if count is not None else (sub.failed_payments_count or 0) + 1, at)
        status = str(resource.get("status") or "").upper()
        if status in ("ACTIVE", "SUSPENDED"):
            apply_provider_status(sub, status, at)

    @classmethod
    async def _handle_payment_refunded(
        cls, raw_request: PayPalWebhookRawRequest, db: AsyncSession,
    ) -> None:
        resource = raw_request.parsed_json.get("resource", {})
        # Refunds have their own resource ID; parent_payment is NOT the Sale ID.
        sale_id = resource.get("sale_id")
        if raw_request.event_type == "PAYMENT.SALE.REVERSED":
            sale_id = sale_id or resource.get("id")
        if not sale_id:
            raise ProviderUnavailableError("Refund is waiting for a valid sale association.")
        at = parse_iso_datetime(resource.get("create_time")) or cls._event_time(raw_request)
        status = "REFUNDED" if raw_request.event_type == "PAYMENT.SALE.REFUNDED" else "REVERSED"
        payment = await PaymentLedgerService.record_refund(
            db, provider_payment_id=sale_id, refunded_at=at, status=status, raw_json=resource,
        )
        if payment is None:
            raise ProviderUnavailableError("Refund is waiting for its original sale; retry required.")

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
