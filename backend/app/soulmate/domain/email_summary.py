"""Email Capture Summary View Model and Label Mapping Rules (DEV-SPEC §8.1, SP-302, Decisions: QUIZ-01)."""

from typing import Any, Dict, Literal, Optional, Union
from app.soulmate.schema import EmailSummaryResponse, SummaryBadgeItem

# Display-ready label mappings without emoji prefixes
GENDER_DISPLAY_MAP: Dict[str, str] = {
    "male": "Male",
    "female": "Female",
}

AGE_RANGE_DISPLAY_MAP: Dict[str, str] = {
    "age_20_30": "20-30",
    "age_30_40": "30-40",
    "age_40_50": "40-50",
    "age_50_plus": "50+",
    "20-30": "20-30",
    "30-40": "30-40",
    "40-50": "40-50",
    "50+": "50+",
}

ETHNICITY_DISPLAY_MAP: Dict[str, str] = {
    "hispanic_latino": "Latino",
    "caucasian_white": "Caucasian",
    "african_african_american": "African",
    "asian": "Asian",
    "no_preference": "Any",
    "latino": "Latino",
    "caucasian": "Caucasian",
    "african": "African",
    "any": "Any",
}

# Standard sample / demo defaults matching Figma 102:486 & 102:557
DEFAULT_VISUAL_VARIANT: Literal["male", "female"] = "female"
DEFAULT_PARTNER_GENDER = "female"
DEFAULT_AGE_RANGE = "age_30_40"
DEFAULT_ETHNICITY = "hispanic_latino"


def format_gender_label(code: Optional[str]) -> str:
    """Formats gender code into display-ready label."""
    if not code:
        return "Female"
    norm = code.strip().lower()
    return GENDER_DISPLAY_MAP.get(norm, norm.capitalize())


def format_age_range_label(code: Optional[str]) -> str:
    """Formats age range code into display-ready label."""
    if not code:
        return "30-40"
    norm = code.strip().lower()
    return AGE_RANGE_DISPLAY_MAP.get(norm, code.replace("age_", "").replace("_", "-"))


def format_ethnicity_label(code: Optional[str]) -> str:
    """Formats ethnicity code into display-ready label."""
    if not code:
        return "Latino"
    norm = code.strip().lower()
    return ETHNICITY_DISPLAY_MAP.get(norm, code.replace("_", " ").title())


def build_email_summary(
    preferred_partner_gender: Optional[str] = None,
    preferred_partner_age_range: Optional[str] = None,
    preferred_partner_ethnicity: Optional[str] = None,
    user_gender: Optional[str] = None,
    is_sample_data: bool = False,
) -> EmailSummaryResponse:
    """
    Builds a display-ready Email Capture summary view model (DEV-SPEC §8.1).

    STRICT INVARIANT (QUIZ-01):
    - The visual_variant and partner_gender are governed exclusively by Q03 (preferred_partner_gender).
    - Q02 (user_gender) is tracked for audit/logging, but NEVER governs the visual variant.
    """
    partner_gender_code = (preferred_partner_gender or DEFAULT_PARTNER_GENDER).strip().lower()
    is_male = partner_gender_code == "male"
    visual_variant: Literal["male", "female"] = "male" if is_male else "female"
    gender_label = "Male" if is_male else "Female"

    age_code = (preferred_partner_age_range or DEFAULT_AGE_RANGE).strip()
    age_label = format_age_range_label(age_code)

    ethnicity_code = (preferred_partner_ethnicity or DEFAULT_ETHNICITY).strip()
    ethnicity_label = format_ethnicity_label(ethnicity_code)

    return EmailSummaryResponse(
        visual_variant=visual_variant,
        gender_display=gender_label,
        age_range_display=age_label,
        ethnicity_display=ethnicity_label,
        partner_gender=SummaryBadgeItem(code=partner_gender_code, label=gender_label),
        partner_age_range=SummaryBadgeItem(code=age_code, label=age_label),
        partner_ethnicity=SummaryBadgeItem(code=ethnicity_code, label=ethnicity_label),
        user_gender=user_gender.strip().lower() if user_gender else None,
        is_sample_data=is_sample_data,
    )


def get_default_email_summary() -> EmailSummaryResponse:
    """Returns sample demo view model when quiz answers are not yet available."""
    return build_email_summary(
        preferred_partner_gender=DEFAULT_PARTNER_GENDER,
        preferred_partner_age_range=DEFAULT_AGE_RANGE,
        preferred_partner_ethnicity=DEFAULT_ETHNICITY,
        is_sample_data=True,
    )
