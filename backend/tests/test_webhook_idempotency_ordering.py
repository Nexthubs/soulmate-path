"""
Unit and Integration Tests for Webhook Event Idempotency and Out-of-Order Handling (SP-406, DEV-SPEC §9.5–9.6, §14, Decisions: PAY-AUTH-01, TIME-01).

Acceptance Criteria:
1. Replay same successful payment event N times -> exactly one ledger entry and one entitlement activation.
2. Cancellation/activation/payment events cannot regress state incorrectly because of stale event order.
3. Ambiguous states have a reconciliation path that preserves monotonicity.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import PayPalWebhookEvent, Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.webhook_models import PayPalWebhookHeaders, PayPalWebhookRawRequest
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.webhook_service import PayPalWebhookService
from app.soulmate.services.webhook_verifier import get_webhook_verifier


@pytest.fixture
async def async_db_session():
    """Provides an async transactional DB session for testing."""
    async with AsyncSessionLocal() as session:
        yield session


class MockSuccessVerifier:
    async def verify(self, raw_body: bytes, headers: PayPalWebhookHeaders, **kwargs: Any) -> bool:
        return True


SAMPLE_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-123",
    "PAYPAL-TRANSMISSION-ID": "trans_123456789",
    "PAYPAL-TRANSMISSION-SIG": "dummy_sig_base64_content",
    "PAYPAL-TRANSMISSION-TIME": "2026-09-25T12:00:00Z",
}


def make_raw_request(event_data: Dict[str, Any]) -> PayPalWebhookRawRequest:
    raw_bytes = json.dumps(event_data).encode("utf-8")

    class DummyReq:
        headers = SAMPLE_HEADERS

    return PayPalWebhookService.parse_raw_request(request=DummyReq(), raw_body=raw_bytes)


async def create_test_session_and_sub(
    db: AsyncSession,
    provider_sub_id: str,
    status: str = "PROCESSING",
    first_payment_at: Optional[datetime] = None,
    cancelled_at: Optional[datetime] = None,
    suspended_at: Optional[datetime] = None,
) -> tuple[SoulmateSession, Subscription]:
    """Helper to seed a test session and subscription."""
    public_id = f"test_sess_{uuid.uuid4().hex[:10]}"
    user_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=user_email,
        email_normalized=user_email,
        subscription_success_at=first_payment_at,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=provider_sub_id,
        provider_plan_id="P-SOULMATE-INTRO",
        provider_status=status,
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        first_payment_at=first_payment_at,
        cancelled_at=cancelled_at,
        suspended_at=suspended_at,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sess, sub


# ==============================================================================
# 1. Acceptance Criteria 1: Replay Same Payment Event N Times
# ==============================================================================


@pytest.mark.asyncio
async def test_replay_payment_event_n_times_single_ledger_and_activation(async_db_session: AsyncSession):
    """
    Acceptance #1:
    Replaying the same PAYMENT.SALE.COMPLETED event N times produces:
    - Exactly 1 record in paypal_webhook_events
    - Exactly 1 record in subscription_payments (single ledger entry)
    - Exactly 1 entitlement activation on SoulmateSession
    - Exactly 1 SKETCH artifact and 1 REPORT artifact with immutable unlock dates
    """
    provider_sub_id = f"I-REPLAY-{uuid.uuid4().hex[:8]}"
    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="APPROVAL_PENDING",
    )
    assert session.subscription_success_at is None
    assert sub.first_payment_at is None

    event_id = f"WH-REPLAY-PAY-{uuid.uuid4().hex[:8]}"
    payment_id = f"SALE-REPLAY-{uuid.uuid4().hex[:8]}"
    payment_time_str = "2026-09-25T12:00:00Z"

    event_data = {
        "id": event_id,
        "event_version": "1.0",
        "create_time": payment_time_str,
        "resource_type": "sale",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "summary": "Payment completed for subscription",
        "resource": {
            "id": payment_id,
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
            "create_time": payment_time_str,
        },
    }

    # First delivery
    raw_req_1 = make_raw_request(event_data)
    resp_1 = await PayPalWebhookService.process_webhook(
        raw_request=raw_req_1,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )
    assert resp_1.status == "received"
    assert resp_1.duplicate is False

    # Check state after first delivery
    await async_db_session.refresh(session)
    await async_db_session.refresh(sub)
    assert session.subscription_success_at is not None
    assert session.status == "paid"
    assert sub.first_payment_at is not None
    assert sub.provider_status == "ACTIVE"

    initial_success_at = session.subscription_success_at

    # Verify artifacts created
    art_stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == session.id)
    artifacts = (await async_db_session.execute(art_stmt)).scalars().all()
    assert len(artifacts) == 2
    sketch_art = next(a for a in artifacts if a.artifact_type == "SKETCH")
    report_art = next(a for a in artifacts if a.artifact_type == "REPORT")
    assert sketch_art.unlock_at == initial_success_at + timedelta(hours=12)
    assert report_art.unlock_at == initial_success_at + timedelta(hours=24)

    # Verify payments ledger has exactly 1 entry
    pay_stmt = select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id)
    payments = (await async_db_session.execute(pay_stmt)).scalars().all()
    assert len(payments) == 1
    assert payments[0].provider_payment_id == payment_id
    assert payments[0].cycle_no == 1
    assert payments[0].amount == Decimal("19.00")
    assert payments[0].status == "COMPLETED"

    # Replay 4 more times (N = 5 total deliveries)
    for _ in range(4):
        raw_req_replay = make_raw_request(event_data)
        resp_replay = await PayPalWebhookService.process_webhook(
            raw_request=raw_req_replay,
            db=async_db_session,
            verifier=MockSuccessVerifier(),
        )
        assert resp_replay.status == "duplicate"
        assert resp_replay.duplicate is True

    # Assert invariant: ZERO secondary mutations after 5 replays
    all_events_stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event_id)
    events_in_db = (await async_db_session.execute(all_events_stmt)).scalars().all()
    assert len(events_in_db) == 1

    all_payments = (await async_db_session.execute(pay_stmt)).scalars().all()
    assert len(all_payments) == 1

    await async_db_session.refresh(session)
    assert session.subscription_success_at == initial_success_at

    all_artifacts = (await async_db_session.execute(art_stmt)).scalars().all()
    assert len(all_artifacts) == 2


@pytest.mark.asyncio
async def test_replayed_payment_id_across_different_event_ids_is_idempotent(async_db_session: AsyncSession):
    """
    If PayPal delivers the same sale payment ID with two different webhook event IDs,
    the ledger must NOT create a duplicate SubscriptionPayment row.
    """
    provider_sub_id = f"I-DIFF-EVENT-{uuid.uuid4().hex[:8]}"
    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="ACTIVE",
    )

    shared_payment_id = f"SALE-SHARED-{uuid.uuid4().hex[:8]}"

    event_1 = {
        "id": f"WH-EVT-1-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T12:00:00Z",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": shared_payment_id,
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
        },
    }
    await PayPalWebhookService.process_webhook(
        raw_request=make_raw_request(event_1),
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    # Event 2 has a DIFFERENT webhook event ID, but the SAME resource ID (duplicate capture)
    event_2 = {
        "id": f"WH-EVT-2-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T12:05:00Z",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": shared_payment_id,
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
        },
    }
    await PayPalWebhookService.process_webhook(
        raw_request=make_raw_request(event_2),
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    # Payments table must still have exactly 1 record
    pay_stmt = select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id)
    payments = (await async_db_session.execute(pay_stmt)).scalars().all()
    assert len(payments) == 1
    assert payments[0].provider_payment_id == shared_payment_id


# ==============================================================================
# 2. Acceptance Criteria 2: Out-of-Order Handling & State Regression Prevention
# ==============================================================================


@pytest.mark.asyncio
async def test_stale_activated_event_does_not_regress_cancelled_subscription(async_db_session: AsyncSession):
    """
    Acceptance #2:
    At T2 (14:00), user cancels -> subscription status becomes CANCELLED with cancelled_at = T2.
    At T3 (14:05), a delayed BILLING.SUBSCRIPTION.ACTIVATED generated at T1 (13:50 < T2) arrives.
    Subscription status MUST NOT regress back to ACTIVE.
    """
    provider_sub_id = f"I-ORDER-CANCEL-{uuid.uuid4().hex[:8]}"
    cancelled_time = datetime(2026, 9, 25, 14, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="CANCELLED",
        cancelled_at=cancelled_time,
    )

    # Delayed ACTIVATED event with older create_time (13:50:00Z)
    stale_activated_event = {
        "id": f"WH-STALE-ACT-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T13:50:00Z",
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": provider_sub_id,
            "status": "ACTIVE",
        },
    }

    raw_req = make_raw_request(stale_activated_event)
    resp = await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )
    assert resp.status == "received"

    # State machine assertion: CANCELLED status must NOT have regressed to ACTIVE
    await async_db_session.refresh(sub)
    assert sub.provider_status == "CANCELLED"
    assert sub.cancelled_at == cancelled_time


@pytest.mark.asyncio
async def test_terminal_cancelled_state_cannot_be_activated_even_by_newer_event(async_db_session: AsyncSession):
    """
    Acceptance #2:
    CANCELLED is a terminal status in PayPal Subscriptions v1.
    Even if an ACTIVATED event with a newer timestamp arrives, it cannot reactivate a CANCELLED subscription.
    """
    provider_sub_id = f"I-TERMINAL-{uuid.uuid4().hex[:8]}"
    cancelled_time = datetime(2026, 9, 25, 14, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="CANCELLED",
        cancelled_at=cancelled_time,
    )

    bogus_activated_event = {
        "id": f"WH-BOGUS-ACT-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T14:30:00Z",  # Newer time
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": provider_sub_id,
            "status": "ACTIVE",
        },
    }

    raw_req = make_raw_request(bogus_activated_event)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    await async_db_session.refresh(sub)
    assert sub.provider_status == "CANCELLED"


@pytest.mark.asyncio
async def test_stale_activated_event_does_not_regress_suspended_subscription(async_db_session: AsyncSession):
    """
    At T2 (14:00), subscription is SUSPENDED.
    A delayed ACTIVATED event with T1 (13:50 < T2) must NOT regress status to ACTIVE.
    """
    provider_sub_id = f"I-ORDER-SUSP-{uuid.uuid4().hex[:8]}"
    suspended_time = datetime(2026, 9, 25, 14, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="SUSPENDED",
        suspended_at=suspended_time,
    )

    stale_activated = {
        "id": f"WH-STALE-SUSP-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T13:50:00Z",
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": provider_sub_id,
            "status": "ACTIVE",
        },
    }

    raw_req = make_raw_request(stale_activated)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    await async_db_session.refresh(sub)
    assert sub.provider_status == "SUSPENDED"


@pytest.mark.asyncio
async def test_newer_activated_event_resumes_suspended_subscription(async_db_session: AsyncSession):
    """
    At T2 (14:00), subscription is SUSPENDED.
    At T3 (14:15 > T2), buyer fixes payment method -> ACTIVATED event arrives.
    Subscription updates to ACTIVE and clears suspended_at.
    """
    provider_sub_id = f"I-RESUME-{uuid.uuid4().hex[:8]}"
    suspended_time = datetime(2026, 9, 25, 14, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="SUSPENDED",
        suspended_at=suspended_time,
    )

    newer_activated = {
        "id": f"WH-RESUME-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T14:15:00Z",
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": provider_sub_id,
            "status": "ACTIVE",
        },
    }

    raw_req = make_raw_request(newer_activated)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    await async_db_session.refresh(sub)
    assert sub.provider_status == "ACTIVE"
    assert sub.suspended_at is None


@pytest.mark.asyncio
async def test_payment_completed_after_cancellation_records_ledger_without_reactivating(async_db_session: AsyncSession):
    """
    In-flight payment capture completing after user cancellation:
    - Records ledger entry for accounting audit
    - Does NOT reactivate subscription back to ACTIVE (remains CANCELLED)
    """
    provider_sub_id = f"I-INFLIGHT-{uuid.uuid4().hex[:8]}"
    cancelled_time = datetime(2026, 9, 25, 14, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="CANCELLED",
        cancelled_at=cancelled_time,
    )

    inflight_payment = {
        "id": f"WH-INFLIGHT-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T14:02:00Z",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": f"SALE-INFLIGHT-{uuid.uuid4().hex[:8]}",
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
        },
    }

    raw_req = make_raw_request(inflight_payment)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    # 1. Payment recorded in ledger
    pay_stmt = select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id)
    payments = (await async_db_session.execute(pay_stmt)).scalars().all()
    assert len(payments) == 1

    # 2. Subscription remains CANCELLED (no regression)
    await async_db_session.refresh(sub)
    assert sub.provider_status == "CANCELLED"


@pytest.mark.asyncio
async def test_subsequent_payment_failed_does_not_clear_first_entitlement(async_db_session: AsyncSession):
    """
    Invariant PAY-AUTH-01 & TIME-01:
    A user whose first cycle succeeded has subscription_success_at set.
    When a subsequent renewal cycle fails (PAYMENT.FAILED),
    it records the failed attempt without destroying history or erasing subscription_success_at.
    """
    provider_sub_id = f"I-FAIL-RENEW-{uuid.uuid4().hex[:8]}"
    first_paid = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="ACTIVE",
        first_payment_at=first_paid,
    )

    failed_event = {
        "id": f"WH-FAILED-RENEW-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T12:00:00Z",
        "event_type": "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
        "resource": {
            "id": f"FAILED-TX-{uuid.uuid4().hex[:8]}",
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "29.00", "currency": "USD"},
        },
    }

    raw_req = make_raw_request(failed_event)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    # Failed payment recorded
    pay_stmt = select(SubscriptionPayment).where(
        SubscriptionPayment.subscription_id == sub.id,
        SubscriptionPayment.status == "FAILED",
    )
    failed_payment = (await async_db_session.execute(pay_stmt)).scalars().first()
    assert failed_payment is not None

    # Invariants preserved
    await async_db_session.refresh(session)
    await async_db_session.refresh(sub)
    assert session.subscription_success_at == first_paid
    assert sub.first_payment_at == first_paid


# ==============================================================================
# 3. Work Item 4: Reconciliation Path for Ambiguous State
# ==============================================================================


@pytest.mark.asyncio
async def test_reconcile_subscription_creates_missing_subscription_linked_to_session(async_db_session: AsyncSession):
    """
    Ambiguous State Reconciliation:
    If a webhook arrives before /confirm created the local subscription,
    reconciliation fetches subscription from PayPal and links to SoulmateSession via custom_id.
    """
    public_id = f"test_custom_{uuid.uuid4().hex[:8]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email="reconcile@example.com",
        email_normalized="reconcile@example.com",
    )
    async_db_session.add(sess)
    await async_db_session.commit()

    ambiguous_sub_id = f"I-AMBIGUOUS-{uuid.uuid4().hex[:8]}"

    # Mock PayPalClient returning the subscription matching custom_id
    mock_client = AsyncMock(spec=PayPalClient)
    mock_client.get_subscription.return_value = {
        "id": ambiguous_sub_id,
        "status": "ACTIVE",
        "plan_id": settings.paypal_soulmate_intro_plan_id or "P-SOULMATE-INTRO",
        "custom_id": public_id,
        "billing_info": {
            "next_billing_time": "2026-10-25T12:00:00Z",
        },
    }

    # Execute reconciliation
    sub = await PayPalWebhookService.reconcile_subscription(
        provider_subscription_id=ambiguous_sub_id,
        db=async_db_session,
        client=mock_client,
    )

    assert sub is not None
    assert sub.provider_subscription_id == ambiguous_sub_id
    assert sub.session_id == sess.id
    assert sub.provider_status == "ACTIVE"
    assert sub.next_billing_at == datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    assert sub.paid_through_at == datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_reconciliation_preserves_local_terminal_cancelled_state(async_db_session: AsyncSession):
    """
    Reconciliation Monotonicity:
    If local subscription is already CANCELLED, reconciliation from PayPal
    must NOT regress status back to ACTIVE if remote has not synced.
    """
    provider_sub_id = f"I-RECON-CANCEL-{uuid.uuid4().hex[:8]}"
    cancelled_time = datetime(2026, 9, 25, 14, 0, 0, tzinfo=timezone.utc)

    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="CANCELLED",
        cancelled_at=cancelled_time,
    )

    # Remote PayPal returns stale ACTIVE status
    mock_client = AsyncMock(spec=PayPalClient)
    mock_client.get_subscription.return_value = {
        "id": provider_sub_id,
        "status": "ACTIVE",
        "billing_info": {},
    }

    reconciled = await PayPalWebhookService.reconcile_subscription(
        provider_subscription_id=provider_sub_id,
        db=async_db_session,
        client=mock_client,
    )

    assert reconciled is not None
    assert reconciled.provider_status == "CANCELLED"


@pytest.mark.asyncio
async def test_failed_webhook_dispatch_retried_on_redelivery(async_db_session: AsyncSession, monkeypatch):
    """
    H-1 Verification (SP-404/406, DEV-SPEC §9.6):
    When business processing fails on first delivery:
    1. Error is captured, transaction is rolled back, exception is raised.
    2. When PayPal retries the same event ID, it must NOT be ignored as a duplicate.
    3. The retry must execute business dispatch, succeed, clear processing_error, and set processed_at.
    4. Subsequent deliveries after success must then be safely deduplicated.
    """
    provider_sub_id = f"I-RETRY-{uuid.uuid4().hex[:8]}"
    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="APPROVAL_PENDING",
    )

    event_id = f"WH-FAIL-THEN-RETRY-{uuid.uuid4().hex[:8]}"
    event_data = {
        "id": event_id,
        "create_time": "2026-09-25T12:00:00Z",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": f"SALE-{uuid.uuid4().hex[:8]}",
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
        },
    }

    original_handler = PayPalWebhookService._handle_payment_sale_completed
    attempt_count = 0

    async def flaky_handler(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise RuntimeError("Simulated transient database error on delivery 1")
        return await original_handler(*args, **kwargs)

    monkeypatch.setattr(PayPalWebhookService, "_handle_payment_sale_completed", flaky_handler)

    # Delivery 1: should raise RuntimeError
    raw_req_1 = make_raw_request(event_data)
    with pytest.raises(RuntimeError, match="Simulated transient database error"):
        await PayPalWebhookService.process_webhook(
            raw_request=raw_req_1,
            db=async_db_session,
            verifier=MockSuccessVerifier(),
        )

    # Assert Delivery 1 recorded error in DB but did NOT activate entitlement
    event_stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event_id)
    recorded_event = (await async_db_session.execute(event_stmt)).scalars().first()
    assert recorded_event is not None
    assert recorded_event.processing_error is not None
    assert "Simulated transient database error" in recorded_event.processing_error
    assert recorded_event.processed_at is None

    await async_db_session.refresh(sub)
    assert sub.first_payment_at is None

    # Delivery 2 (PayPal Retry with same event ID):
    # Must NOT return duplicate! Must retry dispatch and succeed.
    raw_req_2 = make_raw_request(event_data)
    resp_2 = await PayPalWebhookService.process_webhook(
        raw_request=raw_req_2,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )
    assert resp_2.status == "success"
    assert resp_2.duplicate is False

    # Assert Delivery 2 updated recorded event and executed business logic
    await async_db_session.refresh(recorded_event)
    assert recorded_event.processing_error is None
    assert recorded_event.processed_at is not None

    await async_db_session.refresh(sub)
    assert sub.first_payment_at is not None

    # Delivery 3 (Duplicate after success):
    # Now it must be safely deduplicated
    raw_req_3 = make_raw_request(event_data)
    resp_3 = await PayPalWebhookService.process_webhook(
        raw_request=raw_req_3,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )
    assert resp_3.status == "duplicate"
    assert resp_3.duplicate is True


@pytest.mark.asyncio
async def test_payment_failed_increments_count_and_recovery_resets_issue(async_db_session: AsyncSession):
    """
    H-5 Verification (SP-408, DEV-SPEC §9.4, §9.7, §15.8):
    1. BILLING.SUBSCRIPTION.PAYMENT.FAILED increments failed_payments_count and records billing_issue_detected_at.
    2. Subsequent PAYMENT.SALE.COMPLETED resets failed_payments_count = 0 and billing_issue_detected_at = None.
    """
    provider_sub_id = f"I-FAIL-COUNT-{uuid.uuid4().hex[:8]}"
    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="ACTIVE",
    )
    assert sub.failed_payments_count == 0
    assert sub.billing_issue_detected_at is None

    # 1. First failure
    event_1 = {
        "id": f"WH-FAIL-1-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T10:00:00Z",
        "event_type": "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
        "resource": {
            "id": f"FAIL-TX-1-{uuid.uuid4().hex[:8]}",
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "29.00", "currency": "USD"},
        },
    }
    raw_req_1 = make_raw_request(event_1)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req_1,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    await async_db_session.refresh(sub)
    assert sub.failed_payments_count == 1
    assert sub.billing_issue_detected_at is not None

    # 2. Second failure
    event_2 = {
        "id": f"WH-FAIL-2-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T11:00:00Z",
        "event_type": "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
        "resource": {
            "id": f"FAIL-TX-2-{uuid.uuid4().hex[:8]}",
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "29.00", "currency": "USD"},
        },
    }
    raw_req_2 = make_raw_request(event_2)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req_2,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    await async_db_session.refresh(sub)
    assert sub.failed_payments_count == 2

    # 3. Successful recovery payment
    event_success = {
        "id": f"WH-RECOVER-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T12:00:00Z",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": f"SALE-RECOVER-{uuid.uuid4().hex[:8]}",
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "29.00", "currency": "USD"},
            "state": "completed",
        },
    }
    raw_req_success = make_raw_request(event_success)
    await PayPalWebhookService.process_webhook(
        raw_request=raw_req_success,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )

    await async_db_session.refresh(sub)
    assert sub.failed_payments_count == 0
    assert sub.billing_issue_detected_at is None


@pytest.mark.asyncio
async def test_billing_subscription_updated_synchronizes_state_and_resets_failures(async_db_session: AsyncSession):
    """
    H-5 Verification:
    BILLING.SUBSCRIPTION.UPDATED synchronizes remote status, next_billing_time,
    and if ACTIVE, resets failed_payments_count to 0.
    """
    provider_sub_id = f"I-UPDATE-EVT-{uuid.uuid4().hex[:8]}"
    session, sub = await create_test_session_and_sub(
        db=async_db_session,
        provider_sub_id=provider_sub_id,
        status="SUSPENDED",
    )
    sub.failed_payments_count = 3
    sub.billing_issue_detected_at = datetime(2026, 9, 25, 9, 0, 0, tzinfo=timezone.utc)
    await async_db_session.commit()

    update_event = {
        "id": f"WH-UPDATE-{uuid.uuid4().hex[:8]}",
        "create_time": "2026-09-25T13:00:00Z",
        "event_type": "BILLING.SUBSCRIPTION.UPDATED",
        "resource": {
            "id": provider_sub_id,
            "status": "ACTIVE",
            "billing_info": {
                "next_billing_time": "2026-10-25T13:00:00Z",
            },
        },
    }
    raw_req = make_raw_request(update_event)
    resp = await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db_session,
        verifier=MockSuccessVerifier(),
    )
    assert resp.status == "received"

    await async_db_session.refresh(sub)
    assert sub.provider_status == "ACTIVE"
    assert sub.suspended_at is None
    assert sub.failed_payments_count == 0
    assert sub.billing_issue_detected_at is None
    assert sub.next_billing_at == datetime(2026, 10, 25, 13, 0, 0, tzinfo=timezone.utc)

