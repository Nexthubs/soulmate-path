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
