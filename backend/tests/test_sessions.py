"""Comprehensive automated tests for Soulmate Session Create / Recover (SP-201, DEV-SPEC §6, §15.1, §20)."""

import time
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.core.config import settings
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.quiz.constants import CANONICAL_QUIZ_VERSION
from app.soulmate.domain.session_state import INITIAL_SESSION_STATUS, INITIAL_STEP_CODE
from app.soulmate.security import generate_session_token


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.mark.asyncio
async def test_create_anonymous_session(db_session):
    """
    Acceptance: create anonymous session;
    - persists soulmate_sessions record;
    - pins quiz_version to canonical version;
    - initial step is transition_0;
    - status is CREATED;
    - sets secure HttpOnly cookie soulmate_sid.
    """
    transport = ASGITransport(app=app)
    utm_payload = {"utm_source": "meta", "utm_campaign": "fall_2026"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/soulmate/sessions",
            json={"utm_json": utm_payload},
        )

    assert response.status_code == 201
    data = response.json()

    session_id = data["session_id"]
    assert session_id.startswith("ses_")
    assert data["quiz_version"] == CANONICAL_QUIZ_VERSION
    assert data["current_step"] == INITIAL_STEP_CODE
    assert data["status"] == INITIAL_SESSION_STATUS.value

    # Verify Set-Cookie header contains soulmate_sid and security directives
    set_cookie_header = response.headers.get("set-cookie", "")
    assert settings.session_cookie_name in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Path=/" in set_cookie_header
    assert "samesite=lax" in set_cookie_header.lower()

    # Verify custom header exists for API/test clients
    token_header = response.headers.get("X-Soulmate-Session-Token")
    assert token_header is not None
    assert token_header.startswith(session_id)

    # Verify physical database persistence
    db_session_record = db_session.execute(
        select(SoulmateSession).where(SoulmateSession.public_id == session_id)
    ).scalar_one_or_none()

    assert db_session_record is not None
    assert db_session_record.public_id == session_id
    assert db_session_record.quiz_version == CANONICAL_QUIZ_VERSION
    assert db_session_record.current_step == "transition_0"
    assert db_session_record.status == "CREATED"
    assert db_session_record.utm_json == utm_payload


@pytest.mark.asyncio
async def test_recover_current_session_via_cookie():
    """
    Acceptance: refresh resumes current step;
    Calling GET /api/soulmate/sessions/current with valid cookie returns active state.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create session
        create_res = await client.post("/api/soulmate/sessions", json={})
        assert create_res.status_code == 201
        session_id = create_res.json()["session_id"]

        # 2. Recover via cookie automatically preserved in client session
        recover_res = await client.get("/api/soulmate/sessions/current")
        assert recover_res.status_code == 200
        recover_data = recover_res.json()

        assert recover_data["session_id"] == session_id
        assert recover_data["quiz_version"] == CANONICAL_QUIZ_VERSION
        assert recover_data["current_step"] == "transition_0"
        assert recover_data["status"] == "CREATED"
        assert recover_data["answers"] == {}
        assert recover_data["saved_answers_count"] == 0


@pytest.mark.asyncio
async def test_recover_session_resumes_updated_step_and_saved_answers(db_session):
    """
    Acceptance: refresh resumes current step and exposes saved answers needed to restore UI.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create session
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # 2. Simulate progress by writing answers and updated step into DB
        session_rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        session_rec.current_step = "q09"
        session_rec.status = "QUIZ_IN_PROGRESS"

        ans_q02 = SoulmateAnswer(
            session_id=session_rec.id,
            question_code="q02",
            answer_json={"value": "female"},
            duration_ms=2100,
        )
        ans_q08 = SoulmateAnswer(
            session_id=session_rec.id,
            question_code="q08",
            answer_json={"value": "1994-08-25"},
            duration_ms=4500,
        )
        db_session.add_all([ans_q02, ans_q08])
        db_session.commit()

        # 3. Recover via GET /sessions/current
        recover_res = await client.get("/api/soulmate/sessions/current")
        assert recover_res.status_code == 200
        data = recover_res.json()

        assert data["session_id"] == session_id
        assert data["current_step"] == "q09"
        assert data["status"] == "QUIZ_IN_PROGRESS"
        assert data["saved_answers_count"] == 2

        # Check structured answers dictionary for quick UI restoration
        assert "q02" in data["answers"]
        assert data["answers"]["q02"]["value"] == "female"
        assert data["answers"]["q02"]["duration_ms"] == 2100

        assert "q08" in data["answers"]
        assert data["answers"]["q08"]["value"] == "1994-08-25"
        assert data["answers"]["q08"]["duration_ms"] == 4500


