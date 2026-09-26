"""
One-email-one-sketch constraint tests (DEV-SPEC §11.5, §14; SP-606; Decisions: ASSET-01, RECOVERY-01).

Acceptance criteria under test:
1. normalized email / linked-user identity is used consistently (canonical DB key:
   email_normalized, enforced by uq_soulmate_one_sketch_per_email);
2. a second eligible session of the same identity converges on (or may trigger) the
   ONE logical sketch generation — it never produces a second owned sketch;
3. the race condition is covered by the DB constraint/transaction.

Read isolation (Decision RECOVERY-01) is asserted too: a non-owning session's
generate response never exposes the owning session's artifact/job state.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token
from app.soulmate.services.sketch_generation_service import (
    JOB_QUEUED,
    SketchGenerationService,
    sketch_idempotency_key,
)
from app.soulmate.services.subscription_service import SubscriptionService
from test_sketch_generation import load_sketch_artifact, seed_generation_session

GENERATE_URL = "/api/soulmate/artifacts/sketch/generate"


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
async def purge_sp606_data():
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


async def count_sketch_rows(db: AsyncSession, email: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(SoulmateArtifact)
            .where(SoulmateArtifact.email_normalized == email, SoulmateArtifact.artifact_type == "SKETCH")
        )
    ).scalar_one()


async def count_identity_jobs(db: AsyncSession, email: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(AIGenerationJob)
            .where(AIGenerationJob.idempotency_key == sketch_idempotency_key(email, "v1"))
        )
    ).scalar_one()


def _unlocked_sketch(session_id, email: str) -> SoulmateArtifact:
    return SoulmateArtifact(
        session_id=session_id,
        email_normalized=email,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=datetime.now(timezone.utc) - timedelta(hours=1),
        generation_status="NOT_STARTED",
    )


# ---------------------------------------------------------------------------
# AC 3: DB constraint / transaction covers the race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_second_sketch_row_for_same_email(async_db):
    """Direct DB-level proof: two SKETCH rows for one normalized email are impossible."""
    email = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_generation_session(async_db, email=email, with_sketch=False)
    sess_b = await seed_generation_session(async_db, email=email, with_sketch=False)

    async_db.add(_unlocked_sketch(sess_a.id, email))
    await async_db.commit()

    async_db.add(_unlocked_sketch(sess_b.id, email))
    with pytest.raises(IntegrityError):
        await async_db.commit()
    await async_db.rollback()

    assert await count_sketch_rows(async_db, email) == 1


@pytest.mark.asyncio
async def test_concurrent_self_heal_creates_exactly_one_sketch_row():
    """Two same-identity sessions self-healing concurrently → one SKETCH row wins."""
    email = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncSessionLocal() as db:
        sess_a = await seed_generation_session(db, email=email, with_sketch=False)
        sess_b = await seed_generation_session(db, email=email, with_sketch=False)
        a_id, b_id = sess_a.id, sess_b.id

    async def ensure(session_id):
        async with AsyncSessionLocal() as db:
            fresh = await db.get(SoulmateSession, session_id)
            await SubscriptionService.ensure_artifacts_for_session(
                session=fresh, paid_at=fresh.subscription_success_at, db=db
            )
            # SP-501 ensure only flushes; the caller owns the commit.
            await db.commit()

    await asyncio.gather(ensure(a_id), ensure(b_id))

    async with AsyncSessionLocal() as db:
        assert await count_sketch_rows(db, email) == 1
        reports = (
            await db.execute(
                select(func.count())
                .select_from(SoulmateArtifact)
                .where(SoulmateArtifact.email_normalized == email, SoulmateArtifact.artifact_type == "REPORT")
            )
        ).scalar_one()
    assert reports == 2  # both sessions keep their own REPORT placeholder


# ---------------------------------------------------------------------------
# AC 2: the second eligible session converges on / triggers the ONE generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_session_trigger_creates_the_single_identity_job(async_db):
    """Identity asset NOT_STARTED (owning session never triggered): the second
    session may drive the one logical generation — still exactly one job."""
    email = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_generation_session(async_db, email=email, with_sketch=False)
    async_db.add(_unlocked_sketch(sess_a.id, email))
    await async_db.commit()

    sess_b = await seed_generation_session(async_db, email=email, with_sketch=False)

    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess_b)
    assert outcome.created is True
    assert outcome.cross_session is True
    assert outcome.job is None  # cross-session outcomes never carry the owning session's job
    assert await count_identity_jobs(async_db, email) == 1  # B drove the single identity job

    # A trigger from the OWNING session converges on the job B created.
    outcome_a = await SketchGenerationService.enqueue_sketch_generation(async_db, sess_a)
    assert outcome_a.created is False
    assert outcome_a.cross_session is False
    assert outcome_a.job is not None
    assert outcome_a.job.status == JOB_QUEUED

    # Another trigger from B also converges (no second job).
    outcome_b2 = await SketchGenerationService.enqueue_sketch_generation(async_db, sess_b)
    assert outcome_b2.created is False

    assert await count_identity_jobs(async_db, email) == 1
    assert await count_sketch_rows(async_db, email) == 1


@pytest.mark.asyncio
async def test_identity_trigger_is_gated_by_asset_unlock_time(async_db):
    """TIME-01 gates on the asset's persisted unlock_at regardless of triggerer."""
    email = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_generation_session(async_db, email=email, with_sketch=False)
    locked = _unlocked_sketch(sess_a.id, email)
    locked.unlock_at = datetime.now(timezone.utc) + timedelta(hours=12)
    async_db.add(locked)
    await async_db.commit()
    sess_b = await seed_generation_session(async_db, email=email, with_sketch=False)

    from app.core.errors import LockedAssetError

    with pytest.raises(LockedAssetError):
        await SketchGenerationService.enqueue_sketch_generation(async_db, sess_b)
    assert await count_identity_jobs(async_db, email) == 0


