"""Soulmate domain boundary and core contracts (Spec §0, §3, §6, §14)."""

from app.soulmate.domain.session_state import (
    INITIAL_SESSION_STATUS,
    INITIAL_STEP_CODE,
    SessionStatus,
)
from app.soulmate.domain.step_resolver import (
    ALL_FLOW_STEPS_SET,
    ALL_QUESTION_CODES,
    CANONICAL_FLOW_STEPS,
    INTERSTITIAL_CODES,
    INTERSTITIAL_CODES_SET,
    INTERSTITIAL_PREREQUISITES_MAP,
    StepType,
    calculate_progress_percent,
    get_next_step,
    get_previous_step,
    get_step_type,
    resolve_next_step_for_interstitial,
    resolve_next_step_for_question,
    resolve_transition_metadata,
    validate_can_advance_transition,
    validate_can_answer_interstitial,
    validate_can_answer_question,
    validate_can_submit_interstitial,
    validate_can_submit_question,
)
from app.soulmate.domain.profile import (
    OPTIONAL_INTERSTITIAL_KEYS,
    REQUIRED_PROFILE_QUESTIONS,
    InvalidAnswerValueError,
    MissingRequiredAnswerError,
    ProfileValidationError,
    SoulmateProfileV1,
    build_soulmate_profile,
)
from app.soulmate.domain.zodiac import (
    ZODIAC_DEFINITIONS,
    ZodiacDetail,
    ZodiacSign,
    get_zodiac_by_name,
    get_zodiac_for_date,
)
from app.soulmate.domain.identity import (
    derive_user_id_for_email,
    validate_and_normalize_email,
)
from app.soulmate.domain.offer import (
    ResubscriptionPolicy,
    build_subscription_offer,
    evaluate_resubscription_eligibility,
    format_offer_price,
    get_currency_symbol,
)
from app.soulmate.domain.guard import (
    GuardedRoute,
    calculate_unlock_times,
    evaluate_route_guard,
    normalize_route_path,
)
from app.soulmate.domain.paypal_models import (
    PayPalBillingCycle,
    PayPalFixedPrice,
    PayPalFrequency,
    PayPalPaymentPreferences,
    PayPalPlanPayload,
    PayPalPlanVerificationResult,
    PayPalPricingScheme,
    PayPalProductPayload,
    ProvisioningSummary,
)
from app.soulmate.domain.ledger_models import (
    LedgerSearchQuery,
    LedgerSearchResult,
    PaymentLedgerRecord,
    PaymentLedgerSummary,
    PaymentRecordCreate,
)
from app.soulmate.domain.sketch_prompt import (
    ALLOWED_SKETCH_PROMPT_VARIABLES,
    PROMPT_VARIABLE_TO_QUESTION,
    SKETCH_INPUT_OPTION_LABELS,
    SKETCH_PROMPT_NAME,
    RenderedSketchPrompt,
    SketchPromptError,
    SketchPromptInputs,
    SketchPromptInputError,
    SketchPromptTemplate,
    SketchPromptTemplateError,
    build_rendered_sketch_prompt,
    build_sketch_prompt_inputs,
    load_sketch_prompt_template,
    map_sketch_option_to_readable,
    render_sketch_prompt,
    validate_sketch_input_mapping_coverage,
)
from app.soulmate.domain.sketch_models import (
    SketchGenerationResult,
    SketchImageProvider,
    SketchProviderError,
    is_retryable_provider_status,
    provider_code_for_status,
)
from app.soulmate.domain.report import (
    REPORT_SCHEMA_VERSION,
    ReportValidationError,
    SoulmateReportSection,
    SoulmateReportSectionPoint,
    SoulmateReportV1,
    parse_soulmate_report_v1,
)
from app.soulmate.domain.report_models import (
    ReportGenerationDisabledError,
    ReportGenerationInput,
    ReportGenerationResult,
    ReportProviderError,
    SoulmateReportGenerator,
)


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

