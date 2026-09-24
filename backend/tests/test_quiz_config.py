import copy
import json
from pathlib import Path
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.core.config import settings
from app.db.base import utc_now
from app.db.models.quiz import SoulmateQuizVersion
from app.db.models.session import SoulmateSession
from app.db.session import SessionLocal
from app.main import app
from app.quiz.constants import CANONICAL_QUIZ_VERSION
from app.quiz.loader import get_cached_quiz_config, invalidate_quiz_config_cache, load_quiz_config
from app.quiz.schema import QuestionType, QuizConfig, QuizOption, QuizQuestion
from app.quiz.seed import seed_quiz_version
from app.quiz.validator import QuizValidationError, validate_quiz_config


@pytest.fixture
def db_session():
    """Transactional DB session fixture."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_canonical_config_loads_and_validates():
    """Verify canonical configuration loads cleanly and passes all invariants."""
    config = load_quiz_config()
    assert config.version == CANONICAL_QUIZ_VERSION
    assert len(config.questions) == 17

    # Q02-Q18 codes and orders
    expected_codes = [f"q{i:02d}" for i in range(2, 19)]
    actual_codes = [q.code for q in config.questions]
    assert actual_codes == expected_codes

    for idx, q in enumerate(config.questions, start=2):
        assert q.order == idx
        assert q.required is True
        assert q.result_key is not None and len(q.result_key) > 0

    # Invariant: Q02 / Q03 distinct result keys (QUIZ-01)
    q02 = next(q for q in config.questions if q.code == "q02")
    q03 = next(q for q in config.questions if q.code == "q03")
    assert q02.result_key == "user_gender"
    assert q03.result_key == "preferred_partner_gender"
    assert q02.result_key != q03.result_key

    # Invariant: Q08 is date only
    q08 = next(q for q in config.questions if q.code == "q08")
    assert q08.type == QuestionType.DATE
    assert q08.options is None
    assert q08.subtitle is not None

    # Invariant: Q18 is multi only
    q18 = next(q for q in config.questions if q.code == "q18")
    assert q18.type == QuestionType.MULTI
    assert q18.min_select == 1
    assert q18.max_select is None
    assert len(q18.options) >= 2

    # Cached loader returns the same
    cached = get_cached_quiz_config()
    assert cached.version == config.version


def test_validation_rejects_missing_question():
    """Acceptance criterion: exactly Q02-Q18 are present."""
    base_config = load_quiz_config()
    # Remove q05
    invalid_questions = [q for q in base_config.questions if q.code != "q05"]
    invalid_config = QuizConfig(version=base_config.version, questions=invalid_questions)

    with pytest.raises(QuizValidationError, match="Question sequence mismatch"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_extra_question():
    """Acceptance criterion: exactly Q02-Q18 are present, no extra questions."""
    base_config = load_quiz_config()
    extra_q = QuizQuestion(
        code="q19",
        order=19,
        type=QuestionType.SINGLE,
        title="Extra question",
        required=True,
        result_key="extra_key",
        options=[QuizOption(code="a", label="A"), QuizOption(code="b", label="B")],
    )
    invalid_questions = list(base_config.questions) + [extra_q]
    invalid_config = QuizConfig(version=base_config.version, questions=invalid_questions)

    with pytest.raises(QuizValidationError, match="Question sequence mismatch"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_q18_as_single():
    """Acceptance criterion: Q18 is the only multi-select question."""
    base_config = load_quiz_config()
    questions = []
    for q in base_config.questions:
        if q.code == "q18":
            q_copy = q.model_copy(update={"type": QuestionType.SINGLE, "min_select": None})
            questions.append(q_copy)
        else:
            questions.append(q)

    invalid_config = QuizConfig(version=base_config.version, questions=questions)
    with pytest.raises(QuizValidationError, match="Question q18 must be of type 'multi'"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_other_question_as_multi():
    """Acceptance criterion: No other question besides Q18 may be multi-select."""
    base_config = load_quiz_config()
    questions = []
    for q in base_config.questions:
        if q.code == "q04":
            q_copy = q.model_copy(update={"type": QuestionType.MULTI, "min_select": 1})
            questions.append(q_copy)
        else:
            questions.append(q)

    invalid_config = QuizConfig(version=base_config.version, questions=questions)
    with pytest.raises(QuizValidationError, match="Only q18 may be of type 'multi'"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_q08_as_single():
    """Acceptance criterion: Q08 is date."""
    base_config = load_quiz_config()
    questions = []
    for q in base_config.questions:
        if q.code == "q08":
            q_copy = q.model_copy(
                update={
                    "type": QuestionType.SINGLE,
                    "options": [QuizOption(code="d1", label="D1"), QuizOption(code="d2", label="D2")],
                }
            )
            questions.append(q_copy)
        else:
            questions.append(q)

    invalid_config = QuizConfig(version=base_config.version, questions=questions)
    with pytest.raises(QuizValidationError, match="Question q08 must be of type 'date'"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_duplicate_option_codes():
    """Acceptance criterion: duplicate option codes within question fail validation."""
    base_config = load_quiz_config()
    questions = []
    for q in base_config.questions:
        if q.code == "q02":
            q_copy = q.model_copy(
                update={
                    "options": [
                        QuizOption(code="dup", label="Option 1"),
                        QuizOption(code="dup", label="Option 2"),
                    ]
                }
            )
            questions.append(q_copy)
        else:
            questions.append(q)

    invalid_config = QuizConfig(version=base_config.version, questions=questions)
    with pytest.raises(QuizValidationError, match="duplicate option codes"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_duplicate_result_keys():
    """Acceptance criterion: Q02/Q03 result keys remain distinct, no duplicate result keys."""
    base_config = load_quiz_config()
    questions = []
    for q in base_config.questions:
        if q.code == "q03":
            # Violate QUIZ-01 by setting result_key to user_gender
            q_copy = q.model_copy(update={"result_key": "user_gender"})
            questions.append(q_copy)
        else:
            questions.append(q)

    invalid_config = QuizConfig(version=base_config.version, questions=questions)
    with pytest.raises(QuizValidationError, match="Duplicate result_key 'user_gender'"):
        validate_quiz_config(invalid_config)


def test_validation_rejects_out_of_order_questions():
    """Acceptance criterion: questions must be ordered sequentially 2..18."""
    base_config = load_quiz_config()
    questions = list(base_config.questions)
    # Swap q04 and q05
    questions[2], questions[3] = questions[3], questions[2]

    invalid_config = QuizConfig(version=base_config.version, questions=questions)
    with pytest.raises(QuizValidationError):
        validate_quiz_config(invalid_config)


def test_seed_quiz_version_database_roundtrip(db_session):
    """Verify seed_quiz_version correctly persists and updates in PostgreSQL."""
    quiz_ver = seed_quiz_version(db_session, activate=True)
    assert quiz_ver.version == CANONICAL_QUIZ_VERSION
    assert quiz_ver.is_active is True
    assert "questions" in quiz_ver.config_json
    assert len(quiz_ver.config_json["questions"]) == 17

    # Verify querying from DB
    from sqlalchemy import select
    row = db_session.execute(
        select(SoulmateQuizVersion).where(SoulmateQuizVersion.version == CANONICAL_QUIZ_VERSION)
    ).scalar_one()
    assert row.id == quiz_ver.id
    assert row.config_json["version"] == CANONICAL_QUIZ_VERSION


def test_session_creation_pins_canonical_quiz_version(db_session):
    """Work requirement: Session creation must pin quiz_version = soulmate-quiz-v1."""
    sess = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        status="IN_PROGRESS",
        current_step="q02",
    )
    assert sess.quiz_version == CANONICAL_QUIZ_VERSION
    db_session.add(sess)
    db_session.commit()
    db_session.refresh(sess)
    assert sess.quiz_version == CANONICAL_QUIZ_VERSION


def test_canonical_and_frontend_quiz_json_exact_parity():
    """Audit Medium-1: Ensure root canonical config and frontend bundled mirror remain byte-for-byte identical."""
    root_dir = Path(__file__).resolve().parents[2]
    canonical_path = root_dir / "config" / "quiz" / "soulmate-quiz-v1.json"
    frontend_path = root_dir / "frontend" / "src" / "soulmate" / "quiz" / "soulmate-quiz-v1.json"

    assert canonical_path.exists(), f"Canonical quiz file missing at {canonical_path}"
    assert frontend_path.exists(), f"Frontend quiz mirror missing at {frontend_path}"

    with open(canonical_path, "r", encoding="utf-8") as f1, open(frontend_path, "r", encoding="utf-8") as f2:
        canonical_text = f1.read().strip()
        frontend_text = f2.read().strip()

    assert canonical_text == frontend_text, "Frontend quiz JSON has drifted from root canonical quiz JSON!"


def test_quiz_config_cache_invalidation():
    """Audit Medium-2: Verify get_cached_quiz_config caches and invalidate_quiz_config_cache clears it."""
    # Ensure cache is fresh
    invalidate_quiz_config_cache()
    assert get_cached_quiz_config.cache_info().currsize == 0

    c1 = get_cached_quiz_config()
    assert get_cached_quiz_config.cache_info().currsize == 1

    c2 = get_cached_quiz_config()
    assert c1 is c2
    assert get_cached_quiz_config.cache_info().hits == 1

    # Invalidate cache
    invalidate_quiz_config_cache()
    assert get_cached_quiz_config.cache_info().currsize == 0
    assert get_cached_quiz_config.cache_info().hits == 0

    c3 = get_cached_quiz_config()
    assert c3 == c1
    assert get_cached_quiz_config.cache_info().currsize == 1


def test_seed_quiz_version_rejects_content_mutation_on_same_version(db_session, tmp_path):
    """DEV-SPEC §4.5 & SP-003: Version definitions are immutable once seeded; mutating content must raise ValueError."""
    # 1. Seed initial canonical version
    v1 = seed_quiz_version(db_session, activate=True)
    assert v1.version == CANONICAL_QUIZ_VERSION

    # 2. Reseed same version with identical content -> passes idempotently
    v1_reseed = seed_quiz_version(db_session, activate=True)
    assert v1_reseed.id == v1.id

    # 3. Create modified content for the same version string
    base_config = load_quiz_config()
    altered_data = base_config.model_dump(mode="json")
    # Alter question title (valid schema but different content)
    altered_data["questions"][0]["title"] = "Altered title attempting to mutate immutable version!"

    tmp_file = tmp_path / "mutated_quiz.json"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(altered_data, f)

    # 4. Attempting to seed altered content under the same version must fail fast
    with pytest.raises(ValueError) as exc_info:
        seed_quiz_version(db_session, config_path=tmp_file)

    err_text = str(exc_info.value)
    assert "is immutable and already exists with different content" in err_text
    assert "Changing questions requires publishing a new version identifier" in err_text


@pytest.mark.asyncio
async def test_quiz_config_api_endpoint(db_session):
    """
    Acceptance (Audit High - SP-201/SP-207, DEV-SPEC §15.2):
    - GET /api/soulmate/quiz/config returns active version (v1) by default;
    - Query parameter ?version=v1 returns requested version;
    - Non-existent version returns 404 VERSION_NOT_FOUND;
    - Client with session cookie resolves the session's quiz_version.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Default without params
        res = await client.get("/api/soulmate/quiz/config")
        assert res.status_code == 200
        data = res.json()
        assert data["version"] == CANONICAL_QUIZ_VERSION
        assert len(data["questions"]) == 17

        # 2. Query param ?version=soulmate-quiz-v1
        res_v1 = await client.get(f"/api/soulmate/quiz/config?version={CANONICAL_QUIZ_VERSION}")
        assert res_v1.status_code == 200
        assert res_v1.json()["version"] == CANONICAL_QUIZ_VERSION

        # 3. Query param non-existent version -> 404
        res_404 = await client.get("/api/soulmate/quiz/config?version=v999_missing")
        assert res_404.status_code == 404
        assert res_404.json()["error_code"] == "NOT_FOUND"

        # 4. With session cookie
        create_res = await client.post("/api/soulmate/sessions", json={})
        assert create_res.status_code == 201

        res_sess = await client.get("/api/soulmate/quiz/config")
        assert res_sess.status_code == 200
        assert res_sess.json()["version"] == CANONICAL_QUIZ_VERSION


