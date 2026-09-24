"""Soulmate Central Authoritative State Machine & Flow Resolver (DEV-SPEC §1.1, §4, §5, §6, §15.3, SP-203)."""

from enum import Enum
from typing import Any, Dict, List, Optional, Set
from app.core.errors import InvalidFlowStateError
from app.soulmate.domain.zodiac import get_zodiac_for_date


class StepType(str, Enum):
    QUESTION = "question"
    TRANSITION = "transition"
    INTERSTITIAL = "interstitial"
    EMAIL = "email"
    CHECKOUT = "checkout"
    RESULT = "result"


# Canonical 28-step flow sequence matching DEV-SPEC §1.1 and §5.1
CANONICAL_FLOW_STEPS: List[str] = [
    "transition_0",
    "q02",
    "q03",
    "q04",
    "q05",
    "q06",
    "transition_1",
    "q07",
    "transition_2",
    "q08",
    "q09",
    "q10",
    "transition_3",
    "q11",
    "transition_4",
    "q12",
    "q13",
    "q14",
    "q15",
    "q16",
    "q17",
    "q18",
    "transition_5",
    "spiritual_person",
    "familiar_psychic_artistry",
    "warning_response",
    "email",
    "subscribe",
    "result",
]

# Set of all valid step codes for fast validation
ALL_FLOW_STEPS_SET: Set[str] = set(CANONICAL_FLOW_STEPS)

# All 17 sequential question codes in canonical order
ALL_QUESTION_CODES: List[str] = [
    f"q{i:02d}" for i in range(2, 19)
]

# Transition prerequisite question mappings
TRANSITION_PREREQUISITES_MAP: Dict[str, List[str]] = {
    "transition_0": [],
    "transition_1": ["q02", "q03", "q04", "q05", "q06"],
    "transition_2": ["q02", "q03", "q04", "q05", "q06", "q07"],
    "transition_3": ["q02", "q03", "q04", "q05", "q06", "q07", "q08", "q09", "q10"],
    "transition_4": ["q02", "q03", "q04", "q05", "q06", "q07", "q08", "q09", "q10", "q11"],
    "transition_5": ALL_QUESTION_CODES,
    "spiritual_person": ALL_QUESTION_CODES,
    "familiar_psychic_artistry": ALL_QUESTION_CODES,
    "warning_response": ALL_QUESTION_CODES,
    "email": ALL_QUESTION_CODES,
    "subscribe": ALL_QUESTION_CODES,
    "result": ALL_QUESTION_CODES,
}

# Canonical post-quiz interstitial flow codes (DEV-SPEC §5.7, §15.4, SP-206)
INTERSTITIAL_CODES: List[str] = [
    "spiritual_person",
    "familiar_psychic_artistry",
    "warning_response",
]

INTERSTITIAL_CODES_SET: Set[str] = set(INTERSTITIAL_CODES)

# Interstitial progression prerequisites (DEV-SPEC §5.7, SP-206)
INTERSTITIAL_PREREQUISITES_MAP: Dict[str, List[str]] = {
    "spiritual_person": ALL_QUESTION_CODES,
    "familiar_psychic_artistry": ALL_QUESTION_CODES + ["spiritual_person"],
    "warning_response": ALL_QUESTION_CODES + ["spiritual_person", "familiar_psychic_artistry"],
}

# Transition-2 dynamic copy map per COPY-02 & Figma 102:320
TRANSITION_2_COPY_BY_OPTION: Dict[str, Dict[str, str]] = {
    "intelligence": {
        "title": "Awesome!",
        "body": "Those who seek Intelligence in their soulmate value deep conversations, curiosity, and a mind that challenges them.",
    },
    "kindness": {
        "title": "Awesome!",
        "body": "Those who seek Kindness in their soulmate value empathy, genuine care, and a warm heart that nurtures them.",
    },
    "loyalty": {
        "title": "Awesome!",
        "body": "Those who seek Loyalty in their soulmate value unwavering trust, devotion, and a bond that stands the test of time.",
    },
    "creativity": {
        "title": "Awesome!",
        "body": "Those who seek Creativity in their soulmate value imagination, spontaneity, and a unique perspective on life.",
    },
    "passion": {
        "title": "Awesome!",
        "body": "Those who seek Passion in their soulmate value intensity, excitement, and a deep emotional spark.",
    },
    "empathy": {
        "title": "Awesome!",
        "body": "Those who seek Empathy in their soulmate value compassion, active listening, and feeling truly seen.",
    },
}

