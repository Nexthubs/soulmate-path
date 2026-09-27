"""
PAID-THROUGH-01 uniform API-layer enforcement tests (Wave 8 audit round 3).

After a known-and-passed paid window (paid_through_at in the past + non-ACTIVE
provider status, judged on the server clock):
- GET /result -> 403 (the aggregate read ends with the window);
- POST /artifacts/sketch/generate and /artifacts/report/generate -> 403
  (generation of new content is a paid benefit);
- GET /artifacts/sketch and /artifacts/report -> 403 for non-COMPLETED states,
  200 for COMPLETED artifacts (§9.8 retention promise: keep what you received);
- ACTIVE subscriptions crossing their recorded cycle end are EXEMPT
  (renewal payment / webhook lag tolerance) -> 200.
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

RESULT_URL = "/api/soulmate/result"
SKETCH_URL = "/api/soulmate/artifacts/sketch"
SKETCH_GENERATE_URL = "/api/soulmate/artifacts/sketch/generate"
REPORT_URL = "/api/soulmate/artifacts/report"
REPORT_GENERATE_URL = "/api/soulmate/artifacts/report/generate"

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
    assert "PAID-THROUGH-01" in resp.json()["message"]


@pytest.mark.asyncio
async def test_result_aggregate_allows_active_subscription_crossing_recorded_date(
    async_db: AsyncSession,
):
    """Wave 8 audit H-2: ACTIVE + crossed date = renewal/webhook lag, not an
    ended entitlement."""
    sess = await seed_paid_session(
        async_db, provider_status="ACTIVE", paid_through_at=PAST
    )
    async with auth_client(sess) as client:
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sketch_generation_denied_after_paid_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db, provider_status="CANCELLED", paid_through_at=PAST
    )
    async with auth_client(sess) as client:
        resp = await client.post(SKETCH_GENERATE_URL)
    assert resp.status_code == 403
    assert "PAID-THROUGH-01" in resp.json()["message"]


@pytest.mark.asyncio
async def test_report_generation_denied_after_paid_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db, provider_status="CANCELLED", paid_through_at=PAST
    )
    async with auth_client(sess) as client:
        resp = await client.post(REPORT_GENERATE_URL)
    assert resp.status_code == 403
    assert "PAID-THROUGH-01" in resp.json()["message"]


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
    assert "PAID-THROUGH-01" in resp.json()["message"]


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
        resp = await client.get(SKETCH_URL)
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
    assert "PAID-THROUGH-01" in resp.json()["message"]


@pytest.mark.asyncio
async def test_completed_report_remains_retrievable_after_window(async_db: AsyncSession):
    sess = await seed_paid_session(
        async_db,
        provider_status="CANCELLED",
        paid_through_at=PAST,
        report_generation="COMPLETED",
    )
    async with auth_client(sess) as client:
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 200
    assert resp.json()["report"]["status"] == "COMPLETED"