@pytest.mark.asyncio
async def test_recover_by_public_id_with_valid_ownership():
    """Verify GET /api/soulmate/sessions/{public_id} works when caller owns the session."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        get_res = await client.get(f"/api/soulmate/sessions/{session_id}")
        assert get_res.status_code == 200
        assert get_res.json()["session_id"] == session_id


@pytest.mark.asyncio
async def test_idor_cross_session_rejected():
    """
    Acceptance / DEV-SPEC §20:
    No arbitrary session ID allows cross-user/session access.
    User A holding cookie A cannot access session B.
    """
    transport = ASGITransport(app=app)

    # 1. Create Session B in isolated client
    async with AsyncClient(transport=transport, base_url="http://test") as client_b:
        res_b = await client_b.post("/api/soulmate/sessions", json={})
        session_b_id = res_b.json()["session_id"]

    # 2. Create Session A in client A
    async with AsyncClient(transport=transport, base_url="http://test") as client_a:
        res_a = await client_a.post("/api/soulmate/sessions", json={})
        session_a_id = res_a.json()["session_id"]
        assert session_a_id != session_b_id

        # 3. Client A maliciously requests Session B
        cross_res = await client_a.get(f"/api/soulmate/sessions/{session_b_id}")

        assert cross_res.status_code == 403
        error_payload = cross_res.json()
        assert error_payload["error_code"] == "FORBIDDEN_OWNERSHIP"
        assert "forbidden" in error_payload["message"].lower()


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected():
    """Unauthenticated requests to current or specific session are rejected with 403."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without any cookie or header
        res_current = await client.get("/api/soulmate/sessions/current")
        assert res_current.status_code == 403
        assert res_current.json()["error_code"] == "FORBIDDEN_OWNERSHIP"

        res_id = await client.get("/api/soulmate/sessions/ses_random_unauthorized")
        assert res_id.status_code == 403
        assert res_id.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_tampered_signature_rejected():
    """Tampering with token signature triggers 403 FORBIDDEN_OWNERSHIP."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # Forge token with invalid signature
        forged_token = f"{session_id}.{int(time.time())}.bad_signature_abcdef123456"

        client.cookies.set(settings.session_cookie_name, forged_token)
        res = await client.get("/api/soulmate/sessions/current")

        assert res.status_code == 403
        assert res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_expired_session_rejected():
    """Session token older than max_age_days triggers 403 FORBIDDEN_OWNERSHIP."""
    transport = ASGITransport(app=app)

    public_id = f"ses_{uuid.uuid4().hex[:16]}"
    # 31 days in the past (exceeds default 30-day window)
    expired_time = int(time.time()) - (31 * 86400)
    expired_token = generate_session_token(public_id, timestamp=expired_time)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(settings.session_cookie_name, expired_token)
        res = await client.get("/api/soulmate/sessions/current")

        assert res.status_code == 403
        error_payload = res.json()
        assert error_payload["error_code"] == "FORBIDDEN_OWNERSHIP"
        assert "expired" in error_payload["message"].lower()


@pytest.mark.asyncio
async def test_token_via_custom_header_fallback():
    """Verify non-cookie clients can authenticate using X-Soulmate-Session-Token."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        token = create_res.headers["X-Soulmate-Session-Token"]

        # Clear cookies to test header fallback
        client.cookies.clear()

        headers = {"X-Soulmate-Session-Token": token}
        res = await client.get("/api/soulmate/sessions/current", headers=headers)
        assert res.status_code == 200
        assert res.json()["session_id"] == create_res.json()["session_id"]


@pytest.mark.asyncio
async def test_token_via_authorization_bearer_fallback():
    """Verify clients can authenticate using Authorization: Bearer <token>."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        token = create_res.headers["X-Soulmate-Session-Token"]

        client.cookies.clear()

        headers = {"Authorization": f"Bearer {token}"}
        res = await client.get("/api/soulmate/sessions/current", headers=headers)
        assert res.status_code == 200
        assert res.json()["session_id"] == create_res.json()["session_id"]


@pytest.mark.asyncio
async def test_session_version_pinning(db_session):
    """
    Acceptance: old session remains bound to original quiz version.
    Even if config or application changes, existing session's quiz_version never changes.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]
        assert create_res.json()["quiz_version"] == CANONICAL_QUIZ_VERSION

        # Verify DB version
        session_rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()
        assert session_rec.quiz_version == CANONICAL_QUIZ_VERSION

        # Re-fetch session
        recover_res = await client.get("/api/soulmate/sessions/current")
        assert recover_res.json()["quiz_version"] == CANONICAL_QUIZ_VERSION


@pytest.mark.asyncio
async def test_valid_token_for_nonexistent_session_returns_404():
    """If caller possesses a validly signed token for a deleted/non-existent session -> 404."""
    transport = ASGITransport(app=app)
    ghost_public_id = f"ses_{uuid.uuid4().hex[:16]}"
    valid_token = generate_session_token(ghost_public_id)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(settings.session_cookie_name, valid_token)
        res = await client.get("/api/soulmate/sessions/current")

        assert res.status_code == 404
        assert res.json()["error_code"] == "NOT_FOUND"