TRANSITION_2_DEFAULT_COPY: Dict[str, str] = {
    "title": "Awesome!",
    "body": "Those who seek this quality in their soulmate value deep connection, authentic understanding, and mutual respect.",
}

# Transition-3 decision copy map per DEV-SPEC §5.5
TRANSITION_3_DECISION_COPY_MAP: Dict[str, str] = {
    "heart": "people make decisions using their heart.",
    "head": "people make decisions using their head.",
    "both": "people make decisions using their heart and head.",
}



def get_next_step(current_step: str) -> Optional[str]:
    """
    Returns the deterministic next step in the canonical sequence.
    Returns None if current_step is the final step ('result').
    Raises ValueError if current_step is not in the canonical sequence.
    """
    try:
        idx = CANONICAL_FLOW_STEPS.index(current_step)
    except ValueError:
        raise ValueError(f"Unknown step code: '{current_step}'")

    if idx < len(CANONICAL_FLOW_STEPS) - 1:
        return CANONICAL_FLOW_STEPS[idx + 1]
    return None


def get_previous_step(current_step: str) -> Optional[str]:
    """
    Returns the deterministic previous step in the canonical sequence.
    Returns None if current_step is the starting step ('transition_0').
    Raises ValueError if current_step is not in the canonical sequence.
    """
    try:
        idx = CANONICAL_FLOW_STEPS.index(current_step)
    except ValueError:
        raise ValueError(f"Unknown step code: '{current_step}'")

    if idx > 0:
        return CANONICAL_FLOW_STEPS[idx - 1]
    return None


def get_step_type(step_code: str) -> StepType:
    """Categorizes step code into its canonical interaction type."""
    if step_code.startswith("q") and step_code[1:].isdigit():
        return StepType.QUESTION
    elif step_code.startswith("transition_"):
        return StepType.TRANSITION
    elif step_code in ("spiritual_person", "familiar_psychic_artistry", "warning_response"):
        return StepType.INTERSTITIAL
    elif step_code == "email":
        return StepType.EMAIL
    elif step_code == "subscribe":
        return StepType.CHECKOUT
    elif step_code == "result":
        return StepType.RESULT
    else:
        raise ValueError(f"Cannot determine step type for unknown code: '{step_code}'")


def calculate_progress_percent(current_step: str) -> int:
    """Calculates standardized completion percentage (0 - 100)."""
    try:
        idx = CANONICAL_FLOW_STEPS.index(current_step)
    except ValueError:
        return 0
    return int((idx / (len(CANONICAL_FLOW_STEPS) - 1)) * 100)


def get_prerequisite_questions_for_question(question_code: str) -> List[str]:
    """Returns the list of question codes that must be answered before question_code."""
    if question_code not in ALL_QUESTION_CODES:
        raise ValueError(f"Invalid question code: '{question_code}'")

    idx = ALL_QUESTION_CODES.index(question_code)
    return ALL_QUESTION_CODES[:idx]


def validate_can_answer_question(
    question_code: str,
    answered_codes: Set[str],
) -> None:
    """
    Skip Prevention Guard (DEV-SPEC §15.3, SP-203):
    Verifies that all prerequisite questions preceding question_code have been answered.
    Allows legitimate Back/re-answer edits.
    Raises InvalidFlowStateError (409) on illegal forward skips.
    """
    prereqs = get_prerequisite_questions_for_question(question_code)
    missing = [q for q in prereqs if q not in answered_codes]
    if missing:
        raise InvalidFlowStateError(
            f"Cannot answer '{question_code}': intermediate required questions not answered: {missing}",
            details={"missing_prerequisites": missing, "attempted_question": question_code},
        )


