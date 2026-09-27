"""
Canonical report mock fixture tests (SP-705; DEV-SPEC §13.2–13.3; Decisions: REPORT-01, REPORT-02).

Acceptance criteria under test:
- fixture is clearly non-production/test content ([MOCK] labels, REPORT-01/02 pointers);
- supports renderer and E2E testing: the fixture validates against the ReportV1
  contract, drives the mock provider, and survives the full store→retrieve chain
  (ReportService.save_completed_report → GET /api/soulmate/artifacts/report);
- does not pretend to be an actual personalized reading (no profile-derived claims
  beyond the labeled input echo).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.profile import build_soulmate_profile
from app.soulmate.domain.report import parse_soulmate_report_v1
from app.soulmate.domain.report_models import ReportGenerationInput
from app.soulmate.security import generate_session_token
from app.soulmate.services.report_fixture import (
    MOCK_REPORT_INTRO,
    MOCK_REPORT_JSON,
    MOCK_REPORT_TITLE,
    build_mock_report,
)
from app.soulmate.services.report_providers import MockReportProvider, build_report_provider
from app.soulmate.services.report_service import ReportService
from test_report_provider import _get_valid_answers_dict

REPORT_URL = "/api/soulmate/artifacts/report"


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
async def purge_sp705_data():
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp705_%"))
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp705_%")))
        await db.commit()


# ---------------------------------------------------------------------------
# Non-production content guarantees
# ---------------------------------------------------------------------------


def test_fixture_is_unmistakably_non_production():
    assert MOCK_REPORT_TITLE.startswith("[MOCK]")
    assert "Not a Real Reading" in MOCK_REPORT_TITLE
    assert "REPORT-01" in MOCK_REPORT_INTRO and "REPORT-02" in MOCK_REPORT_INTRO
    assert MOCK_REPORT_JSON["closing"].startswith("[MOCK]")


def test_fixture_validates_against_reportv1_contract():
    report = parse_soulmate_report_v1(MOCK_REPORT_JSON)
    assert report.schema_version == "v1"
    assert [s.index for s in report.sections] == ["01.", "02."]
    assert report.sections[0].points  # optional points present for renderer coverage
    assert report.closing  # closing present for renderer coverage


def test_fixture_is_deterministic():
    assert build_mock_report() == build_mock_report()
    assert build_mock_report().model_dump(by_alias=True, exclude_none=True) == json.loads(
        json.dumps(MOCK_REPORT_JSON)
    )


def test_profile_echo_consumes_normalized_profile_and_respects_quiz01():
    profile = build_soulmate_profile(
        {
            "q02": {"value": "female"},
            "q03": {"value": "male"},
            "q05": {"value": "age_20_30"},
            "q07": {"value": "loyalty"},
            # remaining required answers mirror the shared fixture
            "q04": {"value": "single"},
            "q06": {"value": "asian"},
            "q08": {"value": "1994-08-25"},
            "q09": {"value": "fire"},
            "q10": {"value": "heart"},
            "q11": {"value": "building_trust"},
            "q12": {"value": "lack_of_trust"},
            "q13": {"value": "similar_to_me"},
            "q14": {"value": "deep_connection"},
            "q15": {"value": "words_of_affirmation"},
            "q16": {"value": "deep_and_intimate"},
            "q17": {"value": "losing_trust"},
            "q18": {"values": ["building_a_family", "traveling_the_world"]},
        }
    )
    report = build_mock_report(profile=profile)
    body = report.sections[0].body
    assert "'male'" in body  # Q03 preferred_partner_gender (QUIZ-01)
    assert "age_20_30" in body
    assert "loyalty" in body
    assert report.sections[1].title == MOCK_REPORT_JSON["sections"][1]["title"]


@pytest.mark.asyncio
async def test_mock_provider_renders_the_canonical_fixture():
    """SP-704's mock provider and SP-705's fixture are one source of truth."""
    profile = build_soulmate_profile(_get_valid_answers_dict())
    result = await MockReportProvider().generate(
        ReportGenerationInput(profile=profile, prompt_version="v1")
    )
    assert result.report == build_mock_report(profile=profile)


# ---------------------------------------------------------------------------
# E2E chain: fixture → persistence → authorized retrieval (M5 exit criterion)
# ---------------------------------------------------------------------------


async def _seed_entitled_session(db: AsyncSession):
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(hours=30)
    email = f"sp705_{uuid.uuid4().hex[:8]}@example.com"
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
            provider_subscription_id=f"I-SP705-{uuid.uuid4().hex[:8].upper()}",
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
    await db.commit()
    return sess


@pytest.mark.asyncio
async def test_fixture_survives_store_and_retrieve_chain(async_db):
    sess = await _seed_entitled_session(async_db)
    artifact, saved = await ReportService.save_completed_report(
        async_db, sess.id, MOCK_REPORT_JSON,
        provider="mock", model="mock", prompt_version="v1",
    )
    assert saved is True
    assert artifact.generation_status == "COMPLETED"

    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(REPORT_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["status"] == "COMPLETED"
    content = data["content"]
    assert content["schemaVersion"] == "v1"
    assert content["title"] == MOCK_REPORT_TITLE
    assert content["sections"][0]["points"][0]["title"] == "Deterministic"
    assert content["closing"] == "[MOCK] End of test fixture."
    parse_soulmate_report_v1(content)  # served fixture content conforms


@pytest.mark.asyncio
async def test_factory_mock_provider_output_persists_end_to_end(async_db, monkeypatch):
    """The pluggable mock provider (factory-built) drives the same chain."""
    monkeypatch.setattr(settings, "soulmate_report_provider", "mock", raising=False)
    provider = build_report_provider()
    profile = build_soulmate_profile(_get_valid_answers_dict())
    result = await provider.generate(
        ReportGenerationInput(profile=profile, prompt_version="v1")
    )

    sess = await _seed_entitled_session(async_db)
    artifact, saved = await ReportService.save_completed_report(
        async_db, sess.id, result.report,
        provider=result.provider, model=result.model, prompt_version=result.prompt_version,
    )
    assert saved is True
    assert artifact.content_json["title"].startswith("[MOCK]")
