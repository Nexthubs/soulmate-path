"""
Unit and Integration Tests for Subscription Reconciliation and State Mapping (SP-408, DEV-SPEC §9.4–9.8, §10, Decisions: PAY-AUTH-01).

Acceptance Criteria:
1. First successful payment sets authoritative first_payment_completed_at exactly once.
2. Next billing/status can be reconciled from provider when needed.
3. Failure/suspension/cancel/expire states map predictably.
4. Already-owned generated artifacts are not deleted on cancellation.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.subscription_service import SubscriptionService


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


class MockPayPalClient(PayPalClient):
    """Mock PayPalClient that returns configurable subscription payloads without live network calls."""

    def __init__(
        self,
        subscription_responses: Optional[Dict[str, Any]] = None,
        transactions_responses: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(client_id="mock_id", client_secret="mock_secret")
        self.subscription_responses = subscription_responses or {}
        self.transactions_responses = transactions_responses or {}

    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        return self.subscription_responses.get(subscription_id)

    async def list_subscription_transactions(
        self,
        subscription_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        if subscription_id in self.transactions_responses:
            return self.transactions_responses[subscription_id]
        sub = self.subscription_responses.get(subscription_id)
        if sub:
            last_p = sub.get("billing_info", {}).get("last_payment")
            if last_p and (last_p.get("id") or last_p.get("time")):
                tx_id = last_p.get("id") or f"TX-DEFAULT-{subscription_id}"
                return [
                    {
                        "id": tx_id,
                        "status": "COMPLETED",
                        "amount_with_breakdown": {
                            "gross_amount": last_p.get("amount", {"currency_code": "USD", "value": "19.00"})
                        },
                        "time": last_p.get("time"),
                    }
                ]
        return []


async def create_test_session_and_sub(
    db: AsyncSession,
    provider_sub_id: str,
    status: str = "APPROVAL_PENDING",
    first_payment_at: Optional[datetime] = None,
    cancelled_at: Optional[datetime] = None,
    suspended_at: Optional[datetime] = None,
    paid_through_at: Optional[datetime] = None,
    email: Optional[str] = None,
) -> tuple[SoulmateSession, Subscription]:
    """Helper to seed session and linked subscription."""
    public_id = f"test_sess_{uuid.uuid4().hex[:10]}"
    user_email = email or f"buyer_{uuid.uuid4().hex[:8]}@example.com"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="paid" if first_payment_at else "email_captured",
        current_step="result" if first_payment_at else "subscribe",
        email=user_email,
        email_normalized=user_email.lower(),
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
        paid_through_at=paid_through_at,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sess, sub


# ==============================================================================
# 1. Acceptance Criteria 1: First payment sets authoritative first_payment_at once
# ==============================================================================


@pytest.mark.asyncio
async def test_reconciliation_sets_authoritative_first_payment_at_and_activates_entitlement(async_db: AsyncSession):
    """
    Verify: When PayPal confirms initial payment via billing_info.last_payment:
    1. sub.first_payment_at is set to the authoritative payment time.
    2. session.subscription_success_at is set.
    3. session status -> 'paid', current_step -> 'result'.
    4. Artifacts are initialized with unlock_at (+12h and +24h).
    5. Payment is recorded in subscription_payments ledger.
    """
    sub_id = f"I-RECON-{uuid.uuid4().hex[:8].upper()}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id, status="APPROVED")
    assert sub.first_payment_at is None
    assert sess.subscription_success_at is None

    pay_time_str = "2026-09-25T14:30:00Z"
    pay_time_dt = datetime(2026, 9, 25, 14, 30, 0, tzinfo=timezone.utc)
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-INTRO",
        "billing_info": {
            "last_payment": {
                "amount": {"currency_code": "USD", "value": "19.00"},
                "time": pay_time_str,
            },
            "next_billing_time": "2026-10-25T14:30:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    # 1. Verify subscription state
    assert reconciled is not None
    assert reconciled.first_payment_at == pay_time_dt
    assert reconciled.provider_status == "ACTIVE"
    assert reconciled.next_billing_at == datetime(2026, 10, 25, 14, 30, 0, tzinfo=timezone.utc)

    # 2. Verify session entitlement
    await async_db.refresh(sess)
    assert sess.subscription_success_at == pay_time_dt
    assert sess.status == "paid"
    assert sess.current_step == "result"

    # 3. Verify artifacts initialized
    art_stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == sess.id)
    artifacts = (await async_db.execute(art_stmt)).scalars().all()
    assert len(artifacts) == 2
    types = {a.artifact_type for a in artifacts}
    assert types == {"SKETCH", "REPORT"}

    sketch_art = next(a for a in artifacts if a.artifact_type == "SKETCH")
    report_art = next(a for a in artifacts if a.artifact_type == "REPORT")
    assert sketch_art.unlock_at == pay_time_dt + timedelta(hours=12)
    assert report_art.unlock_at == pay_time_dt + timedelta(hours=24)

    # 4. Verify payment ledger recorded
    pay_stmt = select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id)
    payments = (await async_db.execute(pay_stmt)).scalars().all()
    assert len(payments) == 1
    assert payments[0].amount == Decimal("19.00")
    assert payments[0].status == "COMPLETED"


@pytest.mark.asyncio
async def test_subsequent_reconciliation_preserves_first_payment_at_immutable(async_db: AsyncSession):
    """Verify: Repeated reconciliations with different or later payment times NEVER mutate first_payment_at."""
    sub_id = f"I-IMMUTABLE-{uuid.uuid4().hex[:8].upper()}"
    original_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    sess, sub = await create_test_session_and_sub(
        async_db,
        sub_id,
        status="ACTIVE",
        first_payment_at=original_time,
    )

    # Mock PayPal returning later renewal payment
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-INTRO",
        "billing_info": {
            "last_payment": {
                "amount": {"currency_code": "USD", "value": "29.00"},
                "time": "2026-10-25T12:00:00Z",  # Renewal time
            },
            "next_billing_time": "2026-11-25T12:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    # first_payment_at MUST remain the original initial timestamp
    assert reconciled.first_payment_at == original_time
    await async_db.refresh(sess)
    assert sess.subscription_success_at == original_time


# ==============================================================================
# 2. Acceptance Criteria 2: Next billing / status can be reconciled from provider
# ==============================================================================


@pytest.mark.asyncio
async def test_reconcile_next_billing_and_paid_through_dates(async_db: AsyncSession):
    """Verify reconciliation updates next_billing_at and paid_through_at."""
    sub_id = f"I-BILLING-{uuid.uuid4().hex[:8].upper()}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id, status="ACTIVE", first_payment_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc))

    next_billing_str = "2026-10-25T12:00:00Z"
    next_billing_dt = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "billing_info": {
            "next_billing_time": next_billing_str,
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    assert reconciled.next_billing_at == next_billing_dt
    assert reconciled.paid_through_at == next_billing_dt


# ==============================================================================
# 3. Acceptance Criteria 3: Predictable State Mapping & Terminal Monotonicity
# ==============================================================================


@pytest.mark.asyncio
async def test_predictable_state_mapping_for_all_provider_statuses(async_db: AsyncSession):
    """Verify provider states map predictably to application status."""
    # 1. APPROVAL_PENDING / APPROVED without payment -> PROCESSING (is_paid=False)
    sub1_id = f"I-PEND-{uuid.uuid4().hex[:8].upper()}"
    sess1, sub1 = await create_test_session_and_sub(async_db, sub1_id, status="APPROVAL_PENDING", first_payment_at=None)
    st1 = await SubscriptionService.get_subscription_status(async_db, sess1)
    assert st1.status == "PROCESSING"
    assert st1.is_paid is False

    # 2. ACTIVE with payment -> ACTIVE (is_paid=True)
    sub2_id = f"I-ACT-{uuid.uuid4().hex[:8].upper()}"
    sess2, sub2 = await create_test_session_and_sub(async_db, sub2_id, status="ACTIVE", first_payment_at=datetime.now(timezone.utc))
    st2 = await SubscriptionService.get_subscription_status(async_db, sess2)
    assert st2.status == "ACTIVE"
    assert st2.is_paid is True

    # 3. SUSPENDED with prior payment -> SUSPENDED (is_paid=True)
    sub3_id = f"I-SUSP-{uuid.uuid4().hex[:8].upper()}"
    sess3, sub3 = await create_test_session_and_sub(async_db, sub3_id, status="SUSPENDED", first_payment_at=datetime.now(timezone.utc), suspended_at=datetime.now(timezone.utc))
    st3 = await SubscriptionService.get_subscription_status(async_db, sess3)
    assert st3.status == "SUSPENDED"
    assert st3.is_paid is True

    # 4. CANCELLED with prior payment -> CANCELLED (is_paid=True)
    sub4_id = f"I-CANC-{uuid.uuid4().hex[:8].upper()}"
    sess4, sub4 = await create_test_session_and_sub(async_db, sub4_id, status="CANCELLED", first_payment_at=datetime.now(timezone.utc), cancelled_at=datetime.now(timezone.utc))
    st4 = await SubscriptionService.get_subscription_status(async_db, sess4)
    assert st4.status == "CANCELLED"
    assert st4.is_paid is True

    # 5. EXPIRED with prior payment -> EXPIRED (is_paid=True)
    sub5_id = f"I-EXP-{uuid.uuid4().hex[:8].upper()}"
    sess5, sub5 = await create_test_session_and_sub(async_db, sub5_id, status="EXPIRED", first_payment_at=datetime.now(timezone.utc))
    st5 = await SubscriptionService.get_subscription_status(async_db, sess5)
    assert st5.status == "EXPIRED"
    assert st5.is_paid is True


@pytest.mark.asyncio
async def test_reconciliation_preserves_terminal_cancelled_and_expired_states(async_db: AsyncSession):
    """Verify reconciliation will never regress local CANCELLED or EXPIRED status even if PayPal returns ACTIVE."""
    sub_id = f"I-TERMINAL-{uuid.uuid4().hex[:8].upper()}"
    cancel_time = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)
    sess, sub = await create_test_session_and_sub(
        async_db,
        sub_id,
        status="CANCELLED",
        first_payment_at=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
        cancelled_at=cancel_time,
    )

    # PayPal API mistakenly reports ACTIVE
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    assert reconciled.provider_status == "CANCELLED"
    assert reconciled.cancelled_at == cancel_time


# ==============================================================================
# 4. Acceptance Criteria 4: Already-owned artifacts are not deleted on cancellation
# ==============================================================================


@pytest.mark.asyncio
async def test_cancellation_reconciliation_never_deletes_already_owned_artifacts(async_db: AsyncSession):
    """
    Verify: When a subscription transitions to CANCELLED via reconciliation,
    all generated/unlocked artifacts remain completely preserved in the database.
    """
    sub_id = f"I-PRESERVE-{uuid.uuid4().hex[:8].upper()}"
    paid_time = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)
    sess, sub = await create_test_session_and_sub(
        async_db,
        sub_id,
        status="ACTIVE",
        first_payment_at=paid_time,
    )

    # Seed an already-owned completed sketch artifact
    sketch = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=sess.email_normalized,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=paid_time + timedelta(hours=12),
        generation_status="COMPLETED",
        storage_key="s3://soulmate/sketches/user_completed.png",
        content_json={"traits": ["creative", "empathic"]},
    )
    # Seed a report artifact
    report = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=sess.email_normalized,
        artifact_type="REPORT",
        artifact_version="v1",
        unlock_at=paid_time + timedelta(hours=24),
        generation_status="PROCESSING",
    )
    async_db.add_all([sketch, report])
    await async_db.commit()

    sketch_id = sketch.id
    report_id = report.id

    # Now reconcile with PayPal reporting CANCELLED
    cancel_str = "2026-09-25T16:00:00Z"
    mock_payload = {
        "id": sub_id,
        "status": "CANCELLED",
        "status_update_time": cancel_str,
        "billing_info": {
            "next_billing_time": "2026-10-25T10:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    assert reconciled.provider_status == "CANCELLED"
    assert reconciled.cancelled_at == datetime(2026, 9, 25, 16, 0, 0, tzinfo=timezone.utc)
    assert reconciled.paid_through_at == datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

    # CRITICAL: Verify artifacts are NOT deleted and remain 100% intact
    art_stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == sess.id)
    artifacts = (await async_db.execute(art_stmt)).scalars().all()
    assert len(artifacts) == 2

    persisted_sketch = next(a for a in artifacts if a.id == sketch_id)
    assert persisted_sketch.generation_status == "COMPLETED"
    assert persisted_sketch.storage_key == "s3://soulmate/sketches/user_completed.png"
    assert persisted_sketch.content_json == {"traits": ["creative", "empathic"]}

    persisted_report = next(a for a in artifacts if a.id == report_id)
    assert persisted_report.generation_status == "PROCESSING"


# ==============================================================================
# 5. HTTP Endpoints: Reconcile Action & Status Polling with Reconcile
# ==============================================================================


@pytest.mark.asyncio
async def test_api_reconcile_endpoint(async_db: AsyncSession, monkeypatch):
    """Test POST /api/soulmate/subscription/reconcile."""
    sub_id = f"I-APIRECON-{uuid.uuid4().hex[:8].upper()}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id, status="APPROVED")

    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-INTRO",
        "billing_info": {
            "last_payment": {
                "amount": {"currency_code": "USD", "value": "19.00"},
                "time": "2026-09-25T15:00:00Z",
            },
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }

    async def mock_get_sub(self, s_id: str):
        if s_id == sub_id:
            return mock_payload
        return None

    monkeypatch.setattr(PayPalClient, "get_subscription", mock_get_sub)

    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"soulmate_sid": token}) as client:
        resp = await client.post(f"/api/soulmate/subscription/reconcile?session_id={sess.public_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACTIVE"
        assert data["is_paid"] is True
        assert data["subscription_id"] == sub_id
        assert data["first_payment_at"] is not None


@pytest.mark.asyncio
async def test_api_status_polling_with_reconcile_query(async_db: AsyncSession, monkeypatch):
    """Test GET /api/soulmate/subscription/status?reconcile=true."""
    sub_id = f"I-APIPOLL-{uuid.uuid4().hex[:8].upper()}"
    sess, sub = await create_test_session_and_sub(async_db, sub_id, status="APPROVED")

    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-INTRO",
        "billing_info": {
            "last_payment": {
                "amount": {"currency_code": "USD", "value": "19.00"},
                "time": "2026-09-25T15:00:00Z",
            },
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }

    async def mock_get_sub(self, s_id: str):
        if s_id == sub_id:
            return mock_payload
        return None

    monkeypatch.setattr(PayPalClient, "get_subscription", mock_get_sub)

    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"soulmate_sid": token}) as client:
        resp = await client.get(f"/api/soulmate/subscription/status?session_id={sess.public_id}&reconcile=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACTIVE"
        assert data["is_paid"] is True


# ==============================================================================
# 6. Unknown Subscription Reconciliation Security & Ambiguity Protection (C-2, DEV-SPEC §8.3)
# ==============================================================================


@pytest.mark.asyncio
async def test_reconciliation_rejects_unknown_subscription_with_unconfigured_or_invalid_plan(
    async_db: AsyncSession, monkeypatch
):
    """
    C-2 Verification:
    Reconciliation of an unknown subscription must validate plan_id against allowed Soulmate plans.
    Foreign plans or unknown plans must return None and refuse to persist.
    """
    plan_id = "P-SOULMATE-INTRO-VALID"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-INVALID-PLAN-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-ROGUE-FOREIGN-PRODUCT",
        "custom_id": f"test_sess_{uuid.uuid4().hex[:8]}",
        "billing_info": {
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    assert reconciled is None

    # Verify no subscription created in DB
    stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id)
    persisted = (await async_db.execute(stmt)).scalars().first()
    assert persisted is None


@pytest.mark.asyncio
async def test_reconciliation_prioritizes_custom_id_over_subscriber_email(
    async_db: AsyncSession, monkeypatch
):
    """
    C-2 Verification:
    custom_id takes strict precedence over subscriber email when binding unknown subscriptions.
    """
    plan_id = "P-SOULMATE-INTRO-VALID"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    payer_email = f"paypal_payer_{uuid.uuid4().hex[:8]}@example.com"
    sess_a_email = f"sess_a_{uuid.uuid4().hex[:8]}@example.com"

    # Session A: target of custom_id
    sess_a_id = f"test_sess_a_{uuid.uuid4().hex[:8]}"
    sess_a = SoulmateSession(
        public_id=sess_a_id,
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=sess_a_email,
        email_normalized=sess_a_email,
    )
    # Session B: matches subscriber email
    sess_b_id = f"test_sess_b_{uuid.uuid4().hex[:8]}"
    sess_b = SoulmateSession(
        public_id=sess_b_id,
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=payer_email,
        email_normalized=payer_email,
    )
    async_db.add_all([sess_a, sess_b])
    await async_db.commit()

    sub_id = f"I-CUSTOM-PRIORITY-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": plan_id,
        "custom_id": sess_a.public_id,
        "subscriber": {"email_address": payer_email},
        "billing_info": {
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    assert reconciled is not None
    assert reconciled.session_id == sess_a.id
    assert reconciled.session_id != sess_b.id


@pytest.mark.asyncio
async def test_reconciliation_fallback_to_subscriber_email_when_custom_id_missing(
    async_db: AsyncSession, monkeypatch
):
    """
    C-2 Verification:
    When custom_id is missing, fallback binds to single session matching subscriber email.
    """
    plan_id = "P-SOULMATE-INTRO-VALID"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    single_email = f"buyer_single_{uuid.uuid4().hex[:8]}@example.com"
    sess = SoulmateSession(
        public_id=f"test_sess_single_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=single_email,
        email_normalized=single_email,
    )
    async_db.add(sess)
    await async_db.commit()

    sub_id = f"I-EMAIL-FALLBACK-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": plan_id,
        # No custom_id
        "subscriber": {"email_address": single_email},
        "billing_info": {
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    assert reconciled is not None
    assert reconciled.session_id == sess.id


@pytest.mark.asyncio
async def test_reconciliation_rejects_ambiguous_multiple_unpaid_sessions_for_same_email(
    async_db: AsyncSession, monkeypatch
):
    """
    C-2 Verification:
    When multiple unpaid sessions share the same email, refusing to bind prevents cross-session confusion.
    """
    plan_id = "P-SOULMATE-INTRO-VALID"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    ambiguous_email = f"ambiguous_{uuid.uuid4().hex[:8]}@example.com"
    sess1 = SoulmateSession(
        public_id=f"test_sess_ambig1_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=ambiguous_email,
        email_normalized=ambiguous_email,
    )
    sess2 = SoulmateSession(
        public_id=f"test_sess_ambig2_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=ambiguous_email,
        email_normalized=ambiguous_email,
    )
    async_db.add_all([sess1, sess2])
    await async_db.commit()

    sub_id = f"I-AMBIGUOUS-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": plan_id,
        # No custom_id
        "subscriber": {"email_address": ambiguous_email},
        "billing_info": {
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    # Refuses ambiguous auto-binding
    assert reconciled is None

    stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id)
    persisted = (await async_db.execute(stmt)).scalars().first()
    assert persisted is None


@pytest.mark.asyncio
async def test_reconciliation_binds_to_unique_unpaid_session_when_prior_session_already_paid(
    async_db: AsyncSession, monkeypatch
):
    """
    C-2 Verification:
    When a user has a previously paid session and a newer unpaid session,
    the fallback binds to the unique active unpaid session.
    """
    plan_id = "P-SOULMATE-INTRO-VALID"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    email = f"returning_{uuid.uuid4().hex[:8]}@example.com"
    # Session 1: previously completed/paid
    sess_paid = SoulmateSession(
        public_id=f"test_sess_paid_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status="paid",
        current_step="result",
        email=email,
        email_normalized=email,
        subscription_success_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    # Session 2: active unpaid attempt
    sess_unpaid = SoulmateSession(
        public_id=f"test_sess_unpaid_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=email,
        email_normalized=email,
        subscription_success_at=None,
    )
    async_db.add_all([sess_paid, sess_unpaid])
    await async_db.commit()

    sub_id = f"I-RETURNING-UNPAID-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": plan_id,
        # No custom_id
        "subscriber": {"email_address": email},
        "billing_info": {
            "next_billing_time": "2026-10-25T15:00:00Z",
        },
    }
    client = MockPayPalClient({sub_id: mock_payload})

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    assert reconciled is not None
    assert reconciled.session_id == sess_unpaid.id


@pytest.mark.asyncio
async def test_reconciliation_backfills_missed_renewal_payments_when_first_payment_already_set(async_db: AsyncSession):
    """
    H-2 Verification (SP-407/408, DEV-SPEC §9.4–9.7):
    When a subscription already has first_payment_at set (initial payment was processed),
    and a renewal payment webhook was lost, calling reconcile_subscription queries PayPal
    transactions and idempotently backfills the missing renewal payment into subscription_payments ledger.
    """
    sub_id = f"I-RENEWAL-{uuid.uuid4().hex[:8].upper()}"
    first_pay_time = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
    sess, sub = await create_test_session_and_sub(
        async_db,
        sub_id,
        status="ACTIVE",
        first_payment_at=first_pay_time,
    )

    # Initial payment ledger entry already exists
    initial_payment = SubscriptionPayment(
        subscription_id=sub.id,
        provider_payment_id=f"TX-INITIAL-{sub_id}",
        cycle_no=1,
        amount=Decimal("19.00"),
        currency="USD",
        status="COMPLETED",
        paid_at=first_pay_time,
    )
    async_db.add(initial_payment)
    await async_db.commit()

    # Renewal transaction occurs in PayPal (cycle 2)
    renewal_tx_id = f"TX-RENEWAL-{uuid.uuid4().hex[:8].upper()}"
    renewal_time_str = "2026-09-25T12:00:00Z"
    renewal_time_dt = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    mock_sub_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-STANDARD",
        "billing_info": {
            "last_payment": {
                "amount": {"currency_code": "USD", "value": "29.00"},
                "time": renewal_time_str,
            },
            "next_billing_time": "2026-10-25T12:00:00Z",
        },
    }
    mock_txs = [
        {
            "id": f"TX-INITIAL-{sub_id}",
            "status": "COMPLETED",
            "amount_with_breakdown": {
                "gross_amount": {"currency_code": "USD", "value": "19.00"}
            },
            "time": "2026-08-25T12:00:00Z",
        },
        {
            "id": renewal_tx_id,
            "status": "COMPLETED",
            "amount_with_breakdown": {
                "gross_amount": {"currency_code": "USD", "value": "29.00"}
            },
            "time": renewal_time_str,
        },
    ]

    client = MockPayPalClient(
        subscription_responses={sub_id: mock_sub_payload},
        transactions_responses={sub_id: mock_txs},
    )

    # Execute reconciliation
    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    assert reconciled is not None
    # first_payment_at remains unchanged (immutable)
    assert reconciled.first_payment_at == first_pay_time

    # Ledger now has BOTH payments (initial + renewal)
    pay_stmt = select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id).order_by(SubscriptionPayment.created_at)
    payments = (await async_db.execute(pay_stmt)).scalars().all()
    assert len(payments) == 2
    assert payments[0].provider_payment_id == f"TX-INITIAL-{sub_id}"
    assert payments[1].provider_payment_id == renewal_tx_id
    assert payments[1].amount == Decimal("29.00")
    assert payments[1].cycle_no == 2
    assert payments[1].status == "COMPLETED"
    assert payments[1].paid_at == renewal_time_dt


@pytest.mark.asyncio
async def test_reconciliation_skips_ledger_write_without_fictitious_id_when_no_transaction_id(async_db: AsyncSession):
    """
    H-2 Verification:
    When PayPal reports last_payment without a transaction ID and no transactions are returned,
    reconciliation NEVER creates a fictitious ID (like PAYPAL-LASTPAY-...). It safely logs a warning and skips ledger write.
    """
    sub_id = f"I-NO-TX-ID-{uuid.uuid4().hex[:8].upper()}"
    sess, sub = await create_test_session_and_sub(
        async_db,
        sub_id,
        status="ACTIVE",
    )

    # Payload with last_payment having NO id
    mock_sub_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-INTRO",
        "billing_info": {
            "last_payment": {
                "amount": {"currency_code": "USD", "value": "19.00"},
                "time": "2026-09-25T12:00:00Z",
                # Note: No 'id' field!
            },
            "next_billing_time": "2026-10-25T12:00:00Z",
        },
    }

    # Explicitly empty transactions list
    client = MockPayPalClient(
        subscription_responses={sub_id: mock_sub_payload},
        transactions_responses={sub_id: []},
    )

    reconciled = await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=sub_id,
        paypal_client=client,
    )
    await async_db.commit()

    assert reconciled is not None
    # No payment was inserted with fake ID
    pay_stmt = select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id)
    payments = (await async_db.execute(pay_stmt)).scalars().all()
    assert len(payments) == 0

