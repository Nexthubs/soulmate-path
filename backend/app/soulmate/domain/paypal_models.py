"""
PayPal Domain Models and Payloads (DEV-SPEC §9.1–9.2, §22, §25, Decisions: PAY-01, PAY-02).
Defines schemas for catalog products, billing cycles, pricing schemes, and verification contracts.
"""

from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class PayPalFrequency(BaseModel):
    """Cadence configuration for billing cycle (DEV-SPEC §9.1: MONTH x 1)."""
    model_config = ConfigDict(extra="ignore")

    interval_unit: Literal["DAY", "WEEK", "MONTH", "YEAR"] = "MONTH"
    interval_count: int = 1


class PayPalFixedPrice(BaseModel):
    """Fixed price amount and currency."""
    model_config = ConfigDict(extra="ignore")

    value: str
    currency_code: str = "USD"


class PayPalPricingScheme(BaseModel):
    """Pricing scheme for PayPal billing cycles."""
    model_config = ConfigDict(extra="ignore")

    fixed_price: PayPalFixedPrice


class PayPalBillingCycle(BaseModel):
    """
    Billing cycle representation per DEV-SPEC §9.1.1:
    - Cycle 1 (Intro): tenure_type=TRIAL, sequence=1, total_cycles=1, discounted price.
    - Cycle 2 (Regular): tenure_type=REGULAR, sequence=2, total_cycles=0 (infinite), regular price.
    """
    model_config = ConfigDict(extra="ignore")

    frequency: PayPalFrequency = Field(default_factory=PayPalFrequency)
    tenure_type: Literal["REGULAR", "TRIAL"]
    sequence: int
    total_cycles: int
    pricing_scheme: PayPalPricingScheme


class PayPalPaymentPreferences(BaseModel):
    """Payment preferences for automated billing."""
    model_config = ConfigDict(extra="ignore")

    auto_bill_outstanding: bool = True
    setup_fee_failure_action: Literal["CONTINUE", "CANCEL"] = "CONTINUE"
    payment_failure_threshold: int = 1


class PayPalPlanPayload(BaseModel):
    """Payload for creating a reusable PayPal billing plan."""
    model_config = ConfigDict(extra="ignore")

    product_id: str
    name: str
    description: Optional[str] = None
    status: Literal["ACTIVE", "CREATED", "INACTIVE"] = "ACTIVE"
    billing_cycles: List[PayPalBillingCycle]
    payment_preferences: PayPalPaymentPreferences = Field(default_factory=PayPalPaymentPreferences)


class PayPalProductPayload(BaseModel):
    """Payload for creating a reusable PayPal catalog product."""
    model_config = ConfigDict(extra="ignore")

    name: str
    description: Optional[str] = None
    type: Literal["PHYSICAL", "DIGITAL", "SERVICE"] = "SERVICE"
    category: str = "ONLINE_SERVICES"
    image_url: Optional[str] = None
    home_url: Optional[str] = None


class PayPalPlanVerificationResult(BaseModel):
    """Verification diagnosis for a provisioned PayPal billing plan."""
    model_config = ConfigDict(extra="ignore")

    plan_id: str
    plan_name: str
    status: str
    product_id: Optional[str] = None
    matches: bool
    plan_type: Literal["intro", "standard", "unknown"]
    currency: str
    intro_price: Optional[str] = None
    regular_price: Optional[str] = None
    interval: str = "MONTH"
    interval_count: int = 1
    total_billing_cycles: int = 0
    discrepancies: List[str] = Field(default_factory=list)


class ProvisioningSummary(BaseModel):
    """Summary of provisioned PayPal billing infrastructure."""
    model_config = ConfigDict(extra="ignore")

    environment: str
    product_id: str
    product_name: str
    intro_plan_id: str
    standard_plan_id: Optional[str] = None
    intro_plan_verification: PayPalPlanVerificationResult
    standard_plan_verification: Optional[PayPalPlanVerificationResult] = None
    env_output: str
    disclosures_verified: bool = True
