"""Pydantic schemas for Soulmate Session API (DEV-SPEC §6, §15.1)."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class SessionCreateRequest(BaseModel):
    """Optional request payload for session initialization."""
    utm_json: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional tracking and campaign metadata",
    )


class SessionCreateResponse(BaseModel):
    """Session creation response payload matching DEV-SPEC §15.1."""
    session_id: str = Field(..., description="Public session identifier (IDOR-safe public_id)")
    quiz_version: str = Field(..., description="Irrevocably pinned quiz version code")
    current_step: str = Field(..., description="Starting step code, e.g. transition_0")
    status: str = Field(..., description="Initial session lifecycle status")

    model_config = ConfigDict(from_attributes=True)


class SavedAnswerDetail(BaseModel):
    """Saved answer payload for restoring UI state."""
    question_code: str
    answer: Dict[str, Any]
    duration_ms: Optional[int] = None
    answered_at: datetime


class SessionCurrentResponse(BaseModel):
    """Full session recovery response payload for resuming quiz flow."""
    session_id: str = Field(..., description="Public session identifier")
    quiz_version: str = Field(..., description="Pinned quiz version")
    status: str = Field(..., description="Current session lifecycle status")
    current_step: str = Field(..., description="Current active step code")
    email: Optional[str] = Field(default=None, description="Captured user email if available")
    quiz_completed_at: Optional[datetime] = Field(default=None, description="Quiz completion timestamp")
    answers: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Saved answers indexed by question_code for UI restoration",
    )
    saved_answers_count: int = Field(default=0, description="Total count of answered questions")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnswerSubmitRequest(BaseModel):
    """Payload for submitting or editing an answer to a question (DEV-SPEC §15.3)."""
    value: Optional[str] = Field(
        default=None,
        description="Option code for single choice question, or YYYY-MM-DD for date question",
    )
    values: Optional[List[str]] = Field(
        default=None,
        description="Array of option codes for multi choice question",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Time spent on the question in milliseconds",
    )

    model_config = ConfigDict(extra="forbid")


class AnswerSubmitResponse(BaseModel):
    """Response returned upon successfully saving/upserting an answer."""
    saved: bool = Field(default=True, description="Indicates whether the answer was saved")
    question_code: str = Field(..., description="The code of the answered question")
    next_step: str = Field(..., description="Server-resolved next step code")
    zodiac: Optional[Dict[str, str]] = Field(
        default=None,
        description="Server-computed zodiac metadata for Q08 birth_date (DEV-SPEC §4.4, SP-204)",
    )

    model_config = ConfigDict(from_attributes=True)



class FlowStateResponse(BaseModel):
    """Authoritative flow state representation (DEV-SPEC §1.1, §4, §15.3, SP-203)."""
    session_id: str = Field(..., description="Public session identifier")
    current_step: str = Field(..., description="Current active step code")
    step_type: str = Field(..., description="Interaction category (question, transition, interstitial, email, checkout, result)")
    next_step: Optional[str] = Field(None, description="Deterministic next step code or None if at end")
    previous_step: Optional[str] = Field(None, description="Deterministic previous step code or None if at start")
    progress_percent: int = Field(..., ge=0, le=100, description="Standardized completion percentage (0-100)")
    is_quiz_completed: bool = Field(default=False, description="Whether all 17 quiz questions (q02-q18) are completed")
    step_metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata such as dynamic copy or subtitles")

    model_config = ConfigDict(from_attributes=True)


class TransitionContinueResponse(BaseModel):
    """Response returned upon successfully continuing through a transition screen."""
    transition_code: str = Field(..., description="Transition step code that was continued")
    next_step: str = Field(..., description="New active step after transition")
    flow_state: FlowStateResponse = Field(..., description="Authoritative flow state after advancement")

    model_config = ConfigDict(from_attributes=True)


class InterstitialSubmitRequest(BaseModel):
    """Payload for submitting or editing an interstitial answer (DEV-SPEC §5.7, §15.4, SP-206)."""
    value: Union[bool, str] = Field(
        ...,
        description="Answer value: boolean (True/False) or string ('yes'/'no')",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Time spent on the interstitial screen in milliseconds",
    )

    model_config = ConfigDict(extra="forbid")


class InterstitialSubmitResponse(BaseModel):
    """Response returned upon successfully saving/upserting an interstitial answer."""
    saved: bool = Field(default=True, description="Indicates whether the answer was saved")
    interstitial_code: str = Field(..., description="The code of the answered interstitial")
    value: Union[bool, str] = Field(..., description="The normalized persisted answer value")
    next_step: str = Field(..., description="Server-resolved next step code")
    flow_state: Optional[FlowStateResponse] = Field(
        default=None,
        description="Authoritative flow state after advancement",
    )

    model_config = ConfigDict(from_attributes=True)


class EmailCaptureRequest(BaseModel):
    """Payload for submitting user email at Email Capture step (DEV-SPEC §8.2, §15.5, SP-301)."""
    email: str = Field(
        ...,
        min_length=3,
        max_length=320,
        description="User email address to validate, normalize, and bind to session",
    )

    model_config = ConfigDict(extra="forbid")


class EmailCaptureResponse(BaseModel):
    """Response returned upon successfully saving/updating session email (DEV-SPEC §8.2)."""
    ok: bool = Field(default=True, description="Indicates whether email was successfully saved and bound")
    next: str = Field(default="/soulmate/subscribe", description="Next canonical client route")

    model_config = ConfigDict(from_attributes=True)


class SummaryBadgeItem(BaseModel):
    """Display-ready summary badge item with raw code and formatted human label."""
    code: str = Field(..., description="Raw option code, e.g. age_30_40")
    label: str = Field(..., description="Display-ready formatted label, e.g. 30-40")
    is_sample: bool = Field(default=False, description="True if value is a fallback default rather than user answer")

    model_config = ConfigDict(from_attributes=True)


class EmailSummaryResponse(BaseModel):
    """Display-ready Email capture summary view model (DEV-SPEC §8.1, SP-302, Decisions: QUIZ-01)."""
    visual_variant: Literal["male", "female"] = Field(
        ...,
        description="Visual variant determined strictly by Q03 preferred_partner_gender (QUIZ-01)",
    )
    gender_display: str = Field(..., description="Display-ready partner gender label, e.g. 'Male' or 'Female'")
    age_range_display: str = Field(..., description="Display-ready partner age range label, e.g. '30-40'")
    ethnicity_display: str = Field(..., description="Display-ready partner ethnicity label, e.g. 'Latino'")

    partner_gender: SummaryBadgeItem = Field(..., description="Q03 partner gender details")
    partner_age_range: SummaryBadgeItem = Field(..., description="Q05 partner age range details")
    partner_ethnicity: SummaryBadgeItem = Field(..., description="Q06 partner ethnicity details")

    user_gender: Optional[str] = Field(
        default=None,
        description="User's own gender from Q02 (for tracking only, never used for visual variant)",
    )
    is_sample_data: bool = Field(
        default=False,
        description="True if values are demo fallbacks because quiz answers were not yet completed",
    )

    model_config = ConfigDict(from_attributes=True)


class RenewalDisclosure(BaseModel):
    """Structured renewal disclosures for subscription checkout (DEV-SPEC §9.1, §21)."""
    today_text: str = Field(..., description="First month payment disclosure text, e.g. 'Today: $19.00'")
    renewal_text: str = Field(..., description="Renewal price disclosure text, e.g. 'Then $29.00 / month'")
    terms_text: str = Field(
        default="Automatically renews monthly until canceled. Cancel anytime.",
        description="Statutory auto-renewal and cancellation terms",
    )
    interval: str = Field(default="MONTH", description="Billing frequency interval")
    interval_count: int = Field(default=1, description="Interval recurrence count")
    auto_renew: bool = Field(default=True, description="Indicates auto-renewal billing")

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class OfferEligibility(BaseModel):
    """Eligibility status and plan class evaluation under Decision PAY-02."""
    eligible_for_intro: bool = Field(
        default=True,
        description="Whether user/session is eligible for the promotional intro price",
    )
    plan_class: str = Field(
        default="intro",
        description="Assigned plan classification: 'intro' | 'standard' | 'blocked'",
    )
    policy: str = Field(
        default="blocked",
        description="Active re-subscription policy ('blocked' | 'single_intro' | 'allow_intro')",
    )
    is_blocked: bool = Field(
        default=False,
        description="True if returning subscriber is blocked pending policy resolution (PAY-02)",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Explanation or guidance regarding eligibility and plan selection",
    )

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class PayPalClientConfig(BaseModel):
    """Browser-safe PayPal integration configuration (never leaks secrets or webhooks)."""
    client_id: Optional[str] = Field(
        default=None,
        description="Public PayPal Client ID for browser JS SDK",
    )
    env: str = Field(
        default="sandbox",
        description="PayPal environment ('sandbox' | 'production')",
    )
    plan_id: Optional[str] = Field(
        default=None,
        description="PayPal Subscription Plan ID to initiate",
    )

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class SubscriptionOfferResponse(BaseModel):
    """Current subscription offer and checkout configuration (DEV-SPEC §9.1–9.2, §15.6, §21–22)."""
    currency: str = Field(default="USD", description="Billing currency code")
    intro_price: Optional[str] = Field(
        default=None,
        description="Formatted first month intro price, or '{INTRO_PRICE}' if unconfigured (PAY-01)",
    )
    regular_price: Optional[str] = Field(
        default=None,
        description="Formatted regular monthly price, or '{REGULAR_PRICE}' if unconfigured (PAY-01)",
    )
    interval: str = Field(default="MONTH", description="Billing cycle interval")
    paypal_plan_id: Optional[str] = Field(default=None, description="Active PayPal plan ID")
    disclosure: RenewalDisclosure = Field(..., description="Renewal disclosures")
    eligibility: OfferEligibility = Field(..., description="Eligibility evaluation (PAY-02)")
    paypal: PayPalClientConfig = Field(..., description="Safe PayPal client configuration")

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class RouteGuardResponse(BaseModel):
    """Server-authoritative route access verdict and redirection guidance (DEV-SPEC §3, §10, §20)."""
    allowed: bool = Field(..., description="Whether access to target route is granted")
    target_route: str = Field(..., description="Canonical requested route path")
    redirect_to: Optional[str] = Field(default=None, description="Authoritative redirection target if not allowed")
    reason: Optional[str] = Field(default=None, description="Human-readable rationale for verdict")
    server_time: datetime = Field(..., description="Server authoritative UTC timestamp (TIME-01)")
    session_id: Optional[str] = Field(default=None, description="Public session ID evaluated")
    quiz_completed: bool = Field(default=False, description="Whether quiz is completed")
    email_captured: bool = Field(default=False, description="Whether email has been captured")
    is_paid: bool = Field(default=False, description="Whether first payment is confirmed (PAY-AUTH-01)")
    sketch_unlocked: bool = Field(default=False, description="Whether sketch 12h cooldown elapsed (TIME-01)")
    report_unlocked: bool = Field(default=False, description="Whether report 24h cooldown elapsed (TIME-01)")
    sketch_unlock_at: Optional[datetime] = Field(default=None, description="Sketch unlock timestamp")
    report_unlock_at: Optional[datetime] = Field(default=None, description="Report unlock timestamp")

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class PayPalConfirmRequest(BaseModel):
    """Payload for confirming an approved PayPal subscription (DEV-SPEC §15.7, SP-403)."""
    session_id: Optional[str] = Field(
        default=None,
        description="Public session ID (optional if session cookie soulmate_sid is provided)",
    )
    paypal_subscription_id: str = Field(
        ...,
        description="PayPal subscription ID returned by PayPal JS SDK (e.g. 'I-...')",
    )


class PayPalConfirmResponse(BaseModel):
    """Response returned upon associating PayPal subscription with session (DEV-SPEC §15.7, SP-403)."""
    status: str = Field(
        ...,
        description="Subscription state: 'PROCESSING' | 'ACTIVE' | 'INACTIVE'",
    )
    is_paid: bool = Field(
        default=False,
        description="Whether entitlement is unlocked (PAY-AUTH-01: False until webhook confirmed)",
    )
    provider_subscription_id: str = Field(..., description="PayPal subscription ID")
    provider_plan_id: str = Field(..., description="PayPal plan ID")
    provider_status: str = Field(..., description="Provider status, e.g. 'APPROVAL_PENDING', 'APPROVED', 'ACTIVE'")
    session_id: str = Field(..., description="Public session ID")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    message: str = Field(..., description="Operational status message")

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class SubscriptionStatusResponse(BaseModel):
    """Current subscription and entitlement status for the active session (DEV-SPEC §15.8, SP-403)."""
    status: str = Field(
        ...,
        description="'NONE' | 'PROCESSING' | 'ACTIVE' | 'CANCELLED' | 'EXPIRED'",
    )
    is_paid: bool = Field(
        default=False,
        description="Entitlement status (PAY-AUTH-01)",
    )
    subscription_id: Optional[str] = Field(default=None, description="PayPal subscription ID")
    plan_id: Optional[str] = Field(default=None, description="PayPal plan ID")
    provider_status: Optional[str] = Field(default=None, description="Provider status string")
    first_payment_at: Optional[datetime] = Field(default=None, description="Confirmed payment UTC timestamp")
    next_billing_at: Optional[datetime] = Field(default=None, description="Next billing UTC timestamp")
    paid_through_at: Optional[datetime] = Field(default=None, description="Paid-through expiration UTC timestamp")
    cancelled_at: Optional[datetime] = Field(default=None, description="Cancellation UTC timestamp")

    model_config = ConfigDict(from_attributes=True, extra="ignore")