def validate_can_advance_transition(
    transition_code: str,
    answered_codes: Set[str],
) -> None:
    """
    Transition Progression Guard:
    Verifies that all prerequisite questions required before this transition have been answered.
    Raises InvalidFlowStateError (409) if prerequisites are not fulfilled.
    """
    if transition_code not in TRANSITION_PREREQUISITES_MAP:
        raise ValueError(f"Unknown transition code: '{transition_code}'")

    prereqs = TRANSITION_PREREQUISITES_MAP[transition_code]
    missing = [q for q in prereqs if q not in answered_codes]
    if missing:
        raise InvalidFlowStateError(
            f"Cannot advance '{transition_code}': required questions incomplete: {missing}",
            details={"missing_prerequisites": missing, "transition_code": transition_code},
        )


def validate_can_answer_interstitial(
    interstitial_code: str,
    answered_codes: Set[str],
) -> None:
    """
    Skip Prevention Guard for Interstitials (DEV-SPEC §5.7, §15.4, SP-206):
    Verifies that all prerequisite questions and prior interstitials have been answered.
    Allows legitimate Back/re-answer edits.
    Raises InvalidFlowStateError (409) on illegal forward skips.
    """
    if interstitial_code not in INTERSTITIAL_PREREQUISITES_MAP:
        raise ValueError(f"Unknown interstitial code: '{interstitial_code}'")

    prereqs = INTERSTITIAL_PREREQUISITES_MAP[interstitial_code]
    missing = [q for q in prereqs if q not in answered_codes]
    if missing:
        raise InvalidFlowStateError(
            f"Cannot answer interstitial '{interstitial_code}': prerequisites not answered: {missing}",
            details={"missing_prerequisites": missing, "attempted_interstitial": interstitial_code},
        )


def validate_can_submit_question(
    question_code: str,
    current_step: str,
    answered_codes: Set[str],
) -> None:
    """
    Comprehensive Step & Skip Prevention Guard (DEV-SPEC §15.3, SP-203):
    1. Prerequisite questions must be answered (cannot skip ahead).
    2. Rejects if current_step is currently parked at an uncompleted transition screen.
    3. Allows re-answering already answered questions (Back/re-answer path).
    4. For first-time answers, verifies that current_step matches the attempted question.
    """
    # 1. Prerequisite questions check
    validate_can_answer_question(question_code, answered_codes)

    # 2. Cannot bypass transition screens
    if current_step.startswith("transition_"):
        raise InvalidFlowStateError(
            f"Cannot answer '{question_code}': current active step is transition '{current_step}'. Transition must be continued first.",
            details={"current_step": current_step, "attempted_question": question_code},
        )

    # 3. Allow legitimate Back/re-answer edits
    if question_code in answered_codes:
        return

    # 4. First-time answer requires current_step == question_code
    if current_step != question_code:
        raise InvalidFlowStateError(
            f"Cannot answer '{question_code}': current active step is '{current_step}'.",
            details={"current_step": current_step, "attempted_question": question_code},
        )


def validate_can_submit_interstitial(
    interstitial_code: str,
    current_step: str,
    answered_codes: Set[str],
) -> None:
    """
    Comprehensive Step & Skip Prevention Guard for Interstitials (DEV-SPEC §5.7, §15.4, SP-206):
    1. All prerequisite questions and prior interstitials must be answered.
    2. Rejects if current_step is currently parked on a transition step (e.g. transition_5).
    3. Allows re-answering already answered interstitials.
    4. For first-time answers, verifies current_step matches the interstitial.
    """
    # 1. Prerequisite interstitials check
    validate_can_answer_interstitial(interstitial_code, answered_codes)

    # 2. Cannot bypass transition screens (e.g. transition_5)
    if current_step.startswith("transition_"):
        raise InvalidFlowStateError(
            f"Cannot answer interstitial '{interstitial_code}': current active step is transition '{current_step}'. Transition must be continued first.",
            details={"current_step": current_step, "attempted_interstitial": interstitial_code},
        )

    # 3. Allow re-answering
    if interstitial_code in answered_codes:
        return

    # 4. First-time answer requires current_step == interstitial_code
    if current_step != interstitial_code:
        raise InvalidFlowStateError(
            f"Cannot answer interstitial '{interstitial_code}': current active step is '{current_step}'.",
            details={"current_step": current_step, "attempted_interstitial": interstitial_code},
        )


