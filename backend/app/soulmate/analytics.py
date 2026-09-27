"""Central funnel analytics emitter (DEV-SPEC §18, SP-901).

The §18.1 funnel event contract lives here once: every server-side analytics
emission goes through `track_funnel_event`, which enforces the per-event
property allowlist and the §18.2 privacy rules in code (never by convention):

- properties outside the event's declared schema are dropped;
- email-shaped or calendar-date-shaped (DOB-shaped) string values are
  redacted before they reach structured logs;
- free-text answers never appear in the catalog at all.

Events are emitted through the §19.1 structured log pipeline (`log_event`)
with the canonical `soulmate_`-prefixed `event_type`, so the existing logging
infrastructure is the transport and a provider sink can be added later
without touching emitting services.

Client-side (view/click) events share the same contract via the frontend
wrapper `frontend/src/soulmate/analytics/index.ts`; the tests on both sides
pin the same 27-event catalog so the two cannot drift.
"""

import logging
import re
from typing import Any, Dict, Optional

from app.core.logging import log_event

logger = logging.getLogger(__name__)

#: §18.1 catalog: event name -> allowed property names. Mirrors the frontend
#: `SOULMATE_FUNNEL_EVENT_PROPERTIES` table (drift is pinned by tests).
FUNNEL_EVENT_PROPERTIES: Dict[str, frozenset] = {
    "soulmate_landing_view": frozenset({"source", "campaign"}),
    "soulmate_start_click": frozenset({"session_id"}),
    "soulmate_login_click": frozenset({"session_id"}),
    "soulmate_transition_view": frozenset({"step"}),
    "soulmate_transition_continue": frozenset({"step"}),
    "soulmate_quiz_started": frozenset({"quiz_version"}),
    "soulmate_question_view": frozenset({"question_code"}),
    "soulmate_question_answered": frozenset({"question_code", "option_codes", "duration_ms"}),
    "soulmate_quiz_back": frozenset({"from_q", "to_q"}),
    "soulmate_quiz_completed": frozenset({"total_duration"}),
    "soulmate_interstitial_answered": frozenset({"code", "value"}),
    "soulmate_email_view": frozenset({"partner_gender"}),
    "soulmate_email_submitted": frozenset({"domain_type"}),
    "soulmate_subscribe_view": frozenset({"intro_price", "regular_price", "currency"}),
    "soulmate_paypal_start": frozenset({"plan_id"}),
    "soulmate_paypal_approved": frozenset({"subscription_id"}),
    "soulmate_payment_confirmed": frozenset({"amount", "currency"}),
    "soulmate_payment_failed": frozenset({"reason_code"}),
    "soulmate_result_view": frozenset({"sketch_availability", "report_availability"}),
    "soulmate_sketch_unlocked": frozenset({"session_id", "hours_since_payment"}),
    "soulmate_sketch_viewed": frozenset({"artifact_version"}),
    "soulmate_sketch_generation_started": frozenset({"model", "prompt_version"}),
    "soulmate_sketch_generation_completed": frozenset({"latency_ms", "attempts"}),
    "soulmate_sketch_generation_failed": frozenset({"error_code", "attempts"}),
    "soulmate_report_unlocked": frozenset({"session_id", "hours_since_payment"}),
    "soulmate_report_viewed": frozenset({"report_version"}),
    "soulmate_subscription_cancelled": frozenset({"provider_status"}),
}

_EMAIL_LIKE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _redact_value(value: Any) -> Any:
    """§18.2 defense-in-depth: redact email/DOB-shaped string values."""
    if isinstance(value, str) and (_EMAIL_LIKE.match(value) or _DATE_LIKE.match(value)):
        return "[redacted]"
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def sanitize_funnel_properties(event: str, properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Filter `properties` to the event's catalog allowlist and redact PII.

    Used by `track_funnel_event` and by tests that must verify the privacy
    boundary independently of log emission.
    """
    allowed = FUNNEL_EVENT_PROPERTIES.get(event)
    if allowed is None:
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in (properties or {}).items():
        if key not in allowed:
            logger.warning("Funnel analytics: dropped non-catalog property %r on %s", key, event)
            continue
        if value is None:
            continue
        sanitized[key] = _redact_value(value)
    return sanitized


def track_funnel_event(
    event: str,
    *,
    session_id: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit one §18.1 funnel event through the structured log pipeline.

    Best-effort by contract: an analytics failure must never break the
    business flow, so unexpected errors are swallowed after logging.
    """
    try:
        if event not in FUNNEL_EVENT_PROPERTIES:
            logger.warning("Funnel analytics: unknown event %r dropped", event)
            return
        sanitized = sanitize_funnel_properties(event, properties)
        log_event(
            event_type=event,
            message=f"Funnel event: {event}",
            session_id=session_id,
            extra_data=sanitized,
        )
    except Exception:  # noqa: BLE001 - analytics must never raise into business code
        logger.exception("Funnel analytics: failed to emit %s", event)
