"""Allowlisted support case lookup request and response contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SupportLookupRequest(BaseModel):
    """A lookup must use exactly one precise identifier; email travels in the body."""

    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=320)
    paypal_subscription_id: Optional[str] = Field(default=None, max_length=128)
    provider_payment_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("session_id", "email", "paypal_subscription_id", "provider_payment_id")
    @classmethod
    def trim_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def require_exactly_one_identifier(self) -> "SupportLookupRequest":
        provided = (
            self.session_id,
            self.email,
            self.paypal_subscription_id,
            self.provider_payment_id,
        )
        if sum(value is not None for value in provided) != 1:
            raise ValueError("Provide exactly one support lookup identifier.")
        return self


class SupportSessionStatus(BaseModel):
    id: uuid.UUID
    public_id: str
    status: str
    current_step: str
    created_at: datetime
    updated_at: datetime
    quiz_completed_at: Optional[datetime] = None
    email_captured_at: Optional[datetime] = None
    subscription_success_at: Optional[datetime] = None


class SupportSubscriptionStatus(BaseModel):
    id: uuid.UUID
    paypal_subscription_id: str
    provider_status: str
    currency: str
    first_payment_at: Optional[datetime] = None
    next_billing_at: Optional[datetime] = None
    paid_through_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    suspended_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    failed_payments_count: int
    billing_issue_detected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SupportPaymentStatus(BaseModel):
    id: uuid.UUID
    provider_payment_id: str
    cycle_no: Optional[int] = None
    amount: Decimal
    currency: str
    status: str
    paid_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    created_at: datetime


class SupportArtifactStatus(BaseModel):
    id: uuid.UUID
    artifact_type: str
    generation_status: str
    attempt_count: int
    created_at: datetime
    generation_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime


class SupportJobStatus(BaseModel):
    id: uuid.UUID
    job_type: str
    status: str
    attempt: int
    run_after: Optional[datetime] = None
    locked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SupportTimelineEvent(BaseModel):
    occurred_at: datetime
    event_type: str
    entity_type: Literal["session", "subscription", "payment", "artifact", "job"]
    entity_id: uuid.UUID
    status: Optional[str] = None
    status_context: Optional[Literal["at_event", "current_snapshot"]] = None


class SupportLookupResult(BaseModel):
    session: SupportSessionStatus
    subscriptions: list[SupportSubscriptionStatus] = Field(default_factory=list)
    payments: list[SupportPaymentStatus] = Field(default_factory=list)
    artifacts: list[SupportArtifactStatus] = Field(default_factory=list)
    jobs: list[SupportJobStatus] = Field(default_factory=list)
    timeline: list[SupportTimelineEvent] = Field(default_factory=list)
    timeline_history_complete: bool = Field(
        default=False,
        description=(
            "False: retained status fields do not provide a complete transition history; "
            "timeline includes only provable events and current snapshots."
        ),
    )
