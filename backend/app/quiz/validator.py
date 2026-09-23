from typing import Set
from app.quiz.schema import QuestionType, QuizConfig


class QuizValidationError(Exception):
    """Raised when a QuizConfig violates canonical invariants."""
    pass


def validate_quiz_config(config: QuizConfig) -> None:
    """
    Validate canonical quiz configuration against DEV-SPEC §4.1–4.6 invariants.
    
    Acceptance criteria:
    - Exactly Q02–Q18 are present (17 questions)
    - Sequential orders 2..18 matching codes q02..q18
    - Q18 is the only multi-select question
    - Q08 is the only date question
    - Q02/Q03 result keys remain distinct (user_gender vs preferred_partner_gender)
    - No duplicate question codes
    - No duplicate option codes within a question
    - No duplicate result keys across questions
    - All questions required=True
    """
    expected_codes = [f"q{i:02d}" for i in range(2, 19)]
    actual_codes = [q.code for q in config.questions]

    # Invariant 1: Exactly Q02-Q18
    if actual_codes != expected_codes:
        missing = set(expected_codes) - set(actual_codes)
        extra = set(actual_codes) - set(expected_codes)
        raise QuizValidationError(
            f"Question sequence mismatch. Expected exactly {expected_codes}. "
            f"Missing: {sorted(missing)}, Extra: {sorted(extra)}, Actual: {actual_codes}"
        )

    seen_result_keys: Set[str] = set()

    for expected_order, question in enumerate(config.questions, start=2):
        # Order check
        if question.order != expected_order:
            raise QuizValidationError(
                f"Question {question.code} has order {question.order}, expected {expected_order}"
            )

        # Required check
        if not question.required:
            raise QuizValidationError(f"Question {question.code} must be required")

        # Result key uniqueness
        if question.result_key in seen_result_keys:
            raise QuizValidationError(
                f"Duplicate result_key '{question.result_key}' found in question {question.code}"
            )
        seen_result_keys.add(question.result_key)

        # Type-specific invariants
        if question.code == "q18":
            if question.type != QuestionType.MULTI:
                raise QuizValidationError(f"Question q18 must be of type 'multi', got '{question.type}'")
            if question.min_select != 1:
                raise QuizValidationError(f"Question q18 min_select must be 1, got {question.min_select}")
        else:
            if question.type == QuestionType.MULTI:
                raise QuizValidationError(
                    f"Only q18 may be of type 'multi'. Question {question.code} is 'multi'."
                )

        if question.code == "q08":
            if question.type != QuestionType.DATE:
                raise QuizValidationError(f"Question q08 must be of type 'date', got '{question.type}'")
            if question.options:
                raise QuizValidationError("Question q08 (date) must not define options")
            if not question.subtitle:
                raise QuizValidationError("Question q08 must include subtitle text")
        else:
            if question.type == QuestionType.DATE:
                raise QuizValidationError(
                    f"Only q08 may be of type 'date'. Question {question.code} is 'date'."
                )

        # Options check for single/multi
        if question.type in (QuestionType.SINGLE, QuestionType.MULTI):
            if not question.options or len(question.options) < 2:
                raise QuizValidationError(
                    f"Question {question.code} must have at least 2 options, got {len(question.options) if question.options else 0}"
                )
            option_codes = [opt.code for opt in question.options]
            if len(option_codes) != len(set(option_codes)):
                duplicates = [c for c in option_codes if option_codes.count(c) > 1]
                raise QuizValidationError(
                    f"Question {question.code} contains duplicate option codes: {set(duplicates)}"
                )

    # Invariant 4: Q02 / Q03 distinct result keys (QUIZ-01)
    q02 = next(q for q in config.questions if q.code == "q02")
    q03 = next(q for q in config.questions if q.code == "q03")
    if q02.result_key != "user_gender":
        raise QuizValidationError(
            f"Question q02 result_key must be 'user_gender' (QUIZ-01), got '{q02.result_key}'"
        )
    if q03.result_key != "preferred_partner_gender":
        raise QuizValidationError(
            f"Question q03 result_key must be 'preferred_partner_gender' (QUIZ-01), got '{q03.result_key}'"
        )
    if q02.result_key == q03.result_key:
        raise QuizValidationError("q02 and q03 result keys must remain distinct")
