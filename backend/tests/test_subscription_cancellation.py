"""
Unit and Integration Tests for Subscription Cancellation and Settings Action (SP-409, DEV-SPEC §9.8, §15.9, Decisions: PAY-AUTH-01).

Acceptance Criteria:
1. Cancellation uses server-side provider API (POST /v1/billing/subscriptions/{id}/cancel).
2. Current paid-through/access semantics shown correctly.
3. Repeated cancel is safe and idempotent.
4. Cancelled users retain previously generated artifacts (never deleted).
5. Canonical routes and aliases (/api/soulmate/subscription/cancel, /api/account/subscription/cancel, /api/soulmate/subscriptions/cancel).
6. IDOR protection: cannot cancel another session's subscription.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.subscription_service import SubscriptionService
from app.soulmate.services.webhook_service import PayPalWebhookService
from app.soulmate.domain.webhook_models import PayPalWebhookRawRequest


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


class MockCancelPayPalClient(PayPalClient):
    """Mock PayPalClient tracking cancellation calls and providing configurable subscription payloads."""

    def __init__(
        self,
        subscription_data: Optional[Dict[str, Any]] = None,
        cancel_success: bool = True,
    ):
        super().__init__(client_id="mock_id", client_secret="mock_secret")
        self.subscription_data = subscription_data or {}
        self.cancel_success = cancel_success
        self.cancelled_calls: list[dict[str, Any]] = []

    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        return self.subscription_data.get(subscription_id)

    async def cancel_subscription(self, subscription_id: str, reason: str = "Customer request") -> bool:
        self.cancelled_calls.append({"subscription_id": subscription_id, "reason": reason})
        return self.cancel_success


async def create_test_session_with_active_sub(
    db: AsyncSession,
    provider_sub_id: str,
    first_payment_at: Optional[datetime] = None,
    next_billing_at: Optional[datetime] = None,
    paid_through_at: Optional[datetime] = None,
) -> tuple[SoulmateSession, Subscription]:
    """Helper to seed a session with an active paid subscription."""
    public_id = f"test_cancel_sess_{uuid.uuid4().hex[:10]}"
    user_email = f"buyer_{uuid.uuid4().hex[:8]}@example.com"
    now = datetime.now(timezone.utc)

    sess = SoulmateSession(
        public_id=public_id,
        email=user_email,
        email_normalized=user_email.lower(),
        status="paid" if first_payment_at else "subscribed",
        current_step="result",
        subscription_success_at=first_payment_at,
        quiz_completed_at=now - timedelta(hours=2),
        email_captured_at=now - timedelta(hours=1),
    )
    db.add(sess)
    await db.flush()

    sub = Subscription(
        session_id=sess.id,
        user_id=None,
        provider="paypal",
        provider_subscription_id=provider_sub_id,
        provider_plan_id="P-SOULMATE-MONTHLY",
        provider_status="ACTIVE",
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        first_payment_at=first_payment_at,
        next_billing_at=next_billing_at or (now + timedelta(days=30)),
        paid_through_at=paid_through_at,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sess)
    await db.refresh(sub)
    return sess, sub


# ------------------------------------------------------------------------------
# Test 1: Acceptance Criterion 1 & 2 - Server-side Provider API & Paid-Through Access
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_subscription_success_via_provider_api(async_db: AsyncSession):
    """
    Acceptance Criteria 1 & 2:
    - Cancellation uses server-side provider API: POST /v1/billing/subscriptions/{id}/cancel.
    - Saves PayPal billing_info.next_billing_time as local paid_through_at before calling cancel.
    - Clears next_billing_at (no future renewal charges).
    """
    sub_id = f"I-TEST-CANCEL-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    future_billing = now + timedelta(days=25)
    future_billing_iso = future_billing.isoformat().replace("+00:00", "Z")

    sess, sub = await create_test_session_with_active_sub(
        async_db,
        provider_sub_id=sub_id,
        first_payment_at=now - timedelta(days=5),
        next_billing_at=future_billing,
    )

    mock_client = MockCancelPayPalClient(
        subscription_data={
            sub_id: {
                "id": sub_id,
                "status": "ACTIVE",
                "billing_info": {
                    "next_billing_time": future_billing_iso,
                    "last_payment": {"time": (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")},
                },
            }
        },
        cancel_success=True,
    )

    resp = await SubscriptionService.cancel_subscription(
        db=async_db,
        session=sess,
        reason="User requested cancellation via settings",
        paypal_client=mock_client,
    )

    # 1. Verify response semantics
    assert resp.status == "CANCELLED"
    assert resp.provider_status == "CANCELLED"
    assert resp.is_paid is True
    assert resp.cancelled_at is not None
    assert resp.paid_through_at is not None
    assert abs((resp.paid_through_at - future_billing).total_seconds()) < 5

    # 2. Verify server-side PayPal API call was made
    assert len(mock_client.cancelled_calls) == 1
    assert mock_client.cancelled_calls[0]["subscription_id"] == sub_id
    assert mock_client.cancelled_calls[0]["reason"] == "User requested cancellation via settings"

    # 3. Verify DB persistence
    await async_db.refresh(sub)
    assert sub.provider_status == "CANCELLED"
    assert sub.cancelled_at is not None
    assert sub.next_billing_at is None  # Future renewals cleared
    assert sub.paid_through_at is not None


# ------------------------------------------------------------------------------
# Test 2: Acceptance Criterion 3 - Safe & Idempotent Repeated Cancellation
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_cancel_is_safe_and_idempotent(async_db: AsyncSession):
    """
    Acceptance Criterion 3:
    Repeated cancel is safe/idempotent. Subsequent calls return CANCELLED status
    without raising errors and without re-calling PayPal provider API.
    """
    sub_id = f"I-TEST-REPEAT-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    future_billing = now + timedelta(days=20)

    sess, sub = await create_test_session_with_active_sub(
        async_db,
        provider_sub_id=sub_id,
        first_payment_at=now - timedelta(days=10),
        next_billing_at=future_billing,
    )

    mock_client = MockCancelPayPalClient(
        subscription_data={
            sub_id: {
                "id": sub_id,
                "status": "ACTIVE",
                "billing_info": {"next_billing_time": future_billing.isoformat()},
            }
        },
        cancel_success=True,
    )

    # First cancel call
    resp1 = await SubscriptionService.cancel_subscription(
        db=async_db,
        session=sess,
        paypal_client=mock_client,
    )
    assert resp1.status == "CANCELLED"
    assert len(mock_client.cancelled_calls) == 1

    # Second cancel call (repeated / idempotent)
    resp2 = await SubscriptionService.cancel_subscription(
        db=async_db,
        session=sess,
        paypal_client=mock_client,
    )
    assert resp2.status == "CANCELLED"
    assert resp2.cancelled_at == resp1.cancelled_at
    assert resp2.paid_through_at == resp1.paid_through_at
    # Should NOT have made a second call to PayPal API
    assert len(mock_client.cancelled_calls) == 1


# ------------------------------------------------------------------------------
# Test 3: Acceptance Criterion 4 - Cancelled Users Retain Previously Generated Artifacts
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancelled_users_retain_previously_generated_artifacts(async_db: AsyncSession):
    """
    Acceptance Criterion 4:
    Cancelled users retain previously generated artifacts.
    Cancelling a subscription must NEVER delete or alter existing rows in soulmate_artifacts.
    """
    sub_id = f"I-TEST-RETAIN-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    sess, sub = await create_test_session_with_active_sub(
        async_db,
        provider_sub_id=sub_id,
        first_payment_at=now - timedelta(days=2),
    )

    # Seed existing completed artifacts
    sketch = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=sess.email_normalized,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=now - timedelta(hours=10),
        generation_status="COMPLETED",
        storage_key="s3://soulmate-artifacts/sketches/user_sketch_1.png",
    )
    report = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=sess.email_normalized,
        artifact_type="REPORT",
        artifact_version="v1",
        unlock_at=now - timedelta(hours=5),
        generation_status="COMPLETED",
        content_json={"title": "Soulmate Compatibility Report", "sections": ["Intro", "Zodiac", "Destiny"]},
    )
    async_db.add(sketch)
    async_db.add(report)
    await async_db.commit()

    mock_client = MockCancelPayPalClient(
        subscription_data={
            sub_id: {
                "id": sub_id,
                "status": "ACTIVE",
                "billing_info": {"next_billing_time": (now + timedelta(days=28)).isoformat()},
            }
        },
        cancel_success=True,
    )

    # Cancel subscription
    resp = await SubscriptionService.cancel_subscription(
        db=async_db,
        session=sess,
        paypal_client=mock_client,
    )
    assert resp.status == "CANCELLED"

    # Invariant check: Query artifacts to ensure they are 100% preserved
    stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == sess.id)
    artifacts = (await async_db.execute(stmt)).scalars().all()
    assert len(artifacts) == 2

    artifact_types = {a.artifact_type: a for a in artifacts}
    assert "SKETCH" in artifact_types
    assert "REPORT" in artifact_types

    assert artifact_types["SKETCH"].generation_status == "COMPLETED"
    assert artifact_types["SKETCH"].storage_key == "s3://soulmate-artifacts/sketches/user_sketch_1.png"
    assert artifact_types["REPORT"].generation_status == "COMPLETED"
    assert artifact_types["REPORT"].content_json["title"] == "Soulmate Compatibility Report"


# ------------------------------------------------------------------------------
# Test 4: REST API Endpoints & Route Aliases (/api/soulmate/subscription/cancel,
# /api/account/subscription/cancel, /api/soulmate/subscriptions/cancel)
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_api_endpoints_and_aliases(async_db: AsyncSession, monkeypatch):
    """
    Test cancel API endpoints and routing aliases:
    - POST /api/soulmate/subscription/cancel
    - POST /api/account/subscription/cancel (DEV-SPEC §15.9)
    - POST /api/soulmate/subscriptions/cancel (router table alias)
    """
    sub_id = f"I-API-CANCEL-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    sess, sub = await create_test_session_with_active_sub(
        async_db,
        provider_sub_id=sub_id,
        first_payment_at=now - timedelta(days=1),
    )

    mock_client = MockCancelPayPalClient(
        subscription_data={
            sub_id: {
                "id": sub_id,
                "status": "ACTIVE",
                "billing_info": {"next_billing_time": (now + timedelta(days=29)).isoformat()},
            }
        },
        cancel_success=True,
    )
    monkeypatch.setattr("app.soulmate.services.subscription_service.PayPalClient", lambda *args, **kwargs: mock_client)

    token = generate_session_token(sess.public_id)
    cookies = {"soulmate_sid": token}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test 1: Primary endpoint POST /api/soulmate/subscription/cancel
        res1 = await client.post(
            "/api/soulmate/subscription/cancel",
            json={"session_id": sess.public_id, "reason": "Moving on"},
            cookies=cookies,
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "CANCELLED"
        assert data1["is_paid"] is True
        assert data1["subscription_id"] == sub_id

        # Test 2: Alias POST /api/account/subscription/cancel (DEV-SPEC §15.9)
        # Should return idempotent 200 OK since already cancelled
        res2 = await client.post(
            "/api/account/subscription/cancel",
            json={"session_id": sess.public_id},
            cookies=cookies,
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "CANCELLED"

        # Test 3: Alias POST /api/soulmate/subscriptions/cancel
        res3 = await client.post(
            "/api/soulmate/subscriptions/cancel",
            json={"session_id": sess.public_id},
            cookies=cookies,
        )
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["status"] == "CANCELLED"


# ------------------------------------------------------------------------------
# Test 5: IDOR Protection & Unauthenticated Access
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_idor_protection(async_db: AsyncSession):
    """
    IDOR Protection:
    Attempting to cancel session B with session A credentials must return 403 Forbidden.
    """
    sub_id_a = f"I-SUB-A-{uuid.uuid4().hex[:8]}"
    sub_id_b = f"I-SUB-B-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    sess_a, _ = await create_test_session_with_active_sub(async_db, provider_sub_id=sub_id_a, first_payment_at=now)
    sess_b, _ = await create_test_session_with_active_sub(async_db, provider_sub_id=sub_id_b, first_payment_at=now)

    token_a = generate_session_token(sess_a.public_id)
    cookies = {"soulmate_sid": token_a}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A tries to cancel User B's subscription
        res = await client.post(
            "/api/soulmate/subscription/cancel",
            json={"session_id": sess_b.public_id},
            cookies=cookies,
        )
        assert res.status_code == 403
        data = res.json()
        assert data["error_code"] == "FORBIDDEN_OWNERSHIP"


# ------------------------------------------------------------------------------
# Test 6: Webhook BILLING.SUBSCRIPTION.CANCELLED Integration
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_cancellation_sets_paid_through_and_retains_artifacts(async_db: AsyncSession):
    """
    Verifies that incoming PayPal BILLING.SUBSCRIPTION.CANCELLED webhook:
    1. Sets provider_status = CANCELLED and cancelled_at.
    2. Preserves billing_info.next_billing_time as paid_through_at.
    3. Clears next_billing_at.
    4. Retains existing artifacts without deletion.
    """
    sub_id = f"I-WH-CANCEL-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    future_billing = now + timedelta(days=15)
    future_billing_iso = future_billing.isoformat().replace("+00:00", "Z")

    sess, sub = await create_test_session_with_active_sub(
        async_db,
        provider_sub_id=sub_id,
        first_payment_at=now - timedelta(days=15),
        next_billing_at=future_billing,
    )

    # Seed an artifact
    artifact = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=sess.email_normalized,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=now - timedelta(hours=1),
        generation_status="COMPLETED",
        storage_key="s3://sketch.png",
    )
    async_db.add(artifact)
    await async_db.commit()

    webhook_payload = {
        "id": f"WH-EVENT-{uuid.uuid4().hex[:8]}",
        "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
        "create_time": now.isoformat().replace("+00:00", "Z"),
        "resource": {
            "id": sub_id,
            "status": "CANCELLED",
            "billing_info": {
                "next_billing_time": future_billing_iso,
            },
        },
    }

    raw_req = PayPalWebhookRawRequest(
        event_id=webhook_payload["id"],
        event_type="BILLING.SUBSCRIPTION.CANCELLED",
        create_time=webhook_payload["create_time"],
        resource_type="subscription",
        resource_id=sub_id,
        summary="Subscription cancelled",
        headers={},
        raw_body=b"{}",
        parsed_json=webhook_payload,
    )

    await PayPalWebhookService.process_webhook(
        raw_request=raw_req,
        db=async_db,
        require_verification=False,
    )

    # Verify DB state
    await async_db.refresh(sub)
    assert sub.provider_status == "CANCELLED"
    assert sub.cancelled_at is not None
    assert sub.next_billing_at is None
    assert sub.paid_through_at is not None
    assert abs((sub.paid_through_at - future_billing).total_seconds()) < 5

    # Verify artifact is retained
    art_stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == sess.id)
    retained_artifacts = (await async_db.execute(art_stmt)).scalars().all()
    assert len(retained_artifacts) == 1
    assert retained_artifacts[0].storage_key == "s3://sketch.png"


# ------------------------------------------------------------------------------
# Test 7: Non-existent Subscription returns 404 Not Found
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_nonexistent_subscription_raises_404(async_db: AsyncSession):
    """Attempting to cancel when session has no active subscription must return 404."""
    public_id = f"test_nosub_{uuid.uuid4().hex[:10]}"
    sess = SoulmateSession(
        public_id=public_id,
        email="nosub@example.com",
        email_normalized="nosub@example.com",
        status="registered",
        current_step="quiz",
    )
    async_db.add(sess)
    await async_db.commit()

    token = generate_session_token(public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"soulmate_sid": token}) as client:
        res = await client.post(
            "/api/soulmate/subscription/cancel",
            json={"session_id": public_id},
        )
        assert res.status_code == 404
        data = res.json()
        assert data["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cancel_subscription_without_next_billing_time_avoids_fictitious_30_days(async_db: AsyncSession):
    """
    H-4 Verification (SP-409, DEV-SPEC §9.4):
    When PayPal does NOT return next_billing_time and local subscription has no next_billing_at or paid_through_at,
    cancel_subscription must NOT hardcode + timedelta(days=30). It leaves paid_through_at unset without inventing a duration.
    """
    sub_id = f"I-NO-NEXTBILL-{uuid.uuid4().hex[:8].upper()}"
    first_paid = datetime.now(timezone.utc) - timedelta(days=15)
    sess, sub = await create_test_session_with_active_sub(
        async_db,
        sub_id,
        first_payment_at=first_paid,
        next_billing_at=None,
        paid_through_at=None,
    )
    # Ensure next_billing_at and paid_through_at are None
    sub.next_billing_at = None
    sub.paid_through_at = None
    await async_db.commit()

    # Remote payload with NO next_billing_time
    mock_payload = {
        "id": sub_id,
        "status": "ACTIVE",
        "billing_info": {},  # No next_billing_time
    }
    client = MockCancelPayPalClient(subscription_data={sub_id: mock_payload}, cancel_success=True)

    resp = await SubscriptionService.cancel_subscription(
        db=async_db,
        session=sess,
        reason="No next billing test",
        paypal_client=client,
    )

    assert resp.status == "CANCELLED"
    assert resp.paid_through_at is None  # Accurately None, NOT hardcoded +30 days!
    await async_db.refresh(sub)
    assert sub.paid_through_at is None
    assert len(client.cancelled_calls) == 1


