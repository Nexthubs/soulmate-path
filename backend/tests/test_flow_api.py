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

        # Answer q07 with "intelligence" -> next step is transition_2
        q07_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q07",
            json={"value": "intelligence"},
        )
        assert q07_res.status_code == 200
        assert q07_res.json()["next_step"] == "transition_2"

        # Fetch flow state at transition_2 and verify COPY-02 dynamic copy for confirmed option
        flow_res = await client.get(f"/api/soulmate/sessions/{session_id}/flow/state")
        assert flow_res.status_code == 200
        meta = flow_res.json()["step_metadata"]
        assert meta["transition_code"] == "transition_2"
        assert meta["selected_option"] == "intelligence"
        assert meta["is_copy_confirmed"] is True
        assert meta["title"] == "Awesome!"
        assert "Intelligence" in meta["body"]

        # Step back to q07 before re-answering
        back_res = await client.post(f"/api/soulmate/sessions/{session_id}/step/back")
        assert back_res.status_code == 200
        assert back_res.json()["current_step"] == "q07"

        # Re-answer q07 with "loyalty" (unconfirmed option per DECISIONS.md COPY-02)
        q07_re = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q07",
            json={"value": "loyalty"},
        )
        assert q07_re.status_code == 200
        assert q07_re.json()["next_step"] == "transition_2"

        flow_res2 = await client.get(f"/api/soulmate/sessions/{session_id}/flow/state")
        meta2 = flow_res2.json()["step_metadata"]
        assert meta2["selected_option"] == "loyalty"
        assert meta2["is_copy_confirmed"] is False
        assert meta2["copy_status"] == "unconfigured_copy_02"
        assert meta2["body"] is None


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


@pytest.mark.asyncio
async def test_question_submission_cannot_bypass_active_transition():
    """
    Acceptance (Audit High - SP-203):
    - Submitting q02 when current_step is transition_0 is rejected with 409 INVALID_FLOW_STATE.
    - Submitting q07 when current_step is transition_1 is rejected with 409 INVALID_FLOW_STATE.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # 1. Attempt q02 while at transition_0
        q02_bypass = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"value": "female"},
        )
        assert q02_bypass.status_code == 409
        assert q02_bypass.json()["error_code"] == "INVALID_FLOW_STATE"
        assert "transition_0" in q02_bypass.json()["message"]

        # Advance transition_0
        await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")

        # Now q02 succeeds
        q02_ok = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"value": "female"},
        )
        assert q02_ok.status_code == 200

        # Answer q03..q06 to reach transition_1
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q03", json={"value": "male"})
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q04", json={"value": "single"})
        await client.put(f"/api/soulmate/sessions/{session_id}/answers/q05", json={"value": "age_20_30"})
        q06 = await client.put(f"/api/soulmate/sessions/{session_id}/answers/q06", json={"value": "caucasian_white"})
        assert q06.json()["next_step"] == "transition_1"

        # 2. Attempt q07 while at transition_1
        q07_bypass = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q07",
            json={"value": "kindness"},
        )
        assert q07_bypass.status_code == 409
        assert q07_bypass.json()["error_code"] == "INVALID_FLOW_STATE"
        assert "transition_1" in q07_bypass.json()["message"]

        # Advance transition_1
        await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_1/continue")

        # Now q07 succeeds
        q07_ok = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q07",
            json={"value": "kindness"},
        )
        assert q07_ok.status_code == 200


@pytest.mark.asyncio
async def test_interstitial_submission_cannot_bypass_active_transition(db_session):
    """
    Acceptance (Audit High - SP-203):
    - Submitting interstitial when current_step is transition_5 is rejected with 409 INVALID_FLOW_STATE.
    - Continuing transition_5 allows interstitial submission.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # Advance transition_0
        await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_0/continue")

        # Answer all questions q02..q18
        answers = {
            "q02": {"value": "female"},
            "q03": {"value": "male"},
            "q04": {"value": "single"},
            "q05": {"value": "age_20_30"},
            "q06": {"value": "caucasian_white"},
            "q07": {"value": "kindness"},
            "q08": {"value": "1994-08-25"},
            "q09": {"value": "water"},
            "q10": {"value": "heart"},
            "q11": {"value": "building_trust"},
            "q12": {"value": "lack_of_trust"},
            "q13": {"value": "similar_to_me"},
            "q14": {"value": "partnership"},
            "q15": {"value": "words_of_affirmation"},
            "q16": {"value": "deep_and_intimate"},
            "q17": {"value": "losing_trust"},
            "q18": {"values": ["personal_growth"]},
        }

        # Transition map after certain questions
        transitions_to_continue = {
            "q06": "transition_1",
            "q07": "transition_2",
            "q10": "transition_3",
            "q11": "transition_4",
        }

        for q_code, payload in answers.items():
            ans_res = await client.put(f"/api/soulmate/sessions/{session_id}/answers/{q_code}", json=payload)
            assert ans_res.status_code == 200
            if q_code in transitions_to_continue:
                trans = transitions_to_continue[q_code]
                t_res = await client.post(f"/api/soulmate/sessions/{session_id}/transitions/{trans}/continue")
                assert t_res.status_code == 200

        # After q18, current_step is transition_5
        flow_res = await client.get(f"/api/soulmate/sessions/{session_id}/flow/state")
        assert flow_res.json()["current_step"] == "transition_5"

        # Attempt to submit interstitial spiritual_person while at transition_5
        inter_bypass = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
            json={"value": "yes"},
        )
        assert inter_bypass.status_code == 409
        assert inter_bypass.json()["error_code"] == "INVALID_FLOW_STATE"
        assert "transition_5" in inter_bypass.json()["message"]

        # Continue transition_5
        t5_res = await client.post(f"/api/soulmate/sessions/{session_id}/transitions/transition_5/continue")
        assert t5_res.status_code == 200

        # Now interstitial submission succeeds
        inter_ok = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
            json={"value": "yes"},
        )
        assert inter_ok.status_code == 200
