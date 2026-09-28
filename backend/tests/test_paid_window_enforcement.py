"""
PAID-THROUGH-01 uniform API-layer enforcement tests (Wave 8 audit round 3).

After a known-and-passed paid window (judged on the server clock):
- GET /result -> 403 (the aggregate read ends with the window);
- POST /artifacts/sketch/generate and /artifacts/report/generate -> 403
  (generation of new content is a paid benefit);
- GET /artifacts/sketch and /artifacts/report -> 403 for non-COMPLETED states,
  200 for COMPLETED artifacts (§9.8 retention promise: keep what you received);
- cached ACTIVE is reconciled with PayPal; only an advanced paid-through date
  restores benefits, while a failed provider check never grants access.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token
from app.soulmate.services.paypal_client import PayPalAPIError, PayPalClient

RESULT_URL = "/api/soulmate/result"
SKETCH_URL = "/api/soulmate/artifacts/sketch"
SKETCH_GENERATE_URL = "/api/soulmate/artifacts/sketch/generate"
REPORT_URL = "/api/soulmate/artifacts/report"
REPORT_GENERATE_URL = "/api/soulmate/artifacts/report/generate"
GUARD_URL = "/api/soulmate/guard/check"

PAST = datetime.now(timezone.utc) - timedelta(days=1)
FUTURE = datetime.now(timezone.utc) + timedelta(days=25)


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


async def seed_paid_session(
    async_db: AsyncSession,
    *,
    provider_status: str,
    paid_through_at,
    sketch_generation: str = "NOT_STARTED",
    report_generation: str = "NOT_STARTED",
) -> SoulmateSession:
    """Seed a subscribed session + subscription row with the given window state."""
    public_id = f"test_pt_{uuid.uuid4().hex[:12]}"
    email = f"{public_id}@example.com"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        quiz_completed_at=datetime.now(timezone.utc) - timedelta(days=30),
        email=email,
        email_normalized=email,
        subscription_success_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    async_db.add(sess)
    await async_db.commit()
    await async_db.refresh(sess)

    async_db.add(
        Subscription(
            session_id=sess.id,
            provider="paypal",
            provider_subscription_id=f"I-PT-{uuid.uuid4().hex[:8]}",
            provider_plan_id="P-PT-TEST",
            provider_status=provider_status,
            currency="USD",
            regular_price=Decimal("29.00"),
            first_payment_at=datetime.now(timezone.utc) - timedelta(days=30),
            paid_through_at=paid_through_at,
        )
    )

    if sketch_generation != "NONE" or report_generation != "NONE":
        rows = []
        if sketch_generation != "NONE":
            rows.append(
                SoulmateArtifact(
                    session_id=sess.id,
                    email_normalized=email,
                    artifact_type="SKETCH",
                    artifact_version="v1",
                    unlock_at=datetime.now(timezone.utc) - timedelta(days=28),
                    generation_status=sketch_generation,
                    **({"storage_key": f"paid-through-tests/{public_id}/sketch.png"} if sketch_generation == "COMPLETED" else {}),
                )
            )
        if report_generation != "NONE":
            rows.append(
                SoulmateArtifact(
                    session_id=sess.id,
                    email_normalized=email,
                    artifact_type="REPORT",
                    artifact_version="v1",
                    unlock_at=datetime.now(timezone.utc) - timedelta(days=28),
                    generation_status=report_generation,
                    **({"content_json": {
                        "schemaVersion": "v1",
                        "title": "Your Soulmate Report",
                        "intro": "A story of connection.",
                        "sections": [{"index": "01.", "title": "A New Beginning", "body": "Connection grows with care."}],
                        "closing": "Trust the journey.",
                    }} if report_generation == "COMPLETED" else {}),
                )
            )
        for row in rows:
            async_db.add(row)

    await async_db.commit()
    await async_db.refresh(sess)
    return sess


def auth_client(sess: SoulmateSession) -> AsyncClient:
    token = generate_session_token(sess.public_id)
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies={"soulmate_sid": token}
    )


@pytest.mark.asyncio
async def test_result_aggregate_denied_after_paid_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db, provider_status="CANCELLED", paid_through_at=PAST
    )
    async with auth_client(sess) as client:
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 403
    assert "Paid access period has ended" in resp.json()["message"]


@pytest.mark.asyncio
async def test_active_renewal_must_advance_paid_window(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    sess = await seed_paid_session(
        async_db, provider_status="ACTIVE", paid_through_at=PAST
    )
    async def get_subscription(self, subscription_id):
        return {"status": "ACTIVE", "billing_info": {"next_billing_time": FUTURE.isoformat()}}

    async def list_transactions(self, subscription_id, start_time=None, end_time=None):
        return []

    monkeypatch.setattr(PayPalClient, "get_subscription", get_subscription)
    monkeypatch.setattr(PayPalClient, "list_subscription_transactions", list_transactions)
    async with auth_client(sess) as client:
        guard = await client.get(GUARD_URL, params={"target_route": "/soulmate/result"})
        resp = await client.get(RESULT_URL)
    assert guard.status_code == 200 and guard.json()["allowed"] is True
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_status", ["ACTIVE", "CANCELLED", "EXPIRED"])
async def test_stale_active_never_extends_past_window_without_new_date(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch, remote_status: str,
):
    sess = await seed_paid_session(
        async_db, provider_status="ACTIVE", paid_through_at=PAST,
        sketch_generation="NOT_STARTED",
    )
    async def get_subscription(self, subscription_id):
        return {"status": remote_status, "billing_info": {"next_billing_time": PAST.isoformat()}}

    async def list_transactions(self, subscription_id, start_time=None, end_time=None):
        return []

    monkeypatch.setattr(PayPalClient, "get_subscription", get_subscription)
    monkeypatch.setattr(PayPalClient, "list_subscription_transactions", list_transactions)
    async with auth_client(sess) as client:
        guard = await client.get(GUARD_URL, params={"target_route": "/soulmate/result"})
        result = await client.get(RESULT_URL)
        sketch = await client.get(SKETCH_URL)
        generate = await client.post(SKETCH_GENERATE_URL)
    assert guard.status_code == 200 and guard.json()["allowed"] is False
    assert result.status_code == sketch.status_code == generate.status_code == 403


@pytest.mark.asyncio
async def test_stale_active_provider_outage_fails_closed(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    sess = await seed_paid_session(async_db, provider_status="ACTIVE", paid_through_at=PAST)

    async def get_subscription(self, subscription_id):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(PayPalClient, "get_subscription", get_subscription)
    async with auth_client(sess) as client:
        guard = await client.get(GUARD_URL, params={"target_route": "/soulmate/result"})
        result = await client.get(RESULT_URL)
    assert guard.status_code == result.status_code == 503


@pytest.mark.asyncio
async def test_completed_artifacts_stay_readable_during_provider_outage(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    sess = await seed_paid_session(
        async_db, provider_status="ACTIVE", paid_through_at=PAST,
        sketch_generation="COMPLETED", report_generation="COMPLETED",
    )

    async def get_subscription(self, subscription_id):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(PayPalClient, "get_subscription", get_subscription)
    async with auth_client(sess) as client:
        for route, url in (
            ("/soulmate/sketch", SKETCH_URL),
            ("/soulmate/report", REPORT_URL),
        ):
            guard = await client.get(GUARD_URL, params={"target_route": route})
            artifact = await client.get(url)
            assert guard.status_code == 200 and guard.json()["allowed"] is True
            assert artifact.status_code == 200
        result = await client.get(RESULT_URL)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_stale_active_incomplete_snapshot_fails_closed(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    sess = await seed_paid_session(async_db, provider_status="ACTIVE", paid_through_at=PAST)

    async def get_subscription(self, subscription_id):
        return {"billing_info": {"next_billing_time": FUTURE.isoformat()}}

    monkeypatch.setattr(PayPalClient, "get_subscription", get_subscription)
    async with auth_client(sess) as client:
        result = await client.get(RESULT_URL)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_stale_active_transaction_check_failure_fails_closed(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    sess = await seed_paid_session(async_db, provider_status="ACTIVE", paid_through_at=PAST)

    async def get_subscription(self, subscription_id):
        return {"status": "ACTIVE", "billing_info": {"next_billing_time": FUTURE.isoformat()}}

    async def list_transactions(self, subscription_id, start_time=None, end_time=None):
        raise PayPalAPIError("transaction API unavailable")

    monkeypatch.setattr(PayPalClient, "get_subscription", get_subscription)
    monkeypatch.setattr(PayPalClient, "list_subscription_transactions", list_transactions)
    async with auth_client(sess) as client:
        result = await client.get(RESULT_URL)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_sketch_generation_denied_after_paid_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db, provider_status="CANCELLED", paid_through_at=PAST
    )
    async with auth_client(sess) as client:
        resp = await client.post(SKETCH_GENERATE_URL)
    assert resp.status_code == 403
    assert "Paid access period has ended" in resp.json()["message"]


@pytest.mark.asyncio
async def test_report_generation_denied_after_paid_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db, provider_status="CANCELLED", paid_through_at=PAST
    )
    async with auth_client(sess) as client:
        resp = await client.post(REPORT_GENERATE_URL)
    assert resp.status_code == 403
    assert "Paid access period has ended" in resp.json()["message"]


@pytest.mark.asyncio
async def test_sketch_read_denied_for_non_completed_state_after_window(
    async_db: AsyncSession,
):
    sess = await seed_paid_session(
        async_db,
        provider_status="CANCELLED",
        paid_through_at=PAST,
        sketch_generation="NOT_STARTED",
    )
    async with auth_client(sess) as client:
        resp = await client.get(SKETCH_URL)
    assert resp.status_code == 403
    assert "Paid access period has ended" in resp.json()["message"]


@pytest.mark.asyncio
async def test_completed_sketch_remains_retrievable_after_window(async_db: AsyncSession):
    """§9.8 retention promise: generated content is kept — a COMPLETED sketch
    stays readable after the window (re-subscription restores full access)."""
    sess = await seed_paid_session(
        async_db,
        provider_status="CANCELLED",
        paid_through_at=PAST,
        sketch_generation="COMPLETED",
    )
    async with auth_client(sess) as client:
        guard = await client.get(GUARD_URL, params={"target_route": "/soulmate/sketch"})
        resp = await client.get(SKETCH_URL)
    assert guard.status_code == 200
    assert guard.json()["allowed"] is True
    assert resp.status_code == 200
    body = resp.json()
    assert body["sketch"]["status"] == "COMPLETED"
    assert body["image_url"]


@pytest.mark.asyncio
async def test_report_read_denied_for_non_completed_state_after_window(
    async_db: AsyncSession,
):
    sess = await seed_paid_session(
        async_db,
        provider_status="CANCELLED",
        paid_through_at=PAST,
        report_generation="NOT_STARTED",
    )
    async with auth_client(sess) as client:
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 403
    assert "Paid access period has ended" in resp.json()["message"]


@pytest.mark.asyncio
async def test_completed_report_remains_retrievable_after_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db,
        provider_status="CANCELLED",
        paid_through_at=PAST,
        report_generation="COMPLETED",
    )
    async with auth_client(sess) as client:
        guard = await client.get(GUARD_URL, params={"target_route": "/soulmate/report"})
        resp = await client.get(REPORT_URL)
    assert guard.status_code == 200
    assert guard.json()["allowed"] is True
    assert resp.status_code == 200
    assert resp.json()["report"]["status"] == "COMPLETED"
    assert resp.json()["content"]["schemaVersion"] == "v1"


@pytest.mark.asyncio
async def test_incomplete_artifact_pages_remain_denied_after_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db, provider_status="CANCELLED", paid_through_at=PAST,
        sketch_generation="NOT_STARTED", report_generation="FAILED",
    )
    async with auth_client(sess) as client:
        for route in ("/soulmate/sketch", "/soulmate/report"):
            guard = await client.get(GUARD_URL, params={"target_route": route})
            assert guard.status_code == 200
            assert guard.json()["allowed"] is False
            assert guard.json()["redirect_to"] == "/soulmate/subscribe"
