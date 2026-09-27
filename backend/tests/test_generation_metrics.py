"""
Generation metrics tests (DEV-SPEC §18–19, SP-902).

Acceptance criteria under test:
1. Metric stream: the §19.1 structured-log stream carries the SP-902 metrics
   (enqueue created/duplicate, queue latency, success, retry, final failure,
   user retry, stale reclaim) with allowlisted fields only.
2. DB aggregation: `GenerationMetricsService.summary` computes counts, retry
   volume, final failure rate, and queue/generation latency statistics from
   the durable job/artifact state.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.domain.sketch_models import SketchProviderError
from app.soulmate.metrics import (
    GENERATION_METRIC_EVENT,
    GENERATION_METRIC_FIELDS,
    record_generation_metric,
)
from app.soulmate.services.generation_metrics_service import GenerationMetricsService
from app.soulmate.services.sketch_generation_service import (
    JOB_FAILED_PERMANENT,
    JOB_FAILED_RETRYABLE,
    SketchGenerationService,
)

pytestmark = pytest.mark.asyncio


def metric_records(caplog):
    """Capture generation_metric records as (metric, fields, job_id, session_id)."""
    out = []
    for record in caplog.records:
        if getattr(record, "event_type", None) != GENERATION_METRIC_EVENT:
            continue
        data = getattr(record, "extra_data", None) or {}
        out.append((data.get("metric"), data, getattr(record, "job_id", None), getattr(record, "session_id", None)))
    return out


def of_metric(records, name):
    return [r for r in records if r[0] == name]


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
async def purge_sp902_data():
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp902_%"))
        await db.execute(
            delete(AIGenerationJob).where(
                AIGenerationJob.artifact_id.in_(
                    select(SoulmateArtifact.id).where(SoulmateArtifact.session_id.in_(sess_ids))
                )
            )
        )
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp902_%")))
        await db.commit()


# Reuse the SP-603 seeding/fakes (identical worker inputs; isolated email prefix).
from test_sketch_generation import (  # noqa: E402
    FakeProvider,
    RecordingSink,
    seed_generation_session,
)


# ---------------------------------------------------------------------------
# Metric stream schema
# ---------------------------------------------------------------------------


async def test_metric_emitter_enforces_schema():
    assert "generation_final_failure" in GENERATION_METRIC_FIELDS
    assert "queue_latency_ms" in GENERATION_METRIC_FIELDS


async def test_unknown_metric_and_fields_dropped(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    record_generation_metric("not_a_metric", fields={"job_type": "X"})
    record_generation_metric("generation_success", fields={"job_type": "X", "pirate": "arr"})
    record_generation_metric("generation_success", fields={"job_type": "SOULMATE_SKETCH"})
    emitted = metric_records(caplog)
    # The unknown metric is dropped entirely; the non-catalog field is dropped
    # but the remaining valid fields still emit.
    assert [m for m, *_ in emitted] == ["generation_success", "generation_success"]
    assert emitted[0][1] == {"metric": "generation_success", "job_type": "X"}
    assert emitted[1][1] == {"metric": "generation_success", "job_type": "SOULMATE_SKETCH"}


# ---------------------------------------------------------------------------
# Emission points along the worker lifecycle
# ---------------------------------------------------------------------------


async def test_success_run_emits_enqueue_queue_latency_and_success(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    assert outcome.created is True

    status = await SketchGenerationService.process_next_queued_job(
        FakeProvider(), RecordingSink(), job_id=outcome.job.id
    )
    assert status == "COMPLETED"

    records = metric_records(caplog)
    created = of_metric(records, "enqueue_created")
    assert len(created) == 1
    assert created[0][1]["job_type"] == "SOULMATE_SKETCH"

    queue_latency = of_metric(records, "queue_latency_ms")
    assert len(queue_latency) == 1
    assert queue_latency[0][1]["attempt"] == 1
    assert queue_latency[0][1]["latency_ms"] >= 0
    assert queue_latency[0][2] == str(outcome.job.id)

    success = of_metric(records, "generation_success")
    assert len(success) == 1
    assert success[0][1]["attempts"] == 1
    assert success[0][1]["latency_ms"] >= 0


async def test_duplicate_enqueue_emits_idempotency_metric(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    first = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    assert first.created is True
    second = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    assert second.created is False

    assert len(of_metric(metric_records(caplog), "enqueue_created")) == 1
    duplicates = of_metric(metric_records(caplog), "enqueue_duplicate")
    assert len(duplicates) == 1
    assert duplicates[0][2] == str(first.job.id)


async def test_retryable_failure_emits_retry_metric_then_final_failure(async_db, caplog, monkeypatch):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    original_attempts = settings.job_retry_max_attempts
    monkeypatch.setattr(settings, "job_retry_max_attempts", 1)

    sess = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    # Attempt 1 with a retryable error and a 1-attempt budget: terminal.
    provider = FakeProvider(error=SketchProviderError("timeout", retryable=True))
    status = await SketchGenerationService.process_next_queued_job(
        provider, RecordingSink(), job_id=outcome.job.id
    )
    assert status == JOB_FAILED_RETRYABLE
    records = metric_records(caplog)
    # No retry metric: the budget was already exhausted at the first claim.
    assert of_metric(records, "generation_retry") == []
    failures = of_metric(records, "generation_final_failure")
    assert len(failures) == 1
    assert failures[0][1]["attempts"] == 1
    assert failures[0][1]["error_code"] == "PROVIDER_UNAVAILABLE"

    # Explicit user retry of the terminal job emits the user-retry metric.
    caplog.clear()
    # The worker committed in its own session; run the re-enqueue against a
    # fresh session (with its own re-fetched SoulmateSession, matching how the
    # API layer supplies them) so the service sees the terminal job state.
    async with AsyncSessionLocal() as fresh_db:
        fresh_sess = (
            await fresh_db.execute(select(SoulmateSession).where(SoulmateSession.id == sess.id))
        ).scalar_one()
        retry_outcome = await SketchGenerationService.enqueue_sketch_generation(fresh_db, fresh_sess)
    assert retry_outcome.created is False
    user_retries = of_metric(metric_records(caplog), "generation_user_retry")
    assert len(user_retries) == 1
    assert user_retries[0][1]["attempt"] == 1

    # The requeued job is claimable again (SP-902 does not alter that behavior).
    async with AsyncSessionLocal() as check_db:
        refreshed = (
            await check_db.execute(select(AIGenerationJob).where(AIGenerationJob.id == outcome.job.id))
        ).scalar_one()
        assert refreshed.status == "QUEUED"


async def test_permanent_failure_emits_final_failure_without_retry(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    provider = FakeProvider(error=SketchProviderError("quota exhausted", retryable=False))
    status = await SketchGenerationService.process_next_queued_job(
        provider, RecordingSink(), job_id=outcome.job.id
    )
    assert status == JOB_FAILED_PERMANENT
    records = metric_records(caplog)
    assert of_metric(records, "generation_retry") == []
    assert len(of_metric(records, "generation_final_failure")) == 1


async def test_stale_reclaim_emits_count_metric(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)

    # Simulate a worker death: the claim went stale mid-call.
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    job.status = "PROCESSING"
    job.locked_at = datetime.now(timezone.utc) - timedelta(seconds=settings.job_claim_stale_seconds + 30)
    await async_db.commit()

    reclaimed = await SketchGenerationService.reclaim_stale_processing_jobs()
    assert reclaimed >= 1
    reclaims = of_metric(metric_records(caplog), "generation_stale_reclaimed")
    assert len(reclaims) == 1
    assert reclaims[0][1]["count"] >= 1


# ---------------------------------------------------------------------------
# DB aggregation (GenerationMetricsService.summary)
# ---------------------------------------------------------------------------


async def test_summary_counts_rates_and_latencies(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    # The dev database is shared across suites: scope every assertion to a
    # window that opens just before this test's own enqueues.
    window_start = datetime.now(timezone.utc)
    # One successful job.
    ok = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    ok_outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, ok)
    status_ok = await SketchGenerationService.process_next_queued_job(
        FakeProvider(), RecordingSink(), job_id=ok_outcome.job.id
    )
    assert status_ok == "COMPLETED"
    # One permanent-failure job.
    bad = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    bad_outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, bad)
    status_bad = await SketchGenerationService.process_next_queued_job(
        FakeProvider(error=SketchProviderError("quota exhausted", retryable=False)),
        RecordingSink(),
        job_id=bad_outcome.job.id,
    )
    assert status_bad == JOB_FAILED_PERMANENT

    summary = await GenerationMetricsService.summary(
        async_db, job_type="SOULMATE_SKETCH", since=window_start
    )
    assert summary.jobs_enqueued == 2
    assert summary.jobs_completed == 1
    assert summary.jobs_failed_permanent == 1
    assert summary.jobs_queued == 0
    assert summary.final_failure_rate == 0.5
    assert summary.queue_latency.samples == 2
    assert summary.queue_latency.avg_ms >= 0
    assert summary.queue_latency.p50_ms <= summary.queue_latency.max_ms
    # Only the COMPLETED artifact contributes generation latency.
    assert summary.generation_latency.samples == 1
    assert summary.generation_latency.avg_ms >= 0
    assert summary.generation_latency.p50_ms == summary.generation_latency.max_ms
    # No retries occurred in either run.
    assert summary.jobs_retried == 0
    assert summary.retries_total == 0


async def test_summary_window_filters_by_enqueue_time(async_db):
    window_start = datetime.now(timezone.utc)
    ok = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    await SketchGenerationService.enqueue_sketch_generation(async_db, ok)

    # A window covering the enqueue includes the job.
    included = await GenerationMetricsService.summary(
        async_db,
        job_type="SOULMATE_SKETCH",
        since=window_start,
        until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    assert included.jobs_enqueued == 1

    # A window that closed before the enqueue excludes it (safe even on the
    # shared dev DB: no historical job was created in the future).
    excluded = await GenerationMetricsService.summary(
        async_db, job_type="SOULMATE_SKETCH", since=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert excluded.jobs_enqueued == 0
    assert excluded.final_failure_rate is None
    assert excluded.queue_latency.samples == 0
    assert excluded.generation_latency.samples == 0

    # Other job types are not mixed into the window.
    other_type = await GenerationMetricsService.summary(
        async_db, job_type="SOULMATE_REPORT", since=window_start
    )
    assert other_type.jobs_enqueued == 0


async def test_summary_retry_accounting_uses_attempt_column(async_db):
    window_start = datetime.now(timezone.utc)
    ok = await seed_generation_session(async_db, email=f"sp902_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, ok)
    job = await async_db.get(AIGenerationJob, outcome.job.id)
    job.attempt = 3  # as if two retries had been consumed
    await async_db.commit()

    summary = await GenerationMetricsService.summary(
        async_db, job_type="SOULMATE_SKETCH", since=window_start
    )
    assert summary.jobs_retried == 1
    assert summary.retries_total == 2
