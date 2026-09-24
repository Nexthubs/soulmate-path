"""
Tests for Normalized Soulmate Profile builder, validation, and persistence (DEV-SPEC §7, Decisions: QUIZ-01, SP-205).
"""

from datetime import date, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateProfile, SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.soulmate.domain.profile import (
    InvalidAnswerValueError,
    MissingRequiredAnswerError,
    ProfileValidationError,
    SoulmateProfileV1,
    build_soulmate_profile,
)


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _get_valid_answers_dict():
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


def test_pure_builder_with_valid_answers():
    """Validates that build_soulmate_profile produces a complete SoulmateProfileV1."""
    raw = _get_valid_answers_dict()
    profile = build_soulmate_profile(raw)

    assert isinstance(profile, SoulmateProfileV1)
    assert profile.profile_version == "v1"
    assert profile.user_gender == "female"
    assert profile.preferred_partner_gender == "male"
    assert profile.love_life_status == "single"
    assert profile.preferred_partner_age_range == "age_20_30"
    assert profile.preferred_partner_ethnicity == "asian"
    assert profile.key_soulmate_quality == "loyalty"
    assert profile.birth_date == "1994-08-25"
    assert profile.zodiac_sign == "Virgo"
    assert profile.element == "fire"
    assert profile.decision_style == "heart"
    assert profile.personal_challenge == "building_trust"
    assert profile.red_flag == "lack_of_trust"
    assert profile.similarity_preference == "similar_to_me"
    assert profile.relationship_dynamic == "deep_connection"
    assert profile.love_language == "words_of_affirmation"
    assert profile.connection_style == "deep_and_intimate"
    assert profile.relationship_fear == "losing_trust"
    assert profile.life_goals == ["building_a_family", "traveling_the_world"]
    assert profile.spiritual_person is None
    assert profile.familiar_psychic_artistry is None
    assert profile.warning_response is None

    # Serialization check: camelCase alias output matching DEV-SPEC §7 TypeScript interface
    camel_dump = profile.model_dump(by_alias=True)
    assert camel_dump["userGender"] == "female"
    assert camel_dump["preferredPartnerGender"] == "male"
    assert camel_dump["keySoulmateQuality"] == "loyalty"
    assert camel_dump["birthDate"] == "1994-08-25"
    assert camel_dump["zodiacSign"] == "Virgo"


def test_pure_builder_supports_flat_answers():
    """Verifies that flat key-value dictionary is cleanly handled."""
    flat = {
        "q02": "female",
        "q03": "male",
        "q04": "in_relationship",
        "q05": "age_30_40",
        "q06": "caucasian_white",
        "q07": "kindness",
        "q08": "1990-10-15",
        "q09": "water",
        "q10": "both",
        "q11": "finding_right_person",
        "q12": "poor_communication",
        "q13": "brings_contrast",
        "q14": "adventure",
        "q15": "quality_time",
        "q16": "fun_and_adventurous",
        "q17": "growing_apart",
        "q18": ["traveling_the_world"],
    }
    profile = build_soulmate_profile(flat)
    assert profile.user_gender == "female"
    assert profile.preferred_partner_gender == "male"
    assert profile.zodiac_sign == "Libra"  # 10-15 is Libra


@pytest.mark.parametrize(
    "q02_val,q03_val",
    [
        ("male", "female"),
        ("female", "male"),
        ("male", "male"),
        ("female", "female"),
    ],
)
def test_quiz_01_no_q2_q3_ambiguity(q02_val, q03_val):
    """
    CRITICAL CHECK for Decision QUIZ-01:
    - q02 strictly determines user_gender.
    - q03 strictly determines preferred_partner_gender.
    - sketch_input gender strictly equals preferred_partner_gender (Q03), NOT user_gender (Q02).
    """
    raw = _get_valid_answers_dict()
    raw["q02"] = {"value": q02_val}
    raw["q03"] = {"value": q03_val}

    profile = build_soulmate_profile(raw)
    assert profile.user_gender == q02_val
    assert profile.preferred_partner_gender == q03_val

    # Check sketch prompt input generator
    sketch_input = profile.to_sketch_input()
    assert sketch_input["gender"] == q03_val  # Must be partner gender, per QUIZ-01
    assert sketch_input["age_range"] == profile.preferred_partner_age_range
    assert sketch_input["ethnicity"] == profile.preferred_partner_ethnicity
    assert sketch_input["features"] == profile.key_soulmate_quality


