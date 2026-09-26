"""
12h/24h Artifact Status Derivation (SP-502, DEV-SPEC §10, Decisions: TIME-01).

Acceptance criteria under test:
1. Statuses derive from server time + persisted timestamps only — client clock
   changes cannot grant access (the derivation has no client-time input).
2. LOCKED, READY, GENERATING, COMPLETED, FAILED are distinguishable.
3. Unit tests use an injectable/fake clock.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import SoulmateArtifact
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.domain.artifact_status import (
    ArtifactAvailability,
    ArtifactGeneration,
    ArtifactStatus,
    derive_artifact_status,
    derive_artifact_status_view,
    derive_availability,
    normalize_generation,
)
from app.soulmate.services.status_service import ArtifactStatusService


FIRST_PAYMENT_AT = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
SKETCH_UNLOCK_AT = FIRST_PAYMENT_AT + timedelta(hours=12)
REPORT_UNLOCK_AT = FIRST_PAYMENT_AT + timedelta(hours=24)


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


# ==============================================================================
# Pure derivation tests (injectable fake clock, no DB)
# ==============================================================================


def test_availability_locked_before_unlock_and_unlocked_at_boundary():
    # Strictly before unlock_at -> LOCKED (DEV-SPEC §10.1)
    assert derive_availability(SKETCH_UNLOCK_AT, SKETCH_UNLOCK_AT - timedelta(seconds=1)) == ArtifactAvailability.LOCKED
    # Boundary: now == unlock_at -> UNLOCKED
    assert derive_availability(SKETCH_UNLOCK_AT, SKETCH_UNLOCK_AT) == ArtifactAvailability.UNLOCKED
    assert derive_availability(SKETCH_UNLOCK_AT, SKETCH_UNLOCK_AT + timedelta(hours=5)) == ArtifactAvailability.UNLOCKED


def test_combined_status_distinguishes_all_five_states():
    after_unlock = REPORT_UNLOCK_AT + timedelta(minutes=1)
    # Unlocked + NOT_STARTED -> READY
    assert derive_artifact_status(SKETCH_UNLOCK_AT, "NOT_STARTED", after_unlock) == ArtifactStatus.READY
    # Unlocked + QUEUED/PROCESSING -> GENERATING
    assert derive_artifact_status(SKETCH_UNLOCK_AT, "QUEUED", after_unlock) == ArtifactStatus.GENERATING
    assert derive_artifact_status(SKETCH_UNLOCK_AT, "PROCESSING", after_unlock) == ArtifactStatus.GENERATING
    # Unlocked + COMPLETED -> COMPLETED
    assert derive_artifact_status(SKETCH_UNLOCK_AT, "COMPLETED", after_unlock) == ArtifactStatus.COMPLETED
    # Unlocked + FAILED -> FAILED
    assert derive_artifact_status(SKETCH_UNLOCK_AT, "FAILED", after_unlock) == ArtifactStatus.FAILED
    # Locked -> LOCKED regardless of any generation state (countdown wins, §10.3)
    before_unlock = SKETCH_UNLOCK_AT - timedelta(seconds=1)
    for generation in ("NOT_STARTED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"):
        assert derive_artifact_status(SKETCH_UNLOCK_AT, generation, before_unlock) == ArtifactStatus.LOCKED


def test_unknown_generation_value_fails_closed():
    after_unlock = SKETCH_UNLOCK_AT + timedelta(minutes=1)
    # Corrupt persisted value must never present as READY; fail closed to FAILED (Retry/Support)
    assert normalize_generation("SOMETHING_ELSE") == ArtifactGeneration.FAILED
    assert derive_artifact_status(SKETCH_UNLOCK_AT, "SOMETHING_ELSE", after_unlock) == ArtifactStatus.FAILED
    # Lowercase stored values normalize to the canonical enum
    assert normalize_generation("completed") == ArtifactGeneration.COMPLETED


def test_naive_timestamps_treated_as_utc():
    naive_unlock = SKETCH_UNLOCK_AT.replace(tzinfo=None)
    naive_now = SKETCH_UNLOCK_AT.replace(tzinfo=None) - timedelta(minutes=1)
    aware_now = naive_now.replace(tzinfo=timezone.utc)
    assert derive_availability(naive_unlock, aware_now) == derive_availability(SKETCH_UNLOCK_AT, aware_now)


def test_status_changes_only_through_injected_server_clock():
    """
    Client clock independence (TIME-01): the derivation is a pure function of
    persisted unlock_at + persisted generation + the injected server `now`.
    There is no client-time input; only advancing the server clock changes status.
    """
    generation = "NOT_STARTED"
    view_t0 = derive_artifact_status_view(SKETCH_UNLOCK_AT, generation, FIRST_PAYMENT_AT)
    view_t11h = derive_artifact_status_view(SKETCH_UNLOCK_AT, generation, FIRST_PAYMENT_AT + timedelta(hours=11))
    view_t12h = derive_artifact_status_view(SKETCH_UNLOCK_AT, generation, FIRST_PAYMENT_AT + timedelta(hours=12))
    view_t12h_minus_1s = derive_artifact_status_view(
        SKETCH_UNLOCK_AT, generation, SKETCH_UNLOCK_AT - timedelta(seconds=1)
    )

    assert view_t0.status == ArtifactStatus.LOCKED
    assert view_t11h.status == ArtifactStatus.LOCKED
    assert view_t12h_minus_1s.status == ArtifactStatus.LOCKED
    assert view_t12h.status == ArtifactStatus.READY
    assert view_t12h.unlock_at == SKETCH_UNLOCK_AT
    # The view carries the exact server instant used (frontend calibrates countdown from it)
    assert view_t0.availability == ArtifactAvailability.LOCKED
    assert view_t12h.availability == ArtifactAvailability.UNLOCKED


# ==============================================================================
# Service tests (persisted rows + injectable clock through the service)
# ==============================================================================


async def seed_session_with_artifacts(
    db: AsyncSession,
    sketch_generation: str = "NOT_STARTED",
    report_generation: str = "NOT_STARTED",
    with_artifacts: bool = True,
) -> SoulmateSession:
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=f"sp502_{uuid.uuid4().hex[:8]}@example.com",
        email_normalized=f"sp502_{uuid.uuid4().hex[:8]}@example.com",
        subscription_success_at=FIRST_PAYMENT_AT,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    if with_artifacts:
        db.add(
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=sess.email_normalized,
                artifact_type="SKETCH",
                artifact_version="v1",
                unlock_at=SKETCH_UNLOCK_AT,
                generation_status=sketch_generation,
            )
        )
        db.add(
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=sess.email_normalized,
                artifact_type="REPORT",
                artifact_version="v1",
                unlock_at=REPORT_UNLOCK_AT,
                generation_status=report_generation,
            )
        )
        await db.commit()
    return sess


@pytest.mark.asyncio
async def test_service_derives_12h_24h_progression_with_fake_clock(async_db: AsyncSession):
    sess = await seed_session_with_artifacts(async_db)

    # T0 + 11h: both locked (countdown)
    result = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess.id, now=FIRST_PAYMENT_AT + timedelta(hours=11)
    )
    assert result.server_time == FIRST_PAYMENT_AT + timedelta(hours=11)
    assert result.sketch.status == ArtifactStatus.LOCKED
    assert result.report.status == ArtifactStatus.LOCKED

    # T0 + 12h: sketch unlocked (READY), report still locked
    result = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess.id, now=FIRST_PAYMENT_AT + timedelta(hours=12)
    )
    assert result.sketch.status == ArtifactStatus.READY
    assert result.sketch.unlock_at == SKETCH_UNLOCK_AT
    assert result.report.status == ArtifactStatus.LOCKED
    assert result.report.unlock_at == REPORT_UNLOCK_AT

    # T0 + 24h: both unlocked
    result = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess.id, now=FIRST_PAYMENT_AT + timedelta(hours=24)
    )
    assert result.sketch.status == ArtifactStatus.READY
    assert result.report.status == ArtifactStatus.READY


@pytest.mark.asyncio
async def test_service_distinguishes_generation_states_on_unlocked_artifacts(async_db: AsyncSession):
    sess = await seed_session_with_artifacts(
        async_db, sketch_generation="PROCESSING", report_generation="COMPLETED"
    )
    after_both_unlocks = FIRST_PAYMENT_AT + timedelta(hours=25)

    result = await ArtifactStatusService.get_artifact_statuses(async_db, sess.id, now=after_both_unlocks)
    assert result.sketch.status == ArtifactStatus.GENERATING
    assert result.report.status == ArtifactStatus.COMPLETED


@pytest.mark.asyncio
async def test_service_failed_generation_shows_failed_after_unlock(async_db: AsyncSession):
    sess = await seed_session_with_artifacts(async_db, sketch_generation="FAILED")

    result = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess.id, now=FIRST_PAYMENT_AT + timedelta(hours=13)
    )
    assert result.sketch.status == ArtifactStatus.FAILED
    assert result.report.status == ArtifactStatus.LOCKED


@pytest.mark.asyncio
async def test_service_missing_rows_fail_closed(async_db: AsyncSession):
    sess = await seed_session_with_artifacts(async_db, with_artifacts=False)

    result = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess.id, now=FIRST_PAYMENT_AT + timedelta(hours=48)
    )
    assert result.sketch.unlock_at is None
    assert result.sketch.status == ArtifactStatus.LOCKED
    assert result.report.unlock_at is None
    assert result.report.status == ArtifactStatus.LOCKED


@pytest.mark.asyncio
async def test_service_defaults_to_server_clock_when_now_omitted(async_db: AsyncSession):
    sess = await seed_session_with_artifacts(async_db)

    result = await ArtifactStatusService.get_artifact_statuses(async_db, sess.id)
    # Unlock is in 2026-09-26; a default-clock derivation must not crash and must echo a server instant
    assert result.server_time is not None
    assert result.server_time.tzinfo is not None


# ==============================================================================
# RV-02 C1: contact email cannot authorize cross-session Sketch reads
# ==============================================================================


@pytest.mark.asyncio
async def test_second_session_same_email_cannot_read_other_sessions_sketch(async_db: AsyncSession):
    """
    ASSET-01 uniqueness remains enforced, but contact-email equality cannot
    authorize access to the first session’s Sketch metadata.
    """
    email = f"sp502shared_{uuid.uuid4().hex[:8]}@example.com"
    sess_a = await seed_session_with_artifacts(async_db, sketch_generation="COMPLETED")
    # Force session A and its artifact rows onto the SAME shared email
    sess_a.email_normalized = email
    await async_db.commit()
    a_artifacts = (
        await async_db.execute(select(SoulmateArtifact).where(SoulmateArtifact.session_id == sess_a.id))
    ).scalars().all()
    for artifact in a_artifacts:
        artifact.email_normalized = email
    await async_db.commit()

    sess_b = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=email,
        email_normalized=email,
        subscription_success_at=FIRST_PAYMENT_AT,
    )
    async_db.add(sess_b)
    await async_db.commit()
    await async_db.refresh(sess_b)
    async_db.add(
        SoulmateArtifact(
            session_id=sess_b.id,
            email_normalized=email,
            artifact_type="REPORT",
            artifact_version="v1",
            unlock_at=REPORT_UNLOCK_AT,
            generation_status="NOT_STARTED",
        )
    )
    await async_db.commit()

    # Session B: no own SKETCH row, own REPORT row
    result = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess_b.id, now=FIRST_PAYMENT_AT + timedelta(hours=25), email_normalized=email
    )
    # Unverified email must not reveal session A's timestamps or generation state.
    assert result.sketch.unlock_at is None
    assert result.sketch.generation == ArtifactGeneration.NOT_STARTED
    assert result.sketch.status == ArtifactStatus.LOCKED
    # Report is session B's own row
    assert result.report.unlock_at == REPORT_UNLOCK_AT
    assert result.report.status == ArtifactStatus.READY

    # Both call forms must enforce the same session ownership boundary.
    result_no_email = await ArtifactStatusService.get_artifact_statuses(
        async_db, sess_b.id, now=FIRST_PAYMENT_AT + timedelta(hours=25)
    )
    assert result_no_email.sketch.unlock_at is None
    assert result_no_email.sketch.status == ArtifactStatus.LOCKED
