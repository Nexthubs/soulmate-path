"""
Sketch generation retry / idempotency tests (DEV-SPEC §11.4–11.6, §19; SP-604, ASSET-01).

Acceptance criteria under test:
1. transient failures retry with bounded attempts/backoff (§11.6: max 3, exponential);
2. permanent invalid/safety/input failures do not loop forever;
3. a retry never creates a second owned sketch after a success (completion guards);
4. attempt count / final category are stored;
5. concurrency: 20 concurrent triggers for the same eligible identity produce one
   logical asset/generation winner (full stack through POST /artifacts/sketch/generate).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.sketch_models import SketchGenerationResult, SketchProviderError
from app.soulmate.security import generate_session_token
from app.soulmate.services.sketch_generation_service import (
    JOB_COMPLETED,
    JOB_FAILED_PERMANENT,
    JOB_FAILED_RETRYABLE,
    JOB_PROCESSING,
    JOB_QUEUED,
    SketchGenerationService,
    sketch_idempotency_key,
)
from test_sketch_generation import (
    FakeProvider,
    RecordingSink,
    load_sketch_artifact,
    seed_generation_session,
)

GENERATE_URL = "/api/soulmate/artifacts/sketch/generate"


@pytest.fixture(autouse=True)
async def purge_sp604_data():
    """Same purge contract as test_sketch_generation (shared dev DB hygiene)."""
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


def _retryable_error(request_id: str = "req_429") -> SketchProviderError:
    return SketchProviderError(
        "OpenAI image generation failed (HTTP 429): rate limited",
        retryable=True,
        provider_code="429",
        provider_request_id=request_id,
    )


def _permanent_error() -> SketchProviderError:
    return SketchProviderError(
        "OpenAI image generation failed (HTTP 400): content policy violation",
        retryable=False,
        provider_code="400",
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Removes real waiting from backoff assertions (due-ness verified explicitly)."""
    monkeypatch.setattr(settings, "job_retry_base_backoff_seconds", 0.0)


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# AC 1: bounded retries with exponential backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retryable_failures_requeue_with_backoff_until_budget_exhausted(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    provider = FakeProvider(error=_retryable_error())

    # Attempt 1 -> requeued (attempt 1 < 3)
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id
    )
    assert status == JOB_QUEUED
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    await async_db.refresh(job)
    assert job.attempt == 1
    assert job.run_after is not None

    # Attempt 2 -> requeued again (attempt 2 < 3)
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id, now=job.run_after + timedelta(seconds=1)
    )
    assert status == JOB_QUEUED
    await async_db.refresh(job)
    assert job.attempt == 2

    # Attempt 3 -> budget exhausted -> terminal FAILED_RETRYABLE (final category stored)
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id, now=job.run_after + timedelta(seconds=1)
    )
    assert status == JOB_FAILED_RETRYABLE
    await async_db.refresh(job)
    artifact = await load_sketch_artifact(async_db, sess.id)
    await async_db.refresh(artifact)

    assert job.status == JOB_FAILED_RETRYABLE
    assert job.attempt == settings.job_retry_max_attempts == 3
    assert job.error_json["retryable"] is True
    assert job.error_json["provider_code"] == "429"
    assert artifact.generation_status == "FAILED"
    assert artifact.last_error_code == "PROVIDER_UNAVAILABLE"
    assert artifact.attempt_count == 3

    # The terminal job is never re-claimed.
    assert provider.calls == 3
    assert await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id
    ) is None


@pytest.mark.asyncio
async def test_backoff_is_exponential(monkeypatch):
    monkeypatch.setattr(settings, "job_retry_base_backoff_seconds", 5.0)
    from app.soulmate.services.sketch_generation_service import retry_backoff_seconds

    assert retry_backoff_seconds(1) == 5.0
    assert retry_backoff_seconds(2) == 10.0
    assert retry_backoff_seconds(3) == 20.0


# ---------------------------------------------------------------------------
# AC 2: permanent failures never loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permanent_failure_terminates_immediately_and_never_requeues(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    status = await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(error=_permanent_error()), sink=RecordingSink(), job_id=outcome.job.id
    )

    assert status == JOB_FAILED_PERMANENT
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    artifact = await load_sketch_artifact(async_db, sess.id)
    await async_db.refresh(job)
    await async_db.refresh(artifact)

    assert job.status == JOB_FAILED_PERMANENT
    assert job.attempt == 1
    assert job.run_after is None
    assert job.error_json["retryable"] is False
    assert artifact.generation_status == "FAILED"
    assert artifact.last_error_code == "GENERATION_FAILED"

    # Never re-claimed, no loop.
    assert await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(), sink=RecordingSink(), job_id=outcome.job.id
    ) is None


# ---------------------------------------------------------------------------
# AC 3: a retry never creates a second owned sketch after a success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_artifact_short_circuits_without_provider_call(async_db):
    """A (re)queued job whose artifact already completed must not re-call the provider."""
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    artifact = await load_sketch_artifact(async_db, sess.id)
    artifact.generation_status = "COMPLETED"
    artifact.completed_at = datetime.now(timezone.utc)
    await async_db.commit()

    provider = FakeProvider()
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=outcome.job.id
    )

    # Job finalizes without a second generation; the owned artifact is untouched.
    assert provider.calls == 0
    assert status == JOB_COMPLETED  # short-circuited inside the claim transaction
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    await async_db.refresh(job)
    assert job.status == JOB_COMPLETED
    await async_db.refresh(artifact)
    assert artifact.generation_status == "COMPLETED"


