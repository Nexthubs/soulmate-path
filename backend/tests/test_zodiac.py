"""Comprehensive Automated Tests for Server-Authoritative DOB / Zodiac Engine (DEV-SPEC §4.4, §5.5, AGE-01, SP-204)."""

from datetime import date
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.core.errors import ValidationError
from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.soulmate.domain.step_resolver import resolve_transition_metadata
from app.soulmate.domain.zodiac import (
    ZODIAC_DEFINITIONS,
    ZodiacDetail,
    ZodiacSign,
    get_zodiac_by_name,
    get_zodiac_for_date,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# All 24 boundary dates (starts and ends of each sign), plus leap day and year transitions (DEV-SPEC §5.5)
ZODIAC_BOUNDARY_CASES = [
    # Aries: 03-21 ~ 04-19
    ("1995-03-21", ZodiacSign.ARIES, "Aries", "Aries Sun", "fire"),
    ("1995-04-19", ZodiacSign.ARIES, "Aries", "Aries Sun", "fire"),
    # Taurus: 04-20 ~ 05-20
    ("1995-04-20", ZodiacSign.TAURUS, "Taurus", "Taurus Sun", "earth"),
    ("1995-05-20", ZodiacSign.TAURUS, "Taurus", "Taurus Sun", "earth"),
    # Gemini: 05-21 ~ 06-21
    ("1995-05-21", ZodiacSign.GEMINI, "Gemini", "Gemini Sun", "air"),
    ("1995-06-21", ZodiacSign.GEMINI, "Gemini", "Gemini Sun", "air"),
    # Cancer: 06-22 ~ 07-22
    ("1995-06-22", ZodiacSign.CANCER, "Cancer", "Cancer Sun", "water"),
    ("1995-07-22", ZodiacSign.CANCER, "Cancer", "Cancer Sun", "water"),
    # Leo: 07-23 ~ 08-22
    ("1995-07-23", ZodiacSign.LEO, "Leo", "Leo Sun", "fire"),
    ("1995-08-22", ZodiacSign.LEO, "Leo", "Leo Sun", "fire"),
    # Virgo: 08-23 ~ 09-22
    ("1995-08-23", ZodiacSign.VIRGO, "Virgo", "Virgo Sun", "earth"),
    ("1995-09-22", ZodiacSign.VIRGO, "Virgo", "Virgo Sun", "earth"),
    # Libra: 09-23 ~ 10-23
    ("1995-09-23", ZodiacSign.LIBRA, "Libra", "Libra Sun", "air"),
    ("1995-10-23", ZodiacSign.LIBRA, "Libra", "Libra Sun", "air"),
    # Scorpio: 10-24 ~ 11-21
    ("1995-10-24", ZodiacSign.SCORPIO, "Scorpio", "Scorpio Sun", "water"),
    ("1995-11-21", ZodiacSign.SCORPIO, "Scorpio", "Scorpio Sun", "water"),
    # Sagittarius: 11-22 ~ 12-20
    ("1995-11-22", ZodiacSign.SAGITTARIUS, "Sagittarius", "Sagittarius Sun", "fire"),
    ("1995-12-20", ZodiacSign.SAGITTARIUS, "Sagittarius", "Sagittarius Sun", "fire"),
    # Capricorn: 12-21 ~ 01-20 (crosses year boundary)
    ("1995-12-21", ZodiacSign.CAPRICORN, "Capricorn", "Capricorn Sun", "earth"),
    ("1995-12-31", ZodiacSign.CAPRICORN, "Capricorn", "Capricorn Sun", "earth"),
    ("1996-01-01", ZodiacSign.CAPRICORN, "Capricorn", "Capricorn Sun", "earth"),
    ("1996-01-20", ZodiacSign.CAPRICORN, "Capricorn", "Capricorn Sun", "earth"),
    # Aquarius: 01-21 ~ 02-19
    ("1996-01-21", ZodiacSign.AQUARIUS, "Aquarius", "Aquarius Sun", "air"),
    ("1996-02-19", ZodiacSign.AQUARIUS, "Aquarius", "Aquarius Sun", "air"),
    # Pisces: 02-20 ~ 03-20 (including leap day)
    ("1996-02-20", ZodiacSign.PISCES, "Pisces", "Pisces Sun", "water"),
    ("1995-02-28", ZodiacSign.PISCES, "Pisces", "Pisces Sun", "water"),
    ("1996-02-29", ZodiacSign.PISCES, "Pisces", "Pisces Sun", "water"),  # Leap year
    ("1996-03-20", ZodiacSign.PISCES, "Pisces", "Pisces Sun", "water"),
]


@pytest.mark.parametrize("date_str,expected_sign,expected_name,expected_label,expected_element", ZODIAC_BOUNDARY_CASES)
def test_all_zodiac_boundary_dates(date_str, expected_sign, expected_name, expected_label, expected_element):
    """
    Acceptance (SP-204):
    - Server computes zodiac using product-defined boundaries;
    - All boundary dates have tests.
    """
    detail = get_zodiac_for_date(date_str)
    assert detail.sign == expected_sign
    assert detail.name == expected_name
    assert detail.sun_label == expected_label
    assert detail.element == expected_element

    # Also verify with datetime.date object
    parsed_date = date.fromisoformat(date_str)
    detail_from_date = get_zodiac_for_date(parsed_date)
    assert detail_from_date == detail


def test_get_zodiac_by_name():
    """Verify lookup by sign name or code."""
    virgo = get_zodiac_by_name("Virgo")
    assert virgo is not None
    assert virgo.sign == ZodiacSign.VIRGO

    virgo_code = get_zodiac_by_name("virgo")
    assert virgo_code == virgo

    assert get_zodiac_by_name("non_existent_sign") is None


def test_invalid_date_formats():
    """Verify malformed date strings raise ValidationError."""
    with pytest.raises(ValidationError, match="Invalid birth date format"):
        get_zodiac_for_date("not-a-date")

    with pytest.raises(ValidationError, match="Invalid birth date format"):
        get_zodiac_for_date("1995/08/25")

    with pytest.raises(ValidationError, match="Unsupported birth date type"):
        get_zodiac_for_date(12345)  # type: ignore


@pytest.mark.parametrize(
    "q10_choice,expected_phrase,expected_copy",
    [
        ("heart", "heart", "people make decisions using their heart."),
        ("head", "head", "people make decisions using their head."),
        ("both", "heart and head", "people make decisions using their heart and head."),
    ],
)
def test_transition_3_metadata_resolution(q10_choice, expected_phrase, expected_copy):
    """
    Acceptance (DEV-SPEC §5.5, SP-204):
    - Transition-3 dynamically renders zodiac and Q10 decision copy.
    """
    answers = {
        "q08": {"value": "1994-08-25"},  # Virgo
        "q10": {"value": q10_choice},
    }
    meta = resolve_transition_metadata("transition_3", answers)

    assert meta["transition_code"] == "transition_3"
    assert meta["zodiac_sign"] == "Virgo"
    assert meta["zodiac_label"] == "Virgo Sun"
    assert meta["decision_style"] == q10_choice
    assert meta["decision_copy"] == expected_copy
    assert f"Many Virgo Sun individuals make decisions using their {expected_phrase}." in meta["subtitle"]


def test_transition_3_metadata_fallback_when_answers_missing():
    """Transition-3 falls back cleanly if answers are incomplete."""
    meta = resolve_transition_metadata("transition_3", {})
    assert meta["transition_code"] == "transition_3"
    assert meta["zodiac_label"] == "Your Zodiac"
    assert meta["decision_copy"] == "people make decisions using their heart and head."
    assert "Your Zodiac" in meta["subtitle"]


@pytest.mark.asyncio
async def test_q08_submission_returns_and_persists_zodiac(db_session):
    """
    Acceptance:
    - Submitting Q08 returns server-computed zodiac in response;
    - Answer row in DB persists zodiac metadata;
    - Client displays returned zodiac but is not authoritative.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session
        res = await client.post("/api/soulmate/sessions", json={})
        assert res.status_code == 201
        session_id = res.json()["session_id"]

        # Seed prerequisite answers q02..q07
        now = utc_now()
        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        prereqs = {
            "q02": {"value": "female"},
            "q03": {"value": "male"},
            "q04": {"value": "single"},
            "q05": {"value": "age_20_30"},
            "q06": {"value": "caucasian_white"},
            "q07": {"value": "kindness"},
        }
        for q_code, val in prereqs.items():
            db_session.add(
                SoulmateAnswer(
                    session_id=sess.id,
                    question_code=q_code,
                    answer_json=val,
                    answered_at=now,
                    updated_at=now,
                )
            )
        db_session.commit()

        # Submit Q08 (birth date)
        q08_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q08",
            json={"value": "1994-08-25", "duration_ms": 3200},
        )
        assert q08_res.status_code == 200
        data = q08_res.json()

        assert data["saved"] is True
        assert data["question_code"] == "q08"
        assert data["next_step"] == "q09"
        # Server-computed zodiac in response
        assert data["zodiac"] is not None
        assert data["zodiac"]["sign"] == "Virgo"
        assert data["zodiac"]["label"] == "Virgo Sun"

        # Assert DB record contains enriched zodiac
        ans_row = db_session.execute(
            select(SoulmateAnswer).where(
                SoulmateAnswer.session_id == sess.id,
                SoulmateAnswer.question_code == "q08",
            )
        ).scalar_one()
        assert ans_row.answer_json["value"] == "1994-08-25"
        assert ans_row.answer_json["zodiac_sign"] == "Virgo"
        assert ans_row.answer_json["zodiac_label"] == "Virgo Sun"
        assert ans_row.answer_json["zodiac_element"] == "earth"


@pytest.mark.asyncio
async def test_age_01_not_invented_permits_reasonable_dates(db_session):
    """
    Acceptance (Decision AGE-01):
    - No unapproved minimum age floor (such as 18) is invented;
    - Real calendar dates within [1900, today] succeed;
    - Year < 1900 and future dates fail.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/soulmate/sessions", json={})
        session_id = res.json()["session_id"]

        now = utc_now()
        sess = db_session.execute(
            select(SoulmateSession).where(SoulmateSession.public_id == session_id)
        ).scalar_one()

        prereqs = {
            "q02": {"value": "female"},
            "q03": {"value": "male"},
            "q04": {"value": "single"},
            "q05": {"value": "age_20_30"},
            "q06": {"value": "caucasian_white"},
            "q07": {"value": "kindness"},
        }
        for q_code, val in prereqs.items():
            db_session.add(
                SoulmateAnswer(
                    session_id=sess.id,
                    question_code=q_code,
                    answer_json=val,
                    answered_at=now,
                    updated_at=now,
                )
            )
        db_session.commit()

        # 1. 16-year old birth date (2010) is accepted without inventing an unapproved 18+ gate
        ok_res = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q08",
            json={"value": "2010-05-15"},
        )
        assert ok_res.status_code == 200
        assert ok_res.json()["zodiac"]["sign"] == "Taurus"

        # 2. Year < 1900 is rejected
        err_old = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q08",
            json={"value": "1885-05-15"},
        )
        assert err_old.status_code == 400
        assert err_old.json()["error_code"] == "VALIDATION_ERROR"

        # 3. Future date is rejected
        err_future = await client.put(
            f"/api/soulmate/sessions/{session_id}/answers/q08",
            json={"value": "2099-01-01"},
        )
        assert err_future.status_code == 400
        assert err_future.json()["error_code"] == "VALIDATION_ERROR"
