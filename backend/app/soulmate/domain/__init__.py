"""Soulmate domain boundary and core contracts (Spec §0, §3, §14)."""

# Canonical immutable quiz version
CANONICAL_QUIZ_VERSION = "soulmate-quiz-v1"

# Unlock durations from first payment completion (Spec §14)
SKETCH_UNLOCK_HOURS = 12
REPORT_UNLOCK_HOURS = 24

# Non-negotiable result mapping keys (Spec §0.1, AGENTS.md §3)
RESULT_KEY_USER_GENDER = "user_gender"
RESULT_KEY_PREFERRED_PARTNER_GENDER = "preferred_partner_gender"
RESULT_KEY_PREFERRED_PARTNER_AGE_RANGE = "preferred_partner_age_range"
RESULT_KEY_PREFERRED_PARTNER_ETHNICITY = "preferred_partner_ethnicity"
RESULT_KEY_KEY_SOULMATE_QUALITY = "key_soulmate_quality"
RESULT_KEY_BIRTH_DATE = "birth_date"
RESULT_KEY_DECISION_STYLE = "decision_style"
