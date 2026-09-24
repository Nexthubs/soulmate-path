"""
Normalized Soulmate Profile domain model, builder, and validation (DEV-SPEC §7, Decisions: QUIZ-01).

Maps raw versioned answers into a canonical normalized profile consumed by:
- Email summary (DEV-SPEC §8)
- Subscribe variant (DEV-SPEC §9)
- Transition copy (DEV-SPEC §5)
- Sketch Prompt (DEV-SPEC §11)
- Report Generator (DEV-SPEC §13.3)
"""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.core.errors import ValidationError
from app.quiz.loader import get_cached_quiz_config
from app.quiz.schema import QuizConfig
from app.soulmate.domain.zodiac import get_zodiac_for_date


# Canonical mapping of Quiz questions to profile attributes (DEV-SPEC §4.6, §7)
REQUIRED_PROFILE_QUESTIONS: Dict[str, str] = {
    "q02": "user_gender",
    "q03": "preferred_partner_gender",
    "q04": "love_life_status",
    "q05": "preferred_partner_age_range",
    "q06": "preferred_partner_ethnicity",
    "q07": "key_soulmate_quality",
    "q08": "birth_date",
    "q09": "element",
    "q10": "decision_style",
    "q11": "personal_challenge",
    "q12": "red_flag",
    "q13": "similarity_preference",
    "q14": "relationship_dynamic",
    "q15": "love_language",
    "q16": "connection_style",
    "q17": "relationship_fear",
    "q18": "life_goals",
}

# Optional post-quiz interstitial questions (DEV-SPEC §5.7, §7)
OPTIONAL_INTERSTITIAL_KEYS: Set[str] = {
    "spiritual_person",
    "familiar_psychic_artistry",
    "warning_response",
}