def test_missing_single_required_answer_raises_explicit_error():
    """Verifies MissingRequiredAnswerError is raised with specific question code."""
    raw = _get_valid_answers_dict()
    del raw["q02"]

    with pytest.raises(MissingRequiredAnswerError) as exc_info:
        build_soulmate_profile(raw)

    err = exc_info.value
    assert "q02" in err.missing_questions
    assert err.status_code == 400
    assert err.details["missing_questions"] == ["q02"]


def test_missing_multiple_required_answers_raises_explicit_error():
    """Verifies MissingRequiredAnswerError lists all missing questions in details."""
    raw = _get_valid_answers_dict()
    del raw["q05"]
    del raw["q09"]
    del raw["q18"]

    with pytest.raises(MissingRequiredAnswerError) as exc_info:
        build_soulmate_profile(raw)

    err = exc_info.value
    assert set(err.missing_questions) == {"q05", "q09", "q18"}


def test_unknown_option_code_raises_invalid_answer_value_error():
    """Option codes not present in QuizConfig options must raise InvalidAnswerValueError."""
    raw = _get_valid_answers_dict()
    raw["q02"] = {"value": "non_binary"}  # Not in q02 allowed options

    with pytest.raises(InvalidAnswerValueError) as exc_info:
        build_soulmate_profile(raw)

    err = exc_info.value
    assert err.question_code == "q02"
    assert err.status_code == 400


def test_invalid_element_raises_invalid_answer_value_error():
    """Invalid personality element raises InvalidAnswerValueError."""
    raw = _get_valid_answers_dict()
    raw["q09"] = {"value": "metal"}  # Not fire, water, earth, wind

    with pytest.raises(InvalidAnswerValueError) as exc_info:
        build_soulmate_profile(raw)

    assert exc_info.value.question_code == "q09"


def test_invalid_decision_style_raises_invalid_answer_value_error():
    """Invalid decision style raises InvalidAnswerValueError."""
    raw = _get_valid_answers_dict()
    raw["q10"] = {"value": "gut"}  # Not heart, head, both

    with pytest.raises(InvalidAnswerValueError) as exc_info:
        build_soulmate_profile(raw)

    assert exc_info.value.question_code == "q10"


def test_empty_or_invalid_life_goals_raises_error():
    """Q18 life_goals must be a non-empty list of valid options."""
    raw = _get_valid_answers_dict()
    raw["q18"] = {"values": []}

    with pytest.raises(InvalidAnswerValueError):
        build_soulmate_profile(raw)

    raw["q18"] = {"values": ["conquering_the_galaxy"]}
    with pytest.raises(InvalidAnswerValueError):
        build_soulmate_profile(raw)


def test_q18_deduplicates_preserving_order():
    """Q18 duplicate choices are deduplicated while preserving first occurrence."""
    raw = _get_valid_answers_dict()
    raw["q18"] = {
        "values": ["traveling_the_world", "building_a_family", "traveling_the_world"]
    }
    profile = build_soulmate_profile(raw)
    assert profile.life_goals == ["traveling_the_world", "building_a_family"]


def test_birth_date_and_zodiac_calculation():
    """Calculates server-authoritative zodiac from Q08 birth_date."""
    raw = _get_valid_answers_dict()

    # Aries boundary
    raw["q08"] = {"value": "2000-03-21"}
    p1 = build_soulmate_profile(raw)
    assert p1.zodiac_sign == "Aries"

    # Pisces leap day
    raw["q08"] = {"value": "1996-02-29"}
    p2 = build_soulmate_profile(raw)
    assert p2.zodiac_sign == "Pisces"

    # Capricorn year transition
    raw["q08"] = {"value": "1990-12-31"}
    p3 = build_soulmate_profile(raw)
    assert p3.zodiac_sign == "Capricorn"


