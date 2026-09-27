"""
Generation metrics aggregation (DEV-SPEC §18–19, SP-902).

Computes the SP-902 metric families from the durable queue/artifact state
(`ai_generation_jobs` + `soulmate_artifacts`), complementing the raw
`generation_metric` log stream emitted by the worker (see
`app.soulmate.metrics`). Where the stream gives per-event telemetry for
SP-904 alerting, this summary gives the queryable operational numbers:

- success/failure/retry counts per final job state;
- final failure rate over finalized jobs (terminal outcomes only);
- queue latency (enqueue → first claim) — derived from the artifact's
  persisted `generation_started_at` (first-claim time) minus job
  `created_at`;
- generation latency (first claim → durable completion) for COMPLETED
  artifacts.

Idempotency-conflict (duplicate enqueue) counts are NOT computable from the
DB — duplicates converge on the existing job row and leave no durable trace;
the `enqueue_duplicate` metric stream is their only record (documented in
`docs/handoffs/SP-902.md`).

The service is read-only and never exposes customer PII: every statistic is
an aggregate over anonymous job/artifact rows.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.soulmate.services.sketch_generation_service import (
    JOB_COMPLETED,
    JOB_FAILED_PERMANENT,
    JOB_FAILED_RETRYABLE,
    JOB_PROCESSING,
    JOB_QUEUED,
    JOB_TYPE_SKETCH,
)

FINALIZED_STATUSES = (JOB_COMPLETED, JOB_FAILED_RETRYABLE, JOB_FAILED_PERMANENT)


@dataclass(frozen=True)
class LatencyStats:
    """Aggregate latency in whole milliseconds over a window."""

    samples: int
    avg_ms: Optional[int]
    p50_ms: Optional[int]
    p95_ms: Optional[int]
    max_ms: Optional[int]


@dataclass(frozen=True)
class GenerationMetricsSummary:
    """SP-902 metrics for one job type over an enqueue-time window."""

    job_type: str
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    # Counts by final/current job state (jobs whose created_at is in window).
    jobs_enqueued: int
    jobs_queued: int
    jobs_processing: int
    jobs_completed: int
    jobs_failed_retryable: int
    jobs_failed_permanent: int
    # Retry accounting: jobs that consumed more than one attempt, and the
    # total number of consumed retries (attempts beyond the first).
    jobs_retried: int
    retries_total: int
    # Terminal failures / finalized jobs; None when nothing finalized yet.
    final_failure_rate: Optional[float]
    queue_latency: LatencyStats
    generation_latency: LatencyStats


def _latency_stats(values_ms: List[int]) -> LatencyStats:
    """Percentiles use linear interpolation over the sorted sample."""
    if not values_ms:
        return LatencyStats(samples=0, avg_ms=None, p50_ms=None, p95_ms=None, max_ms=None)
    ordered = sorted(values_ms)

    def percentile(fraction: float) -> int:
        if len(ordered) == 1:
            return ordered[0]
        rank = fraction * (len(ordered) - 1)
        low = int(rank)
        high = min(low + 1, len(ordered) - 1)
        weight = rank - low
        return int(round(ordered[low] * (1 - weight) + ordered[high] * weight))

    return LatencyStats(
        samples=len(ordered),
        avg_ms=int(round(sum(ordered) / len(ordered))),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        max_ms=ordered[-1],
    )


def _ms(delta: Optional[object]) -> Optional[int]:
    if delta is None:
        return None
    return max(0, int(delta.total_seconds() * 1000))


class GenerationMetricsService:
    """Read-only aggregation of generation pipeline metrics (SP-902)."""

    @classmethod
    async def summary(
        cls,
        db: AsyncSession,
        *,
        job_type: str = JOB_TYPE_SKETCH,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> GenerationMetricsSummary:
        """
        Aggregate metrics over jobs enqueued in `since..until` (inclusive,
        both optional — None leaves the bound open).
        """
        base = [AIGenerationJob.job_type == job_type]
        if since is not None:
            base.append(AIGenerationJob.created_at >= since)
        if until is not None:
            base.append(AIGenerationJob.created_at <= until)

        status_rows = (
            await db.execute(
                select(AIGenerationJob.status, func.count(AIGenerationJob.id))
                .where(*base)
                .group_by(AIGenerationJob.status)
            )
        ).all()
        counts: Dict[str, int] = {status: count for status, count in status_rows}

        retried_row = (
            await db.execute(
                select(
                    func.count(AIGenerationJob.id),
                    func.coalesce(func.sum(func.greatest(AIGenerationJob.attempt - 1, 0)), 0),
                )
                .where(*base, AIGenerationJob.attempt.is_not(None), AIGenerationJob.attempt > 1)
            )
        ).one()
        jobs_retried, retries_total = int(retried_row[0]), int(retried_row[1])

        # Queue latency: jobs whose artifact recorded a first claim time.
        queue_rows = (
            await db.execute(
                select(SoulmateArtifact.generation_started_at, AIGenerationJob.created_at)
                .select_from(AIGenerationJob)
                .join(SoulmateArtifact, AIGenerationJob.artifact_id == SoulmateArtifact.id)
                .where(
                    *base,
                    SoulmateArtifact.generation_started_at.is_not(None),
                    AIGenerationJob.created_at.is_not(None),
                )
            )
        ).all()
        queue_values = [
            _ms(started - created)
            for started, created in queue_rows
            if started is not None and created is not None
        ]

        # Generation latency: first claim → durable completion (COMPLETED only).
        generation_rows = (
            await db.execute(
                select(SoulmateArtifact.generation_started_at, SoulmateArtifact.completed_at)
                .select_from(AIGenerationJob)
                .join(SoulmateArtifact, AIGenerationJob.artifact_id == SoulmateArtifact.id)
                .where(
                    *base,
                    AIGenerationJob.status == JOB_COMPLETED,
                    SoulmateArtifact.generation_started_at.is_not(None),
                    SoulmateArtifact.completed_at.is_not(None),
                )
            )
        ).all()
        generation_values = [
            _ms(completed - started)
            for started, completed in generation_rows
            if started is not None and completed is not None
        ]

        completed = counts.get(JOB_COMPLETED, 0)
        failed_retryable = counts.get(JOB_FAILED_RETRYABLE, 0)
        failed_permanent = counts.get(JOB_FAILED_PERMANENT, 0)
        finalized = completed + failed_retryable + failed_permanent

        return GenerationMetricsSummary(
            job_type=job_type,
            window_start=since,
            window_end=until,
            jobs_enqueued=sum(counts.values()),
            jobs_queued=counts.get(JOB_QUEUED, 0),
            jobs_processing=counts.get(JOB_PROCESSING, 0),
            jobs_completed=completed,
            jobs_failed_retryable=failed_retryable,
            jobs_failed_permanent=failed_permanent,
            jobs_retried=jobs_retried,
            retries_total=retries_total,
            final_failure_rate=(failed_retryable + failed_permanent) / finalized
            if finalized
            else None,
            queue_latency=_latency_stats([v for v in queue_values if v is not None]),
            generation_latency=_latency_stats([v for v in generation_values if v is not None]),
        )
