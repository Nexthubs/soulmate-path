"""Integration tests for Flow State, Transitions, Skip Prevention, and Back Navigation (SP-203)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.mark.asyncio
async def test_get_flow_state_initial_session(db_session):
    """
    Acceptance:
    - Session starts at transition_0;
    - GET /{public_id}/flow/state returns authoritative step and 0% progress;
    - Correct step_type is 'transition'.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        assert res.status_code == 201
        session_id = res.json()["session_id"]

        flow_res = await client.get(f"/api/soulmate/sessions/{session_id}/flow/state")
        assert flow_res.status_code == 200
        data = flow_res.json()

        assert data["session_id"] == session_id
        assert data["current_step"] == "transition_0"
        assert data["step_type"] == "transition"
        assert data["next_step"] == "q02"
        assert data["previous_step"] is None
        assert data["progress_percent"] == 0
        assert data["is_quiz_completed"] is False
        assert data["step_metadata"]["transition_code"] == "transition_0"


@pytest.mark.asyncio
async def test_flow_state_idor_protection():
    """Verify flow endpoints reject unauthorized access with HTTP 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session 1
        res1 = await client.post("/api/soulmate/sessions", json={})
        s1_id = res1.json()["session_id"]

        # Create session 2 (replaces cookie in client)
        res2 = await client.post("/api/soulmate/sessions", json={})
        s2_id = res2.json()["session_id"]

        # Client now holds s2 cookie, attempting to access s1 flow state
        flow_res = await client.get(f"/api/soulmate/sessions/{s1_id}/flow/state")
        assert flow_res.status_code == 403
        assert flow_res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"

        # Attempt to continue transition on s1
        trans_res = await client.post(f"/api/soulmate/sessions/{s1_id}/transitions/transition_0/continue")
        assert trans_res.status_code == 403
        assert trans_res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"

        # Attempt to navigate back on s1
        back_res = await client.post(f"/api/soulmate/sessions/{s1_id}/step/back")
        assert back_res.status_code == 403
        assert back_res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_continue_transition_0_and_idempotency(db_session):
    """
    Acceptance:
    - POST /transitions/transition_0/continue advances step from transition_0 to q02;
    - Repeated calls return identical state idempotently.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # Advance transition_0
        cont_res = await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")
        assert cont_res.status_code == 200
        data = cont_res.json()

        assert data["transition_code"] == "transition_0"
        assert data["next_step"] == "q02"
        assert data["flow_state"]["current_step"] == "q02"
        assert data["flow_state"]["step_type"] == "question"
        assert data["flow_state"]["previous_step"] == "transition_0"

        # Repeat call (idempotent network retry)
        retry_res = await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")
        assert retry_res.status_code == 200
        assert retry_res.json()["next_step"] == "q02"


@pytest.mark.asyncio
async def test_skip_prevention_on_answer_submission(db_session):
    """
    Acceptance (DEV-SPEC §15.3, SP-203):
    - Submitting q04 without answering q02 and q03 returns HTTP 409 INVALID_FLOW_STATE.
    - Error details contain missing prerequisite questions.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # Advance past transition_0
        await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")

        # Illegal skip attempt: submit q04 directly
        skip_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q04",
            json={"value": "20-29"},
        )
        assert skip_res.status_code == 409
        err = skip_res.json()
        assert err["error_code"] == "INVALID_FLOW_STATE"
        assert "q02" in err["details"]["missing_prerequisites"]
        assert "q03" in err["details"]["missing_prerequisites"]


@pytest.mark.asyncio
async def test_step_back_and_reanswer_preserves_answers(db_session):
    """
    Acceptance:
    - Answering q02 and q03 advances flow to q04.
    - POST /step/back moves session step to q03 while preserving q02 and q03 in DB.
    - Re-answering q03 updates the answer without dropping answers or corrupting flow.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]
        await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")

        # Answer q02
        ans2 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"value": "female"},
        )
        assert ans2.status_code == 200
        assert ans2.json()["next_step"] == "q03"

        # Answer q03
        ans3 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q03",
            json={"value": "male"},
        )
        assert ans3.status_code == 200
        assert ans3.json()["next_step"] == "q04"

        # Navigate back to q03
        back_res = await client.post(f"/api/soulmate/sessions/{session_id}/step/back")
        assert back_res.status_code == 200
        assert back_res.json()["current_step"] == "q03"

        # Verify DB answers are preserved
        q02_row = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q02",
            )
        ).scalar_one_or_none()
        assert q02_row is not None
        assert q02_row.answer_json["value"] == "female"

        # Re-answer q03 with "female"
        reans3 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q03",
            json={"value": "female"},
        )
        assert reans3.status_code == 200
        assert reans3.json()["next_step"] == "q04"

        # Check DB updated
        q03_row = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q03",
            )
        ).scalar_one_or_none()
        assert q03_row is not None
        assert q03_row.answer_json["value"] == "female"


@pytest.mark.asyncio
async def test_transition_prerequisites_and_copy_resolution(db_session):
    """
    Acceptance (COPY-02):
    - transition_1 requires q02 through q06;
    - transition_2 resolves dynamic copy based on q07 answer.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]
        await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")

        # Answer q02 to q05
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q02", json={"value": "female"})
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q03", json={"value": "male"})
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q04", json={"value": "single"})
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q05", json={"value": "age_20_30"})

        # Try to continue transition_1 before answering q06
        trans1_fail = await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_1/continue")
        assert trans1_fail.status_code == 409

        # Answer q06 -> next step will be transition_1
        q06_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q06",
            json={"value": "caucasian_white"},
        )
        assert q06_res.status_code == 200
        assert q06_res.json()["next_step"] == "transition_1"


        # Now continue transition_1 -> succeeds and advances to q07
        trans1_ok = await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_1/continue")
        assert trans1_ok.status_code == 200
        assert trans1_ok.json()["next_step"] == "q07"

        # Answer q07 with "loyalty" -> next step is transition_2
        q07_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q07",
            json={"value": "loyalty"},
        )
        assert q07_res.status_code == 200
        assert q07_res.json()["next_step"] == "transition_2"

        # Fetch flow state at transition_2 and verify COPY-02 dynamic copy
        flow_res = await client.get(f"/api/soulmate/sessions/{session_id}/flow/state")
        assert flow_res.status_code == 200
        meta = flow_res.json()["step_metadata"]
        assert meta["transition_code"] == "transition_2"
        assert meta["selected_option"] == "loyalty"
        assert meta["title"] == "Awesome!"
        assert "Loyalty" in meta["body"]


@pytest.mark.asyncio
async def test_navigate_back_from_initial_step_fails():
    """Verify attempting to navigate back from transition_0 returns HTTP 409."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        back_res = await client.post(f"/api/soulmate/sessions/{session_id}/step/back")
        assert back_res.status_code == 409
        assert back_res.json()["error_code"] == "INVALID_FLOW_STATE"