def test_birth_date_validation_age_01():
    """Date validation preserves AGE-01 (rejects future and malformed dates, accepts historical valid dates without unapproved floor)."""
    raw = _get_valid_answers_dict()

    # Future date
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    raw["q08"] = {"value": tomorrow}
    with pytest.raises(ProfileValidationError) as exc_info:
        build_soulmate_profile(raw)
    assert "future" in exc_info.value.message.lower()

    # Historical valid date passes without inventing an unapproved 1900 floor
    raw["q08"] = {"value": "1899-12-31"}
    profile = build_soulmate_profile(raw)
    assert profile.birth_date == "1899-12-31"

    # Malformed string
    raw["q08"] = {"value": "not-a-date"}
    with pytest.raises(ProfileValidationError):
        build_soulmate_profile(raw)


def test_soulmate_profile_v1_birth_date_validation_and_to_db_dict_resilience():
    """Verifies that SoulmateProfileV1 validates birth_date strictly and to_db_dict handles dates safely."""
    base_kwargs = {
        "user_gender": "female",
        "preferred_partner_gender": "male",
        "love_life_status": "single",
        "preferred_partner_age_range": "age_20_30",
        "preferred_partner_ethnicity": "asian",
        "key_soulmate_quality": "loyalty",
        "birth_date": "1994-08-25",
        "zodiac_sign": "Virgo",
        "element": "fire",
        "decision_style": "heart",
        "personal_challenge": "building_trust",
        "red_flag": "lack_of_trust",
        "similarity_preference": "similar_to_me",
        "relationship_dynamic": "deep_connection",
        "love_language": "words_of_affirmation",
        "connection_style": "deep_and_intimate",
        "relationship_fear": "losing_trust",
        "life_goals": ["building_a_family"],
    }

    # Valid string
    p1 = SoulmateProfileV1(**base_kwargs)
    db_dict = p1.to_db_dict()
    assert db_dict["birth_date"] == date(1994, 8, 25)

    # Valid date object
    base_kwargs["birth_date"] = date(1990, 1, 1)
    p2 = SoulmateProfileV1(**base_kwargs)
    assert p2.birth_date == "1990-01-01"
    assert p2.to_db_dict()["birth_date"] == date(1990, 1, 1)

    # Invalid birth_date format raises ProfileValidationError
    base_kwargs["birth_date"] = "1990/01/01"
    with pytest.raises(ProfileValidationError):
        SoulmateProfileV1(**base_kwargs)

    base_kwargs["birth_date"] = "invalid"
    with pytest.raises(ProfileValidationError):
        SoulmateProfileV1(**base_kwargs)


@pytest.mark.asyncio
async def test_sync_profile_for_session_graceful_on_profile_validation_error(db_session):
    """Verifies ProfileService.sync_profile_for_session catches ProfileValidationError and returns None without crashing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        # Insert complete answers but with an invalid option value for q09 (e.g. "plasma")
        now = utc_now()
        raw_answers = _get_valid_answers_dict()
        raw_answers["q09"] = {"value": "plasma"}
        for q_code, payload in raw_answers.items():
            ans = SoulmateAnswer(
                session_id=sess.id,
                question_code=q_code,
                answer_json=payload,
                answered_at=now,
                updated_at=now,
            )
            db_session.add(ans)
        sess.current_step = "transition_5"
        db_session.commit()

        # Continuing transition_5 should NOT crash, but gracefully return flow response
        cont_res = await client.post(
            f"/api/soulmate/sessions/{session_id}/transitions/transition_5/continue"
        )
        assert cont_res.status_code == 200

        # Profile was not materialized due to validation error
        stmt = select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        assert db_session.execute(stmt).scalar_one_or_none() is None


def test_optional_interstitial_answers():
    """Parses optional post-quiz interstitial questions when present."""
    raw = _get_valid_answers_dict()
    raw["spiritual_person"] = True
    raw["familiar_psychic_artistry"] = "no"
    raw["warning_response"] = "yes"

    profile = build_soulmate_profile(raw)
    assert profile.spiritual_person is True
    assert profile.familiar_psychic_artistry is False
    assert profile.warning_response == "yes"


@pytest.mark.asyncio
async def test_db_profile_sync_at_transition_5(db_session):
    """
    Integration test:
    - Session answers all questions q02..q18.
    - Advancing transition_5 automatically materializes and persists SoulmateProfile in DB.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        # Insert answers for q02 through q18 in DB
        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        now = utc_now()
        raw_answers = _get_valid_answers_dict()
        for q_code, payload in raw_answers.items():
            ans = SoulmateAnswer(
                session_id=sess.id,
                question_code=q_code,
                answer_json=payload,
                answered_at=now,
                updated_at=now,
            )
            db_session.add(ans)

        sess.current_step = "transition_5"
        db_session.commit()

        # Verify no profile before transition_5 continue
        stmt = select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        assert db_session.execute(stmt).scalar_one_or_none() is None

        # Continue transition_5
        cont_res = await client.post(
            f"/api/soulmate/sessions/{session_id}/transitions/transition_5/continue"
        )
        assert cont_res.status_code == 200
        assert cont_res.json()["next_step"] == "spiritual_person"

        # SoulmateProfile row must now be created and persisted in DB!
        db_session.expire_all()
        profile_row = db_session.execute(stmt).scalar_one_or_none()
        assert profile_row is not None
        assert profile_row.user_gender == "female"
        assert profile_row.preferred_partner_gender == "male"
        assert profile_row.key_soulmate_quality == "loyalty"
        assert profile_row.zodiac_sign == "Virgo"
        assert profile_row.profile_version == "v1"


