"""
Report persistence + retrieval tests (DEV-SPEC §13.2, §13.4, §14, §15.11, §20; SP-702;
Decisions: REPORT-01, REPORT-02, RECOVERY-01, TIME-01, ASSET-01).

Acceptance criteria under test:
- report JSON/version/status persisted (validated SoulmateReportV1 into
  soulmate_artifacts.content_json, generation_status COMPLETED, provider metadata);
- authorized retrieval only (cookie/session ownership, IDOR-safe, §20);
- one canonical current V1 report per entitled session (DB unique constraint +
  no-clobber save);
- unlock gating on retrieval (TIME-01: persisted unlock_at is authoritative);
- read path re-validates stored content and fails closed (SP-701 contract).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.report import SoulmateReportV1, parse_soulmate_report_v1
from app.soulmate.security import generate_session_token
from app.soulmate.services.report_service import ReportService

REPORT_URL = "/api/soulmate/artifacts/report"


def _report_payload(**overrides):
    payload = {
        "schemaVersion": "v1",
        "title": "Your Soulmate Report",
        "intro": "Before two souls cross paths, they rendezvous energetically.",
        "sections": [
            {
                "index": "01.",
                "title": "Releasing the Fear of Being Alone",
                "body": "Real alignment begins the moment you cherish your solitude.",
            }
        ],
        "closing": "Trust the timing of your life.",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
async def purge_sp702_data():
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp702_%"))
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp702_%")))
        await db.commit()


async def _seed_entitled_session(
    db: AsyncSession,
    *,
    paid_hours_ago: float = 30.0,
    report_generation: str = "NOT_STARTED",
    report_content: dict | None = None,
) -> SoulmateSession:
    """
    Entitled paid session with SP-501-style SKETCH + REPORT placeholder rows.

    Unlock timestamps faithfully follow TIME-01 (unlock = first_payment_at + 12h/24h):
    with the default 30h-old payment the REPORT is naturally unlocked; pass
    `paid_hours_ago < 24` to get a still-locked REPORT.
    """
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(hours=paid_hours_ago)
    email = f"sp702_{uuid.uuid4().hex[:8]}@example.com"
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=email,
        email_normalized=email,
        subscription_success_at=paid_at,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    db.add(
        Subscription(
            session_id=sess.id,
            provider="paypal",
            provider_subscription_id=f"I-SP702-{uuid.uuid4().hex[:8].upper()}",
            provider_plan_id="P-SOULMATE-INTRO",
            provider_status="ACTIVE",
            currency="USD",
            intro_price=Decimal("19.00"),
            regular_price=Decimal("29.00"),
            first_payment_at=paid_at,
        )
    )
    db.add(
        SoulmateArtifact(
            session_id=sess.id,
            email_normalized=email,
            artifact_type="SKETCH",
            artifact_version="v1",
            unlock_at=paid_at + timedelta(hours=12),
            generation_status="COMPLETED",
        )
    )
    db.add(
        SoulmateArtifact(
            session_id=sess.id,
            email_normalized=email,
            artifact_type="REPORT",
            artifact_version="v1",
            unlock_at=paid_at + timedelta(hours=24),
            generation_status=report_generation,
            content_json=report_content,
        )
    )
    await db.commit()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Service: persistence (SP-702 acceptance #1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_persists_validated_content_and_metadata(async_db):
    sess = await _seed_entitled_session(async_db)
    artifact, saved = await ReportService.save_completed_report(
        async_db,
        sess.id,
        _report_payload(),
        provider="openai_compatible",
        model="gpt-5.2",
        prompt_version="v1",
        provider_request_id="req_123",
    )
    assert saved is True
    assert artifact.generation_status == "COMPLETED"
    assert artifact.completed_at is not None
    assert artifact.provider == "openai_compatible"
    assert artifact.model == "gpt-5.2"
    assert artifact.prompt_version == "v1"
    assert artifact.provider_request_id == "req_123"
    # content_json stores the validated camelCase V1 payload (renderer contract)
    assert artifact.content_json["schemaVersion"] == "v1"
    assert artifact.content_json["sections"][0]["index"] == "01."
    parse_soulmate_report_v1(artifact.content_json)  # stored form validates


@pytest.mark.asyncio
async def test_save_accepts_model_instance(async_db):
    sess = await _seed_entitled_session(async_db)
    report = SoulmateReportV1.model_validate(_report_payload())
    artifact, saved = await ReportService.save_completed_report(async_db, sess.id, report)
    assert saved is True
    assert artifact.content_json["schemaVersion"] == "v1"


@pytest.mark.asyncio
async def test_save_rejects_invalid_payload_without_partial_write(async_db):
    sess = await _seed_entitled_session(async_db)
    malicious = _report_payload()
    malicious["sections"][0]["body"] = "<script>alert(1)</script>"
    with pytest.raises(Exception) as exc_info:
        await ReportService.save_completed_report(
            async_db, sess.id, malicious, provider="openai_compatible", model="m"
        )
    from app.soulmate.domain.report import ReportValidationError

    assert isinstance(exc_info.value, ReportValidationError)
    # No partial write: the placeholder row is untouched.
    row = await ReportService.get_report_artifact(async_db, sess.id)
    assert row.generation_status == "NOT_STARTED"
    assert row.content_json is None


@pytest.mark.asyncio
async def test_save_missing_row_fails_closed(async_db):
    sess = await _seed_entitled_session(async_db)
    from app.core.errors import NotFoundError

    await async_db.execute(
        delete(SoulmateArtifact).where(
            SoulmateArtifact.session_id == sess.id,
            SoulmateArtifact.artifact_type == "REPORT",
        )
    )
    await async_db.commit()
    with pytest.raises(NotFoundError):
        await ReportService.save_completed_report(async_db, sess.id, _report_payload())


# ---------------------------------------------------------------------------
# Service: one canonical current V1 report (SP-702 acceptance #3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_is_no_clobber_on_completed_report(async_db):
    sess = await _seed_entitled_session(async_db)
    first, saved_first = await ReportService.save_completed_report(
        async_db, sess.id, _report_payload(), provider="openai_compatible", model="m1"
    )
    again, saved_again = await ReportService.save_completed_report(
        async_db,
        sess.id,
        _report_payload(title="A Different Second Report"),
        provider="other",
        model="m2",
    )
    assert saved_first is True
    assert saved_again is False
    assert again.id == first.id
    # Canonical content and its provenance metadata are immutable.
    assert again.content_json["title"] == "Your Soulmate Report"
    assert again.provider == "openai_compatible"
    assert again.model == "m1"


@pytest.mark.asyncio
async def test_db_constraint_admits_only_one_report_v1_row(async_db):
    sess = await _seed_entitled_session(async_db)
    row = await ReportService.get_report_artifact(async_db, sess.id)
    # Cache plain values before the failing commit: the subsequent rollback expires
    # ORM instances (expire_on_commit=False does not protect rollback), and touching
    # an expired attribute in async context raises MissingGreenlet.
    session_id = sess.id
    duplicate = SoulmateArtifact(
        session_id=session_id,
        email_normalized=row.email_normalized,
        artifact_type="REPORT",
        artifact_version="v1",
        unlock_at=row.unlock_at,
        generation_status="NOT_STARTED",
    )
    async_db.add(duplicate)
    with pytest.raises(IntegrityError):
        await async_db.commit()
    await async_db.rollback()
    # Exactly one canonical row survives.
    stmt = select(SoulmateArtifact).where(
        SoulmateArtifact.session_id == session_id,
        SoulmateArtifact.artifact_type == "REPORT",
    )
    rows = (await async_db.execute(stmt)).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_concurrent_saves_serialize_and_converge_on_one_content(async_db):
    sess = await _seed_entitled_session(async_db)
    payload_a = _report_payload(title="Report A")
    payload_b = _report_payload(title="Report B")

    async def save_from_own_session(payload):
        async with AsyncSessionLocal() as db:
            return await ReportService.save_completed_report(
                db, sess.id, payload, provider="openai_compatible", model="m"
            )

    results = await asyncio.gather(
        save_from_own_session(payload_a),
        save_from_own_session(payload_b),
    )
    saved_flags = [saved for _, saved in results]
    assert sorted(saved_flags) == [False, True]  # exactly one writer wins

    row = await ReportService.get_report_artifact(async_db, sess.id)
    assert row.generation_status == "COMPLETED"
    winner = results[0] if saved_flags[0] else results[1]
    assert row.content_json["title"] == winner[0].content_json["title"]


# ---------------------------------------------------------------------------
# Service: read-path validation (fail closed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_report_content_returns_none_until_completed(async_db):
    sess = await _seed_entitled_session(async_db, report_generation="PROCESSING")
    row = await ReportService.get_report_artifact(async_db, sess.id)
    assert ReportService.get_report_content(row) is None


@pytest.mark.asyncio
async def test_get_report_content_revalidates_stored_json(async_db):
    sess = await _seed_entitled_session(async_db, report_content=_report_payload())
    row = await ReportService.get_report_artifact(async_db, sess.id)
    row.generation_status = "COMPLETED"
    await async_db.commit()
    content = ReportService.get_report_content(row)
    assert content["schemaVersion"] == "v1"
    assert content["closing"] == "Trust the timing of your life."


@pytest.mark.asyncio
async def test_get_report_content_fails_closed_on_corrupt_stored_content(async_db):
    sess = await _seed_entitled_session(async_db, report_content={"unexpected": "payload"})
    row = await ReportService.get_report_artifact(async_db, sess.id)
    row.generation_status = "COMPLETED"
    await async_db.commit()
    from app.soulmate.domain.report import ReportValidationError

    with pytest.raises(ReportValidationError):
        ReportService.get_report_content(row)


# ---------------------------------------------------------------------------
# Config: §13.3 OpenAI-compatible provider surface (owner direction 2026-09-27)
# ---------------------------------------------------------------------------


def test_report_provider_config_falls_back_to_shared_openai(monkeypatch):
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-shared", raising=False)
    monkeypatch.setattr(settings, "soulmate_report_api_base_url", None, raising=False)
    monkeypatch.setattr(settings, "soulmate_report_api_key", None, raising=False)
    assert settings.report_api_base_url == "https://api.openai.com/v1"
    assert settings.report_api_key == "sk-shared"

    monkeypatch.setattr(
        settings, "soulmate_report_api_base_url", "https://relay.example.com/v1", raising=False
    )
    monkeypatch.setattr(settings, "soulmate_report_api_key", "sk-report", raising=False)
    assert settings.report_api_base_url == "https://relay.example.com/v1"
    assert settings.report_api_key == "sk-report"

    # Whitespace-only values behave like unset.
    monkeypatch.setattr(settings, "soulmate_report_api_base_url", "   ", raising=False)
    monkeypatch.setattr(settings, "soulmate_report_api_key", "", raising=False)
    assert settings.report_api_base_url == "https://api.openai.com/v1"
    assert settings.report_api_key == "sk-shared"


def test_report_generation_stays_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", None, raising=False)
    assert settings.is_report_generation_enabled is False


# ---------------------------------------------------------------------------
# API: authorized retrieval (SP-702 acceptance #2, §20, TIME-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_endpoint_requires_authentication(async_db):
    await _seed_entitled_session(async_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_report_endpoint_rejects_cross_session_idor(async_db):
    sess_a = await _seed_entitled_session(async_db)
    sess_b = await _seed_entitled_session(async_db)
    token_a = generate_session_token(sess_a.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_a)
        resp = await client.get(f"{REPORT_URL}?session_id={sess_b.public_id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_locked_report_returns_status_without_content(async_db):
    # COMPLETED content exists but unlock_at (= first_payment_at + 24h) is still in
    # the future because the payment is recent (TIME-01).
    sess = await _seed_entitled_session(
        async_db,
        paid_hours_ago=1.0,
        report_generation="COMPLETED",
        report_content=_report_payload(),
    )
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["status"] == "LOCKED"
    assert data["content"] is None
    assert data["server_time"] is not None


@pytest.mark.asyncio
async def test_unlocked_not_started_report_is_ready_without_content(async_db):
    sess = await _seed_entitled_session(async_db, report_generation="NOT_STARTED")
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(REPORT_URL)
    data = resp.json()
    assert data["report"]["status"] == "READY"
    assert data["content"] is None


@pytest.mark.asyncio
async def test_completed_unlocked_report_serves_validated_content(async_db):
    sess = await _seed_entitled_session(async_db, report_content=_report_payload())
    row = await ReportService.get_report_artifact(async_db, sess.id)
    row.generation_status = "COMPLETED"
    await async_db.commit()

    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["status"] == "COMPLETED"
    content = data["content"]
    assert content is not None
    assert content["schemaVersion"] == "v1"
    assert content["title"] == "Your Soulmate Report"
    assert content["sections"][0]["title"] == "Releasing the Fear of Being Alone"
    parse_soulmate_report_v1(content)  # served content conforms to the V1 contract


@pytest.mark.asyncio
async def test_corrupt_stored_content_fails_closed_with_validation_error(async_db):
    sess = await _seed_entitled_session(
        async_db, report_generation="COMPLETED", report_content={"not": "a report"}
    )
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_missing_artifact_rows_fail_closed_to_locked(async_db):
    sess = await _seed_entitled_session(async_db)
    await async_db.execute(
        delete(SoulmateArtifact).where(SoulmateArtifact.session_id == sess.id)
    )
    await async_db.commit()
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(REPORT_URL)
    data = resp.json()
    assert data["report"]["status"] == "LOCKED"
    assert data["content"] is None
