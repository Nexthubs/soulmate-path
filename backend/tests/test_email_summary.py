"""Comprehensive automated tests for Email Capture summary view model (SP-302, DEV-SPEC §8.1, Decisions: QUIZ-01)."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.db.models.session import SoulmateAnswer, SoulmateProfile, SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.soulmate.domain.email_summary import (
    build_email_summary,
    format_age_range_label,
    format_ethnicity_label,
    format_gender_label,
    get_default_email_summary,
)
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.security import generate_session_token


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ============================================================================
# 1. Pure Domain Logic & Label Formatting Tests (SP-302 Acceptance)
# ============================================================================


def test_gender_label_formatting():
    assert format_gender_label("male") == "Male"
    assert format_gender_label("female") == "Female"
    assert format_gender_label(None) == "Female"


def test_age_range_label_formatting():
    assert format_age_range_label("age_20_30") == "20-30"
    assert format_age_range_label("age_30_40") == "30-40"
    assert format_age_range_label("age_40_50") == "40-50"
    assert format_age_range_label("age_50_plus") == "50+"
    assert format_age_range_label("30-40") == "30-40"
    assert format_age_range_label(None) == "30-40"


def test_ethnicity_label_formatting():
    assert format_ethnicity_label("hispanic_latino") == "Latino"
    assert format_ethnicity_label("caucasian_white") == "Caucasian"
    assert format_ethnicity_label("african_african_american") == "African"
    assert format_ethnicity_label("asian") == "Asian"
    assert format_ethnicity_label("no_preference") == "Any"
    assert format_ethnicity_label(None) == "Latino"


def test_quiz_01_gender_invariant_in_email_summary():
    """
    STRICT INVARIANT (Decision QUIZ-01):
    The visual_variant and partner_gender must be strictly determined by Q03 (preferred_partner_gender).
    Q02 (user_gender) must NEVER dictate the visual variant.
    """
    # Case 1: user female (Q02), partner male (Q03) -> variant male
    summary_1 = build_email_summary(
        preferred_partner_gender="male",
        user_gender="female",
        preferred_partner_age_range="age_30_40",
        preferred_partner_ethnicity="hispanic_latino",
    )
    assert summary_1.visual_variant == "male"
    assert summary_1.gender_display == "Male"
    assert summary_1.partner_gender.code == "male"
    assert summary_1.partner_gender.label == "Male"
    assert summary_1.user_gender == "female"

    # Case 2: user male (Q02), partner female (Q03) -> variant female
    summary_2 = build_email_summary(
        preferred_partner_gender="female",
        user_gender="male",
        preferred_partner_age_range="age_20_30",
        preferred_partner_ethnicity="asian",
    )
    assert summary_2.visual_variant == "female"
    assert summary_2.gender_display == "Female"
    assert summary_2.partner_gender.code == "female"
    assert summary_2.partner_gender.label == "Female"
    assert summary_2.user_gender == "male"

    # Case 3: user male (Q02), partner male (Q03) -> variant male
    summary_3 = build_email_summary(
        preferred_partner_gender="male",
        user_gender="male",
    )
    assert summary_3.visual_variant == "male"
    assert summary_3.gender_display == "Male"

    # Case 4: user female (Q02), partner female (Q03) -> variant female
    summary_4 = build_email_summary(
        preferred_partner_gender="female",
        user_gender="female",
    )
    assert summary_4.visual_variant == "female"
    assert summary_4.gender_display == "Female"


def test_default_sample_email_summary():
    """Default summary returns demo preview with is_sample_data=True."""
    default_summary = get_default_email_summary()
    assert default_summary.is_sample_data is True
    assert default_summary.visual_variant == "female"
    assert default_summary.gender_display == "Female"
    assert default_summary.age_range_display == "30-40"
    assert default_summary.ethnicity_display == "Latino"


# ============================================================================
# 2. Integration / API Endpoint Tests (GET /sessions/{id}/email-summary)
# ============================================================================


@pytest.mark.asyncio
async def test_get_email_summary_from_profile_success(db_session):
    """
    Acceptance:
    Returns display-ready Q3/Q5/Q6 values or equivalent normalized profile fields,
    without frontend guessing labels from raw codes.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create session
        create_res = await client.post("/api/soulmate/sessions", json={})
        assert create_res.status_code == 201
        session_id = create_res.json()["session_id"]

        # 2. Populate SoulmateProfile
        rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        profile = SoulmateProfile(
            session_id=rec.id,
            user_gender="female",
            preferred_partner_gender="male",
            preferred_partner_age_range="age_40_50",
            preferred_partner_ethnicity="african_african_american",
        )
        db_session.add(profile)
        db_session.commit()

        # 3. Request email summary via public_id endpoint
        res = await client.get(f"/api/soulmate/sessions/{session_id}/email-summary")
        assert res.status_code == 200
        data = res.json()

        assert data["visual_variant"] == "male"
        assert data["gender_display"] == "Male"
        assert data["age_range_display"] == "40-50"
        assert data["ethnicity_display"] == "African"
        assert data["is_sample_data"] is False
        assert data["user_gender"] == "female"

        # Check structured badge items
        assert data["partner_gender"]["code"] == "male"
        assert data["partner_gender"]["label"] == "Male"
        assert data["partner_age_range"]["code"] == "age_40_50"
        assert data["partner_age_range"]["label"] == "40-50"
        assert data["partner_ethnicity"]["code"] == "african_african_american"
        assert data["partner_ethnicity"]["label"] == "African"


