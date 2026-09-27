"""
Report on_demand generation tests (DEV-SPEC §13.3–13.4, §15.11; SP-706;
Decisions: REPORT-01, REPORT-02, TIME-01, PAY-AUTH-01, RECOVERY-01).

Acceptance criteria under test:
- POST /artifacts/report/generate gates: entitlement (PAY-AUTH-01), server unlock
  (TIME-01 on the persisted unlock_at), and the production switch
  (REPORT-01/02 — disabled deployments get 503 REPORT_GENERATION_DISABLED);
- enqueue is idempotent: one logical job per session V1 report, COMPLETED reports
  are never regenerated, concurrent triggers converge (unique idempotency key);
- the two-phase fenced worker: happy path persists validated content inside the
  fence; retryable provider failures requeue with backoff; permanent failures
  (contract-violating output, missing profile, unavailable template) terminate
  without a requeue; the completion guard skips the provider for completed reports;
- the REPORT job queue is independent of the sketch queue (job_type separation).
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateProfile, SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.profile import SoulmateProfileV1, build_soulmate_profile
from app.soulmate.domain.report_models import (
    ReportGenerationDisabledError,
    ReportGenerationInput,
)
from app.soulmate.security import generate_session_token
from app.soulmate.services.report_fixture import MOCK_REPORT_JSON
from app.soulmate.services.report_generation_service import (
    JOB_COMPLETED,
    JOB_FAILED_PERMANENT,
    JOB_FAILED_RETRYABLE,
    JOB_QUEUED,
    ReportGenerationService,
    report_idempotency_key,
)
from test_report_provider import _get_valid_answers_dict

GENERATE_URL = "/api/soulmate/artifacts/report/generate"
REPORT_URL = "/api/soulmate/artifacts/report"


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
def _enable_report_generation(monkeypatch):
    """The on_demand trigger requires the production switch; tests enable it."""
    monkeypatch.setattr(settings, "soulmate_report_provider", "openai_compatible", raising=False)
    monkeypatch.setattr(settings, "soulmate_report_prompt_version", "v1", raising=False)


@pytest.fixture(autouse=True)
async def purge_sp706_data():
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp706_%"))
        await db.execute(
            delete(AIGenerationJob).where(
                AIGenerationJob.artifact_id.in_(
                    select(SoulmateArtifact.id).where(SoulmateArtifact.session_id.in_(sess_ids))
                )
            )
        )
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateProfile).where(SoulmateProfile.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp706_%")))
        await db.commit()


async def _seed_generating_session(
    db: AsyncSession,
    *,
    paid_hours_ago: float = 30.0,
    with_profile: bool = True,
) -> SoulmateSession:
    """Entitled, unlocked paid session with a normalized profile and V1 placeholders."""
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(hours=paid_hours_ago)
    email = f"sp706_{uuid.uuid4().hex[:8]}@example.com"
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
            provider_subscription_id=f"I-SP706-{uuid.uuid4().hex[:8].upper()}",
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
            artifact_type="REPORT",
            artifact_version="v1",
            unlock_at=paid_at + timedelta(hours=24),
            generation_status="NOT_STARTED",
        )
    )
    if with_profile:
        from datetime import date

        profile = build_soulmate_profile(_get_valid_answers_dict())
        row = SoulmateProfile(
            session_id=sess.id,
            profile_version="v1",
            user_gender=profile.user_gender,
            preferred_partner_gender=profile.preferred_partner_gender,
            love_life_status=profile.love_life_status,
            preferred_partner_age_range=profile.preferred_partner_age_range,
            preferred_partner_ethnicity=profile.preferred_partner_ethnicity,
            key_soulmate_quality=profile.key_soulmate_quality,
            birth_date=date.fromisoformat(profile.birth_date),
            zodiac_sign=profile.zodiac_sign,
            element=profile.element,
            decision_style=profile.decision_style,
            personal_challenge=profile.personal_challenge,
            red_flag=profile.red_flag,
            similarity_preference=profile.similarity_preference,
            relationship_dynamic=profile.relationship_dynamic,
            love_language=profile.love_language,
            connection_style=profile.connection_style,
            relationship_fear=profile.relationship_fear,
            life_goals=profile.life_goals,
        )
        db.add(row)
    await db.commit()
    await db.refresh(sess)
    return sess


class _FakeProvider:
    """Scriptable SoulmateReportGenerator double for worker tests."""

    provider_name = "fake"

    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def generate(self, generation_input: ReportGenerationInput):
        self.calls += 1
        assert isinstance(generation_input, ReportGenerationInput)
        if self.error is not None:
            raise self.error
        return self.result


def _fake_result():
    from app.soulmate.domain.report import parse_soulmate_report_v1
    from app.soulmate.domain.report_models import ReportGenerationResult

    return ReportGenerationResult(
        report=parse_soulmate_report_v1(MOCK_REPORT_JSON),
        provider="fake",
        model="fake-model",
        prompt_version="v1",
        provider_request_id="req-fake-1",
        duration_ms=5,
    )


# ---------------------------------------------------------------------------
# Enqueue gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_requires_entitlement(async_db):
    from app.core.errors import ForbiddenOwnershipError

    now = datetime.now(timezone.utc)
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="EMAIL_CAPTURED",
        current_step="subscribe",
    )
    async_db.add(sess)
    await async_db.commit()
    with pytest.raises(ForbiddenOwnershipError):
        await ReportGenerationService.enqueue_report_generation(async_db, sess, now=now)


@pytest.mark.asyncio
async def test_enqueue_fails_closed_while_switch_off(async_db, monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", None, raising=False)
    sess = await _seed_generating_session(async_db)
    with pytest.raises(ReportGenerationDisabledError):
        await ReportGenerationService.enqueue_report_generation(async_db, sess)


@pytest.mark.asyncio
async def test_enqueue_is_unlock_gated_on_persisted_time(async_db, monkeypatch):
    from app.core.errors import LockedAssetError

    monkeypatch.setattr(
        settings, "soulmate_report_unlock_hours", 24, raising=False
    )  # hermetic default (conftest pins it anyway)
    sess = await _seed_generating_session(async_db, paid_hours_ago=1.0)  # unlock in the future
    with pytest.raises(LockedAssetError):
        await ReportGenerationService.enqueue_report_generation(async_db, sess)


@pytest.mark.asyncio
async def test_enqueue_creates_one_job_and_converges(async_db):
    sess = await _seed_generating_session(async_db)
    first = await ReportGenerationService.enqueue_report_generation(async_db, sess)
    assert first.created is True
    assert first.job.status == JOB_QUEUED
    assert first.job.job_type == "SOULMATE_REPORT"
    assert first.job.idempotency_key == report_idempotency_key(sess.id, "v1")

    second = await ReportGenerationService.enqueue_report_generation(async_db, sess)
    assert second.created is False
    assert second.job.id == first.job.id

    jobs = (
        (
            await async_db.execute(
                select(AIGenerationJob).where(AIGenerationJob.job_type == "SOULMATE_REPORT")
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_enqueue_never_regenerates_completed_report(async_db):
    sess = await _seed_generating_session(async_db)
    row = (
        await async_db.execute(
            select(SoulmateArtifact).where(
                SoulmateArtifact.session_id == sess.id,
                SoulmateArtifact.artifact_type == "REPORT",
            )
        )
    ).scalars().first()
    row.generation_status = "COMPLETED"
    row.content_json = {"schemaVersion": "v1", "title": "T", "intro": "I",
                        "sections": [{"index": "01.", "title": "S", "body": "B"}]}
    await async_db.commit()

    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)
    assert outcome.created is False
    assert outcome.job is None


# ---------------------------------------------------------------------------
# Worker: fenced two-phase processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_happy_path_persists_validated_content(async_db):
    sess = await _seed_generating_session(async_db)
    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)

    status = await ReportGenerationService.process_next_queued_job(
        provider=_FakeProvider(result=_fake_result()), job_id=outcome.job.id
    )
    assert status == JOB_COMPLETED

    await async_db.refresh(outcome.artifact)
    assert outcome.artifact.generation_status == "COMPLETED"
    assert outcome.artifact.content_json["schemaVersion"] == "v1"
    assert outcome.artifact.content_json["title"].startswith("[MOCK]")
    assert outcome.artifact.provider == "fake"
    assert outcome.artifact.model == "fake-model"
    assert outcome.artifact.prompt_version == "v1"
    assert outcome.artifact.provider_request_id == "req-fake-1"


@pytest.mark.asyncio
async def test_worker_retryable_error_requeues_then_budget_exhausts(async_db, monkeypatch):
    import httpx

    from app.soulmate.domain.report_models import ReportProviderError

    sess = await _seed_generating_session(async_db)
    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)

    provider = _FakeProvider(
        error=ReportProviderError(
            "provider overloaded", retryable=True, provider_code="429"
        )
    )
    monkeypatch.setattr(settings, "job_retry_max_attempts", 2, raising=False)
    monkeypatch.setattr(settings, "job_retry_base_backoff_seconds", 0.0, raising=False)

    s1 = await ReportGenerationService.process_next_queued_job(provider=provider, job_id=outcome.job.id)
    assert s1 == JOB_QUEUED  # attempt 1/2 requeued
    s2 = await ReportGenerationService.process_next_queued_job(provider=provider, job_id=outcome.job.id)
    assert s2 == JOB_FAILED_RETRYABLE  # attempt 2/2 exhausts the budget
    await async_db.refresh(outcome.artifact)
    assert outcome.artifact.generation_status == "FAILED"
    # The terminal code is the LAST real failure's code; ATTEMPT_BUDGET_EXHAUSTED
    # is only written by the crash-loop claim path (claims without failure reports).
    assert outcome.artifact.last_error_code == "PROVIDER_UNAVAILABLE"
    assert provider.calls == 2  # the exhausted final claim never reaches the provider


@pytest.mark.asyncio
async def test_worker_permanent_error_terminates_immediately(async_db):
    from app.soulmate.domain.report_models import ReportProviderError

    sess = await _seed_generating_session(async_db)
    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)

    provider = _FakeProvider(
        error=ReportProviderError("output violated the contract", retryable=False)
    )
    status = await ReportGenerationService.process_next_queued_job(provider=provider, job_id=outcome.job.id)
    assert status == JOB_FAILED_PERMANENT
    await async_db.refresh(outcome.artifact)
    assert outcome.artifact.generation_status == "FAILED"


@pytest.mark.asyncio
async def test_worker_missing_profile_fails_permanently(async_db):
    sess = await _seed_generating_session(async_db, with_profile=False)
    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)
    provider = _FakeProvider(result=_fake_result())
    status = await ReportGenerationService.process_next_queued_job(provider=provider, job_id=outcome.job.id)
    assert status == JOB_FAILED_PERMANENT
    assert provider.calls == 0  # invalid input never reaches the provider
    await async_db.refresh(outcome.artifact)
    assert outcome.artifact.generation_status == "FAILED"


@pytest.mark.asyncio
async def test_worker_completion_guard_skips_provider(async_db):
    sess = await _seed_generating_session(async_db)
    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)
    # Complete the artifact behind the worker's back (e.g. a winning concurrent attempt).
    row = (
        await async_db.execute(
            select(SoulmateArtifact).where(SoulmateArtifact.id == outcome.artifact.id)
        )
    ).scalars().first()
    row.generation_status = "COMPLETED"
    row.content_json = {"schemaVersion": "v1", "title": "Winner", "intro": "I",
                        "sections": [{"index": "01.", "title": "S", "body": "B"}]}
    await async_db.commit()

    provider = _FakeProvider(result=_fake_result())
    status = await ReportGenerationService.process_next_queued_job(provider=provider, job_id=outcome.job.id)
    assert status == JOB_COMPLETED
    assert provider.calls == 0
    await async_db.refresh(row)
    assert row.content_json["title"] == "Winner"  # no-clobber


@pytest.mark.asyncio
async def test_worker_contract_violating_output_fails_permanently(async_db):
    from app.soulmate.domain.report import parse_soulmate_report_v1
    from app.soulmate.domain.report_models import ReportGenerationResult

    bad = parse_soulmate_report_v1(MOCK_REPORT_JSON).model_copy(deep=True)
    object.__setattr__(bad, "__dict__", {**bad.__dict__, "title": "<script>alert(1)</script>"})
    sess = await _seed_generating_session(async_db)
    outcome = await ReportGenerationService.enqueue_report_generation(async_db, sess)

    provider = _FakeProvider(
        result=ReportGenerationResult(
            report=bad, provider="fake", model="m", prompt_version="v1", duration_ms=1
        )
    )
    status = await ReportGenerationService.process_next_queued_job(provider=provider, job_id=outcome.job.id)
    assert status == JOB_FAILED_PERMANENT
    await async_db.refresh(outcome.artifact)
    assert outcome.artifact.generation_status == "FAILED"
    assert outcome.artifact.content_json is None  # nothing persisted


# ---------------------------------------------------------------------------
# Endpoint (§15.11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_endpoint_queues_for_entitled_unlocked_session(async_db):
    sess = await _seed_generating_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.post(GENERATE_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_status"] == JOB_QUEUED
    assert data["report"]["status"] in ("GENERATING", "QUEUED", "READY")


@pytest.mark.asyncio
async def test_generate_endpoint_requires_authentication(async_db):
    await _seed_generating_session(async_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(GENERATE_URL)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_generate_endpoint_rejects_cross_session(async_db):
    sess_a = await _seed_generating_session(async_db)
    sess_b = await _seed_generating_session(async_db)
    token_a = generate_session_token(sess_a.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_a)
        resp = await client.post(f"{GENERATE_URL}?session_id={sess_b.public_id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_generate_endpoint_locked_returns_423(async_db):
    from app.core.errors import LockedAssetError

    assert LockedAssetError().status_code == 423
    sess = await _seed_generating_session(async_db, paid_hours_ago=1.0)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.post(GENERATE_URL)
    assert resp.status_code == 423


@pytest.mark.asyncio
async def test_generate_endpoint_disabled_returns_503(async_db, monkeypatch):
    monkeypatch.setattr(settings, "soulmate_report_provider", None, raising=False)
    sess = await _seed_generating_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.post(GENERATE_URL)
    assert resp.status_code == 503
    assert resp.json()["error_code"] == "PROVIDER_UNAVAILABLE"
    assert resp.json()["details"]["reason"] == "REPORT_GENERATION_DISABLED"
