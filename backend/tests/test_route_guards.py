"""
Automated unit, service, and API tests for Route Guards (SP-304, DEV-SPEC §3, §10, §20, Decisions: PAY-AUTH-01, TIME-01).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.db.base import utc_now
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal, SessionLocal
from app.main import app
from app.soulmate.domain.guard import (
    GuardedRoute,
    calculate_unlock_times,
    evaluate_route_guard,
    normalize_route_path,
)
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.security import generate_session_token
from app.soulmate.services.guard_service import GuardService


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def async_db():
    """Provides an asynchronous DB session for service layer calls."""
    async with AsyncSessionLocal() as session:
        yield session


# ==============================================================================
# 1. Pure Domain Logic Tests (DEV-SPEC §3, Table Verification)
# ==============================================================================


def test_normalize_route_path():
    assert normalize_route_path("/soulmate/quiz?step=q02") == "/soulmate/quiz"
    assert normalize_route_path("/soulmate/email/") == "/soulmate/email"
    assert normalize_route_path("/soulmate/result") == "/soulmate/result"


def test_calculate_unlock_times_time_01():
    """TIME-01: sketch at +12h, report at +24h from first payment."""
    t0 = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
    times = calculate_unlock_times(t0, sketch_hours=12, report_hours=24)
    assert times["sketch_unlock_at"] == t0 + timedelta(hours=12)
    assert times["report_unlock_at"] == t0 + timedelta(hours=24)

    none_times = calculate_unlock_times(None)
    assert none_times["sketch_unlock_at"] is None
    assert none_times["report_unlock_at"] is None


def test_guard_quiz_route():
    """Row 1: /soulmate/quiz requires active session, else redirect to /soulmate."""
    # No session
    r1 = evaluate_route_guard(target_route="/soulmate/quiz", session_exists=False)
    assert r1["allowed"] is False
    assert r1["redirect_to"] == "/soulmate"

    # Has session
    r2 = evaluate_route_guard(target_route="/soulmate/quiz", session_exists=True)
    assert r2["allowed"] is True
    assert r2["redirect_to"] is None


def test_guard_email_route():
    """Row 2: /soulmate/email requires Quiz completed, else back to current quiz step."""
    # No session
    r1 = evaluate_route_guard(target_route="/soulmate/email", session_exists=False)
    assert r1["allowed"] is False
    assert r1["redirect_to"] == "/soulmate"

    # Quiz not completed -> redirect to current quiz step
    r2 = evaluate_route_guard(
        target_route="/soulmate/email",
        session_exists=True,
        quiz_completed=False,
        current_step="q07",
    )
    assert r2["allowed"] is False
    assert r2["redirect_to"] == "/soulmate/quiz?step=q07"

    # Quiz completed
    r3 = evaluate_route_guard(
        target_route="/soulmate/email",
        session_exists=True,
        quiz_completed=True,
    )
    assert r3["allowed"] is True
    assert r3["redirect_to"] is None


def test_guard_subscribe_route():
    """Row 3: /soulmate/subscribe requires Email captured, else /soulmate/email."""
    # No session
    r1 = evaluate_route_guard(target_route="/soulmate/subscribe", session_exists=False)
    assert r1["allowed"] is False
    assert r1["redirect_to"] == "/soulmate"

    # Quiz not completed
    r2 = evaluate_route_guard(
        target_route="/soulmate/subscribe",
        session_exists=True,
        quiz_completed=False,
        current_step="q12",
    )
    assert r2["allowed"] is False
    assert r2["redirect_to"] == "/soulmate/quiz?step=q12"

    # Quiz completed, but email not captured -> /soulmate/email
    r3 = evaluate_route_guard(
        target_route="/soulmate/subscribe",
        session_exists=True,
        quiz_completed=True,
        email_captured=False,
    )
    assert r3["allowed"] is False
    assert r3["redirect_to"] == "/soulmate/email"

    # Email captured -> allowed
    r4 = evaluate_route_guard(
        target_route="/soulmate/subscribe",
        session_exists=True,
        quiz_completed=True,
        email_captured=True,
    )
    assert r4["allowed"] is True
    assert r4["redirect_to"] is None


def test_guard_result_route_pay_auth_01():
    """Row 4: /soulmate/result requires confirmed first payment (PAY-AUTH-01), else /soulmate/subscribe."""
    # Unpaid
    r1 = evaluate_route_guard(
        target_route="/soulmate/result",
        session_exists=True,
        is_paid=False,
    )
    assert r1["allowed"] is False
    assert r1["redirect_to"] == "/soulmate/subscribe"

    # Paid
    r2 = evaluate_route_guard(
        target_route="/soulmate/result",
        session_exists=True,
        is_paid=True,
    )
    assert r2["allowed"] is True
    assert r2["redirect_to"] is None


def test_guard_sketch_route_time_01():
    """Row 5: /soulmate/sketch requires confirmed payment AND 12h unlocked (TIME-01), else /soulmate/result."""
    t0 = datetime(2026, 9, 24, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Unpaid -> /soulmate/subscribe
    r1 = evaluate_route_guard(
        target_route="/soulmate/sketch",
        session_exists=True,
        is_paid=False,
    )
    assert r1["allowed"] is False
    assert r1["redirect_to"] == "/soulmate/subscribe"

    # 2. Paid, but only +6h elapsed (< 12h cooldown) -> /soulmate/result
    t_early = t0 + timedelta(hours=6)
    r2 = evaluate_route_guard(
        target_route="/soulmate/sketch",
        session_exists=True,
        is_paid=True,
        first_payment_at=t0,
        server_time=t_early,
    )
    assert r2["allowed"] is False
    assert r2["sketch_unlocked"] is False
    assert r2["redirect_to"] == "/soulmate/result"

    # 3. Paid, +12h 1m elapsed (unlocked) -> allowed
    t_ready = t0 + timedelta(hours=12, minutes=1)
    r3 = evaluate_route_guard(
        target_route="/soulmate/sketch",
        session_exists=True,
        is_paid=True,
        first_payment_at=t0,
        server_time=t_ready,
    )
    assert r3["allowed"] is True
    assert r3["sketch_unlocked"] is True
    assert r3["redirect_to"] is None


def test_guard_report_route_time_01():
    """Row 6: /soulmate/report requires confirmed payment AND 24h unlocked (TIME-01), else /soulmate/result."""
    t0 = datetime(2026, 9, 24, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Unpaid -> /soulmate/subscribe
    r1 = evaluate_route_guard(
        target_route="/soulmate/report",
        session_exists=True,
        is_paid=False,
    )
    assert r1["allowed"] is False
    assert r1["redirect_to"] == "/soulmate/subscribe"

    # 2. Paid, +18h elapsed (sketch unlocked, but report still locked < 24h) -> /soulmate/result
    t_18h = t0 + timedelta(hours=18)
    r2 = evaluate_route_guard(
        target_route="/soulmate/report",
        session_exists=True,
        is_paid=True,
        first_payment_at=t0,
        server_time=t_18h,
    )
    assert r2["allowed"] is False
    assert r2["sketch_unlocked"] is True
    assert r2["report_unlocked"] is False
    assert r2["redirect_to"] == "/soulmate/result"

    # 3. Paid, +24h 5m elapsed -> allowed
    t_24h = t0 + timedelta(hours=24, minutes=5)
    r3 = evaluate_route_guard(
        target_route="/soulmate/report",
        session_exists=True,
        is_paid=True,
        first_payment_at=t0,
        server_time=t_24h,
    )
    assert r3["allowed"] is True
    assert r3["report_unlocked"] is True
    assert r3["redirect_to"] is None


# ==============================================================================
# 2. Service Layer Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_guard_service_evaluates_session_lifecycle(async_db, db_session: Session):
    """Verify GuardService accurately maps persistent database records to route verdicts."""
    public_id = f"test_guard_{uuid.uuid4().hex[:12]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.QUIZ_IN_PROGRESS.value,
        current_step="q05",
    )
    db_session.add(sess)
    db_session.commit()

    # Step 1: /soulmate/email before quiz completion -> rejected, redirect to quiz step
    v1 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/email", session=sess)
    assert v1.allowed is False
    assert v1.redirect_to == "/soulmate/quiz?step=q05"

    # Step 2: Complete quiz on session
    sess.status = SessionStatus.QUIZ_COMPLETED.value
    sess.current_step = "transition_5"
    sess.quiz_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    # /soulmate/email now allowed
    v2 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/email", session=sess)
    assert v2.allowed is True
    assert v2.redirect_to is None

    # /soulmate/subscribe still rejected (email not captured yet)
    v3 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/subscribe", session=sess)
    assert v3.allowed is False
    assert v3.redirect_to == "/soulmate/email"

    # Step 3: Capture email
    sess.email = f"guard_test_{uuid.uuid4().hex[:8]}@example.com"
    sess.status = SessionStatus.EMAIL_CAPTURED.value
    db_session.commit()

    # /soulmate/subscribe now allowed
    v4 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/subscribe", session=sess)
    assert v4.allowed is True
    assert v4.redirect_to is None

    # /soulmate/result rejected (not paid)
    v5 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert v5.allowed is False
    assert v5.redirect_to == "/soulmate/subscribe"

    # Step 4: Record confirmed first payment
    pay_time = datetime.now(timezone.utc) - timedelta(hours=14)  # 14 hours ago
    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-GUARD-{uuid.uuid4().hex[:8]}",
        provider_plan_id="P-INTRO-GUARD",
        provider_status="ACTIVE",
        currency="USD",
        regular_price=Decimal("29.00"),
        first_payment_at=pay_time,
    )
    db_session.add(sub)
    sess.status = SessionStatus.SUBSCRIBED.value
    db_session.commit()

    # /soulmate/result now allowed
    v6 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert v6.allowed is True

    # /soulmate/sketch now allowed (14h >= 12h)
    v7 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/sketch", session=sess)
    assert v7.allowed is True
    assert v7.sketch_unlocked is True

    # /soulmate/report still locked (14h < 24h) -> redirects to /soulmate/result
    v8 = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/report", session=sess)
    assert v8.allowed is False
    assert v8.report_unlocked is False
    assert v8.redirect_to == "/soulmate/result"


# ==============================================================================
# 3. HTTP API Endpoint Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_api_check_route_guard_anonymous():
    """Anonymous caller checking /soulmate/email is redirected to landing page."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/soulmate/guard/check?target_route=/soulmate/email")
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is False
        assert data["redirect_to"] == "/soulmate"
        assert "server_time" in data