@pytest.mark.asyncio
async def test_db_profile_resync_on_answer_change_post_quiz(db_session):
    """
    DEV-SPEC §7: "并在答案变化时重算"
    If an answer changes after quiz completion, SoulmateProfile is automatically updated.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create session
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        # 2. Add complete answers and set transition_5
        now = utc_now()
        raw_answers = _get_valid_answers_dict()
        for q_code, payload in raw_answers.items():
            ans = SoulmateAnswer(
                session_id=sess.id,
                question_code=q_code,
                answer_json=payload,
                answered_at=now,
                updated_at=now,
            )
            db_session.add(ans)
        sess.current_step = "transition_5"
        db_session.commit()

        # 3. Transition 5 materializes profile
        await client.post(
            f"/api/soulmate/sessions/{session_id}/transitions/transition_5/continue"
        )

        db_session.expire_all()
        stmt = select(SoulmateProfile).where(SoulmateProfile.session_id == sess.id)
        initial_profile = db_session.execute(stmt).scalar_one()
        assert initial_profile.key_soulmate_quality == "loyalty"
        initial_updated_at = initial_profile.updated_at

        # 4. User edits Q07 to "intelligence"
        edit_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q07",
            json={"value": "intelligence"},
        )
        assert edit_res.status_code == 200

        # 5. Check updated profile in DB
        db_session.expire_all()
        updated_profile = db_session.execute(stmt).scalar_one()
        assert updated_profile.key_soulmate_quality == "intelligence"
        assert updated_profile.updated_at >= initial_updated_at


@pytest.mark.asyncio
async def test_get_profile_api_endpoint(db_session):
    """Verifies GET /api/soulmate/sessions/{public_id}/profile endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create session 1
        res1 = await client.post("/api/soulmate/sessions", json={})
        s1_id = res1.json()["session_id"]

        # Before quiz is complete, 404 is returned
        r1 = await client.get(f"/api/soulmate/sessions/{s1_id}/profile")
        assert r1.status_code == 404

        # 2. Add complete answers in DB
        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == s1_id)
        ).scalar_one()
        now = utc_now()
        raw_answers = _get_valid_answers_dict()
        for q_code, payload in raw_answers.items():
            ans = SoulmateAnswer(
                session_id=sess.id,
                question_code=q_code,
                answer_json=payload,
                answered_at=now,
                updated_at=now,
            )
            db_session.add(ans)
        db_session.commit()

        # 3. GET /profile succeeds and returns SoulmateProfileV1
        r2 = await client.get(f"/api/soulmate/sessions/{s1_id}/profile")
        assert r2.status_code == 200
        data = r2.json()
        assert data["userGender"] == "female"
        assert data["preferredPartnerGender"] == "male"
        assert data["zodiacSign"] == "Virgo"
        assert data["keySoulmateQuality"] == "loyalty"

        # 4. IDOR test: different session receives 403 Forbidden
        res2 = await client.post("/api/soulmate/sessions", json={})
        # (res2 sets cookie for session 2 in client)
        r3 = await client.get(f"/api/soulmate/sessions/{s1_id}/profile")
        assert r3.status_code == 403
        assert r3.json()["error_code"] == "FORBIDDEN_OWNERSHIP"