@pytest.mark.asyncio
async def test_finalize_discards_result_when_claim_was_reclaimed(async_db):
    """A result arriving after its claim was reclaimed must not overwrite state."""
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    # Simulate: the claim was stale-reclaimed while a zombie worker still finished.
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    job.status = JOB_QUEUED
    job.run_after = datetime.now(timezone.utc) + timedelta(seconds=30)
    await async_db.commit()

    status = await SketchGenerationService._finalize_success(
        job_id=outcome.job.id,
        artifact_id=outcome.artifact.id,
        rendered=None,
        result=SketchGenerationResult(
            provider="openai",
            model="gpt-image-2",
            image_bytes=b"zombie-bytes",
            image_format="webp",
            size="1024x1536",
            quality="medium",
            provider_request_id="req_zombie",
            duration_ms=10,
        ),
        storage_key="soulmate/sketches/zombie/original.webp",
    )

    assert status == JOB_QUEUED  # discarded, no state change
    artifact = await load_sketch_artifact(async_db, sess.id)
    assert artifact.generation_status == "QUEUED"
    assert artifact.provider_request_id is None  # zombie result never persisted


# ---------------------------------------------------------------------------
# Stale-claim reclamation (worker death mid-call) — bounded like ordinary retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_claims_are_reclaimed_with_attempt_accounting(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    stale = datetime.now(timezone.utc) - timedelta(seconds=settings.job_claim_stale_seconds + 60)

    # Simulate a worker that died mid-call (claim committed, process never finished).
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    job.status = JOB_PROCESSING
    job.locked_at = stale
    artifact = await load_sketch_artifact(async_db, sess.id)
    artifact.generation_status = "PROCESSING"
    await async_db.commit()

    reclaimed = await SketchGenerationService.reclaim_stale_processing_jobs()
    assert reclaimed == 1
    await async_db.refresh(job)
    assert job.status == JOB_QUEUED
    assert job.attempt == 1
    assert job.run_after is not None
    assert job.error_json["error_code"] == "CLAIM_STALE"

    # Fresh claims must not run before run_after (backoff honored; explicit clock).
    assert await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(), sink=RecordingSink(), job_id=outcome.job.id, now=job.run_after - timedelta(seconds=1)
    ) is None


@pytest.mark.asyncio
async def test_stale_reclaim_budget_exhaustion_terminates(async_db):
    sess = await seed_generation_session(async_db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    stale = datetime.now(timezone.utc) - timedelta(seconds=settings.job_claim_stale_seconds + 60)

    job = await async_db.get(AIGenerationJob, outcome.job.id)
    artifact = await load_sketch_artifact(async_db, sess.id)
    for attempt in range(settings.job_retry_max_attempts):
        job.status = JOB_PROCESSING
        job.locked_at = stale
        await async_db.commit()
        await async_db.refresh(job)
        await SketchGenerationService.reclaim_stale_processing_jobs()
        await async_db.refresh(job)

    assert job.status == JOB_FAILED_RETRYABLE
    assert job.attempt == settings.job_retry_max_attempts
    await async_db.refresh(artifact)
    assert artifact.generation_status == "FAILED"
    assert artifact.last_error_code == "CLAIM_STALE"
    assert artifact.attempt_count == settings.job_retry_max_attempts


# ---------------------------------------------------------------------------
# AC 5: 20 concurrent triggers -> one logical asset/generation winner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_twenty_concurrent_triggers_produce_one_generation(async_db):
    sess = await seed_generation_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        responses = await asyncio.gather(*[client.post(GENERATE_URL) for _ in range(20)])

    assert all(r.status_code == 200 for r in responses)
    payloads = [r.json() for r in responses]
    # Every trigger sees the same logical generation state.
    assert all(p["job_status"] == "QUEUED" for p in payloads)
    assert all(p["sketch"]["generation"] == "QUEUED" for p in payloads)

    jobs = (
        await async_db.execute(
            select(AIGenerationJob).where(
                AIGenerationJob.idempotency_key == sketch_idempotency_key(sess.email_normalized, "v1")
            )
        )
    ).scalars().all()
    assert len(jobs) == 1  # one logical generation winner

    # The single winner generates exactly once; nothing else creates a second asset.
    provider = FakeProvider()
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(), job_id=jobs[0].id
    )
    assert status == JOB_COMPLETED
    assert provider.calls == 1

    artifact = await load_sketch_artifact(async_db, sess.id)
    await async_db.refresh(artifact)
    assert artifact.generation_status == "COMPLETED"
    assert artifact.attempt_count == 1

    # Post-success retries/triggers never generate again.
    assert await SketchGenerationService.process_next_queued_job(
        provider=FakeProvider(), sink=RecordingSink(), job_id=jobs[0].id
    ) is None
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        again = await client.post(GENERATE_URL)
    assert again.status_code == 200
    assert again.json()["job_status"] is None  # completed; no job attached
    assert again.json()["sketch"]["status"] == "COMPLETED"
    jobs_after = (
        await async_db.execute(
            select(AIGenerationJob).where(
                AIGenerationJob.idempotency_key == sketch_idempotency_key(sess.email_normalized, "v1")
            )
        )
    ).scalars().all()
    assert len(jobs_after) == 1
