"""Tests for Interstitial Answer Storage, Validation, Progression, and Idempotency (SP-206)."""

import logging
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.errors import InvalidFlowStateError, ValidationError
from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateProfile, SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.soulmate.domain.step_resolver import (
    INTERSTITIAL_CODES,
    validate_can_answer_interstitial,
)
from app.soulmate.services.interstitial_service import InterstitialService


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _get_valid_quiz_answers_dict():
    """Generates a complete, valid dictionary of answers for q02 through q18."""
    return {
        "q02": {"value": "female"},
        "q03": {"value": "male"},
        "q04": {"value": "single"},
        "q05": {"value": "age_20_30"},
        "q06": {"value": "asian"},
        "q07": {"value": "loyalty"},
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


def _seed_completed_quiz(db_session, session_public_id: str):
    """Seeds q02..q18 answers and sets current_step to spiritual_person."""
    sess = db_session.execute(
        select(SoulmateSession).where(SoulmateSession.public_id == session_public_id)
    ).scalar_one()

    now = utc_now()
    raw_answers = _get_valid_quiz_answers_dict()
    for q_code, payload in raw_answers.items():
        ans = SoulmateAnswer(
            session_id=sess.id,
            question_code=q_code,
            answer_json=payload,
            answered_at=now,
            updated_at=now,
        )
        db_session.add(ans)

    sess.current_step = "spiritual_person"
    sess.quiz_completed_at = now
    sess.status = "QUIZ_COMPLETED"
    db_session.commit()


# ==============================================================================
# 1. Unit Tests: Normalization and Domain Guard
# ==============================================================================

class TestInterstitialNormalization:
    @pytest.mark.parametrize(
        "code",
        ["spiritual_person", "familiar_psychic_artistry"],
    )
    @pytest.mark.parametrize(
        "raw_val, expected",
        [
            (True, True),
            (False, False),
            ("yes", True),
            ("no", False),
            ("YES", True),
            ("NO", False),
            ("true", True),
            ("false", False),
            ("TRUE", True),
            ("FALSE", False),
            ("1", True),
            ("0", False),
        ],
    )
    def test_boolean_interstitial_normalization_valid(self, code, raw_val, expected):
        norm = InterstitialService.normalize_interstitial_value(code, raw_val)
        assert norm is expected

    @pytest.mark.parametrize(
        "code",
        ["spiritual_person", "familiar_psychic_artistry"],
    )
    @pytest.mark.parametrize(
        "invalid_val",
        ["maybe", "unknown", "", "   ", 123, None, ["yes"], {"value": True}],
    )
    def test_boolean_interstitial_normalization_invalid(self, code, invalid_val):
        with pytest.raises(ValidationError):
            InterstitialService.normalize_interstitial_value(code, invalid_val)

    @pytest.mark.parametrize(
        "raw_val, expected",
        [
            ("yes", "yes"),
            ("no", "no"),
            ("YES", "yes"),
            ("NO", "no"),
            ("Yes", "yes"),
            ("No", "no"),
            (True, "yes"),
            (False, "no"),
            ("true", "yes"),
            ("false", "no"),
            ("1", "yes"),
            ("0", "no"),
        ],
    )
    def test_warning_response_normalization_valid(self, raw_val, expected):
        norm = InterstitialService.normalize_interstitial_value("warning_response", raw_val)
        assert norm == expected

    @pytest.mark.parametrize(
        "invalid_val",
        ["maybe", "agree", "", "   ", 123, None, ["yes"], {"value": "yes"}],
    )
    def test_warning_response_normalization_invalid(self, invalid_val):
        with pytest.raises(ValidationError):
            InterstitialService.normalize_interstitial_value("warning_response", invalid_val)

    def test_unknown_interstitial_code_raises_validation_error(self):
        with pytest.raises(ValidationError):
            InterstitialService.normalize_interstitial_value("unknown_code", True)


class TestInterstitialSkipPrevention:
    all_qs = {f"q{i:02d}" for i in range(2, 19)}

    def test_validate_unknown_code_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_can_answer_interstitial("q02", self.all_qs)

    def test_validate_missing_quiz_questions_rejected(self):
        # Only some questions answered
        incomplete_qs = {"q02", "q03", "q04"}
        with pytest.raises(InvalidFlowStateError) as exc_info:
            validate_can_answer_interstitial("spiritual_person", incomplete_qs)
        assert "q05" in str(exc_info.value.details.get("missing_prerequisites"))

    def test_validate_spiritual_person_passes_when_all_quiz_questions_answered(self):
        validate_can_answer_interstitial("spiritual_person", self.all_qs)

    def test_validate_familiar_psychic_artistry_requires_spiritual_person(self):
        # Without spiritual_person -> rejected
        with pytest.raises(InvalidFlowStateError) as exc_info:
            validate_can_answer_interstitial("familiar_psychic_artistry", self.all_qs)
        assert "spiritual_person" in exc_info.value.details.get("missing_prerequisites")

        # With spiritual_person -> passes
        with_spiritual = self.all_qs | {"spiritual_person"}
        validate_can_answer_interstitial("familiar_psychic_artistry", with_spiritual)

    def test_validate_warning_response_requires_both_prior_interstitials(self):
        # Missing both
        with pytest.raises(InvalidFlowStateError):
            validate_can_answer_interstitial("warning_response", self.all_qs)

        # Missing psychic artistry
        with_spiritual = self.all_qs | {"spiritual_person"}
        with pytest.raises(InvalidFlowStateError) as exc_info:
            validate_can_answer_interstitial("warning_response", with_spiritual)
        assert "familiar_psychic_artistry" in exc_info.value.details.get("missing_prerequisites")

        # All prior answered -> passes
        with_both = self.all_qs | {"spiritual_person", "familiar_psychic_artistry"}
        validate_can_answer_interstitial("warning_response", with_both)


# ==============================================================================
# 2. Integration Tests: API Endpoints, Progression, Idempotency, and IDOR
# ==============================================================================

@pytest.mark.asyncio
async def test_interstitial_full_flow_progression_and_profile_sync(db_session):
    """
    Acceptance:
    - Sequence: spiritual_person -> familiar_psychic_artistry -> warning_response -> email;
    - Each step saves answer into soulmate_answers;
    - SoulmateProfile columns are synchronized atomically;
    - GET /profile exposes updated fields in camelCase.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # Seed completed quiz questions
        _seed_completed_quiz(db_session, session_id)

        # 1. Answer spiritual_person: True
        r1 = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
            json={"value": "yes", "duration_ms": 1500},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["saved"] is True
        assert d1["interstitial_code"] == "spiritual_person"
        assert d1["value"] is True
        assert d1["next_step"] == "familiar_psychic_artistry"
        assert d1["flow_state"]["current_step"] == "familiar_psychic_artistry"
        assert d1["flow_state"]["next_step"] == "warning_response"

        # Check DB answer & profile
        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()
        assert sess.current_step == "familiar_psychic_artistry"

        ans1 = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session_id == sess.id,
                SoulmateAnswer.question_code == "spiritual_person",
            )
        ).scalar_one()
        assert ans1.answer_json == {"value": True}
        assert ans1.duration_ms == 1500

        prof1 = db_session.execute(
            select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        ).scalar_one()
        assert prof1.spiritual_person is True
        assert prof1.familiar_psychic_artistry is None
        assert prof1.warning_response is None

        # 2. Answer familiar_psychic_artistry: False
        r2 = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/familiar_psychic_artistry",
            json={"value": False, "duration_ms": 1200},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["saved"] is True
        assert d2["interstitial_code"] == "familiar_psychic_artistry"
        assert d2["value"] is False
        assert d2["next_step"] == "warning_response"
        assert d2["flow_state"]["current_step"] == "warning_response"
        assert d2["flow_state"]["next_step"] == "email"

        # Check DB profile
        db_session.expire_all()
        prof2 = db_session.execute(
            select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        ).scalar_one()
        assert prof2.spiritual_person is True
        assert prof2.familiar_psychic_artistry is False
        assert prof2.warning_response is None

        # 3. Answer warning_response: "yes"
        r3 = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/warning_response",
            json={"value": "yes", "duration_ms": 2000},
        )
        assert r3.status_code == 200
        d3 = r3.json()
        assert d3["saved"] is True
        assert d3["interstitial_code"] == "warning_response"
        assert d3["value"] == "yes"
        assert d3["next_step"] == "email"
        assert d3["flow_state"]["current_step"] == "email"
        assert d3["flow_state"]["next_step"] == "subscribe"

        # Check DB profile
        db_session.expire_all()
        prof3 = db_session.execute(
            select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        ).scalar_one()
        assert prof3.spiritual_person is True
        assert prof3.familiar_psychic_artistry is False
        assert prof3.warning_response == "yes"

        # 4. Check GET /profile endpoint
        prof_res = await client.get(f"/api/soulmate/sessions/{session_id}/profile")
        assert prof_res.status_code == 200
        prof_json = prof_res.json()
        assert prof_json["spiritualPerson"] is True
        assert prof_json["familiarPsychicArtistry"] is False
        assert prof_json["warningResponse"] == "yes"


@pytest.mark.asyncio
async def test_interstitial_idempotency_and_back_reanswer(db_session):
    """
    Acceptance:
    - Re-submitting an answer updates the existing row in-place (no duplicate answer rows);
    - Back navigation and re-answering preserves prior answers and updates profile.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]
        _seed_completed_quiz(db_session, session_id)

        # Answer spiritual_person: True
        await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
            json={"value": True},
        )

        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        ans_count_before = len(
            db_session.execute(
                select(SoulmateAnswer).where(SoulmateAnswer.session_id == sess.id)
            ).scalars().all()
        )

        # Idempotent re-submission with new value (False)
        r_repeat = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
            json={"value": False},
        )
        assert r_repeat.status_code == 200
        assert r_repeat.json()["value"] is False

        # Verify no duplicate row created
        db_session.expire_all()
        ans_count_after = len(
            db_session.execute(
                select(SoulmateAnswer).where(SoulmateAnswer.session_id == sess.id)
            ).scalars().all()
        )
        assert ans_count_after == ans_count_before

        # Profile updated
        prof = db_session.execute(
            select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        ).scalar_one()
        assert prof.spiritual_person is False


