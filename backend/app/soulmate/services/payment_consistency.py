"""Transaction serialization and event ordering for payment-owned state.

Locks are transaction-scoped PostgreSQL advisory locks, including for rows which
do not exist yet. Acquire in event -> subscription -> session -> ledger order.
"""

from datetime import datetime
from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.billing import Subscription


async def payment_lock(db: AsyncSession, namespace: str, key: object) -> None:
    lock_id = int.from_bytes(
        sha256(f"soulmate:{namespace}:{key}".encode()).digest()[:8],
        "big", signed=True,
    )
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})


def apply_provider_status(sub: Subscription, status: str, at: datetime) -> bool:
    """Reject stale snapshots and irreversible terminal-state regressions."""
    previous = sub.provider_status_updated_at
    legacy_times = [t for t in (sub.cancelled_at, sub.expired_at, sub.suspended_at) if t]
    if previous is None and legacy_times:
        previous = max(legacy_times)
    if previous is not None and at <= previous:
        return False
    if sub.provider_status in {"CANCELLED", "EXPIRED"} and status != sub.provider_status:
        return False
    sub.provider_status = status
    sub.provider_status_updated_at = at
    if status == "CANCELLED":
        sub.cancelled_at = sub.cancelled_at or at
        sub.next_billing_at = None
    elif status == "EXPIRED":
        sub.expired_at = sub.expired_at or at
        sub.next_billing_at = None
    elif status == "SUSPENDED":
        sub.suspended_at = at
    elif status == "ACTIVE":
        sub.suspended_at = None
    return True


def apply_billing_count(sub: Subscription, count: int, at: datetime) -> bool:
    previous = sub.billing_updated_at or sub.billing_issue_detected_at
    if previous is not None and at <= previous:
        return False
    sub.failed_payments_count = max(0, count)
    sub.billing_updated_at = at
    sub.billing_issue_detected_at = (sub.billing_issue_detected_at or at) if count else None
    return True
