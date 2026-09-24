"""Comprehensive automated tests for Answer Submission and Validation (SP-202, DEV-SPEC §4, §15.3, §20)."""

import asyncio
from datetime import date, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.core.config import settings
from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.soulmate.domain.step_resolver import get_prerequisite_questions_for_question


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DUMMY_ANSWERS = {
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


def seed_prerequisites_for_question(session_public_id: str, target_question: str) -> None:
    """Pre-populates prerequisite answers in DB to satisfy flow resolver for targeted question tests."""
    prereqs = get_prerequisite_questions_for_question(target_question)
    if not prereqs:
        return
    with SessionLocal() as db:
        sess = db.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_public_id)
        ).scalar_one()
        now = utc_now()
        for q_code in prereqs:
            ans = SoulmateAnswer(
                session_id=sess.id,
                question_code=q_code,
                answer_json=DUMMY_ANSWERS[q_code],
                answered_at=now,
                updated_at=now,
            )
            db.add(ans)
        db.commit()


@pytest.mark.asyncio
async def test_submit_single_choice_q02(db_session):

    """
    Acceptance:
    - Submits single choice answer (q02);
    - Validates option membership;
    - Atomically persists answer in soulmate_answers;
    - Advances session step to q03;
    - Advances status to QUIZ_IN_PROGRESS.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create session
        create_res = await client.post("/api/soulmate/sessions", json={})
        assert create_res.status_code == 201
        session_id = create_res.json()["session_id"]

        # 2. Submit answer to q02
        payload = {"value": "female", "duration_ms": 2300}
        answer_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json=payload,
        )
        assert answer_res.status_code == 200
        data = answer_res.json()

        assert data["saved"] is True
        assert data["question_code"] == "q02"
        assert data["next_step"] == "q03"

        # 3. Assert DB record in soulmate_answers
        ans_rec = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q02",
            )
        ).scalar_one_or_none()

        assert ans_rec is not None
        assert ans_rec.question_code == "q02"
        assert ans_rec.answer_json == {"value": "female"}
        assert ans_rec.duration_ms == 2300

        # 4. Assert session record in soulmate_sessions
        session_rec = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        assert session_rec.current_step == "q03"
        assert session_rec.status == "QUIZ_IN_PROGRESS"


@pytest.mark.asyncio
async def test_submit_date_q08_valid(db_session):
    """Verify valid calendar birth date submission for q08."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]
        seed_prerequisites_for_question(session_id, "q08")

        payload = {"value": "1994-08-25", "duration_ms": 3500}
        answer_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q08",
            json=payload,
        )
        assert answer_res.status_code == 200
        data = answer_res.json()

        assert data["saved"] is True
        assert data["question_code"] == "q08"
        assert data["next_step"] == "q09"

        # Verify DB
        ans_rec = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q08",
            )
        ).scalar_one()
        assert ans_rec.answer_json["value"] == "1994-08-25"
        assert ans_rec.answer_json["zodiac_sign"] == "Virgo"
        assert ans_rec.duration_ms == 3500



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_date",
    [
        "1994-02-31",  # Non-existent calendar date
        "1994-13-15",  # Invalid month
        "1994-00-10",  # Invalid month 0
        "1994-05-00",  # Invalid day 0
        "not-a-date",  # Malformed string
        "1994/08/25",  # Slashes instead of dashes
        "1880-01-01",  # Year prior to 1900
        (date.today() + timedelta(days=1)).isoformat(),  # Future date
    ],
)
async def test_submit_date_q08_invalid_dates(invalid_date):
    """Verify Q08 date validation rejects invalid calendar, future, or out-of-range dates."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]
        seed_prerequisites_for_question(session_id, "q08")

        res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q08",
            json={"value": invalid_date},
        )

        assert res.status_code == 400
        data = res.json()
        assert data["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_submit_multi_choice_q18_deduplication(db_session):
    """
    Acceptance: Q18 deduplicate values;
    Duplicate selections submitted by client are stored as unique values.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]
        seed_prerequisites_for_question(session_id, "q18")

        # Submitting duplicates
        payload = {
            "values": ["personal_growth", "personal_growth", "traveling_the_world", "personal_growth"],
            "duration_ms": 6200,
        }
        res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q18",
            json=payload,
        )
        assert res.status_code == 200
        data = res.json()

        assert data["saved"] is True
        assert data["question_code"] == "q18"
        assert data["next_step"] == "transition_5"

        # Check DB has deduplicated array preserving order
        ans_rec = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q18",
            )
        ).scalar_one()

        assert ans_rec.answer_json == {"values": ["personal_growth", "traveling_the_world"]}