@pytest.mark.asyncio
async def test_interstitial_skip_prevention_rejection(db_session):
    """
    Acceptance:
    - Attempting to skip ahead in interstitials raises HTTP 409 InvalidFlowStateError.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fresh session at transition_0
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # 1. Calling spiritual_person before quiz is done -> 409
        r_skip_quiz = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
            json={"value": True},
        )
        assert r_skip_quiz.status_code == 409
        assert r_skip_quiz.json()["error_code"] == "INVALID_FLOW_STATE"

        # Seed completed quiz questions
        _seed_completed_quiz(db_session, session_id)

        # 2. Calling familiar_psychic_artistry before spiritual_person -> 409
        r_skip_spiritual = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/familiar_psychic_artistry",
            json={"value": True},
        )
        assert r_skip_spiritual.status_code == 409
        assert r_skip_spiritual.json()["error_code"] == "INVALID_FLOW_STATE"
        assert "spiritual_person" in r_skip_spiritual.json()["details"]["missing_prerequisites"]

        # 3. Calling warning_response before familiar_psychic_artistry -> 409
        r_skip_warning = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/warning_response",
            json={"value": "yes"},
        )
        assert r_skip_warning.status_code == 409
        assert r_skip_warning.json()["error_code"] == "INVALID_FLOW_STATE"


@pytest.mark.asyncio
async def test_interstitial_namespace_isolation(db_session):
    """
    Acceptance:
    - Interstitials cannot be submitted via /answers/:question_code;
    - Questions (q02-q18) cannot be submitted via /interstitials/:code.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]
        _seed_completed_quiz(db_session, session_id)

        # 1. Calling /interstitials with a question code (q02) -> 400 ValidationError
        r1 = await client.put(
            f"/api/soulmate/sessions/{session_id}/interstitials/q02",
            json={"value": "female"},
        )
        assert r1.status_code == 400
        assert r1.json()["error_code"] == "VALIDATION_ERROR"
        assert "Invalid interstitial code 'q02'" in r1.json()["message"]

        # 2. Calling /answers with an interstitial code -> 400 ValidationError
        r2 = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/spiritual_person",
            json={"value": "yes"},
        )
        assert r2.status_code == 400
        assert r2.json()["error_code"] == "VALIDATION_ERROR"
        assert "does not exist in quiz version" in r2.json()["message"]


