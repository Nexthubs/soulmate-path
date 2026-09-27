"""Central generation and payment metric emitters (DEV-SPEC §18–19, SP-902/903).

Operational metrics for the DB-backed generation queues: sketch (SP-603/604)
and report (SP-706). This is distinct from the §18.1 funnel analytics stream
in `app.soulmate.analytics`; it is the §19 observability stream that SP-904
alerts will key on.

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

Payment/webhook operational metrics use a separate stable `payment_metric`
stream. Their field names and category values are allowlisted here so raw
provider reason codes, event IDs, payloads, and exception messages do not enter
the metric stream.
"""

import logging
import math
from numbers import Real
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


PAYMENT_METRIC_EVENT = "payment_metric"

PAYMENT_METRIC_FIELDS: Dict[str, frozenset] = {
    "webhook_verification_failure": frozenset({"reason_category"}),
    "webhook_event_processing_failure": frozenset({"event_category", "error_category"}),
    "webhook_duplicate_event": frozenset({"event_category"}),
    "first_payment_confirmation_latency": frozenset({"latency_ms"}),
    "reconciliation_mismatch": frozenset({"mismatch_category"}),
    "payment_failure": frozenset({"reason_category"}),
}

_PAYMENT_CATEGORY_VALUES = {
    "reason_category": frozenset({
        "missing_headers", "verifier_unavailable", "signature_rejected",
        "verification_error", "insufficient_funds", "payment_method",
        "issuer_declined", "payer_action_required", "unknown", "other",
    }),
    "event_category": frozenset({
        "sale_completed", "subscription_payment_failed", "subscription_event",
        "refund_or_reversal", "other",
    }),
    "error_category": frozenset({"validation", "provider_unavailable", "other"}),
    "mismatch_category": frozenset({
        "provider_status", "failed_payment_count", "first_payment_time", "other",
    }),
}


def record_payment_metric(metric: str, *, fields: Optional[Dict[str, Any]] = None) -> None:
    """Emit one allowlisted payment metric as a best-effort structured log."""
    try:
        allowed = PAYMENT_METRIC_FIELDS.get(metric)
        if allowed is None:
            logger.warning("Payment metrics: unknown metric dropped")
            return
        safe_fields: Dict[str, Any] = {}
        for key, value in (fields or {}).items():
            if key not in allowed:
                logger.warning("Payment metrics: dropped non-catalog field on %s", metric)
                continue
            if value is None:
                continue
            categories = _PAYMENT_CATEGORY_VALUES.get(key)
            if categories is not None:
                safe_fields[key] = value if isinstance(value, str) and value in categories else "other"
            elif key == "latency_ms":
                if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                    continue
                safe_fields[key] = max(0, int(value))
        log_event(
            event_type=PAYMENT_METRIC_EVENT,
            message=f"Payment metric: {metric}",
            extra_data={"metric": metric, "count": 1, **safe_fields},
        )
    except Exception:  # noqa: BLE001 - telemetry never changes payment processing
        logger.exception("Payment metrics: failed to record a metric")


def payment_webhook_event_category(event_type: str) -> str:
    """Collapse provider event names into a finite, non-sensitive category."""
    if event_type == "PAYMENT.SALE.COMPLETED":
        return "sale_completed"
    if event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
        return "subscription_payment_failed"
    if event_type in {"PAYMENT.SALE.REFUNDED", "PAYMENT.SALE.REVERSED"}:
        return "refund_or_reversal"
    if isinstance(event_type, str) and event_type.startswith("BILLING.SUBSCRIPTION."):
        return "subscription_event"
    return "other"


def payment_failure_reason_category(reason_code: Any) -> str:
    """Map provider failure codes to safe operational categories."""
    if not isinstance(reason_code, str) or not reason_code.strip():
        return "unknown"
    code = reason_code.strip().upper()
    if code == "INSUFFICIENT_FUNDS":
        return "insufficient_funds"
    if code in {"INSTRUMENT_DECLINED", "PAYMENT_DENIED", "GENERIC_DECLINE", "CARD_DECLINED"}:
        return "issuer_declined"
    if code in {"PAYER_CANNOT_PAY", "PAYER_ACTION_REQUIRED", "PAYER_AUTHENTICATION_REQUIRED"}:
        return "payer_action_required"
    if code in {
        "INVALID_PAYMENT_METHOD", "PAYMENT_METHOD_INVALID", "PAYMENT_SOURCE_INVALID",
        "CARD_EXPIRED", "CREDIT_CARD_EXPIRED", "BANK_ACCOUNT_RESTRICTED",
    }:
        return "payment_method"
    return "other"
