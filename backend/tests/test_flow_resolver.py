"""Table-driven unit tests for Soulmate Flow Resolver (DEV-SPEC §1.1, §4, §5, §6, §15.3, SP-203)."""

import pytest
from app.core.errors import InvalidFlowStateError
from app.soulmate.domain.step_resolver import (
    ALL_FLOW_STEPS_SET,
    ALL_QUESTION_CODES,
    CANONICAL_FLOW_STEPS,
    TRANSITION_2_COPY_BY_OPTION,
    TRANSITION_2_DEFAULT_COPY,
    StepType,
    calculate_progress_percent,
    get_next_step,
    get_prerequisite_questions_for_question,
    get_previous_step,
    get_step_type,
    resolve_next_step_for_interstitial,
    resolve_next_step_for_question,
    resolve_transition_metadata,
    validate_can_advance_transition,
    validate_can_answer_question,
)


def test_canonical_flow_steps_sequence():
    """Verify canonical sequence contains all 29 steps and starts/ends correctly."""
    assert len(CANONICAL_FLOW_STEPS) == 29
    assert CANONICAL_FLOW_STEPS[0] == "transition_0"
    assert CANONICAL_FLOW_STEPS[-1] == "result"
    assert len(ALL_FLOW_STEPS_SET) == 29
    assert len(ALL_QUESTION_CODES) == 17  # q02 to q18



def test_table_driven_get_next_step():
    """Verify every forward edge in the canonical sequence."""
    for i in range(len(CANONICAL_FLOW_STEPS) - 1):
        curr = CANONICAL_FLOW_STEPS[i]
        expected_next = CANONICAL_FLOW_STEPS[i + 1]
        assert get_next_step(curr) == expected_next, f"Next step after '{curr}' should be '{expected_next}'"

    # Terminal step returns None
    assert get_next_step("result") is None

    # Invalid step code raises ValueError
    with pytest.raises(ValueError, match="Unknown step code"):
        get_next_step("non_existent_step")


def test_table_driven_get_previous_step():
    """Verify every backward edge in the canonical sequence."""
    # Starting step returns None
    assert get_previous_step("transition_0") is None

    for i in range(1, len(CANONICAL_FLOW_STEPS)):
        curr = CANONICAL_FLOW_STEPS[i]
        expected_prev = CANONICAL_FLOW_STEPS[i - 1]
        assert get_previous_step(curr) == expected_prev, f"Previous step before '{curr}' should be '{expected_prev}'"

    # Invalid step code raises ValueError
    with pytest.raises(ValueError, match="Unknown step code"):
        get_previous_step("non_existent_step")


@pytest.mark.parametrize(
    "step_code,expected_type",
    [
        ("transition_0", StepType.TRANSITION),
        ("q02", StepType.QUESTION),
        ("q06", StepType.QUESTION),
        ("transition_1", StepType.TRANSITION),
        ("q07", StepType.QUESTION),
        ("transition_2", StepType.TRANSITION),
        ("q11", StepType.QUESTION),
        ("transition_4", StepType.TRANSITION),
        ("q18", StepType.QUESTION),
        ("transition_5", StepType.TRANSITION),
        ("spiritual_person", StepType.INTERSTITIAL),
        ("familiar_psychic_artistry", StepType.INTERSTITIAL),
        ("warning_response", StepType.INTERSTITIAL),
        ("email", StepType.EMAIL),
        ("subscribe", StepType.CHECKOUT),
        ("result", StepType.RESULT),
    ],
)
def test_get_step_type(step_code: str, expected_type: StepType):
    assert get_step_type(step_code) == expected_type


def test_get_step_type_invalid():
    with pytest.raises(ValueError, match="Cannot determine step type"):
        get_step_type("invalid_step_xyz")


def test_calculate_progress_percent():
    assert calculate_progress_percent("transition_0") == 0
    assert calculate_progress_percent("result") == 100

    # Ensure progress strictly monotonically increases
    prev_pct = -1
    for step in CANONICAL_FLOW_STEPS:
        pct = calculate_progress_percent(step)
        assert 0 <= pct <= 100
        assert pct >= prev_pct
        prev_pct = pct

    # Invalid step returns 0
    assert calculate_progress_percent("unknown_step") == 0