@pytest.mark.asyncio
async def test_quiz_version_isolation_in_answer_submission(db_session):
    """
    Acceptance (Audit High - SP-201/SP-202/SP-207):
    - Session bound to non-canonical quiz version validates answers against its own version schema;
    - Options valid only in v2 succeed for v2 session, but fail for v1 session.
    """
    v_name = f"v2_test_{uuid.uuid4().hex[:8]}"
    base_config = load_quiz_config()
    v2_data = base_config.model_dump(mode="json")
    v2_data["version"] = v_name
    # Add new option 'non_binary' to q02
    v2_data["questions"][0]["options"].append({"code": "non_binary", "label": "Non-binary"})

    v2_row = SoulmateQuizVersion(
        version=v_name,
        is_active=False,
        config_json=v2_data,
        created_at=utc_now(),
    )
    db_session.add(v2_row)
    db_session.commit()

    transport = ASGITransport(app=app)
    # 1. Create normal v1 session
    async with AsyncClient(transport=transport, base_url="http://test") as client_v1:
        s1_res = await client_v1.post("/api/soulmate/sessions", json={})
        s1_id = s1_res.json()["session_id"]
        await client_v1.post(f"/api/soulmate/sessions/{s1_id}/transitions/transition_0/continue")

        # In v1, 'non_binary' is invalid option
        fail_res = await client_v1.put(
            f"/api/soulmate/sessions/{s1_id}/answers/q02",
            json={"value": "non_binary"},
        )
        assert fail_res.status_code == 400
        assert fail_res.json()["error_code"] == "VALIDATION_ERROR"

    # 2. Create session with v2_test version
    async with AsyncClient(transport=transport, base_url="http://test") as client_v2:
        s2_res = await client_v2.post("/api/soulmate/sessions", json={})
        s2_id = s2_res.json()["session_id"]

        # Manually bind session to v2_test and set current_step to q02
        with SessionLocal() as db:
            from sqlalchemy import select
            sess = db.execute(select(SoulmateSession).where(SoulmateSession.public_id == s2_id)).scalar_one()
            sess.quiz_version = v_name
            sess.current_step = "q02"
            db.commit()

        # In v2_test, 'non_binary' is valid!
        ok_res = await client_v2.put(
            f"/api/soulmate/sessions/{s2_id}/answers/q02",
            json={"value": "non_binary"},
        )
        assert ok_res.status_code == 200
        assert ok_res.json()["saved"] is True
        assert ok_res.json()["next_step"] == "q03"

        # Verify GET /api/soulmate/quiz/config with v2 cookie returns v2_test schema
        cfg_res = await client_v2.get("/api/soulmate/quiz/config")
        assert cfg_res.status_code == 200
        assert cfg_res.json()["version"] == v_name
        q02_opts = [opt["code"] for opt in cfg_res.json()["questions"][0]["options"]]
        assert "non_binary" in q02_opts


