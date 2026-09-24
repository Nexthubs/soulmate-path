"""Comprehensive automated tests for Email capture, normalization, and identity binding (SP-301, DEV-SPEC §8, §15.5, §20)."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import ValidationError
from app.db.models.session import SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.soulmate.domain.identity import (
    derive_user_id_for_email,
    validate_and_normalize_email,
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
# 1. Pure Domain Logic Tests: validate_and_normalize_email & derive_user_id
# ============================================================================


def test_email_validation_and_normalization_success():
    """Acceptance: validates format and normalizes email consistently."""
    test_cases = [
        ("  user@example.com  ", "user@example.com", "user@example.com"),
        ("ALICE.SMITH+tag@GMAIL.COM", "ALICE.SMITH+tag@GMAIL.COM", "alice.smith+tag@gmail.com"),
        ("john-doe_123@sub.domain.co.uk", "john-doe_123@sub.domain.co.uk", "john-doe_123@sub.domain.co.uk"),
        ("customer.service@company.org", "customer.service@company.org", "customer.service@company.org"),
    ]

    for input_val, expected_raw, expected_norm in test_cases:
        raw, norm = validate_and_normalize_email(input_val)
        assert raw == expected_raw
        assert norm == expected_norm


def test_email_validation_rejects_invalid_formats():
    """Validation rejects empty, malformed, or out-of-spec email addresses."""
    invalid_inputs = [
        "",
        "   ",
        "invalid",
        "@example.com",
        "user@",
        "user@.com",
        "user@com",
        "user@example..com",
        "user name@example.com",
        "user@domain@another.com",
        "a" * 65 + "@example.com",  # Local part > 64 chars
        "user@" + "a" * 256 + ".com",  # Domain > 255 chars
    ]

    for bad_email in invalid_inputs:
        with pytest.raises(ValidationError):
            validate_and_normalize_email(bad_email)


def test_derive_user_id_for_email_deterministic():
    """
    Acceptance: normalized identity is consistent for later one-email-one-sketch logic;
    derive_user_id_for_email generates deterministic, stable UUIDv5.
    """
    email_a = "soulmate.seeker@example.com"
    email_b = "SOULMATE.SEEKER@example.com"

    _, norm_a = validate_and_normalize_email(email_a)
    _, norm_b = validate_and_normalize_email(email_b)

    id_a1 = derive_user_id_for_email(norm_a)
    id_a2 = derive_user_id_for_email(norm_a)
    id_b = derive_user_id_for_email(norm_b)

    assert id_a1 == id_a2
    assert id_a1 == id_b
    assert isinstance(id_a1, uuid.UUID)

    # Different emails derive different UUIDs
    different_id = derive_user_id_for_email("other.person@example.com")
    assert id_a1 != different_id


# ============================================================================
# 2. Integration / API Endpoint Tests (POST /sessions/{id}/email)
# ============================================================================


@pytest.mark.asyncio
async def test_capture_email_and_bind_identity_success(db_session):
    """
    Acceptance:
    - POST /api/soulmate/sessions/:sessionId/email persists email and email_normalized.
    - Binds anonymous session to consistent user identity (user_id).
    - Advances status to EMAIL_CAPTURED.
    - Advances current_step to subscribe if currently at email.
    - Returns {ok: True, next: "/soulmate/subscribe"}.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create anonymous session
        create_res = await client.post("/api/soulmate/sessions", json={})
        assert create_res.status_code == 201
        session_id = create_res.json()["session_id"]

        # 2. Set current_step to email in DB to test step advance
        rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()
        rec.current_step = "email"
        rec.status = SessionStatus.QUIZ_COMPLETED.value
        db_session.commit()

        # 3. Submit email
        suffix = uuid.uuid4().hex[:8]
        raw_input = f"  Test.User_{suffix}@EXAMPLE.com  "
        expected_norm = f"test.user_{suffix}@example.com"
        response = await client.post(
            f"/api/soulmate/sessions/{session_id}/email",
            json={"email": raw_input},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["next"] == "/soulmate/subscribe"

        # 4. Verify DB persistence
        db_session.expire_all()
        updated_rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        assert updated_rec.email == f"Test.User_{suffix}@EXAMPLE.com"
        assert updated_rec.email_normalized == expected_norm
        assert updated_rec.email_captured_at is not None
        assert updated_rec.status == SessionStatus.EMAIL_CAPTURED.value
        assert updated_rec.current_step == "subscribe"
        assert updated_rec.user_id is not None
        assert updated_rec.user_id == derive_user_id_for_email(expected_norm)


@pytest.mark.asyncio
async def test_identity_consistency_across_multiple_sessions(db_session):
    """
    Acceptance:
    - Multiple sessions capturing the same email (with varying case/spaces) bind to the exact same user_id.
    - Enables downstream one-email-one-sketch enforcement without session collisions.
    """
    transport = ASGITransport(app=app)
    suffix = uuid.uuid4().hex[:8]
    email_a = f"Seeker_{suffix}@Domain.COM"
    email_b = f"  seeker_{suffix}@domain.com  "
    expected_norm = f"seeker_{suffix}@domain.com"

    # Session 1
    async with AsyncClient(transport=transport, base_url="http://test") as client_1:
        res1 = await client_1.post("/api/soulmate/sessions", json={})
        session1_id = res1.json()["session_id"]

        res_email1 = await client_1.post(
            f"/api/soulmate/sessions/{session1_id}/email",
            json={"email": email_a},
        )
        assert res_email1.status_code == 200

    # Session 2 (distinct browser/token)
    async with AsyncClient(transport=transport, base_url="http://test") as client_2:
        res2 = await client_2.post("/api/soulmate/sessions", json={})
        session2_id = res2.json()["session_id"]
        assert session2_id != session1_id

        res_email2 = await client_2.post(
            f"/api/soulmate/sessions/{session2_id}/email",
            json={"email": email_b},
        )
        assert res_email2.status_code == 200

    # Verify both sessions share the exact same user_id and email_normalized
    rec1 = db_session.execute(
        select(SoulmateSession).where(SoulmateSession.public_id == session1_id)
    ).scalar_one()
    rec2 = db_session.execute(
        select(SoulmateSession).where(SoulmateSession.public_id == session2_id)
    ).scalar_one()

    assert rec1.email_normalized == expected_norm
    assert rec2.email_normalized == expected_norm
    assert rec1.user_id == rec2.user_id


@pytest.mark.asyncio
async def test_existing_user_id_reused_from_prior_session(db_session):
    """
    When an existing session with the same normalized email already has a user_id,
    a subsequent session reuses that user_id rather than generating a disjoint identity.
    """
    transport = ASGITransport(app=app)
    custom_user_id = uuid.uuid4()
    unique_email = f"prior_{uuid.uuid4().hex[:8]}@example.com"

    # Pre-populate prior session with custom user_id
    prior_session = SoulmateSession(
        public_id=f"ses_{uuid.uuid4().hex[:16]}",
        user_id=custom_user_id,
        email=unique_email,
        email_normalized=unique_email.lower(),
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.EMAIL_CAPTURED.value,
        current_step="subscribe",
    )
    db_session.add(prior_session)
    db_session.commit()

    # New session enters the same email (with uppercase)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        new_session_id = create_res.json()["session_id"]

        email_res = await client.post(
            f"/api/soulmate/sessions/{new_session_id}/email",
            json={"email": unique_email.upper()},
        )
        assert email_res.status_code == 200

    new_rec = db_session.execute(
        select(SoulmateSession).where(SoulmateSession.public_id == new_session_id)
    ).scalar_one()
    assert new_rec.user_id == custom_user_id


@pytest.mark.asyncio
async def test_re_capturing_email_in_same_session_is_idempotent(db_session):
    """Submitting email multiple times or editing email in the same session succeeds idempotently."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # First capture
        res1 = await client.post(
            f"/api/soulmate/sessions/{session_id}/email",
            json={"email": "first@example.com"},
        )
        assert res1.status_code == 200

        # Second capture (updated email)
        res2 = await client.post(
            f"/api/soulmate/sessions/{session_id}/email",
            json={"email": "second@example.com"},
        )
        assert res2.status_code == 200
        assert res2.json()["ok"] is True

    rec = db_session.execute(
        select(SoulmateSession).where(SoulmateSession.public_id == session_id)
    ).scalar_one()
    assert rec.email == "second@example.com"
    assert rec.email_normalized == "second@example.com"


# ============================================================================
# 3. Security, IDOR, and Failure Path Tests (DEV-SPEC §20)
# ============================================================================


@pytest.mark.asyncio
async def test_idor_cross_session_email_binding_rejected():
    """
    Acceptance: user cannot bind another user's session by ID (DEV-SPEC §20).
    Client A holding cookie A attempting to bind email on Session B triggers 403 FORBIDDEN_OWNERSHIP.
    """
    transport = ASGITransport(app=app)

    # 1. Create Session B
    async with AsyncClient(transport=transport, base_url="http://test") as client_b:
        res_b = await client_b.post("/api/soulmate/sessions", json={})
        session_b_id = res_b.json()["session_id"]

    # 2. Create Session A and attempt to modify Session B
    async with AsyncClient(transport=transport, base_url="http://test") as client_a:
        res_a = await client_a.post("/api/soulmate/sessions", json={})
        session_a_id = res_a.json()["session_id"]
        assert session_a_id != session_b_id

        # Malicious cross-session email binding attempt
        cross_res = await client_a.post(
            f"/api/soulmate/sessions/{session_b_id}/email",
            json={"email": "attacker@example.com"},
        )

        assert cross_res.status_code == 403
        data = cross_res.json()
        assert data["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_unauthenticated_email_submission_rejected():
    """Calling email capture endpoint without session authentication triggers 403."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/soulmate/sessions/ses_unauthenticated/email",
            json={"email": "test@example.com"},
        )
        assert res.status_code == 403
        assert res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_tampered_signature_email_submission_rejected():
    """Tampered session token signature triggers 403 FORBIDDEN_OWNERSHIP."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # Forge token
        client.cookies.set(
            settings.session_cookie_name,
            f"{session_id}.1774000000.tampered_signature",
        )

        res = await client.post(
            f"/api/soulmate/sessions/{session_id}/email",
            json={"email": "test@example.com"},
        )
        assert res.status_code == 403
        assert res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_invalid_email_format_returns_validation_error():
    """Invalid email payload returns 400 or 422 with structured validation error."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        res = await client.post(
            f"/api/soulmate/sessions/{session_id}/email",
            json={"email": "not_an_email"},
        )
        assert res.status_code in (400, 422)
        assert "VALIDATION" in res.json().get("error_code", "")


@pytest.mark.asyncio
async def test_nonexistent_session_with_valid_token_returns_404():
    """Validly signed token for a deleted or nonexistent session returns 404."""
    transport = ASGITransport(app=app)
    ghost_id = f"ses_{uuid.uuid4().hex[:16]}"
    ghost_token = generate_session_token(ghost_id)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(settings.session_cookie_name, ghost_token)
        res = await client.post(
            f"/api/soulmate/sessions/{ghost_id}/email",
            json={"email": "valid@example.com"},
        )
        assert res.status_code == 404
        assert res.json()["error_code"] == "NOT_FOUND"