__all__ = [
    "CANONICAL_QUIZ_VERSION",
    "SKETCH_UNLOCK_HOURS",
    "REPORT_UNLOCK_HOURS",
    "RESULT_KEY_USER_GENDER",
    "RESULT_KEY_PREFERRED_PARTNER_GENDER",
    "RESULT_KEY_PREFERRED_PARTNER_AGE_RANGE",
    "RESULT_KEY_PREFERRED_PARTNER_ETHNICITY",
    "RESULT_KEY_KEY_SOULMATE_QUALITY",
    "RESULT_KEY_BIRTH_DATE",
    "RESULT_KEY_DECISION_STYLE",
    "SessionStatus",
    "INITIAL_SESSION_STATUS",
    "INITIAL_STEP_CODE",
    "ALL_FLOW_STEPS_SET",
    "ALL_QUESTION_CODES",
    "CANONICAL_FLOW_STEPS",
    "INTERSTITIAL_CODES",
    "INTERSTITIAL_CODES_SET",
    "INTERSTITIAL_PREREQUISITES_MAP",
    "StepType",
    "calculate_progress_percent",
    "get_next_step",
    "get_previous_step",
    "get_step_type",
    "resolve_next_step_for_question",
    "resolve_next_step_for_interstitial",
    "resolve_transition_metadata",
    "validate_can_advance_transition",
    "validate_can_answer_interstitial",
    "validate_can_answer_question",
    "validate_can_submit_interstitial",
    "validate_can_submit_question",
    "ZodiacSign",
    "ZodiacDetail",
    "ZODIAC_DEFINITIONS",
    "get_zodiac_for_date",
    "get_zodiac_by_name",
    "SoulmateProfileV1",
    "build_soulmate_profile",
    "ProfileValidationError",
    "MissingRequiredAnswerError",
    "InvalidAnswerValueError",
    "REQUIRED_PROFILE_QUESTIONS",
    "OPTIONAL_INTERSTITIAL_KEYS",
    "validate_and_normalize_email",
    "derive_user_id_for_email",
    "ResubscriptionPolicy",
    "get_currency_symbol",
    "format_offer_price",
    "evaluate_resubscription_eligibility",
    "build_subscription_offer",
    "GuardedRoute",
    "normalize_route_path",
    "calculate_unlock_times",
    "evaluate_route_guard",
    "PayPalFrequency",
    "PayPalFixedPrice",
    "PayPalPricingScheme",
    "PayPalBillingCycle",
    "PayPalPaymentPreferences",
    "PayPalPlanPayload",
    "PayPalProductPayload",
    "PayPalPlanVerificationResult",
    "ProvisioningSummary",
    "PaymentRecordCreate",
    "PaymentLedgerRecord",
    "PaymentLedgerSummary",
    "LedgerSearchQuery",
    "LedgerSearchResult",
    "SKETCH_PROMPT_NAME",
    "ALLOWED_SKETCH_PROMPT_VARIABLES",
    "PROMPT_VARIABLE_TO_QUESTION",
    "SKETCH_INPUT_OPTION_LABELS",
    "SketchPromptError",
    "SketchPromptTemplateError",
    "SketchPromptInputError",
    "SketchPromptTemplate",
    "SketchPromptInputs",
    "RenderedSketchPrompt",
    "build_sketch_prompt_inputs",
    "build_rendered_sketch_prompt",
    "load_sketch_prompt_template",
    "render_sketch_prompt",
    "map_sketch_option_to_readable",
    "validate_sketch_input_mapping_coverage",
    "SketchImageProvider",
    "SketchGenerationResult",
    "SketchProviderError",
    "is_retryable_provider_status",
    "provider_code_for_status",
    "REPORT_SCHEMA_VERSION",
    "ReportValidationError",
    "SoulmateReportSection",
    "SoulmateReportSectionPoint",
    "SoulmateReportV1",
    "parse_soulmate_report_v1",
    "ReportGenerationDisabledError",
    "ReportGenerationInput",
    "ReportGenerationResult",
    "ReportProviderError",
    "SoulmateReportGenerator",
]