@pytest.mark.asyncio
async def test_completed_identity_asset_never_regenerated_from_second_session(async_db):
    email = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_generation_session(async_db, email=email, sketch_generation="COMPLETED")
    artifact = await load_sketch_artifact(async_db, sess_a.id)
    async_db.add(
        AIGenerationJob(
            artifact_id=artifact.id,
            job_type="SOULMATE_SKETCH",
            idempotency_key=sketch_idempotency_key(email, "v1"),
            status="COMPLETED",
        )
    )
    await async_db.commit()

    sess_b = await seed_generation_session(async_db, email=email, with_sketch=False)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess_b)

    assert outcome.created is False
    assert outcome.cross_session is True
    assert outcome.job is None  # owning session's job state is not exposed
    assert await count_identity_jobs(async_db, email) == 1
    assert await count_sketch_rows(async_db, email) == 1


# ---------------------------------------------------------------------------
# AC 1: normalized email identity used consistently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_key_uses_normalized_email_not_display_email(async_db):
    """Different display casing, same normalized email → same identity."""
    normalized = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_generation_session(
        async_db, email=normalized, with_sketch=False, display_email=normalized.upper()
    )
    async_db.add(_unlocked_sketch(sess_a.id, normalized))
    await async_db.commit()

    sess_b = await seed_generation_session(async_db, email=normalized, with_sketch=False)
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess_b)

    assert outcome.cross_session is True
    assert outcome.created is True
    assert await count_identity_jobs(async_db, normalized) == 1

    # The owning session (same identity, display email cased differently) converges.
    outcome_a = await SketchGenerationService.enqueue_sketch_generation(async_db, sess_a)
    assert outcome_a.job is not None
    assert outcome_a.job.idempotency_key == sketch_idempotency_key(normalized, "v1")


# ---------------------------------------------------------------------------
# API-level read isolation (RECOVERY-01): no cross-session state leaks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_response_for_second_session_stays_session_scoped(async_db):
    email = f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_generation_session(async_db, email=email, sketch_generation="COMPLETED")
    artifact = await load_sketch_artifact(async_db, sess_a.id)
    async_db.add(
        AIGenerationJob(
            artifact_id=artifact.id,
            job_type="SOULMATE_SKETCH",
            idempotency_key=sketch_idempotency_key(email, "v1"),
            status="COMPLETED",
        )
    )
    await async_db.commit()

    sess_b = await seed_generation_session(async_db, email=email, with_sketch=False)
    token_b = generate_session_token(sess_b.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_b)
        resp = await client.post(GENERATE_URL)

    assert resp.status_code == 200
    data = resp.json()
    # Session-scoped view: session B owns no sketch row (RECOVERY-01 isolation).
    assert data["sketch"]["unlock_at"] is None
    assert data["sketch"]["status"] == "LOCKED"
    # The owning session's job state is never exposed to the second session.
    assert data["job_status"] is None
