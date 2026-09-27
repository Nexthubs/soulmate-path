"""
Route Guard Domain Logic (DEV-SPEC §3, §10, §20, Decisions: PAY-AUTH-01, TIME-01).
Pure functions for evaluating route access and determining authoritative redirection.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional


class GuardedRoute(str, Enum):
    QUIZ = "/soulmate/quiz"
    EMAIL = "/soulmate/email"
    SUBSCRIBE = "/soulmate/subscribe"
    RESULT = "/soulmate/result"
    SKETCH = "/soulmate/sketch"
    REPORT = "/soulmate/report"


def normalize_route_path(path: str) -> str:
    """Strip query strings and trailing slashes for canonical path comparison."""
    clean = path.split("?")[0].strip()
    if clean.endswith("/") and len(clean) > 1:
        clean = clean[:-1]
    return clean


def calculate_unlock_times(
    first_payment_at: Optional[datetime],
    sketch_hours: int = 12,
    report_hours: int = 24,
) -> Dict[str, Optional[datetime]]:
    """Calculate authoritative unlock timestamps based on server first payment time (TIME-01)."""
    if not first_payment_at:
        return {
            "sketch_unlock_at": None,
            "report_unlock_at": None,
        }
    return {
        "sketch_unlock_at": first_payment_at + timedelta(hours=sketch_hours),
        "report_unlock_at": first_payment_at + timedelta(hours=report_hours),
    }


def evaluate_route_guard(
    target_route: str,
    session_exists: bool,
    current_step: Optional[str] = None,
    quiz_completed: bool = False,
    email_captured: bool = False,
    is_paid: bool = False,
    first_payment_at: Optional[datetime] = None,
    paid_through_at: Optional[datetime] = None,
    server_time: Optional[datetime] = None,
    sketch_hours: int = 12,
    report_hours: int = 24,
) -> Dict[str, Any]:
    """
    Evaluates whether the requested target route is accessible per DEV-SPEC §3 table.
    Enforces PAY-AUTH-01 (server payment authority) and TIME-01 (server unlock clock authority).

    PAID-THROUGH-01 (resolved 2026-09-27): paid entitlement survives cancellation
    until the end of the already-paid cycle — when `paid_through_at` is known and
    has passed (server clock), paid routes are denied even for previously paid
    sessions. A NULL `paid_through_at` is "unknown", never "ended": no denial is
    made without positive evidence (ACTIVE subscriptions normally have no
    paid_through_at until reconciliation records their cycle end).
    """
    if server_time is None:
        server_time = datetime.now(timezone.utc)

    route_clean = normalize_route_path(target_route)
    unlock_times = calculate_unlock_times(first_payment_at, sketch_hours, report_hours)
    sketch_unlock_at = unlock_times["sketch_unlock_at"]
    report_unlock_at = unlock_times["report_unlock_at"]

    sketch_unlocked = bool(is_paid and sketch_unlock_at and server_time >= sketch_unlock_at)
    report_unlocked = bool(is_paid and report_unlock_at and server_time >= report_unlock_at)
    paid_through_ended = bool(paid_through_at and server_time >= paid_through_at)

    base_context = {
        "target_route": route_clean,
        "server_time": server_time,
        "quiz_completed": quiz_completed,
        "email_captured": email_captured,
        "is_paid": is_paid,
        "paid_through_ended": paid_through_ended,
        "sketch_unlocked": sketch_unlocked,
        "report_unlocked": report_unlocked,
        "sketch_unlock_at": sketch_unlock_at,
        "report_unlock_at": report_unlock_at,
    }

    def _paid_access_ended() -> Dict[str, Any]:
        return {
            **base_context,
            "allowed": False,
            "redirect_to": "/soulmate/subscribe",
            "reason": "Paid access period has ended (PAID-THROUGH-01). Re-subscribe to regain access.",
        }

    # 1. /soulmate/quiz: requires active session. If missing -> /soulmate (new session)
    if route_clean == GuardedRoute.QUIZ.value:
        if not session_exists:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate",
                "reason": "Active session required. Start at landing page.",
            }
        return {**base_context, "allowed": True, "redirect_to": None, "reason": None}

    # 2. /soulmate/email: requires Quiz completed. If not met -> back to current quiz step
    if route_clean == GuardedRoute.EMAIL.value:
        if not session_exists:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate",
                "reason": "Active session required. Start at landing page.",
            }
        if not quiz_completed:
            fallback_step = current_step or "q01"
            return {
                **base_context,
                "allowed": False,
                "redirect_to": f"/soulmate/quiz?step={fallback_step}",
                "reason": "Quiz must be completed before email capture.",
            }
        return {**base_context, "allowed": True, "redirect_to": None, "reason": None}

    # 3. /soulmate/subscribe: requires Email captured. If not met -> /soulmate/email
    if route_clean == GuardedRoute.SUBSCRIBE.value:
        if not session_exists:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate",
                "reason": "Active session required. Start at landing page.",
            }
        if not quiz_completed:
            fallback_step = current_step or "q01"
            return {
                **base_context,
                "allowed": False,
                "redirect_to": f"/soulmate/quiz?step={fallback_step}",
                "reason": "Quiz must be completed before checkout.",
            }
        if not email_captured:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate/email",
                "reason": "Email must be submitted before subscription checkout.",
            }
        return {**base_context, "allowed": True, "redirect_to": None, "reason": None}

    # 4. /soulmate/result: requires first payment confirmed. If not met -> /soulmate/subscribe
    if route_clean == GuardedRoute.RESULT.value:
        if not session_exists or not is_paid:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate/subscribe",
                "reason": "First payment must be confirmed to access result dashboard (PAY-AUTH-01).",
            }
        if paid_through_ended:
            return _paid_access_ended()
        return {**base_context, "allowed": True, "redirect_to": None, "reason": None}

    # 5. /soulmate/sketch: requires first payment confirmed and 12h unlocked. If not met -> /soulmate/result
    if route_clean == GuardedRoute.SKETCH.value:
        if not session_exists or not is_paid:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate/subscribe",
                "reason": "Payment required before viewing sketch.",
            }
        if paid_through_ended:
            return _paid_access_ended()
        if not sketch_unlocked:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate/result",
                "reason": "Sketch view is locked until the 12-hour countdown completes (TIME-01).",
            }
        return {**base_context, "allowed": True, "redirect_to": None, "reason": None}

    # 6. /soulmate/report: requires first payment confirmed and 24h unlocked. If not met -> /soulmate/result
    if route_clean == GuardedRoute.REPORT.value:
        if not session_exists or not is_paid:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate/subscribe",
                "reason": "Payment required before viewing report.",
            }
        if paid_through_ended:
            return _paid_access_ended()
        if not report_unlocked:
            return {
                **base_context,
                "allowed": False,
                "redirect_to": "/soulmate/result",
                "reason": "Report view is locked until the 24-hour countdown completes (TIME-01).",
            }
        return {**base_context, "allowed": True, "redirect_to": None, "reason": None}

    # Unrecognized route defaults to allowed
    return {**base_context, "allowed": True, "redirect_to": None, "reason": None}
