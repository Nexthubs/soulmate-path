"""
Automated tests for Confirm Subscription API & Subscription Status (SP-403, DEV-SPEC §9.3–9.4, §15.7–15.8, Decisions: PAY-AUTH-01).
"""

from datetime import datetime, timezone
from decimal import Decimal
import uuid
from typing import Any, Dict, Optional
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ForbiddenOwnershipError, NotFoundError, ValidationError
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal, SessionLocal
from app.main import app
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.security import generate_session_token
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.subscription_service import SubscriptionService


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_session(db_session: Session) -> SoulmateSession:
    """Creates an active test SoulmateSession."""
    public_id = f"test_confirm_{uuid.uuid4().hex[:12]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.EMAIL_CAPTURED.value,
        current_step="transition_5",
        email=f"{public_id}@example.com",
        email_normalized=f"{public_id}@example.com",
    )
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)
    return sess


class MockPayPalClient(PayPalClient):
    """Mock PayPalClient that returns configurable subscription payloads without live network calls."""

    def __init__(self, subscription_responses: Optional[Dict[str, Any]] = None):
        super().__init__(client_id="mock_id", client_secret="mock_secret")
        self.subscription_responses = subscription_responses or {}

    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        return self.subscription_responses.get(subscription_id)


# ==============================================================================
# 1. Service Layer Tests: Validation, Ownership, Idempotency & PAY-AUTH-01
# ==============================================================================


@pytest.mark.asyncio
async def test_confirm_subscription_success_and_pay_auth_01(test_session: SoulmateSession, monkeypatch):
    """
    Acceptance:
    - Provider subscription ID validated server-side;
    - Ownership/session binding enforced;
    - Entitlement remains pending (PAY-AUTH-01): first_payment_at is None, is_paid is False.
    """
    plan_id = "P-SOULMATE-INTRO-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-TEST-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVAL_PENDING",
        "plan_id": plan_id,
        "custom_id": test_session.public_id,
        "shipping_amount": {"currency_code": "USD", "value": "0.00"},
        "billing_info": {
            "next_billing_time": "2026-10-24T12:00:00Z",
        },
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        result = await SubscriptionService.confirm_paypal_subscription(
            db=async_db,
            session=test_session,
            paypal_subscription_id=sub_id,
            paypal_client=mock_client,
        )

    # Acceptance: provider subscription ID validated
    assert result.provider_subscription_id == sub_id
    assert result.provider_plan_id == plan_id
    assert result.provider_status == "APPROVAL_PENDING"

    # HIGH-RISK INVARIANT (PAY-AUTH-01):
    # Success callback does NOT grant entitlement. first_payment_at is None, is_paid is False.
    assert result.status == "PROCESSING"
    assert result.is_paid is False

    # Verify persisted DB record
    with SessionLocal() as sync_db:
        stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id)
        db_sub = sync_db.execute(stmt).scalars().first()
        assert db_sub is not None
        assert db_sub.session_id == test_session.id
        assert db_sub.provider_plan_id == plan_id
        assert db_sub.first_payment_at is None


@pytest.mark.asyncio
async def test_confirm_subscription_idempotency_duplicate(test_session: SoulmateSession, monkeypatch):
    """
    Acceptance: duplicate confirmation is idempotent.
    Repeated confirmation calls with the same session & subscription ID return 200 without creating duplicates.
    """
    plan_id = "P-SOULMATE-INTRO-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-DUP-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        "custom_id": test_session.public_id,
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        res1 = await SubscriptionService.confirm_paypal_subscription(
            db=async_db,
            session=test_session,
            paypal_subscription_id=sub_id,
            paypal_client=mock_client,
        )

        # Call again with the exact same subscription ID
        res2 = await SubscriptionService.confirm_paypal_subscription(
            db=async_db,
            session=test_session,
            paypal_subscription_id=sub_id,
            paypal_client=mock_client,
        )

    assert res1.provider_subscription_id == sub_id
    assert res2.provider_subscription_id == sub_id
    assert "idempotent duplicate" in res2.message.lower()

    # Verify exactly one record exists in database
    with SessionLocal() as sync_db:
        stmt = select(Subscription).where(Subscription.provider_subscription_id == sub_id)
        rows = sync_db.execute(stmt).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_confirm_subscription_cross_session_hijack_prevention(db_session: Session, monkeypatch):
    """
    Acceptance: ownership/session binding enforced.
    Cross-session subscription hijacking is rejected with ForbiddenOwnershipError.
    """
    plan_id = "P-SOULMATE-INTRO-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    # Session A
    sess_a = SoulmateSession(
        public_id=f"ses_a_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.EMAIL_CAPTURED.value,
        current_step="transition_5",
    )
    # Session B
    sess_b = SoulmateSession(
        public_id=f"ses_b_{uuid.uuid4().hex[:8]}",
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.EMAIL_CAPTURED.value,
        current_step="transition_5",
    )
    db_session.add_all([sess_a, sess_b])
    db_session.commit()
    db_session.refresh(sess_a)
    db_session.refresh(sess_b)

    sub_id = f"I-HIJACK-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        "custom_id": sess_a.public_id,
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        # Session A confirms sub_id
        await SubscriptionService.confirm_paypal_subscription(
            db=async_db,
            session=sess_a,
            paypal_subscription_id=sub_id,
            paypal_client=mock_client,
        )

        # Session B attempts to confirm the same sub_id -> must be forbidden
        with pytest.raises(ForbiddenOwnershipError) as exc_info:
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=sess_b,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )

    assert "already bound to a different session" in str(exc_info.value)