@pytest.mark.asyncio
async def test_submit_multi_choice_q18_empty_rejected():
    """Verify Q18 rejects empty selection list (min_select: 1)."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]
        seed_prerequisites_for_question(session_id, "q18")

        res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q18",
            json={"values": []},
        )
        assert res.status_code == 400
        assert res.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_invalid_option_code_rejected():
    """
    Acceptance: invalid option codes are rejected.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # Single option not in question
        res_single = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"value": "hacker_option"},
        )
        assert res_single.status_code == 400
        assert res_single.json()["error_code"] == "VALIDATION_ERROR"

        # Multi option with invalid code
        seed_prerequisites_for_question(session_id, "q18")
        res_multi = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q18",
            json={"values": ["personal_growth", "invalid_future_code"]},
        )
        assert res_multi.status_code == 400
        assert res_multi.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_nonexistent_question_code_rejected():
    """Submitting answer for question code not in quiz config returns 400 VALIDATION_ERROR."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q99",
            json={"value": "option_xyz"},
        )
        assert res.status_code == 400
        assert res.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_mismatched_payload_type_rejected():
    """Verify single question rejects 'values' and multi question rejects 'value'."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # 1. Sending 'values' to single question q02
        res1 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"values": ["female"]},
        )
        assert res1.status_code == 400
        assert res1.json()["error_code"] == "VALIDATION_ERROR"

        # 2. Sending 'value' to multi question q18
        seed_prerequisites_for_question(session_id, "q18")
        res2 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q18",
            json={"value": "personal_growth"},
        )
        assert res2.status_code == 400
        assert res2.json()["error_code"] == "VALIDATION_ERROR"



@pytest.mark.asyncio
async def test_re_answer_flow_updates_existing_answer(db_session):
    """
    Acceptance: saved answer can be edited by Back/re-answer flow according to current spec.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        # First answer: female
        res1 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"value": "female", "duration_ms": 1200},
        )
        assert res1.status_code == 200

        # Back / re-answer: male
        res2 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q02",
            json={"value": "male", "duration_ms": 2500},
        )
        assert res2.status_code == 200

        # Assert exactly one row exists in soulmate_answers with updated value
        answers = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q02",
            )
        ).scalars().all()

        assert len(answers) == 1
        assert answers[0].answer_json == {"value": "male"}
        assert answers[0].duration_ms == 2500

        # Recover session to verify full recovery reflects edited answer
        recover_res = await client.get("/api/soulmate/sessions/current")
        assert recover_res.status_code == 200
        assert recover_res.json()["answers"]["q02"]["value"] == "male"


@pytest.mark.asyncio
async def test_duplicate_rapid_single_taps_idempotent(db_session):
    """
    Acceptance: duplicate rapid single taps cannot create duplicate rows.
    Concurrent PUT requests to the same session + question code are atomic and idempotent.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]

        payload = {"value": "male", "duration_ms": 1000}

        # Simulate 5 concurrent rapid taps
        tasks = [
            client.put(f"/api/soulmate/sessions/{session_id}/answers/q02", json=payload)
            for _ in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        # All concurrent requests must succeed cleanly without 500 UniqueViolation
        for r in responses:
            assert r.status_code == 200
            assert r.json()["saved"] is True

        # Assert exactly 1 row exists in physical database
        answers = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session.has(SoulmateSession.public_id == session_id),
                SoulmateAnswer.question_code == "q02",
            )
        ).scalars().all()

        assert len(answers) == 1
        assert answers[0].answer_json == {"value": "male"}


@pytest.mark.asyncio
async def test_answer_submission_idor_rejected():
    """
    Acceptance / DEV-SPEC §20:
    User A holding cookie A cannot submit an answer to Session B.
    """
    transport = ASGITransport(app=app)

    # 1. Create Session B in client B
    async with AsyncClient(transport=transport, base_url="http://test") as client_b:
        res_b = await client_b.post("/api/soulmate/sessions", json={})
        session_b_id = res_b.json()["session_id"]

    # 2. Client A maliciously submits answer to Session B
    async with AsyncClient(transport=transport, base_url="http://test") as client_a:
        res_a = await client_a.post("/api/soulmate/sessions", json={})
        session_a_id = res_a.json()["session_id"]
        assert session_a_id != session_b_id

        res = await client_a.put(
            f"/api/soulmate/sessions/{session_b_id}/answers/q02",
            json={"value": "female"},
        )
        assert res.status_code == 403
        assert res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_unauthenticated_answer_submission_rejected():
    """Submitting answer without cookie/token returns 403 FORBIDDEN_OWNERSHIP."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.put(
            "/api/soulmate/sessions/ses_some_session/answers/q02",
            json={"value": "female"},
        )
        assert res.status_code == 403
        assert res.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question_code,expected_next_step",
    [
        ("q02", "q03"),
        ("q05", "q06"),
        ("q06", "transition_1"),
        ("q07", "transition_2"),
        ("q08", "q09"),
        ("q10", "transition_3"),
        ("q11", "transition_4"),
        ("q17", "q18"),
        ("q18", "transition_5"),
    ],
)
async def test_transition_step_progression(question_code, expected_next_step):
    """Verify flow step resolver correctly points to next question or interstitial."""
    transport = ASGITransport(app=app)

    # Valid payload map for each question
    sample_payloads = {
        "q02": {"value": "female"},
        "q05": {"value": "age_20_30"},
        "q06": {"value": "caucasian_white"},
        "q07": {"value": "intelligence"},
        "q08": {"value": "1992-04-18"},
        "q10": {"value": "heart"},
        "q11": {"value": "building_trust"},
        "q17": {"value": "losing_trust"},
        "q18": {"values": ["personal_growth"]},
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post("/api/soulmate/sessions", json={})
        session_id = create_res.json()["session_id"]
        seed_prerequisites_for_question(session_id, question_code)

        res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/{question_code}",
            json=sample_payloads[question_code],
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == expected_next_step

