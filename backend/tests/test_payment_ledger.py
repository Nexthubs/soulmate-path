"""
Unit and Integration Tests for Payment Ledger (SP-407, DEV-SPEC §9.4–9.7, §14, Decisions: PAY-AUTH-01).

Acceptance Criteria:
1. Each completed provider payment has durable provider payment ID, amount, currency, paid time, subscription link, cycle context when available.
2. Duplicate provider payment ID cannot create multiple rows.
3. Support lookup for customer support/reconciliation.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.billing import Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.ledger_models import (
    LedgerSearchQuery,
    PaymentRecordCreate,
)
from app.soulmate.security import generate_session_token
from app.soulmate.services.ledger_service import PaymentLedgerService


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


async def create_test_session_and_sub(
    db: AsyncSession,
    provider_sub_id: str,
    status: str = "ACTIVE",
    email: Optional[str] = None,
) -> tuple[SoulmateSession, Subscription]:
    """Helper to create an authenticated session and linked subscription."""
    public_id = f"test_sess_{uuid.uuid4().hex[:10]}"
    user_email = email or f"buyer_{uuid.uuid4().hex[:8]}@example.com"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="paid",
        current_step="result",
        email=user_email,
        email_normalized=user_email.lower(),
        subscription_success_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
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
        first_payment_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sess, sub


# ==============================================================================
# 1. Acceptance Criteria 1: Durable Payment Fields & Cycle Context
# ==============================================================================


@pytest.mark.asyncio
async def test_record_completed_payment_persists_all_durable_fields(async_db: AsyncSession):
    """Verify each completed provider payment has durable provider payment ID, amount, currency, paid time, subscription link, cycle context."""
    sub_id = f"I-LEDGER-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    sale_id = f"SALE-{uuid.uuid4().hex[:10]}"
    event_id = f"WH-EVT-{uuid.uuid4().hex[:8]}"
    paid_at = datetime(2026, 9, 25, 12, 30, 0, tzinfo=timezone.utc)
    raw_payload = {"id": sale_id, "amount": {"total": "19.00", "currency": "USD"}, "status": "COMPLETED"}

    payment, created = await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            provider_event_id=event_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=paid_at,
            raw_json=raw_payload,
        ),
    )
    await async_db.commit()

    assert created is True
    assert payment.id is not None
    assert payment.subscription_id == sub.id
    assert payment.provider_payment_id == sale_id
    assert payment.provider_event_id == event_id
    assert payment.amount == Decimal("19.00")
    assert payment.currency == "USD"
    assert payment.status == "COMPLETED"
    assert payment.paid_at == paid_at
    assert payment.cycle_no == 1  # First payment auto-derived as cycle 1
    assert payment.raw_json == raw_payload


@pytest.mark.asyncio
async def test_subsequent_cycle_payments_derive_monotonic_cycle_numbers(async_db: AsyncSession):
    """Verify recurring payments for the same subscription derive cycle_no = 2, 3... monotonically."""
    sub_id = f"I-CYCLES-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    # Cycle 1: Intro month
    sale_1 = f"SALE-1-{uuid.uuid4().hex[:8]}"
    p1, _ = await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_1,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
        ),
    )
    await async_db.commit()
    assert p1.cycle_no == 1

    # Cycle 2: Regular monthly renewal
    sale_2 = f"SALE-2-{uuid.uuid4().hex[:8]}"
    p2, _ = await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_2,
            amount=Decimal("29.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
        ),
    )
    await async_db.commit()
    assert p2.cycle_no == 2

    # Cycle 3: Second renewal
    sale_3 = f"SALE-3-{uuid.uuid4().hex[:8]}"
    p3, _ = await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_3,
            amount=Decimal("29.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc),
        ),
    )
    await async_db.commit()
    assert p3.cycle_no == 3


# ==============================================================================
# 2. Acceptance Criteria 2: Duplicate Provider Payment ID Idempotency
# ==============================================================================


@pytest.mark.asyncio
async def test_duplicate_provider_payment_id_cannot_create_multiple_rows(async_db: AsyncSession):
    """Verify duplicate provider payment ID returns existing record without inserting duplicate rows."""
    sub_id = f"I-DUP-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    sale_id = f"SALE-DUP-{uuid.uuid4().hex[:8]}"

    # Call 1: initial insert
    p1, created1 = await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await async_db.commit()
    assert created1 is True

    # Call 2: duplicate call with exact same provider_payment_id
    p2, created2 = await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await async_db.commit()
    assert created2 is False
    assert p1.id == p2.id

    # Call 3: duplicate call across 5 repeats
    for _ in range(5):
        dup, c = await PaymentLedgerService.record_payment(
            db=async_db,
            create_data=PaymentRecordCreate(
                subscription_id=sub.id,
                provider_payment_id=sale_id,
                amount=Decimal("19.00"),
                currency="USD",
                status="COMPLETED",
            ),
        )
        assert c is False
        assert dup.id == p1.id

    # Verify database table has strictly 1 record
    count = await async_db.scalar(
        select(func.count(SubscriptionPayment.id)).where(SubscriptionPayment.subscription_id == sub.id)
    )
    assert count == 1


# ==============================================================================
# 3. Acceptance Criteria 3: Support Lookup & Reconciliation
# ==============================================================================


@pytest.mark.asyncio
async def test_lookup_payment_by_provider_payment_id_hydrates_context(async_db: AsyncSession):
    """Verify lookup by provider payment ID returns complete context (subscription, session, email)."""
    sub_id = f"I-LOOKUP-{uuid.uuid4().hex[:8]}"
    buyer_email = f"customer_{uuid.uuid4().hex[:6]}@example.com"
    sess, sub = await create_test_session_and_sub(async_db, sub_id, email=buyer_email)

    sale_id = f"SALE-LOOKUP-{uuid.uuid4().hex[:8]}"
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime(2026, 9, 25, 13, 0, 0, tzinfo=timezone.utc),
        ),
    )
    await async_db.commit()

    record = await PaymentLedgerService.get_payment_by_provider_payment_id(async_db, sale_id)
    assert record is not None
    assert record.provider_payment_id == sale_id
    assert record.subscription_id == sub.id
    assert record.provider_subscription_id == sub_id
    assert record.session_public_id == sess.public_id
    assert record.customer_email == buyer_email.lower()


@pytest.mark.asyncio
async def test_lookup_payments_by_email(async_db: AsyncSession):
    """Verify customer support can query all payment transactions for a given email address."""
    sub_id = f"I-EMAIL-{uuid.uuid4().hex[:8]}"
    target_email = f"support_target_{uuid.uuid4().hex[:6]}@example.com"
    sess, sub = await create_test_session_and_sub(async_db, sub_id, email=target_email)

    sale_1 = f"SALE-EM-1-{uuid.uuid4().hex[:8]}"
    sale_2 = f"SALE-EM-2-{uuid.uuid4().hex[:8]}"

    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_1,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_2,
            amount=Decimal("29.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await async_db.commit()

    # Query with uppercase/whitespace to test normalization
    records = await PaymentLedgerService.get_payments_by_email(async_db, f"  {target_email.upper()}  ")
    assert len(records) == 2
    payment_ids = {r.provider_payment_id for r in records}
    assert sale_1 in payment_ids
    assert sale_2 in payment_ids


@pytest.mark.asyncio
async def test_record_refund_and_summary_aggregation(async_db: AsyncSession):
    """Verify refund transitions status and subscription ledger summary computes accurate aggregates."""
    sub_id = f"I-REFUND-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    sale_id = f"SALE-REF-{uuid.uuid4().hex[:8]}"
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
        ),
    )
    await async_db.commit()

    refund_time = datetime(2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc)
    refunded_payment = await PaymentLedgerService.record_refund(
        db=async_db,
        provider_payment_id=sale_id,
        refunded_at=refund_time,
        status="REFUNDED",
        raw_json={"refund_id": "REF-999"},
    )
    await async_db.commit()

    assert refunded_payment is not None
    assert refunded_payment.status == "REFUNDED"
    assert refunded_payment.refunded_at == refund_time

    summary = await PaymentLedgerService.get_subscription_ledger_summary(async_db, sub.id)
    assert summary is not None
    assert summary.total_payments_count == 1
    assert summary.completed_payments_count == 0
    assert summary.refunded_payments_count == 1
    assert summary.latest_status == "REFUNDED"


@pytest.mark.asyncio
async def test_search_payments_with_filters_and_pagination(async_db: AsyncSession):
    """Verify search_payments supports multi-field filtering and pagination."""
    sub_id = f"I-SEARCH-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    # Insert 3 payments with distinct statuses
    sale_completed = f"SALE-C-{uuid.uuid4().hex[:8]}"
    sale_failed = f"SALE-F-{uuid.uuid4().hex[:8]}"

    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_completed,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_failed,
            amount=Decimal("29.00"),
            currency="USD",
            status="FAILED",
        ),
    )
    await async_db.commit()

    # Search for COMPLETED only on this subscription
    res_completed = await PaymentLedgerService.search_payments(
        db=async_db,
        query=LedgerSearchQuery(
            subscription_id=sub.id,
            status="COMPLETED",
            limit=10,
            offset=0,
        ),
    )
    assert res_completed.total == 1
    assert len(res_completed.items) == 1
    assert res_completed.items[0].provider_payment_id == sale_completed

    # Search for FAILED only
    res_failed = await PaymentLedgerService.search_payments(
        db=async_db,
        query=LedgerSearchQuery(
            subscription_id=sub.id,
            status="FAILED",
            limit=10,
            offset=0,
        ),
    )
    assert res_failed.total == 1
    assert res_failed.items[0].provider_payment_id == sale_failed


# ==============================================================================
# 4. HTTP API Endpoints: Support & User Session History
# ==============================================================================


@pytest.mark.asyncio
async def test_api_support_lookup_by_provider_payment_id(async_db: AsyncSession):
    """Test GET /api/soulmate/ledger/payments/{provider_payment_id}."""
    sub_id = f"I-APIPAY-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    sale_id = f"SALE-API-{uuid.uuid4().hex[:8]}"
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
        ),
    )
    await async_db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Success lookup
        resp = await client.get(f"/api/soulmate/ledger/payments/{sale_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_payment_id"] == sale_id
        assert data["amount"] == "19.00"
        assert data["currency"] == "USD"
        assert data["status"] == "COMPLETED"
        assert data["provider_subscription_id"] == sub_id
        assert data["session_public_id"] == sess.public_id

        # 404 for unknown payment ID
        resp_404 = await client.get("/api/soulmate/ledger/payments/NON-EXISTENT-SALE-999")
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_api_support_ledger_search_endpoint(async_db: AsyncSession):
    """Test GET /api/soulmate/ledger/search."""
    sub_id = f"I-APISEARCH-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    sale_id = f"SALE-SEARCH-{uuid.uuid4().hex[:8]}"
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await async_db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/soulmate/ledger/search?provider_subscription_id={sub_id}&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        items = data["items"]
        assert any(item["provider_payment_id"] == sale_id for item in items)


@pytest.mark.asyncio
async def test_api_session_payments_endpoint_idor_protected(async_db: AsyncSession):
    """Test GET /api/soulmate/subscription/payments is protected against IDOR."""
    sub_id = f"I-USERSESS-{uuid.uuid4().hex[:8]}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id)

    sale_id = f"SALE-SESS-{uuid.uuid4().hex[:8]}"
    await PaymentLedgerService.record_payment(
        db=async_db,
        create_data=PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id=sale_id,
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
        ),
    )
    await async_db.commit()

    token = generate_session_token(sess.public_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"soulmate_sid": token}) as client:
        # 1. Authenticated session fetches its own payments
        resp = await client.get(f"/api/soulmate/subscription/payments?session_id={sess.public_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["provider_payment_id"] == sale_id

        # 2. Cross-session IDOR attempt: token for sess, but requesting other session
        other_sess_id = f"other_sess_{uuid.uuid4().hex[:8]}"
        resp_idor = await client.get(f"/api/soulmate/subscription/payments?session_id={other_sess_id}")
        assert resp_idor.status_code == 403
