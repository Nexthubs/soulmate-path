"""
Sketch generation queue/worker tests (DEV-SPEC §11.3–11.7; SP-603, Decisions: ASSET-01).

Acceptance criteria under test:
1. generation can survive the request lifecycle (enqueue → request ends → worker
   processes the durable job in its own session/transaction);
2. job state is durable enough for retry/observability (§11.6 states, attempt,
   error_json, artifact metadata per §11.3);
3. concurrent enqueue attempts converge on one logical generation (unique
   idempotency key + advisory lock).
"""

import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.sketch_models import SketchGenerationResult, SketchProviderError
from app.soulmate.security import generate_session_token
from app.soulmate.services.profile_service import ProfileService
from app.soulmate.services.sketch_generation_service import (
    JOB_COMPLETED,
    JOB_FAILED_PERMANENT,
    JOB_FAILED_RETRYABLE,
    JOB_QUEUED,
    JOB_PROCESSING,
    LoggingSketchResultSink,
    SketchGenerationService,
    sketch_idempotency_key,
)
from app.soulmate.services.status_service import ArtifactStatusService

GENERATE_URL = "/api/soulmate/artifacts/sketch/generate"


def _valid_answers():
    return {
        "q02": "female",
        "q03": "male",
        "q04": "single",
        "q05": "age_20_30",
        "q06": "asian",
        "q07": "loyalty",
        "q08": "1994-08-25",
        "q09": "fire",
        "q10": "heart",
        "q11": "building_trust",
        "q12": "lack_of_trust",
        "q13": "similar_to_me",
        "q14": "deep_connection",
        "q15": "words_of_affirmation",
        "q16": "deep_and_intimate",
        "q17": "losing_trust",
        "q18": ["building_a_family", "traveling_the_world"],
    }


class FakeProvider:
    """Fake SketchImageProvider — returns canned bytes or raises a canned error."""

    provider_name = "fake"

    def __init__(self, result: SketchGenerationResult | None = None, error: Exception | None = None):
        self.result = result or SketchGenerationResult(
            provider="openai",
            model="gpt-image-2",
            image_bytes=b"fake-sketch-bytes",
            image_format="webp",
            size="1024x1536",
            quality="medium",
            provider_request_id="req_fake_1",
            duration_ms=1234,
        )
        self.error = error
        self.calls = 0

    async def generate_image(self, prompt: str) -> SketchGenerationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert prompt and "{" not in prompt and "}" not in prompt
        return self.result


class RecordingSink:
    """Test sink capturing persisted bytes (durable-storage seam, SP-605 slot)."""

    def __init__(self):
        self.persisted: list = []

    async def persist(self, *, artifact_id, result: SketchGenerationResult):
        self.persisted.append((artifact_id, result))
        return f"soulmate/sketches/{artifact_id}/original.webp"


async def seed_generation_session(
    db: AsyncSession,
    *,
    unlocked: bool = True,
    sketch_generation: str = "NOT_STARTED",
    email: str | None = None,
):
    """Paid session + artifacts + complete profile (the worker's real input)."""
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(hours=1)
    email = email or f"sp603_{uuid.uuid4().hex[:8]}@example.com"

    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=email,
        email_normalized=email,
        subscription_success_at=paid_at,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    db.add(
        Subscription(
            session_id=sess.id,
            provider="paypal",
            provider_subscription_id=f"I-SP603-{uuid.uuid4().hex[:8].upper()}",
            provider_plan_id="P-SOULMATE-INTRO",
            provider_status="ACTIVE",
            currency="USD",
            intro_price=Decimal("19.00"),
            regular_price=Decimal("29.00"),
            first_payment_at=paid_at,
            next_billing_at=now + timedelta(days=30),
        )
    )

    db.add(
        SoulmateArtifact(
            session_id=sess.id,
            email_normalized=email,
            artifact_type="SKETCH",
            artifact_version="v1",
            unlock_at=now - timedelta(hours=1) if unlocked else now + timedelta(hours=12),
            generation_status=sketch_generation,
        )
    )
    db.add(
        SoulmateArtifact(
            session_id=sess.id,
            email_normalized=email,
            artifact_type="REPORT",
            artifact_version="v1",
            unlock_at=now - timedelta(hours=1),
            generation_status="NOT_STARTED",
        )
    )
    await db.commit()

    for code, raw in _valid_answers().items():
        value = raw if isinstance(raw, list) else [raw]
        db.add(
            SoulmateAnswer(
                session_id=sess.id,
                question_code=code,
                answer_json={"values": value} if len(value) > 1 or isinstance(raw, list) else {"value": value[0]},
            )
        )
    await db.commit()
    await db.refresh(sess)
    await ProfileService.sync_profile_for_session(db, sess)
    await db.refresh(sess)
    return sess