@pytest.mark.asyncio
async def test_get_current_email_summary_endpoint_success(db_session):
    """GET /api/soulmate/sessions/current/email-summary recovers summary for active cookie session."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        profile = SoulmateProfile(
            session_id=rec.id,
            user_gender="male",
            preferred_partner_gender="female",
            preferred_partner_age_range="age_20_30",
            preferred_partner_ethnicity="asian",
        )
        db_session.add(profile)
        db_session.commit()

        # Call /current/email-summary
        res = await client.get("/api/soulmate/sessions/current/email-summary")
        assert res.status_code == 200
        data = res.json()

        assert data["visual_variant"] == "female"
        assert data["gender_display"] == "Female"
        assert data["age_range_display"] == "20-30"
        assert data["ethnicity_display"] == "Asian"
        assert data["is_sample_data"] is False


@pytest.mark.asyncio
async def test_get_email_summary_from_answers_when_profile_not_materialized(db_session):
    """If profile row is not yet materialized, extracts Q3/Q5/Q6 answers from soulmate_answers."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        ans_q02 = SoulmateAnswer(
            session_id=rec.id,
            question_code="q02",
            answer_json={"value": "female"},
        )
        ans_q03 = SoulmateAnswer(
            session_id=rec.id,
            question_code="q03",
            answer_json={"value": "male"},
        )
        ans_q05 = SoulmateAnswer(
            session_id=rec.id,
            question_code="q05",
            answer_json={"value": "age_50_plus"},
        )
        ans_q06 = SoulmateAnswer(
            session_id=rec.id,
            question_code="q06",
            answer_json={"value": "caucasian_white"},
        )
        db_session.add_all([ans_q02, ans_q03, ans_q05, ans_q06])
        db_session.commit()

        res = await client.get(f"/api/soulmate/sessions/{session_id}/email-summary")
        assert res.status_code == 200
        data = res.json()

        assert data["visual_variant"] == "male"
        assert data["gender_display"] == "Male"
        assert data["age_range_display"] == "50+"
        assert data["ethnicity_display"] == "Caucasian"
        assert data["is_sample_data"] is False


@pytest.mark.asyncio
async def test_get_email_summary_unanswered_session_returns_sample_data():
    """Unanswered session returns default demo preview with is_sample_data=True."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        res = await client.get(f"/api/soulmate/sessions/{session_id}/email-summary")
        assert res.status_code == 200
        data = res.json()

        assert data["is_sample_data"] is True
        assert data["visual_variant"] == "female"
        assert data["gender_display"] == "Female"
        assert data["age_range_display"] == "30-40"
        assert data["ethnicity_display"] == "Latino"


# ============================================================================
# 3. Security, IDOR, and Failure Path Tests (DEV-SPEC §20)
# ============================================================================


@pytest.mark.asyncio
async def test_idor_cross_session_email_summary_rejected():
    """IDOR Guard: user A cannot access user B's email summary by ID (403 FORBIDDEN_OWNERSHIP)."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client_b:
        res_b = await client_b.post("/api/soulmate/sessions", json={})
        session_b_id = res_b.json()["session_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client_a:
        res_a = await client_a.post("/api/soulmate/sessions", json={})
        session_a_id = res_a.json()["session_id"]
        assert session_a_id != session_b_id

        cross_res = await client_a.get(f"/api/soulmate/sessions/{session_b_id}/email-summary")
        assert cross_res.status_code == 403
        assert cross_res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_unauthenticated_email_summary_rejected():
    """Calling email-summary without credentials returns 403 FORBIDDEN_OWNERSHIP."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/soulmate/sessions/ses_unauthenticated/email-summary")
        assert res.status_code == 403
        assert res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_nonexistent_session_with_valid_token_returns_404():
    """Validly signed token for a non-existent session returns 404 NOT_FOUND."""
    transport = ASGITransport(app=app)
    ghost_id = f"ses_{uuid.uuid4().hex[:16]}"
    valid_token = generate_session_token(ghost_id)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(settings.session_cookie_name, valid_token)
        res = await client.get(f"/api/soulmate/sessions/{ghost_id}/email-summary")
        assert res.status_code == 404
        assert res.json()["error_code"] == "NOT_FOUND"