def test_get_prerequisite_questions_for_question():
    assert get_prerequisite_questions_for_question("q02") == []
    assert get_prerequisite_questions_for_question("q03") == ["q02"]
    assert get_prerequisite_questions_for_question("q07") == ["q02", "q03", "q04", "q05", "q06"]
    assert get_prerequisite_questions_for_question("q18") == [f"q{i:02d}" for i in range(2, 18)]

    with pytest.raises(ValueError, match="Invalid question code"):
        get_prerequisite_questions_for_question("q01")

    with pytest.raises(ValueError, match="Invalid question code"):
        get_prerequisite_questions_for_question("q19")


def test_validate_can_answer_question_skip_prevention():
    """Verify skip attempts are rejected with HTTP 409 InvalidFlowStateError."""
    # 1. First question q02 always allowed
    validate_can_answer_question("q02", set())

    # 2. Attempting q03 without q02 raises error
    with pytest.raises(InvalidFlowStateError) as exc_info:
        validate_can_answer_question("q03", set())
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["missing_prerequisites"] == ["q02"]

    # 3. Attempting q06 with only q02 answered
    with pytest.raises(InvalidFlowStateError) as exc_info:
        validate_can_answer_question("q06", {"q02"})
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["missing_prerequisites"] == ["q03", "q04", "q05"]

    # 4. Valid sequential progression
    answered = {"q02", "q03"}
    validate_can_answer_question("q04", answered)


def test_validate_can_answer_question_back_and_reanswer():
    """Verify back navigation & re-answering past questions is permitted."""
    answered = {"q02", "q03", "q04", "q05"}

    # Re-answering q02 is allowed
    validate_can_answer_question("q02", answered)

    # Re-answering q04 is allowed
    validate_can_answer_question("q04", answered)

    # Answering the next sequential question q06 is allowed
    validate_can_answer_question("q06", answered)


def test_validate_can_advance_transition():
    """Verify transition prerequisite validation."""
    # transition_0 has no prerequisites
    validate_can_advance_transition("transition_0", set())

    # transition_1 requires q02 through q06
    with pytest.raises(InvalidFlowStateError) as exc:
        validate_can_advance_transition("transition_1", {"q02", "q03"})
    assert "q04" in exc.value.details["missing_prerequisites"]

    q02_to_q06 = {"q02", "q03", "q04", "q05", "q06"}
    validate_can_advance_transition("transition_1", q02_to_q06)

    # transition_2 requires q02 through q07
    with pytest.raises(InvalidFlowStateError):
        validate_can_advance_transition("transition_2", q02_to_q06)
    validate_can_advance_transition("transition_2", q02_to_q06 | {"q07"})

    # transition_5 requires all questions q02 through q18
    all_questions = set(ALL_QUESTION_CODES)
    with pytest.raises(InvalidFlowStateError):
        validate_can_advance_transition("transition_5", all_questions - {"q18"})
    validate_can_advance_transition("transition_5", all_questions)

    # Unknown transition code raises ValueError
    with pytest.raises(ValueError, match="Unknown transition code"):
        validate_can_advance_transition("transition_99", set())


def test_resolve_transition_metadata_copy_02():
    """Verify Transition-2 dynamic copy resolution per COPY-02."""
    for option_code, expected_copy in TRANSITION_2_COPY_BY_OPTION.items():
        answers = {"q07": {"value": option_code}}
        meta = resolve_transition_metadata("transition_2", answers)
        assert meta["transition_code"] == "transition_2"
        assert meta["selected_option"] == option_code
        assert meta["title"] == expected_copy["title"]
        assert meta["body"] == expected_copy["body"]

    # Unknown or missing option falls back to default copy without crashing
    default_meta = resolve_transition_metadata("transition_2", {})
    assert default_meta["title"] == TRANSITION_2_DEFAULT_COPY["title"]
    assert default_meta["body"] == TRANSITION_2_DEFAULT_COPY["body"]


def test_resolve_transition_metadata_copy_03():
    """Verify Transition-4 static copy per COPY-03 and Figma 102:372."""
    meta = resolve_transition_metadata("transition_4", {})
    assert meta["transition_code"] == "transition_4"
    assert meta["title"] == "So many share this challenge"
    assert "Moving on from the past is hard" in meta["subtitle"]
    assert meta["cta"] == "Continue"



def test_backwards_compatibility_helpers():
    assert resolve_next_step_for_question("q02") == "q03"
    assert resolve_next_step_for_interstitial("spiritual_person") == "familiar_psychic_artistry"

    with pytest.raises(ValueError):
        resolve_next_step_for_question("result")

    with pytest.raises(ValueError):
        resolve_next_step_for_interstitial("result")