async def load_sketch_artifact(db: AsyncSession, session_id) -> SoulmateArtifact:
    stmt = select(SoulmateArtifact).where(
        SoulmateArtifact.session_id == session_id,
        SoulmateArtifact.artifact_type == "SKETCH",
    )
    return (await db.execute(stmt)).scalars().one()


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
async def purge_sp603_data():
    """
    Removes all rows seeded by this module (emails sp603_*) after every test so
    leftover QUEUED jobs can never leak into other tests' global claim scope.
    """
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp603_%"))
        await db.execute(
            delete(AIGenerationJob).where(
                AIGenerationJob.artifact_id.in_(select(SoulmateArtifact.id).where(SoulmateArtifact.session_id.in_(sess_ids)))
            )
        )
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp603_%")))
        await db.commit()


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_creates_queued_job_and_artifact_state(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    assert outcome.created is True
    assert outcome.job is not None
    assert outcome.job.status == JOB_QUEUED
    assert outcome.job.job_type == "SOULMATE_SKETCH"
    assert outcome.job.idempotency_key == sketch_idempotency_key(sess.email_normalized, "v1")
    assert outcome.job.idempotency_key.startswith("sketch:")

    artifact = await load_sketch_artifact(async_db, sess.id)
    assert artifact.generation_status == "QUEUED"


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_per_identity(async_db):
    sess = await seed_generation_session(async_db)
    first = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    second = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    assert first.job.id == second.job.id
    assert second.created is False
    jobs = (
        (await async_db.execute(select(AIGenerationJob).where(AIGenerationJob.artifact_id == first.artifact.id)))
        .scalars()
        .all()
    )
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_concurrent_enqueue_attempts_converge_on_one_job(async_db):
    """AC 3: N concurrent triggers for the same identity → one logical generation."""
    sess = await seed_generation_session(async_db)
    email = sess.email_normalized

    async def enqueue_once():
        async with AsyncSessionLocal() as db:
            fresh = await db.get(SoulmateSession, sess.id)
            return await SketchGenerationService.enqueue_sketch_generation(db, fresh)

    outcomes = await asyncio.gather(*[enqueue_once() for _ in range(10)])

    jobs = (
        (await async_db.execute(select(AIGenerationJob).where(AIGenerationJob.job_type == "SOULMATE_SKETCH")))
        .scalars()
        .all()
    )
    # Exactly one job for this email across all concurrent attempts.
    assert sum(1 for j in jobs if j.idempotency_key == sketch_idempotency_key(email, "v1")) == 1
    assert all(o.job is not None for o in outcomes)


@pytest.mark.asyncio
async def test_enqueue_requires_entitlement(async_db):
    sess = await seed_generation_session(async_db)
    sess.subscription_success_at = None
    await async_db.commit()

    from app.core.errors import ForbiddenOwnershipError

    with pytest.raises(ForbiddenOwnershipError):
        await SketchGenerationService.enqueue_sketch_generation(async_db, sess)


@pytest.mark.asyncio
async def test_enqueue_requires_server_side_unlock(async_db):
    sess = await seed_generation_session(async_db, unlocked=False)

    from app.core.errors import LockedAssetError

    with pytest.raises(LockedAssetError):
        await SketchGenerationService.enqueue_sketch_generation(async_db, sess)


@pytest.mark.asyncio
async def test_enqueue_after_completed_does_not_regenerate(async_db):
    sess = await seed_generation_session(async_db, sketch_generation="COMPLETED")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    assert outcome.job is None
    assert outcome.created is False


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_completes_generation_and_persists_metadata(async_db):
    """AC 1+2: durable job processed after enqueue; §11.3 metadata persisted."""
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    sink = RecordingSink()
    provider = FakeProvider()
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=sink, job_id=outcome.job.id
    )

    assert status == JOB_COMPLETED
    assert provider.calls == 1
    assert len(sink.persisted) == 1

    async with AsyncSessionLocal() as verify_db:
        artifact = await verify_db.get(SoulmateArtifact, outcome.artifact.id)
        job = await verify_db.get(AIGenerationJob, outcome.job.id)

    assert artifact.generation_status == "COMPLETED"
    assert artifact.provider == "openai"
    assert artifact.model == "gpt-image-2"
    assert artifact.prompt_version == "v1"
    assert artifact.input_json == {
        "gender": "male",
        "age_range": "20-30",
        "ethnicity": "Asian",
        "features": "Loyalty",
    }
    assert artifact.provider_request_id == "req_fake_1"
    assert artifact.storage_key is not None
    assert artifact.attempt_count == 1
    assert artifact.completed_at is not None
    assert artifact.generation_started_at is not None

    assert job.status == JOB_COMPLETED
    assert job.attempt == 1


