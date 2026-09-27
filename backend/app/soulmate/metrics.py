"""Central generation-metrics emitter (DEV-SPEC §18–19, SP-902).

Operational metrics for the generation pipeline (queue/worker, SP-603/604) —
distinct from the §18.1 funnel analytics stream in `app.soulmate.analytics`:
this is the §19 observability stream that SP-904 alerts will key on.

Every metric is emitted through the §19.1 structured log pipeline as a single
stable `event_type="generation_metric"` record with the metric name and its
dimensions/values in `extra_data`. Metric fields are allowlisted in code, so
the stream schema is explicit and a rename cannot silently leak a value.

Available metrics:
- `enqueue_created` / `enqueue_duplicate` — idempotency outcomes at enqueue
  (duplicates are NOT durably persisted anywhere, so the log stream is the
  only record of idempotency conflicts);
- `queue_latency_ms` — enqueue → claim, at successful claim time;
- `generation_success` — winning-attempt claim → durable completion;
- `generation_retry` — retryable failure requeued with backoff;
- `generation_final_failure` — terminal (attempt budget exhausted / permanent);
- `generation_user_retry` — explicit user requeue of a FAILED_RETRYABLE job;
- `generation_stale_reclaimed` — count of stale PROCESSING claims reclaimed.

The emitter is best-effort: a metrics failure must never break generation.
"""

import logging
from typing import Any, Dict, Optional

from app.core.logging import log_event

logger = logging.getLogger(__name__)

#: Single stable event_type for the generation metrics stream.
GENERATION_METRIC_EVENT = "generation_metric"

#: Metric name -> allowed extra_data fields. The schema lives here once.
GENERATION_METRIC_FIELDS: Dict[str, frozenset] = {
    "enqueue_created": frozenset({"job_type"}),
    "enqueue_duplicate": frozenset({"job_type"}),
    "queue_latency_ms": frozenset({"job_type", "latency_ms", "attempt"}),
    "generation_success": frozenset({"job_type", "latency_ms", "attempts"}),
    "generation_retry": frozenset({"job_type", "error_code", "attempt", "backoff_seconds"}),
    "generation_final_failure": frozenset({"job_type", "error_code", "attempts"}),
    "generation_user_retry": frozenset({"job_type", "attempt"}),
    "generation_stale_reclaimed": frozenset({"job_type", "count"}),
}


def record_generation_metric(
    metric: str,
    *,
    job_id: Optional[Any] = None,
    artifact_id: Optional[Any] = None,
    session_id: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit one generation metric into the §19.1 structured log stream.

    Fields outside the metric's allowlist are dropped (schema discipline);
    the emission is best-effort and never raises into business code.
    """
    try:
        allowed = GENERATION_METRIC_FIELDS.get(metric)
        if allowed is None:
            logger.warning("Generation metrics: unknown metric %r dropped", metric)
            return
        safe_fields: Dict[str, Any] = {}
        for key, value in (fields or {}).items():
            if key not in allowed:
                logger.warning(
                    "Generation metrics: dropped non-catalog field %r on %s", key, metric
                )
                continue
            if value is None:
                continue
            safe_fields[key] = value
        log_event(
            event_type=GENERATION_METRIC_EVENT,
            message=f"Generation metric: {metric}",
            session_id=session_id,
            artifact_id=str(artifact_id) if artifact_id is not None else None,
            job_id=str(job_id) if job_id is not None else None,
            extra_data={"metric": metric, **safe_fields},
        )
    except Exception:  # noqa: BLE001 - metrics must never raise into business code
        logger.exception("Generation metrics: failed to record %s", metric)