def resolve_transition_metadata(
    transition_code: str,
    answers_map: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Resolves dynamic copy and presentation metadata for transitions
    (satisfying COPY-02 for Transition-2 and COPY-03 for Transition-4).
    """
    metadata: Dict[str, Any] = {"transition_code": transition_code}

    if transition_code == "transition_0":
        metadata.update({
            "title": "Find Your Soulmate",
            "subtitle": "Take our quick questionnaire to begin",
        })
    elif transition_code == "transition_1":
        metadata.update({
            "title": "Your artist has started",
            "subtitle": "Sketching now",
        })
    elif transition_code == "transition_2":
        # Resolve based on Q07 key_soulmate_quality (COPY-02)
        q07_answer = answers_map.get("q07")
        q07_value = None
        if isinstance(q07_answer, dict):
            q07_value = q07_answer.get("value") or (q07_answer.get("answer", {}).get("value"))

        copy_entry = TRANSITION_2_COPY_BY_OPTION.get(str(q07_value).lower(), TRANSITION_2_DEFAULT_COPY)
        metadata.update({
            "source_question": "q07",
            "selected_option": q07_value,
            "title": copy_entry["title"],
            "body": copy_entry["body"],
        })
    elif transition_code == "transition_3":
        # Resolve dynamic Zodiac (Q08) and Decision Style (Q10) per DEV-SPEC §5.5
        q08_answer = answers_map.get("q08")
        q08_value = None
        if isinstance(q08_answer, dict):
            q08_value = q08_answer.get("value") or (q08_answer.get("answer", {}).get("value"))

        zodiac_sign = None
        zodiac_label = "Your Zodiac"
        if q08_value:
            try:
                zodiac_detail = get_zodiac_for_date(str(q08_value))
                zodiac_sign = zodiac_detail.name
                zodiac_label = zodiac_detail.sun_label
            except Exception:
                pass

        q10_answer = answers_map.get("q10")
        q10_value = None
        if isinstance(q10_answer, dict):
            q10_value = q10_answer.get("value") or (q10_answer.get("answer", {}).get("value"))

        q10_norm = str(q10_value).lower().strip() if q10_value else "both"
        decision_copy = TRANSITION_3_DECISION_COPY_MAP.get(
            q10_norm, "people make decisions using their heart and head."
        )
        decision_phrase = (
            "heart" if q10_norm == "heart" else ("head" if q10_norm == "head" else "heart and head")
        )
        subtitle = f"Many {zodiac_label} individuals make decisions using their {decision_phrase}."

        metadata.update({
            "zodiac_sign": zodiac_sign,
            "zodiac_label": zodiac_label,
            "decision_style": q10_value,
            "decision_copy": decision_copy,
            "title": "Good to know!",
            "subtitle": subtitle,
        })
    elif transition_code == "transition_4":

        # Static Figma 102:372 behavior (COPY-03)
        metadata.update({
            "title": "So many share this challenge",
            "subtitle": "Moving on from the past is hard, but so many share this journey. We’ll help you find peace and clarity.",
            "body": "Moving on from the past is hard, but so many share this journey. We’ll help you find peace and clarity.",
            "cta": "Continue",
        })

    elif transition_code == "transition_5":
        metadata.update({
            "title": "Calculating your soulmate match...",
            "progress_items": [
                {"label": "Heart’s Intentions", "percent": 100},
                {"label": "Portrait of the Soulmate", "percent": 85},
                {"label": "Connection Insights", "percent": 0},
            ],
        })

    return metadata


# Backwards compatibility helpers
def resolve_next_step_for_question(question_code: str) -> str:
    nxt = get_next_step(question_code)
    if not nxt:
        raise ValueError(f"No next step for question: '{question_code}'")
    return nxt


def resolve_next_step_for_interstitial(interstitial_code: str) -> str:
    nxt = get_next_step(interstitial_code)
    if not nxt:
        raise ValueError(f"No next step for interstitial: '{interstitial_code}'")
    return nxt