@pytest.mark.asyncio
async def test_worker_records_retryable_failure_observably(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    provider = FakeProvider(
        error=SketchProviderError(
            "OpenAI image generation failed (HTTP 429)",
            retryable=True,
            provider_code="429",
            provider_request_id="req_429",
        )
    )
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id
    )

    assert status == JOB_FAILED_RETRYABLE
    async with AsyncSessionLocal() as verify_db:
        artifact = await verify_db.get(SoulmateArtifact, outcome.artifact.id)
        job = await verify_db.get(AIGenerationJob, outcome.job.id)

    assert artifact.generation_status == "FAILED"
    assert artifact.last_error_code == "PROVIDER_UNAVAILABLE"
    assert artifact.attempt_count == 1
    assert job.status == JOB_FAILED_RETRYABLE
    assert job.attempt == 1
    assert job.error_json["retryable"] is True
    assert job.error_json["provider_code"] == "429"


@pytest.mark.asyncio
async def test_worker_records_permanent_failure(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    provider = FakeProvider(
        error=SketchProviderError(
            "OpenAI image generation failed (HTTP 400): policy",
            retryable=False,
            provider_code="400",
        )
    )
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id
    )

    assert status == JOB_FAILED_PERMANENT
    async with AsyncSessionLocal() as verify_db:
        artifact = await verify_db.get(SoulmateArtifact, outcome.artifact.id)
        job = await verify_db.get(AIGenerationJob, outcome.job.id)

    assert artifact.generation_status == "FAILED"
    assert artifact.last_error_code == "GENERATION_FAILED"
    assert job.status == JOB_FAILED_PERMANENT
    assert job.error_json["retryable"] is False


@pytest.mark.asyncio
async def test_worker_never_claims_processing_or_terminal_jobs(async_db):
    sess = await seed_generation_session(async_db, sketch_generation="QUEUED")
    # Simulate a job already claimed by another worker.
    job = AIGenerationJob(
        artifact_id=(await load_sketch_artifact(async_db, sess.id)).id,
        job_type="SOULMATE_SKETCH",
        idempotency_key=sketch_idempotency_key(sess.email_normalized, "v1"),
        status=JOB_PROCESSING,
    )
    async_db.add(job)
    await async_db.commit()

    processed_status = await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(), sink=RecordingSink(), job_id=job.id
    )
    assert processed_status is None  # nothing claimable


@pytest.mark.asyncio
async def test_worker_missing_profile_fails_permanent(async_db):
    sess = await seed_generation_session(async_db)
    # Remove the profile so generation inputs cannot be established.
    from app.db.models.session import SoulmateProfile

    profile = (
        await async_db.execute(select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id))
    ).scalar_one()
    await async_db.delete(profile)
    await async_db.commit()

    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    status = await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(), sink=RecordingSink()
    )

    assert status == JOB_FAILED_PERMANENT
    async with AsyncSessionLocal() as verify_db:
        artifact = await verify_db.get(SoulmateArtifact, outcome.artifact.id)
    assert artifact.generation_status == "FAILED"


# ---------------------------------------------------------------------------
# API endpoint — survives the request lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_endpoint_enqueues_and_worker_completes_after_request(async_db):
    """AC 1: the request only enqueues; the durable job is processed afterwards."""
    sess = await seed_generation_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.post(GENERATE_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_status"] == "QUEUED"
    assert data["sketch"]["generation"] == "QUEUED"
    assert data["sketch"]["status"] == "GENERATING"

    # Request lifecycle is over here; the worker runs in its own session.
    job = (
        await async_db.execute(
            select(AIGenerationJob).where(
                AIGenerationJob.idempotency_key == sketch_idempotency_key(sess.email_normalized, "v1")
            )
        )
    ).scalar_one()
    status = await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(), sink=RecordingSink(), job_id=job.id
    )
    assert status == JOB_COMPLETED

    async with AsyncSessionLocal() as verify_db:
        artifact = await load_sketch_artifact(verify_db, sess.id)
        statuses = await ArtifactStatusService.get_artifact_statuses(verify_db, sess.id)
    assert artifact.generation_status == "COMPLETED"
    assert statuses.sketch.status == "COMPLETED"


@pytest.mark.asyncio
async def test_generate_endpoint_is_idempotent_and_requires_auth(async_db):
    sess = await seed_generation_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        first = await client.post(GENERATE_URL)
        second = await client.post(GENERATE_URL)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["job_status"] == second.json()["job_status"] == "QUEUED"

    # Anonymous callers are rejected.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        anon = await client.post(GENERATE_URL)
    assert anon.status_code == 403


@pytest.mark.asyncio
async def test_generate_endpoint_rejects_locked_sketch(async_db):
    sess = await seed_generation_session(async_db, unlocked=False)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.post(GENERATE_URL)
    assert resp.status_code == 423