@pytest.mark.asyncio
async def test_api_check_route_guard_with_cookie(db_session: Session):
    """Caller with session cookie gets personalized authoritative verdict."""
    public_id = f"test_api_g_{uuid.uuid4().hex[:12]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.QUIZ_IN_PROGRESS.value,
        current_step="q03",
    )
    db_session.add(sess)
    db_session.commit()

    token = generate_session_token(public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)

        # Checking /soulmate/email when on q03 -> redirects back to q03
        resp = await client.get("/api/soulmate/guard/check?target_route=/soulmate/email")
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is False
        assert data["redirect_to"] == "/soulmate/quiz?step=q03"
        assert data["session_id"] == public_id


@pytest.mark.asyncio
async def test_api_check_route_guard_with_session_id_and_idor_guard(db_session: Session):
    """
    IDOR Security Guard (DEV-SPEC §20):
    Caller cannot check route guard for a foreign session without authorization.
    """
    public_id_a = f"test_guard_a_{uuid.uuid4().hex[:12]}"
    public_id_b = f"test_guard_b_{uuid.uuid4().hex[:12]}"
    sess_a = SoulmateSession(public_id=public_id_a, quiz_version="soulmate-quiz-v1", status=SessionStatus.QUIZ_IN_PROGRESS.value, current_step="q01")
    sess_b = SoulmateSession(public_id=public_id_b, quiz_version="soulmate-quiz-v1", status=SessionStatus.QUIZ_IN_PROGRESS.value, current_step="q01")
    db_session.add_all([sess_a, sess_b])
    db_session.commit()

    token_a = generate_session_token(public_id_a)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_a)

        # 1. Matching token for session_a -> 200 OK
        resp_ok = await client.get(f"/api/soulmate/guard/check?target_route=/soulmate/quiz&session_id={public_id_a}")
        assert resp_ok.status_code == 200
        assert resp_ok.json()["allowed"] is True

        # 2. Token A requesting session_b -> 403 Forbidden (IDOR Guard)
        resp_idor = await client.get(f"/api/soulmate/guard/check?target_route=/soulmate/quiz&session_id={public_id_b}")
        assert resp_idor.status_code == 403
        assert resp_idor.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_guard_service_rejects_active_subscription_without_first_payment_at_h3(async_db, db_session: Session):
    """
    H-3, PAY-AUTH-01, TIME-01 Verification:
    A subscription with provider_status='ACTIVE' but first_payment_at=None must NOT grant access
    to /soulmate/result or unlocked content. Only server-confirmed first_payment_at authorizes access.
    """
    public_id = f"test_h3_guard_{uuid.uuid4().hex[:12]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.EMAIL_CAPTURED.value,
        current_step="subscribe",
        quiz_completed_at=utc_now(),
        email="seeker_h3@example.com",
        email_normalized="seeker_h3@example.com",
    )
    db_session.add(sess)
    db_session.commit()

    # Subscription created with provider_status="ACTIVE", but first_payment_at is None
    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-H3-UNPAID-{uuid.uuid4().hex[:8]}",
        provider_plan_id="P-TEST-H3",
        provider_status="ACTIVE",
        currency="USD",
        regular_price=Decimal("29.00"),
        first_payment_at=None,
    )
    db_session.add(sub)
    db_session.commit()

    # 1. GuardService evaluation
    verdict = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert verdict.allowed is False
    assert verdict.is_paid is False
    assert verdict.redirect_to == "/soulmate/subscribe"

    # 2. HTTP Route Guard endpoint evaluation
    token = generate_session_token(public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get("/api/soulmate/guard/check?target_route=/soulmate/result")
        assert resp.status_code == 200
        body = resp.json()
        assert body["allowed"] is False
        assert body["is_paid"] is False
        assert body["redirect_to"] == "/soulmate/subscribe"

    # 3. Simulate verified payment webhook populating first_payment_at
    sub.first_payment_at = utc_now()
    sess.status = SessionStatus.SUBSCRIBED.value
    db_session.commit()

    # Now allowed
    verdict_paid = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert verdict_paid.allowed is True
    assert verdict_paid.is_paid is True
    assert verdict_paid.redirect_to is None


# ==============================================================================
# 4. PAID-THROUGH-01 (resolved 2026-09-27): paid entitlement survives
#    cancellation until the known paid-cycle end. HIGH-RISK evidence — denial
#    requires positive evidence (a passed paid_through_at on the server clock);
#    NULL means unknown and never denies.
# ==============================================================================


def test_guard_paid_through_window_matrix():
    """Domain matrix: paid routes honor the paid-through access window."""
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    paid_at = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    future_end = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    past_end = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Paid + future paid_through (cancelled mid-cycle) -> access continues
    r = evaluate_route_guard(
        "/soulmate/result", session_exists=True, is_paid=True,
        first_payment_at=paid_at, paid_through_at=future_end, server_time=now,
    )
    assert r["allowed"] is True
    assert r["paid_through_ended"] is False
    # sketch unlocked (13h > 12h) and still inside the paid window
    r = evaluate_route_guard(
        "/soulmate/sketch", session_exists=True, is_paid=True,
        first_payment_at=paid_at, paid_through_at=future_end, server_time=now,
    )
    assert r["allowed"] is True

    # 2. Paid + passed paid_through (non-ACTIVE provider state) -> denied on ALL
    # paid routes, redirect to subscribe
    for route in ("/soulmate/result", "/soulmate/sketch", "/soulmate/report"):
        r = evaluate_route_guard(
            route, session_exists=True, is_paid=True,
            first_payment_at=paid_at, paid_through_at=past_end, server_time=now,
            provider_status="CANCELLED",
        )
        assert r["allowed"] is False, route
        assert r["redirect_to"] == "/soulmate/subscribe", route
        assert "PAID-THROUGH-01" in r["reason"]
        assert r["paid_through_ended"] is True

    # 2b. Wave 8 audit H-2 (round 3): an ACTIVE subscription crossing its
    # recorded cycle end is NOT denied — renewal payment or webhook may simply
    # be in flight; the provider currently reports it as entitled.
    r = evaluate_route_guard(
        "/soulmate/result", session_exists=True, is_paid=True,
        first_payment_at=paid_at, paid_through_at=past_end, server_time=now,
        provider_status="ACTIVE",
    )
    assert r["allowed"] is True
    assert r["paid_through_ended"] is False

    # 3. Boundary: access ends exactly at paid_through_at (server clock, >=)
    r = evaluate_route_guard(
        "/soulmate/result", session_exists=True, is_paid=True,
        first_payment_at=paid_at, paid_through_at=now, server_time=now,
    )
    assert r["allowed"] is False

    # 4. NULL paid_through -> unknown, never "ended" (ACTIVE subs normally have none)
    r = evaluate_route_guard(
        "/soulmate/result", session_exists=True, is_paid=True,
        first_payment_at=paid_at, paid_through_at=None, server_time=now,
    )
    assert r["allowed"] is True
    assert r["paid_through_ended"] is False

    # 5. Unpaid stays denied first (PAY-AUTH-01 unchanged), even with a date present
    r = evaluate_route_guard(
        "/soulmate/result", session_exists=True, is_paid=False,
        first_payment_at=None, paid_through_at=future_end, server_time=now,
    )
    assert r["allowed"] is False
    assert "PAY-AUTH-01" in r["reason"]

    # 6. Paid-through denial wins over unlock: sketch 12h-unlocked but window over
    r = evaluate_route_guard(
        "/soulmate/sketch", session_exists=True, is_paid=True,
        first_payment_at=paid_at, paid_through_at=past_end, server_time=now,
        provider_status="EXPIRED",
    )
    assert r["allowed"] is False
    assert r["redirect_to"] == "/soulmate/subscribe"


@pytest.mark.asyncio
async def test_guard_service_enforces_cancelled_paid_through_window(async_db, db_session: Session):
    """Service-level evidence: a CANCELLED subscription keeps paid-route access
    until paid_through_at, then loses it — server-persisted data only."""
    public_id = f"test_guard_pt_{uuid.uuid4().hex[:12]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.SUBSCRIBED.value,
        current_step="result",
        quiz_completed_at=datetime.now(timezone.utc),
        email=f"{public_id}@example.com",
        email_normalized=f"{public_id}@example.com",
        subscription_success_at=datetime.now(timezone.utc) - timedelta(days=40),
    )
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)

    # Cancelled 5 days ago, paid through 25 more days -> still inside the window
    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-GUARDPT-{uuid.uuid4().hex[:8]}",
        provider_plan_id="P-INTRO-GUARD",
        provider_status="CANCELLED",
        currency="USD",
        regular_price=Decimal("29.00"),
        first_payment_at=datetime.now(timezone.utc) - timedelta(days=40),
        cancelled_at=datetime.now(timezone.utc) - timedelta(days=5),
        paid_through_at=datetime.now(timezone.utc) + timedelta(days=25),
    )
    db_session.add(sub)
    db_session.commit()

    v_inside = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert v_inside.allowed is True

    # The paid cycle ends -> access is denied on the same persisted row
    sub.paid_through_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    v_after = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert v_after.allowed is False
    assert v_after.redirect_to == "/soulmate/subscribe"
    assert "PAID-THROUGH-01" in v_after.reason

    # Sketch: unlocked (40 days > 12h) yet denied — the window rule wins
    v_sketch = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/sketch", session=sess)
    assert v_sketch.allowed is False
    assert v_sketch.sketch_unlocked is True
    assert v_sketch.redirect_to == "/soulmate/subscribe"

    # ACTIVE subscription without any paid_through_at keeps access (unknown != ended)
    sub.provider_status = "ACTIVE"
    sub.paid_through_at = None
    db_session.commit()
    v_active = await GuardService.evaluate_guard(db=async_db, target_route="/soulmate/result", session=sess)
    assert v_active.allowed is True