@pytest.mark.asyncio
async def test_confirm_subscription_not_found_on_paypal(test_session: SoulmateSession):
    """Provider subscription ID that does not exist on PayPal is rejected with NotFoundError."""
    mock_client = MockPayPalClient({})  # Returns None for any query

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(NotFoundError) as exc_info:
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id="I-NONEXISTENT",
                paypal_client=mock_client,
            )

    assert "not found on PayPal" in str(exc_info.value)


@pytest.mark.asyncio
async def test_confirm_subscription_unapproved_plan_rejected(test_session: SoulmateSession, monkeypatch):
    """Subscription targeting an unapproved plan is rejected with ValidationError."""
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", "P-APPROVED-PLAN-1")
    monkeypatch.setattr(settings, "paypal_soulmate_standard_plan_id", "P-APPROVED-PLAN-2")

    sub_id = "I-WRONG-PLAN-123"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": "P-UNAPPROVED-ROGUE-PLAN",
        "custom_id": test_session.public_id,
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ValidationError) as exc_info:
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )

    assert "does not match configured Soulmate plans" in str(exc_info.value)


@pytest.mark.asyncio
async def test_confirm_subscription_fails_closed_when_no_plans_configured(test_session: SoulmateSession, monkeypatch):
    """H-2: When neither intro nor standard plan is configured, confirmation rejects fail-closed."""
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", None)
    monkeypatch.setattr(settings, "paypal_soulmate_standard_plan_id", None)

    sub_id = "I-NO-PLANS-CONFIGURED"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": "P-ANY-PLAN",
        "custom_id": test_session.public_id,
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ValidationError) as exc_info:
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )

    assert "not configured" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_confirm_subscription_fails_closed_when_provider_plan_id_missing(test_session: SoulmateSession, monkeypatch):
    """H-2: When provider payload lacks plan_id, confirmation rejects fail-closed."""
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", "P-APPROVED-1")

    sub_id = "I-MISSING-PLAN-ID"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": None,
        "custom_id": test_session.public_id,
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ValidationError) as exc_info:
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )

    assert "does not match configured Soulmate plans" in str(exc_info.value)


@pytest.mark.asyncio
async def test_confirm_subscription_invalid_status_rejected(test_session: SoulmateSession, monkeypatch):
    """Subscription in cancelled or expired terminal status is rejected."""
    plan_id = "P-VALID-PLAN-999"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = "I-CANCELLED-999"
    mock_payload = {
        "id": sub_id,
        "status": "CANCELLED",
        "plan_id": plan_id,
        "custom_id": test_session.public_id,
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ValidationError) as exc_info:
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )

    assert "invalid status: 'CANCELLED'" in str(exc_info.value)


# ==============================================================================
# 2. HTTP Endpoint & Integration Tests (DEV-SPEC §15.7, §15.8)
# ==============================================================================