@pytest.mark.asyncio
async def test_interstitial_idor_protection(db_session):
    """
    Acceptance:
    - Session ownership is verified; cross-session attempts reject with HTTP 403.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session 1
        r1 = await client.post("/api/soulmate/sessions", json={})
        s1_id = r1.json()["session_id"]
        _seed_completed_quiz(db_session, s1_id)

        # Create session 2 (client cookie now belongs to session 2)
        r2 = await client.post("/api/soulmate/sessions", json={})
        s2_id = r2.json()["session_id"]
        assert s1_id != s2_id

        # Attempt to submit to session 1 using session 2's cookie -> 403
        r_forbidden = await client.put(
            f"/api/soulmate/sessions/{s1_id}/interstitials/spiritual_person",
            json={"value": True},
        )
        assert r_forbidden.status_code == 403
        assert r_forbidden.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_interstitial_analytics_non_pii_logging(db_session, caplog):
    """
    Acceptance:
    - Analytics logs record interstitial answer without PII.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]
        _seed_completed_quiz(db_session, session_id)

        with caplog.at_level(logging.INFO):
            await client.put(
                f"/api/soulmate/sessions/{session_id}/interstitials/spiritual_person",
                json={"value": True},
            )

        # Verify structured log event
        log_records = [
            r for r in caplog.records
            if getattr(r, "event_type", None) == "interstitial_answered"
        ]
        assert len(log_records) == 1
        record = log_records[0]
        assert record.interstitial_code == "spiritual_person"
        assert record.answer_value is True
        assert not hasattr(record, "email")
        assert not hasattr(record, "user_email")
        assert not hasattr(record, "user_name")
        assert "spiritual_person" in record.getMessage()

