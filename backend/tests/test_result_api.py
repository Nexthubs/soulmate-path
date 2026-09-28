"""
Result aggregate API tests (SP-503, DEV-SPEC §10.4, §15.8; Decisions: TIME-01, PAY-AUTH-01).

Acceptance criteria under test:
1. Single API supplies subscription + sketch + report status and server time —
   no client-side merging of multiple authority calls.
2. Response contains only the authorized user's data (session token / IDOR guard).
3. Stable schema suitable for the Result page UI (SP-106) and polling (SP-505).
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token


RESULT_URL = "/api/soulmate/result"
EXPECTED_ARTIFACT_KEYS = {"unlock_at", "availability", "generation", "status"}
EXPECTED_SUBSCRIPTION_KEYS = {"provider", "provider_status", "first_payment_at", "next_billing_at"}


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


async def seed_entitled_session(
    db: AsyncSession,
    with_subscription: bool = True,
    first_payment_at: bool = True,
    entitled: bool = True,
    with_artifacts: bool = True,
    sketch_generation: str = "NOT_STARTED",
    sketch_unlock_offset_hours: float = 12.0,
    email: str | None = None,
) -> tuple[SoulmateSession, Subscription | None]:
    """
    Seed a paid session (+ optional subscription/artifacts) with unlock timestamps
    relative to the current server clock so no wall-clock date is hard-coded:
    sketch unlocks 12h from now (LOCKED), report unlocked 1h ago (READY).
    """
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(hours=1)
    email = email or f"sp503_{uuid.uuid4().hex[:8]}@example.com"

    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED" if entitled else "email_captured",
        current_step="result" if entitled else "subscribe",
        email=email,
        email_normalized=email,
        subscription_success_at=paid_at if entitled else None,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    sub = None
    if with_subscription:
        sub = Subscription(
            session_id=sess.id,
            provider="paypal",
            provider_subscription_id=f"I-SP503-{uuid.uuid4().hex[:8].upper()}",
            provider_plan_id="P-SOULMATE-INTRO",
            provider_status="ACTIVE" if first_payment_at else "APPROVAL_PENDING",
            currency="USD",
            intro_price=Decimal("19.00"),
            regular_price=Decimal("29.00"),
            first_payment_at=paid_at if first_payment_at else None,
            next_billing_at=now + timedelta(days=30) if first_payment_at else None,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)

    if with_artifacts:
        db.add(
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="SKETCH",
                artifact_version="v1",
                unlock_at=now + timedelta(hours=sketch_unlock_offset_hours),
                generation_status=sketch_generation,
            )
        )
        db.add(
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="REPORT",
                artifact_version="v1",
                unlock_at=now - timedelta(hours=1),
                generation_status="NOT_STARTED",
            )
        )
        await db.commit()

    return sess, sub


async def load_artifacts(db: AsyncSession, session_id) -> list[SoulmateArtifact]:
    stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == session_id)
    return list((await db.execute(stmt)).scalars().all())


@pytest.mark.asyncio
async def test_result_aggregate_single_call_supplies_all_authorities(async_db: AsyncSession):
    """AC 1: one request returns server_time + subscription + sketch + report statuses."""
    sess, _ = await seed_entitled_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 200
    data = resp.json()

    # Top-level shape: server time + subscription + both artifact statuses in one payload
    assert set(data.keys()) == {"session_id", "server_time", "subscription", "sketch", "report"}
    assert data["session_id"] == sess.public_id
    assert data["server_time"] is not None

    assert set(data["subscription"].keys()) == EXPECTED_SUBSCRIPTION_KEYS
    assert data["subscription"]["provider"] == "paypal"
    assert data["subscription"]["provider_status"] == "ACTIVE"
    assert data["subscription"]["first_payment_at"] is not None
    assert data["subscription"]["next_billing_at"] is not None

    for artifact_key in ("sketch", "report"):
        assert set(data[artifact_key].keys()) == EXPECTED_ARTIFACT_KEYS

    # Sketch unlock is 12h in the future -> LOCKED countdown; report unlocked -> READY
    assert data["sketch"]["availability"] == "LOCKED"
    assert data["sketch"]["status"] == "LOCKED"
    assert data["sketch"]["generation"] == "NOT_STARTED"
    assert data["report"]["availability"] == "UNLOCKED"
    assert data["report"]["status"] == "READY"


@pytest.mark.asyncio
async def test_result_aggregate_works_with_session_id_query(async_db: AsyncSession):
    sess, _ = await seed_entitled_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(f"{RESULT_URL}?session_id={sess.public_id}")
    assert resp.status_code == 200
    assert resp.json()["sketch"]["status"] in {"LOCKED", "READY", "GENERATING", "COMPLETED", "FAILED"}


@pytest.mark.asyncio
async def test_result_aggregate_requires_authentication(async_db: AsyncSession):
    """AC 2: anonymous callers are rejected (entitlement data never leaks)."""
    sess, _ = await seed_entitled_session(async_db)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_result_aggregate_rejects_cross_session_idor(async_db: AsyncSession):
    """AC 2: session A's token requesting session B's aggregate is rejected (DEV-SPEC §20)."""
    sess_a, _ = await seed_entitled_session(async_db)
    sess_b, _ = await seed_entitled_session(async_db)
    token_a = generate_session_token(sess_a.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_a)
        resp = await client.get(f"{RESULT_URL}?session_id={sess_b.public_id}")
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_result_aggregate_requires_confirmed_first_payment(async_db: AsyncSession):
    """
    AC 2 / PAY-AUTH-01: an unentitled session (subscription_success_at None, even with an
    ACTIVE-looking subscription but no confirmed first payment) must not receive Result data.
    """
    sess, _ = await seed_entitled_session(async_db, entitled=False, first_payment_at=False)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_result_aggregate_self_heals_missing_artifact_rows(async_db: AsyncSession):
    """Entitled session with drifted/missing placeholder rows is healed on read (SP-501 ensure)."""
    sess, sub = await seed_entitled_session(async_db, with_artifacts=False)
    assert sub is not None and sub.first_payment_at is not None
    assert await load_artifacts(async_db, sess.id) == []

    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 200
    data = resp.json()

    # Response now carries concrete unlock timestamps derived from the authoritative first payment
    assert data["sketch"]["unlock_at"] is not None
    assert data["report"]["unlock_at"] is not None
    assert data["sketch"]["status"] == "LOCKED"

    # Exactly one SKETCH + one REPORT row persisted, unlocked from first_payment_at (+12h/+24h)
    artifacts = await load_artifacts(async_db, sess.id)
    assert len(artifacts) == 2
    assert {a.artifact_type for a in artifacts} == {"SKETCH", "REPORT"}
    first_payment = sub.first_payment_at
    for artifact in artifacts:
        expected = first_payment + timedelta(hours=12 if artifact.artifact_type == "SKETCH" else 24)
        assert artifact.unlock_at == expected


@pytest.mark.asyncio
async def test_result_aggregate_schema_stable_across_polling(async_db: AsyncSession):
    """AC 3: consecutive polls return the same stable schema with non-regressing server_time."""
    sess, _ = await seed_entitled_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp1 = await client.get(RESULT_URL)
        resp2 = await client.get(RESULT_URL)

    assert resp1.status_code == resp2.status_code == 200
    data1, data2 = resp1.json(), resp2.json()
    assert set(data1.keys()) == set(data2.keys()) == {
        "session_id", "server_time", "subscription", "sketch", "report"
    }
    assert data1["session_id"] == data2["session_id"] == sess.public_id
    assert set(data1["sketch"].keys()) == set(data2["sketch"].keys()) == EXPECTED_ARTIFACT_KEYS

    def parse_iso(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse_iso(data2["server_time"]) >= parse_iso(data1["server_time"])


@pytest.mark.asyncio
async def test_result_aggregate_reflects_generation_states(async_db: AsyncSession):
    """Unlocked artifacts surface combined §10.3 states through the API (locked wins first)."""
    sess, _ = await seed_entitled_session(async_db, sketch_generation="PROCESSING", sketch_unlock_offset_hours=-1)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sketch"]["status"] == "GENERATING"
    assert data["sketch"]["generation"] == "PROCESSING"


@pytest.mark.asyncio
async def test_result_aggregate_does_not_expose_same_email_other_sessions_sketch(async_db: AsyncSession):
    """
    Contact email does not prove ownership: a second paid session must not
    expose the first session’s Sketch metadata. Its own Report remains accessible.
    """
    from datetime import timedelta as _timedelta

    shared_email = f"sp503shared_{uuid.uuid4().hex[:8]}@example.com"
    sess_a, sub_a = await seed_entitled_session(async_db, email=shared_email)
    sess_b, sub_b = await seed_entitled_session(
        async_db, email=shared_email, with_artifacts=False
    )
    assert sub_a is not None and sub_b is not None
    assert sub_a.first_payment_at is not None and sub_b.first_payment_at is not None

    token_b = generate_session_token(sess_b.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_b)
        resp = await client.get(RESULT_URL)
    assert resp.status_code == 200
    data = resp.json()

    # Contact-email equality is not ownership, even for another paid session.
    assert data["sketch"]["unlock_at"] is None
    assert data["sketch"]["status"] == "LOCKED"
    assert data["sketch"]["generation"] == "NOT_STARTED"

    # Report: session B's own row (its first payment + 24h), self-healed on read
    expected_report_unlock = sub_b.first_payment_at + _timedelta(hours=24)
    assert datetime.fromisoformat(data["report"]["unlock_at"].replace("Z", "+00:00")) == expected_report_unlock

    # Exactly one sketch row still exists for the email (no duplicates created)
    stmt = select(SoulmateArtifact).where(
        SoulmateArtifact.email_normalized == shared_email,
        SoulmateArtifact.artifact_type == "SKETCH",
    )
    sketches = list((await async_db.execute(stmt)).scalars().all())
    assert len(sketches) == 1
    assert sketches[0].session_id == sess_a.id