@pytest.mark.asyncio
async def test_api_confirm_subscription_endpoint(test_session: SoulmateSession, monkeypatch):
    """Verify POST /api/soulmate/subscription/paypal/confirm with cookie auth."""
    plan_id = "P-INTRO-HTTP-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-HTTP-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        "custom_id": test_session.public_id,
    }

    # Monkeypatch PayPalClient.get_subscription
    async def mock_get_sub(self, s_id: str):
        if s_id == sub_id:
            return mock_payload
        return None

    monkeypatch.setattr(PayPalClient, "get_subscription", mock_get_sub)

    token = generate_session_token(test_session.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)

        # 1. First confirmation
        resp = await client.post(
            "/api/soulmate/subscription/paypal/confirm",
            json={"paypal_subscription_id": sub_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_subscription_id"] == sub_id
        assert data["status"] == "PROCESSING"
        assert data["is_paid"] is False  # PAY-AUTH-01

        # 2. Repeated duplicate confirmation (idempotent)
        resp2 = await client.post(
            "/api/soulmate/subscription/paypal/confirm",
            json={"paypal_subscription_id": sub_id},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["provider_subscription_id"] == sub_id
        assert "idempotent duplicate" in data2["message"].lower()


@pytest.mark.asyncio
async def test_api_confirm_subscription_idor_rejected(test_session: SoulmateSession):
    """Cross-session IDOR attempt with foreign session_id query is rejected with 403."""
    foreign_public_id = f"ses_foreign_{uuid.uuid4().hex[:8]}"
    token = generate_session_token(test_session.public_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)

        resp = await client.post(
            "/api/soulmate/subscription/paypal/confirm",
            json={
                "session_id": foreign_public_id,
                "paypal_subscription_id": "I-ANY-SUB",
            },
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_subscription_status_polling_endpoint(test_session: SoulmateSession, db_session: Session):
    """
    Verify GET /api/soulmate/subscription/status (DEV-SPEC §15.8):
    1. Returns 'NONE' when no subscription exists.
    2. Returns 'PROCESSING' and is_paid=False after confirmation.
    3. Returns 'ACTIVE' and is_paid=True after webhook sets first_payment_at.
    """
    token = generate_session_token(test_session.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)

        # 1. Initial: No subscription
        resp1 = await client.get("/api/soulmate/subscription/status")
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "NONE"
        assert resp1.json()["is_paid"] is False

        # 2. Insert pending subscription in DB
        sub_id = f"I-STAT-{uuid.uuid4().hex[:8].upper()}"
        sub = Subscription(
            session_id=test_session.id,
            provider="paypal",
            provider_subscription_id=sub_id,
            provider_plan_id="P-TEST",
            provider_status="APPROVED",
            currency="USD",
            regular_price=Decimal("29.00"),
            first_payment_at=None,
        )
        db_session.add(sub)
        db_session.commit()

        resp2 = await client.get("/api/soulmate/subscription/status")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "PROCESSING"
        assert data2["is_paid"] is False
        assert data2["subscription_id"] == sub_id

        # 3. Simulate payment completed event (reconciliation)
        sub.first_payment_at = datetime.now(timezone.utc)
        db_session.commit()

        resp3 = await client.get("/api/soulmate/subscription/status")
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["status"] == "ACTIVE"
        assert data3["is_paid"] is True


@pytest.mark.asyncio
async def test_router_aliases_matching_dev_spec(test_session: SoulmateSession, monkeypatch):
    """
    Verify DEV-SPEC router table aliases:
    - POST /api/soulmate/paypal/confirm (§9.3)
    - POST /api/soulmate/payments/paypal/confirm (§15.7)
    - GET /api/soulmate/subscriptions/me (§15.8)
    """
    plan_id = "P-SOULMATE-ALIAS"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-ALIAS-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        "custom_id": test_session.public_id,
    }

    async def mock_get_sub(self, s_id: str):
        if s_id == sub_id:
            return mock_payload
        return None

    monkeypatch.setattr(PayPalClient, "get_subscription", mock_get_sub)

    token = generate_session_token(test_session.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)

        # Alias 1: /paypal/confirm
        resp1 = await client.post("/api/soulmate/paypal/confirm", json={"paypal_subscription_id": sub_id})
        assert resp1.status_code == 200
        assert resp1.json()["provider_subscription_id"] == sub_id

        # Alias 2: /payments/paypal/confirm
        resp2 = await client.post("/api/soulmate/payments/paypal/confirm", json={"paypal_subscription_id": sub_id})
        assert resp2.status_code == 200
        assert resp2.json()["provider_subscription_id"] == sub_id

        # Alias 3: /subscriptions/me
        resp3 = await client.get("/api/soulmate/subscriptions/me")
        assert resp3.status_code == 200
        assert resp3.json()["subscription_id"] == sub_id
        assert resp3.json()["status"] == "PROCESSING"


# ==============================================================================
# 5. Security & Ownership Verification Tests (C-1 Audit Remediation, DEV-SPEC §15.7)
# ==============================================================================


@pytest.mark.asyncio
async def test_confirm_subscription_rejects_unattached_subscription_with_mismatched_custom_id(
    test_session: SoulmateSession, monkeypatch
):
    """
    C-1 Verification:
    Reject claiming an unattached subscription if its custom_id belongs to another session.
    Must raise ForbiddenOwnershipError (HTTP 403).
    """
    plan_id = "P-SOULMATE-C1-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-UNATTACHED-MISMATCH-CUSTOM-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        "custom_id": "sess_different_session_999",
        "subscriber": {"email_address": "buyer@example.com"},
        "billing_info": {"next_billing_time": "2026-10-25T12:00:00Z"},
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ForbiddenOwnershipError, match="does not belong to this session"):
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )


@pytest.mark.asyncio
async def test_confirm_subscription_rejects_missing_custom_id_even_if_subscriber_email_matches(
    test_session: SoulmateSession, monkeypatch
):
    """
    Critical Finding Remediation (DEV-SPEC §15.7, §20):
    Even if subscriber email matches the session's captured email,
    confirmation MUST be rejected if custom_id is absent because quiz funnel emails are unverified.
    """
    plan_id = "P-SOULMATE-C1-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    # Use test_session's email
    matching_email = test_session.email_normalized or "user@example.com"
    test_session.email_normalized = matching_email

    sub_id = f"I-MISSING-CUSTOM-ID-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        # No custom_id
        "subscriber": {"email_address": matching_email},
        "billing_info": {"next_billing_time": "2026-10-25T12:00:00Z"},
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ForbiddenOwnershipError, match="lacks valid session binding"):
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )


@pytest.mark.asyncio
async def test_confirm_subscription_rejects_when_both_custom_id_and_email_are_missing(
    test_session: SoulmateSession, monkeypatch
):
    """
    Critical Finding Remediation (DEV-SPEC §15.7, §20):
    When both custom_id and subscriber email are missing from PayPal response,
    confirmation must reject fail-closed with ForbiddenOwnershipError.
    """
    plan_id = "P-SOULMATE-C1-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-NO-BINDING-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        # No custom_id and no subscriber
        "billing_info": {"next_billing_time": "2026-10-25T12:00:00Z"},
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        with pytest.raises(ForbiddenOwnershipError, match="lacks valid session binding"):
            await SubscriptionService.confirm_paypal_subscription(
                db=async_db,
                session=test_session,
                paypal_subscription_id=sub_id,
                paypal_client=mock_client,
            )


@pytest.mark.asyncio
async def test_confirm_subscription_accepts_matching_custom_id_even_with_different_paypal_email(
    test_session: SoulmateSession, monkeypatch
):
    """
    C-1 Verification:
    When custom_id strictly matches session public_id, confirmation succeeds
    even if the user paid using a personal PayPal account with a different email address.
    """
    plan_id = "P-SOULMATE-C1-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-MATCH-CUSTOM-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVAL_PENDING",
        "plan_id": plan_id,
        "custom_id": test_session.public_id,
        "subscriber": {"email_address": "different_paypal_acct@example.com"},
        "billing_info": {"next_billing_time": "2026-10-25T12:00:00Z"},
    }
    mock_client = MockPayPalClient({sub_id: mock_payload})

    async with AsyncSessionLocal() as async_db:
        result = await SubscriptionService.confirm_paypal_subscription(
            db=async_db,
            session=test_session,
            paypal_subscription_id=sub_id,
            paypal_client=mock_client,
        )
        assert result.provider_subscription_id == sub_id
        assert result.session_id == test_session.public_id


@pytest.mark.asyncio
async def test_confirm_subscription_endpoint_returns_403_on_mismatched_unattached_sub(
    test_session: SoulmateSession, monkeypatch
):
    """
    C-1 Integration Verification:
    POST /api/soulmate/paypal/confirm returns 403 Forbidden when trying to claim an unattached
    subscription belonging to someone else.
    """
    plan_id = "P-SOULMATE-C1-TEST"
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", plan_id)

    sub_id = f"I-UNATTACHED-403-{uuid.uuid4().hex[:8].upper()}"
    mock_payload = {
        "id": sub_id,
        "status": "APPROVED",
        "plan_id": plan_id,
        "custom_id": "sess_foreign_victim",
    }

    async def mock_get_sub(self, s_id: str):
        if s_id == sub_id:
            return mock_payload
        return None

    monkeypatch.setattr(PayPalClient, "get_subscription", mock_get_sub)

    token = generate_session_token(test_session.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.post("/api/soulmate/paypal/confirm", json={"paypal_subscription_id": sub_id})
        assert resp.status_code == 403
        assert "does not belong to this session" in resp.json()["message"]
