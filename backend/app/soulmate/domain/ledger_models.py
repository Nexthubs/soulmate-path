"""
Domain models and DTOs for the Payment Ledger (DEV-SPEC §9.4–9.7, §14, Decision: PAY-AUTH-01, SP-407).
Provides structured, typed representations for recording, verifying, and looking up subscription payments.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class PaymentRecordCreate(BaseModel):
    """Input payload to record a provider payment in the durable ledger."""

    subscription_id: uuid.UUID = Field(..., description="Internal Subscription UUID")
    provider_payment_id: str = Field(..., min_length=1, max_length=128, description="Durable provider payment/sale/capture ID")
    amount: Decimal = Field(..., ge=0, description="Payment monetary amount")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO 4217 3-letter currency code")
    status: str = Field(default="COMPLETED", max_length=32, description="Payment status: COMPLETED, FAILED, REFUNDED, REVERSED")
    paid_at: Optional[datetime] = Field(default=None, description="Authoritative payment timestamp from provider")
    provider_event_id: Optional[str] = Field(default=None, max_length=128, description="PayPal webhook event ID")
    cycle_no: Optional[int] = Field(default=None, ge=1, description="Explicit billing cycle number if known; auto-derived if omitted")
    raw_json: Optional[Dict[str, Any]] = Field(default=None, description="Full raw provider payment resource payload")


class PaymentLedgerRecord(BaseModel):
    """Detailed view model for a durable payment ledger record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subscription_id: uuid.UUID
    provider_payment_id: str
    provider_event_id: Optional[str] = None
    cycle_no: Optional[int] = None
    amount: Decimal
    currency: str
    status: str
    paid_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    created_at: datetime
    raw_json: Optional[Dict[str, Any]] = None

    # Contextual links for customer support and reconciliation
    provider_subscription_id: Optional[str] = None
    session_id: Optional[uuid.UUID] = None
    session_public_id: Optional[str] = None
    customer_email: Optional[str] = None


class PaymentLedgerSummary(BaseModel):
    """Aggregate billing summary for a subscription."""

    subscription_id: uuid.UUID
    provider_subscription_id: Optional[str] = None
    session_public_id: Optional[str] = None
    customer_email: Optional[str] = None
    currency: str = "USD"
    total_payments_count: int = 0
    completed_payments_count: int = 0
    failed_payments_count: int = 0
    refunded_payments_count: int = 0
    total_amount_paid: Decimal = Decimal("0.00")
    first_payment_at: Optional[datetime] = None
    latest_payment_at: Optional[datetime] = None
    latest_status: str = "NONE"


class LedgerSearchQuery(BaseModel):
    """Filter criteria for customer support and reconciliation lookups."""

    provider_payment_id: Optional[str] = Field(default=None, description="PayPal sale/capture ID")
    provider_subscription_id: Optional[str] = Field(default=None, description="PayPal subscription ID (I-...)")
    subscription_id: Optional[uuid.UUID] = Field(default=None, description="Internal subscription UUID")
    session_public_id: Optional[str] = Field(default=None, description="Public session ID")
    email: Optional[str] = Field(default=None, description="Customer email address (case-insensitive normalized)")
    status: Optional[str] = Field(default=None, description="Payment status filter: COMPLETED, FAILED, REFUNDED, REVERSED")
    start_date: Optional[datetime] = Field(default=None, description="Earliest paid_at filter")
    end_date: Optional[datetime] = Field(default=None, description="Latest paid_at filter")
    limit: int = Field(default=50, ge=1, le=200, description="Max results per page")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class LedgerSearchResult(BaseModel):
    """Paginated list of payment ledger records."""

    items: List[PaymentLedgerRecord]
    total: int
    limit: int
    offset: int