class ProfileValidationError(ValidationError):
    """Raised when building or validating a normalized profile fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details or {})


class MissingRequiredAnswerError(ProfileValidationError):
    """Raised when one or more required questions (q02-q18) are missing."""

    def __init__(self, missing_questions: List[str], message: Optional[str] = None):
        msg = (
            message
            or f"Cannot build soulmate profile: missing required questions: {', '.join(sorted(missing_questions))}."
        )
        super().__init__(
            message=msg,
            details={"missing_questions": sorted(missing_questions)},
        )
        self.missing_questions = sorted(missing_questions)


class InvalidAnswerValueError(ProfileValidationError):
    """Raised when an answer value is unknown, invalid, or violates question options."""

    def __init__(
        self,
        question_code: str,
        value: Any,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        msg = (
            message
            or f"Invalid answer value '{value}' for question '{question_code}'."
        )
        d = details or {}
        d.update({"question_code": question_code, "invalid_value": value})
        super().__init__(message=msg, details=d)
        self.question_code = question_code
        self.value = value


class SoulmateProfileV1(BaseModel):
    """
    Canonical Normalized Soulmate Profile matching DEV-SPEC §7.

    Supports both snake_case attribute access (Pythonic / DB) and
    camelCase serialization (matching TypeScript interface SoulmateProfileV1).
    """

    profile_version: str = Field(default="v1", description="Profile schema version")

    # Core demographics & partner preferences (DEV-SPEC §7, Decisions: QUIZ-01)
    user_gender: Literal["male", "female"] = Field(
        ...,
        description="User's own gender (strictly mapped from Q02, per QUIZ-01)",
    )
    preferred_partner_gender: Literal["male", "female"] = Field(
        ...,
        description="Target partner gender (strictly mapped from Q03, per QUIZ-01)",
    )
    love_life_status: str = Field(..., description="Current love life status from Q04")
    preferred_partner_age_range: str = Field(
        ..., description="Desired partner age range from Q05"
    )
    preferred_partner_ethnicity: str = Field(
        ..., description="Desired partner ethnicity from Q06"
    )
    key_soulmate_quality: str = Field(
        ..., description="Most valued soulmate quality from Q07"
    )

    # Astrological and decision profile (DEV-SPEC §4.4, §5.5, §7)
    birth_date: str = Field(
        ...,
        description="User birth date in YYYY-MM-DD format from Q08",
    )
    zodiac_sign: str = Field(
        ...,
        description="Server-authoritative zodiac sign calculated from birth_date (DEV-SPEC §5.5)",
    )
    element: Literal["fire", "water", "earth", "wind"] = Field(
        ..., description="Personality elemental alignment from Q09"
    )
    decision_style: Literal["heart", "head", "both"] = Field(
        ..., description="Decision style from Q10"
    )

    # Relational & emotional dynamics (DEV-SPEC §7)
    personal_challenge: str = Field(..., description="Primary personal challenge from Q11")
    red_flag: str = Field(..., description="Primary relationship red flag from Q12")
    similarity_preference: str = Field(
        ..., description="Preference for similarity vs contrast from Q13"
    )
    relationship_dynamic: str = Field(
        ..., description="Ideal dynamic with partner from Q14"
    )
    love_language: str = Field(..., description="Primary love language from Q15")
    connection_style: str = Field(..., description="Ideal connection style from Q16")
    relationship_fear: str = Field(..., description="Primary relationship fear from Q17")
    life_goals: List[str] = Field(
        ...,
        min_length=1,
        description="List of selected life goals from Q18 (min 1)",
    )

    # Post-quiz interstitials (DEV-SPEC §5.7, §7)
    spiritual_person: Optional[bool] = Field(
        default=None,
        description="Whether user identifies as spiritual (interstitial popup 1)",
    )
    familiar_psychic_artistry: Optional[bool] = Field(
        default=None,
        description="Familiarity with psychic artistry (interstitial popup 2)",
    )
    warning_response: Optional[Literal["yes", "no"]] = Field(
        default=None,
        description="Response to shocking compatibility warning (interstitial popup 3)",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        from_attributes=True,
    )

    @field_validator("birth_date", mode="before")
    @classmethod
    def _coerce_birth_date(cls, v: Any) -> str:
        if isinstance(v, datetime):
            v = v.date()
        if isinstance(v, date):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, str):
            val_clean = v.strip()
            try:
                parsed = date.fromisoformat(val_clean)
            except ValueError:
                raise ProfileValidationError(
                    f"Invalid birth_date format '{v}', expected 'YYYY-MM-DD'.",
                    details={"field": "birth_date", "value": v},
                )
            if parsed.year < 1900:
                raise ProfileValidationError(
                    f"Birth date year cannot be earlier than 1900 (got {parsed.year}).",
                    details={"field": "birth_date", "value": val_clean},
                )
            if parsed > date.today():
                raise ProfileValidationError(
                    f"Birth date cannot be in the future (got {parsed}).",
                    details={"field": "birth_date", "value": val_clean},
                )
            return parsed.strftime("%Y-%m-%d")
        raise ProfileValidationError(
            f"Birth date must be a valid date or 'YYYY-MM-DD' string, got {type(v).__name__}.",
            details={"field": "birth_date", "value": str(v)},
        )

    def to_db_dict(self) -> Dict[str, Any]:
        """Converts profile to column-compatible dictionary for SQLAlchemy SoulmateProfile."""
        try:
            parsed_date = date.fromisoformat(self.birth_date)
        except (ValueError, TypeError) as exc:
            raise ProfileValidationError(
                f"Invalid birth_date format '{self.birth_date}', expected 'YYYY-MM-DD'.",
                details={"field": "birth_date", "value": self.birth_date},
            ) from exc

        return {
            "profile_version": self.profile_version,
            "user_gender": self.user_gender,
            "preferred_partner_gender": self.preferred_partner_gender,
            "love_life_status": self.love_life_status,
            "preferred_partner_age_range": self.preferred_partner_age_range,
            "preferred_partner_ethnicity": self.preferred_partner_ethnicity,
            "key_soulmate_quality": self.key_soulmate_quality,
            "birth_date": parsed_date,
            "zodiac_sign": self.zodiac_sign,
            "element": self.element,
            "decision_style": self.decision_style,
            "personal_challenge": self.personal_challenge,
            "red_flag": self.red_flag,
            "similarity_preference": self.similarity_preference,
            "relationship_dynamic": self.relationship_dynamic,
            "love_language": self.love_language,
            "connection_style": self.connection_style,
            "relationship_fear": self.relationship_fear,
            "life_goals": self.life_goals,
            "spiritual_person": self.spiritual_person,
            "familiar_psychic_artistry": self.familiar_psychic_artistry,
            "warning_response": self.warning_response,
        }

    def to_sketch_input(self) -> Dict[str, Any]:
        """
        Extracts normalized inputs for Sketch generation (DEV-SPEC §11.2, Decisions: QUIZ-01).
        Crucial: gender is preferred_partner_gender (Q03), NOT user_gender (Q02).
        """
        return {
            "gender": self.preferred_partner_gender,
            "age_range": self.preferred_partner_age_range,
            "ethnicity": self.preferred_partner_ethnicity,
            "features": self.key_soulmate_quality,
        }

    def to_email_input(self) -> Dict[str, Any]:
        """Extracts normalized fields for Email capture page (DEV-SPEC §8.1)."""
        return {
            "preferred_partner_gender": self.preferred_partner_gender,
            "preferred_partner_age_range": self.preferred_partner_age_range,
            "preferred_partner_ethnicity": self.preferred_partner_ethnicity,
        }

    def to_report_input(self) -> Dict[str, Any]:
        """Extracts normalized profile for Report generator (DEV-SPEC §13.3)."""
        return self.model_dump(by_alias=True)


def _extract_answer_value(raw: Any) -> Any:
    """Extracts raw value or values array from various answer representations."""
    if hasattr(raw, "answer_json"):
        raw = raw.answer_json
    if isinstance(raw, dict):
        if "values" in raw:
            return raw["values"]
        if "value" in raw:
            return raw["value"]
    return raw


def build_soulmate_profile(
    answers: Union[Dict[str, Any], Sequence[Any]],
    quiz_config: Optional[QuizConfig] = None,
    strict: bool = True,
) -> SoulmateProfileV1:
    """
    Pure, testable builder mapping raw versioned quiz answers to SoulmateProfileV1 (DEV-SPEC §7).

    Validates:
    1. Presence of all required questions (q02-q18) when strict=True.
    2. Valid option codes against QuizConfig.
    3. Birth date calendar boundaries (1900 to today, AGE-01).
    4. Server-authoritative Zodiac calculation.
    5. Disambiguation between Q02 (user_gender) and Q03 (preferred_partner_gender) (QUIZ-01).

    Raises:
    - MissingRequiredAnswerError if required questions are missing.
    - InvalidAnswerValueError if an option code is unrecognized.
    - ProfileValidationError if payload is malformed or invalid.
    """
    config = quiz_config or get_cached_quiz_config()

    # Map question configs by code
    questions_by_code = {q.code: q for q in config.questions}

    # Normalize input answers into a lookup by question code / key
    answer_map: Dict[str, Any] = {}
    if isinstance(answers, dict):
        for k, v in answers.items():
            answer_map[k] = _extract_answer_value(v)
    elif isinstance(answers, (list, tuple, set)):
        for item in answers:
            if hasattr(item, "question_code"):
                answer_map[item.question_code] = _extract_answer_value(item)
            elif isinstance(item, dict) and "question_code" in item:
                answer_map[item["question_code"]] = _extract_answer_value(item)

    # 1. Check for missing required questions
    missing: List[str] = []
    for q_code in REQUIRED_PROFILE_QUESTIONS:
        if q_code not in answer_map or answer_map[q_code] is None:
            missing.append(q_code)

    if missing and strict:
        raise MissingRequiredAnswerError(missing_questions=missing)

    # 2. Extract and validate each required field
    # Q02: user_gender (QUIZ-01)
    q02_val = answer_map.get("q02")
    if q02_val not in ("male", "female"):
        raise InvalidAnswerValueError(
            question_code="q02",
            value=q02_val,
            message=f"Invalid user_gender '{q02_val}' for Q02; expected 'male' or 'female'.",
        )

    # Q03: preferred_partner_gender (QUIZ-01)
    q03_val = answer_map.get("q03")
    if q03_val not in ("male", "female"):
        raise InvalidAnswerValueError(
            question_code="q03",
            value=q03_val,
            message=f"Invalid preferred_partner_gender '{q03_val}' for Q03; expected 'male' or 'female'.",
        )

    # Q04: love_life_status
    q04_val = _validate_single_option(
        question_code="q04",
        val=answer_map.get("q04"),
        question_config=questions_by_code.get("q04"),
    )

    # Q05: preferred_partner_age_range
    q05_val = _validate_single_option(
        question_code="q05",
        val=answer_map.get("q05"),
        question_config=questions_by_code.get("q05"),
    )

    # Q06: preferred_partner_ethnicity
    q06_val = _validate_single_option(
        question_code="q06",
        val=answer_map.get("q06"),
        question_config=questions_by_code.get("q06"),
    )

    # Q07: key_soulmate_quality
    q07_val = _validate_single_option(
        question_code="q07",
        val=answer_map.get("q07"),
        question_config=questions_by_code.get("q07"),
    )

    # Q08: birth_date & zodiac_sign
    raw_date = answer_map.get("q08")
    parsed_date, date_str = _validate_and_parse_birth_date(raw_date)
    zodiac_detail = get_zodiac_for_date(parsed_date)
    zodiac_sign = zodiac_detail.name

    # Q09: element
    q09_val = _validate_single_option(
        question_code="q09",
        val=answer_map.get("q09"),
        question_config=questions_by_code.get("q09"),
    )
    if q09_val not in ("fire", "water", "earth", "wind"):
        raise InvalidAnswerValueError(
            question_code="q09",
            value=q09_val,
            message=f"Invalid element '{q09_val}' for Q09; expected fire, water, earth, or wind.",
        )

    # Q10: decision_style
    q10_val = _validate_single_option(
        question_code="q10",
        val=answer_map.get("q10"),
        question_config=questions_by_code.get("q10"),
    )
    if q10_val not in ("heart", "head", "both"):
        raise InvalidAnswerValueError(
            question_code="q10",
            value=q10_val,
            message=f"Invalid decision_style '{q10_val}' for Q10; expected heart, head, or both.",
        )

    # Q11: personal_challenge
    q11_val = _validate_single_option(
        question_code="q11",
        val=answer_map.get("q11"),
        question_config=questions_by_code.get("q11"),
    )

    # Q12: red_flag
    q12_val = _validate_single_option(
        question_code="q12",
        val=answer_map.get("q12"),
        question_config=questions_by_code.get("q12"),
    )

    # Q13: similarity_preference
    q13_val = _validate_single_option(
        question_code="q13",
        val=answer_map.get("q13"),
        question_config=questions_by_code.get("q13"),
    )

    # Q14: relationship_dynamic
    q14_val = _validate_single_option(
        question_code="q14",
        val=answer_map.get("q14"),
        question_config=questions_by_code.get("q14"),
    )

    # Q15: love_language
    q15_val = _validate_single_option(
        question_code="q15",
        val=answer_map.get("q15"),
        question_config=questions_by_code.get("q15"),
    )

    # Q16: connection_style
    q16_val = _validate_single_option(
        question_code="q16",
        val=answer_map.get("q16"),
        question_config=questions_by_code.get("q16"),
    )

    # Q17: relationship_fear
    q17_val = _validate_single_option(
        question_code="q17",
        val=answer_map.get("q17"),
        question_config=questions_by_code.get("q17"),
    )

    # Q18: life_goals (multi-select)
    q18_val = _validate_multi_options(
        question_code="q18",
        val=answer_map.get("q18"),
        question_config=questions_by_code.get("q18"),
    )

    # 3. Optional interstitial answers (DEV-SPEC §5.7)
    spiritual_person = _parse_optional_bool(
        answer_map.get("spiritual_person")
    )
    familiar_psychic_artistry = _parse_optional_bool(
        answer_map.get("familiar_psychic_artistry")
    )
    warning_response = _parse_optional_warning(
        answer_map.get("warning_response")
    )

    return SoulmateProfileV1(
        profile_version="v1",
        user_gender=q02_val,
        preferred_partner_gender=q03_val,
        love_life_status=q04_val,
        preferred_partner_age_range=q05_val,
        preferred_partner_ethnicity=q06_val,
        key_soulmate_quality=q07_val,
        birth_date=date_str,
        zodiac_sign=zodiac_sign,
        element=q09_val,
        decision_style=q10_val,
        personal_challenge=q11_val,
        red_flag=q12_val,
        similarity_preference=q13_val,
        relationship_dynamic=q14_val,
        love_language=q15_val,
        connection_style=q16_val,
        relationship_fear=q17_val,
        life_goals=q18_val,
        spiritual_person=spiritual_person,
        familiar_psychic_artistry=familiar_psychic_artistry,
        warning_response=warning_response,
    )


def _validate_single_option(
    question_code: str,
    val: Any,
    question_config: Optional[Any],
) -> str:
    """Validates single choice answer against defined options."""
    if not isinstance(val, str) or not val.strip():
        raise InvalidAnswerValueError(
            question_code=question_code,
            value=val,
            message=f"Question '{question_code}' requires a non-empty string option code.",
        )
    val_clean = val.strip()
    if question_config and question_config.options:
        valid_codes = {opt.code for opt in question_config.options}
        if val_clean not in valid_codes:
            raise InvalidAnswerValueError(
                question_code=question_code,
                value=val_clean,
                message=f"Option '{val_clean}' is not a valid option for question '{question_code}'. Valid options: {sorted(valid_codes)}.",
                details={"allowed_options": sorted(valid_codes)},
            )
    return val_clean


def _validate_multi_options(
    question_code: str,
    val: Any,
    question_config: Optional[Any],
) -> List[str]:
    """Validates multi-choice answer list (Q18). Deduplicates while preserving order."""
    if not isinstance(val, (list, tuple, set)) or len(val) == 0:
        raise InvalidAnswerValueError(
            question_code=question_code,
            value=val,
            message=f"Question '{question_code}' requires a non-empty list of selected option codes.",
        )
    # Deduplicate preserving order
    seen: Set[str] = set()
    cleaned: List[str] = []
    for item in val:
        if not isinstance(item, str) or not item.strip():
            raise InvalidAnswerValueError(
                question_code=question_code,
                value=item,
                message=f"Invalid option code '{item}' in {question_code} list.",
            )
        code = item.strip()
        if code not in seen:
            seen.add(code)
            cleaned.append(code)

    if not cleaned:
        raise InvalidAnswerValueError(
            question_code=question_code,
            value=val,
            message=f"Question '{question_code}' requires at least one option.",
        )

    if question_config and question_config.options:
        valid_codes = {opt.code for opt in question_config.options}
        invalid = [code for code in cleaned if code not in valid_codes]
        if invalid:
            raise InvalidAnswerValueError(
                question_code=question_code,
                value=invalid,
                message=f"Invalid options {invalid} for {question_code}. Valid options: {sorted(valid_codes)}.",
                details={"invalid_codes": invalid, "allowed_options": sorted(valid_codes)},
            )

    return cleaned


def _validate_and_parse_birth_date(val: Any) -> tuple[date, str]:
    """Validates calendar date format YYYY-MM-DD, checks year >= 1900 and not in future (AGE-01)."""
    if isinstance(val, datetime):
        val = val.date()
    if isinstance(val, date):
        parsed = val
        date_str = parsed.strftime("%Y-%m-%d")
    elif isinstance(val, str):
        val_clean = val.strip()
        try:
            parsed = date.fromisoformat(val_clean)
            date_str = val_clean
        except ValueError:
            raise ProfileValidationError(
                f"Invalid date format '{val}' for Q08. Expected 'YYYY-MM-DD'.",
                details={"question_code": "q08", "value": val},
            )
    else:
        raise ProfileValidationError(
            f"Birth date for Q08 must be a valid date string or date object, got {type(val)}.",
            details={"question_code": "q08", "value": val},
        )

    # Preserve AGE-01 rules
    if parsed.year < 1900:
        raise ProfileValidationError(
            f"Birth date year cannot be earlier than 1900 (got {parsed.year}).",
            details={"question_code": "q08", "value": date_str},
        )
    today = date.today()
    if parsed > today:
        raise ProfileValidationError(
            f"Birth date cannot be in the future (got {parsed}).",
            details={"question_code": "q08", "value": date_str},
        )

    return parsed, date_str


def _parse_optional_bool(val: Any) -> Optional[bool]:
    """Parses optional boolean or string 'yes'/'no'."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        lowered = val.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    return None


def _parse_optional_warning(val: Any) -> Optional[Literal["yes", "no"]]:
    """Parses optional warning modal response ('yes' | 'no')."""
    if val is None:
        return None
    if isinstance(val, str):
        lowered = val.strip().lower()
        if lowered in ("yes", "no"):
            return lowered  # type: ignore[return-value]
    return None
