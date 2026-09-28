"""SP-905 support lookup authorization, scoping, and response privacy checks."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app


SUPPORT_KEY = "sp905-test-support-key-longer-than-32-characters"


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


async def seed_support_case(
    db: AsyncSession,
    *,
    email: str,
    payment_id: str,
) -> tuple[SoulmateSession, Subscription, SubscriptionPayment, SoulmateArtifact, AIGenerationJob]:
    now = datetime.now(timezone.utc)
    session = SoulmateSession(
        public_id=f"ses_{uuid.uuid4().hex}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=email,
        email_normalized=email.strip().lower(),
        email_captured_at=now - timedelta(hours=3),
        quiz_completed_at=now - timedelta(hours=4),
        subscription_success_at=now - timedelta(hours=2),
    )
    db.add(session)
    await db.flush()

    subscription = Subscription(
        session_id=session.id,
        provider="paypal",
        provider_subscription_id=f"I-SP905-{uuid.uuid4().hex}",
        provider_plan_id="test-plan",
        provider_status="ACTIVE",
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        first_payment_at=now - timedelta(hours=2),
        paid_through_at=now + timedelta(days=25),
    )
    db.add(subscription)
    await db.flush()

    payment = SubscriptionPayment(
        subscription_id=subscription.id,
        provider_payment_id=payment_id,
        provider_event_id=f"WH-SP905-{uuid.uuid4().hex}",
        cycle_no=1,
        amount=Decimal("19.00"),
        currency="USD",
        status="COMPLETED",
        paid_at=now - timedelta(hours=2),
        raw_json={"provider_secret_marker": "raw-provider-secret-must-not-leak"},
    )
    artifact = SoulmateArtifact(
        session_id=session.id,
        email_normalized=email.strip().lower(),
        artifact_type="SKETCH",
        unlock_at=now - timedelta(hours=1),
        generation_status="COMPLETED",
        input_json={"private_input_marker": "private-input-must-not-leak"},
        content_json={"private_content_marker": "private-content-must-not-leak"},
        storage_key="private/storage/key-must-not-leak",
        provider_request_id="provider-request-must-not-leak",
        attempt_count=1,
        generation_started_at=now - timedelta(minutes=20),
        completed_at=now - timedelta(minutes=10),
    )
    db.add_all([payment, artifact])
    await db.flush()

    job = AIGenerationJob(
        artifact_id=artifact.id,
        job_type="SKETCH_GENERATION",
        idempotency_key=f"sp905:{uuid.uuid4().hex}",
        status="COMPLETED",
        attempt=1,
        error_json={"private_job_error_marker": "job-error-must-not-leak"},
    )
    db.add(job)
    await db.commit()
    await db.refresh(session)
    await db.refresh(subscription)
    await db.refresh(payment)
    await db.refresh(artifact)
    await db.refresh(job)
    return session, subscription, payment, artifact, job


def support_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Support-Key": SUPPORT_KEY},
    )


@pytest.mark.asyncio
async def test_lookup_accepts_each_exact_key_and_returns_status_only(async_db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "support_api_key", SUPPORT_KEY)
    email = f"SP905-{uuid.uuid4().hex[:10]}@example.com"
    session, subscription, payment, artifact, job = await seed_support_case(
        async_db,
        email=email,
        payment_id=f"CAP-SP905-{uuid.uuid4().hex}",
    )
    keys = [
        {"session_id": str(session.id)},
        {"session_id": session.public_id},
        {"email": f"  {email.upper()}  "},
        {"paypal_subscription_id": subscription.provider_subscription_id},
        {"provider_payment_id": payment.provider_payment_id},
    ]

    async with support_client() as client:
        responses = [await client.post("/api/soulmate/support/lookup", json=key) for key in keys]

    assert all(response.status_code == 200 for response in responses)
    for response in responses:
        data = response.json()
        assert data["session"]["id"] == str(session.id)
        assert data["session"]["public_id"] == session.public_id
        assert data["payments"][0]["provider_payment_id"] == payment.provider_payment_id
        assert data["artifacts"][0]["id"] == str(artifact.id)
        assert data["jobs"][0]["id"] == str(job.id)
        assert data["timeline"]
        assert data["timeline_history_complete"] is False
        assert [event["occurred_at"] for event in data["timeline"]] == sorted(
            event["occurred_at"] for event in data["timeline"]
        )
        for protected_value in (
            email,
            email.lower(),
            "raw_json",
            "customer_email",
            "provider_event_id",
            "provider_secret_marker",
            "raw-provider-secret-must-not-leak",
            "private_input_marker",
            "private_content_marker",
            "private/storage/key-must-not-leak",
            "provider-request-must-not-leak",
            "private_job_error_marker",
        ):
            assert protected_value not in response.text


@pytest.mark.asyncio
async def test_timeline_separates_historical_events_from_current_status_snapshots(
    async_db: AsyncSession, monkeypatch
):
    monkeypatch.setattr(settings, "support_api_key", SUPPORT_KEY)
    email = f"SP905-timeline-{uuid.uuid4().hex[:8]}@example.com"
    session, subscription, payment, artifact, job = await seed_support_case(
        async_db,
        email=email,
        payment_id=f"CAP-SP905-TIMELINE-{uuid.uuid4().hex}",
    )

    snapshot_at = datetime.now(timezone.utc)
    subscription.provider_status = "CANCELLED"
    subscription.provider_status_updated_at = snapshot_at - timedelta(minutes=1)
    subscription.cancelled_at = snapshot_at - timedelta(minutes=1)
    payment.status = "REFUNDED"
    payment.refunded_at = snapshot_at - timedelta(seconds=30)
    job.status = "FAILED"
    job.updated_at = snapshot_at - timedelta(seconds=10)
    await async_db.commit()

    async with support_client() as client:
        response = await client.post(
            "/api/soulmate/support/lookup",
            json={"session_id": str(session.id)},
        )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["timeline_history_complete"] is False
    events = response_data["timeline"]

    def event_for(event_type: str, entity_id: uuid.UUID) -> dict:
        return next(
            event
            for event in events
            if event["event_type"] == event_type and event["entity_id"] == str(entity_id)
        )

    # Creation/recording events do not inherit a state read at lookup time.
    assert event_for("session_created", session.id)["status"] is None
    assert not any(event["event_type"] == "session_status" for event in events)
    assert event_for("subscription_created", subscription.id)["status"] is None
    assert event_for("payment_recorded", payment.id)["status"] is None
    assert event_for("artifact_created", artifact.id)["status"] is None
    assert event_for("generation_job_created", job.id)["status"] is None

    # Status transitions carry a status only when the persisted timestamp proves it.
    cancelled = event_for("subscription_cancelled", subscription.id)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["status_context"] == "at_event"
    paid = event_for("payment_paid", payment.id)
    assert paid["status"] == "COMPLETED"
    assert paid["status_context"] == "at_event"

    # Mutable current values are labeled as snapshots, never as past events.
    snapshots = {
        event["entity_id"]: event
        for event in events
        if event["event_type"] == "current_status_snapshot"
    }
    assert snapshots[str(session.id)]["status"] == session.status
    assert snapshots[str(subscription.id)]["status"] == "CANCELLED"
    assert snapshots[str(payment.id)]["status"] == "REFUNDED"
    assert snapshots[str(job.id)]["status"] == "FAILED"
    assert all(event["status_context"] == "current_snapshot" for event in snapshots.values())


@pytest.mark.asyncio
async def test_lookup_by_payment_does_not_include_another_session(async_db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "support_api_key", SUPPORT_KEY)
    target, _, payment, _, _ = await seed_support_case(
        async_db,
        email=f"target-{uuid.uuid4().hex[:8]}@example.com",
        payment_id=f"CAP-TARGET-{uuid.uuid4().hex}",
    )
    unrelated, _, other_payment, _, _ = await seed_support_case(
        async_db,
        email=f"unrelated-{uuid.uuid4().hex[:8]}@example.com",
        payment_id=f"CAP-OTHER-{uuid.uuid4().hex}",
    )

    async with support_client() as client:
        response = await client.post(
            "/api/soulmate/support/lookup",
            json={"provider_payment_id": payment.provider_payment_id},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session"]["id"] == str(target.id)
    assert all(item["provider_payment_id"] != other_payment.provider_payment_id for item in data["payments"])
    assert str(unrelated.id) not in response.text
    assert unrelated.public_id not in response.text


@pytest.mark.asyncio
async def test_lookup_requires_configured_key_and_one_identifier(async_db: AsyncSession, monkeypatch, caplog):
    monkeypatch.setattr(settings, "support_api_key", None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        disabled = await client.post(
            "/api/soulmate/support/lookup",
            json={"session_id": "missing"},
            headers={"X-Support-Key": settings.session_secret_key},
        )
    assert disabled.status_code == 503

    monkeypatch.setattr(settings, "support_api_key", settings.session_secret_key)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Support-Key": settings.session_secret_key},
    ) as client:
        reused = await client.post("/api/soulmate/support/lookup", json={"session_id": "missing"})
    assert reused.status_code == 503

    monkeypatch.setattr(settings, "support_api_key", SUPPORT_KEY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post("/api/soulmate/support/lookup", json={"session_id": "missing"})
        wrong = await client.post(
            "/api/soulmate/support/lookup",
            json={"session_id": "missing"},
            headers={"X-Support-Key": "wrong"},
        )
    assert missing.status_code == 403
    assert wrong.status_code == 403

    private_email = f"invalid-shape-{uuid.uuid4().hex[:8]}@example.com"
    async with support_client() as client:
        ambiguous_request = await client.post(
            "/api/soulmate/support/lookup",
            json={"session_id": "missing", "email": private_email},
        )
        broad_request = await client.post("/api/soulmate/support/lookup", json={})
    assert ambiguous_request.status_code == 422
    assert broad_request.status_code == 422
    assert private_email not in ambiguous_request.text
    assert private_email not in caplog.text


@pytest.mark.asyncio
async def test_email_lookup_fails_closed_when_multiple_sessions_match(async_db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "support_api_key", SUPPORT_KEY)
    email = f"shared-{uuid.uuid4().hex[:8]}@example.com"
    first, *_ = await seed_support_case(async_db, email=email, payment_id=f"CAP-A-{uuid.uuid4().hex}")
    second = SoulmateSession(
        public_id=f"ses_{uuid.uuid4().hex}",
        quiz_version="soulmate-quiz-v1",
        status="EMAIL_CAPTURED",
        current_step="subscribe",
        email=email,
        email_normalized=email.lower(),
    )
    async_db.add(second)
    await async_db.commit()
    await async_db.refresh(second)

    async with support_client() as client:
        response = await client.post("/api/soulmate/support/lookup", json={"email": email})

    assert response.status_code == 409
    assert email not in response.text
    assert str(first.id) not in response.text
    assert str(second.id) not in response.text
