"""
PayPal Webhook Domain Models & Transmission Data Structures (DEV-SPEC §9.5–9.6, SP-404).

Defines canonical webhook event types, header extraction structures, and raw body container
ensuring raw bytes and cryptographic metadata are preserved without framework mutation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional
from pydantic import BaseModel, ConfigDict, Field


class PayPalWebhookEventType(str, Enum):
    """Canonical PayPal webhook event types required by DEV-SPEC §9.5."""

    # Subscription lifecycle events
    BILLING_SUBSCRIPTION_CREATED = "BILLING.SUBSCRIPTION.CREATED"
    BILLING_SUBSCRIPTION_ACTIVATED = "BILLING.SUBSCRIPTION.ACTIVATED"
    BILLING_SUBSCRIPTION_UPDATED = "BILLING.SUBSCRIPTION.UPDATED"
    BILLING_SUBSCRIPTION_PAYMENT_FAILED = "BILLING.SUBSCRIPTION.PAYMENT.FAILED"
    BILLING_SUBSCRIPTION_SUSPENDED = "BILLING.SUBSCRIPTION.SUSPENDED"
    BILLING_SUBSCRIPTION_CANCELLED = "BILLING.SUBSCRIPTION.CANCELLED"
    BILLING_SUBSCRIPTION_EXPIRED = "BILLING.SUBSCRIPTION.EXPIRED"

    # Payment settlement & refund events
    PAYMENT_SALE_COMPLETED = "PAYMENT.SALE.COMPLETED"
    PAYMENT_SALE_REFUNDED = "PAYMENT.SALE.REFUNDED"
    PAYMENT_SALE_REVERSED = "PAYMENT.SALE.REVERSED"


# Set of all recognized webhook event types for validation
RECOGNIZED_WEBHOOK_EVENTS = {e.value for e in PayPalWebhookEventType}


@dataclass(frozen=True)
class PayPalWebhookHeaders:
    """
    Extracted PayPal webhook transmission headers required for cryptographic signature verification.
    Preserves case-insensitive lookup and completeness checks.
    """

    auth_algo: Optional[str] = None
    cert_url: Optional[str] = None
    transmission_id: Optional[str] = None
    transmission_sig: Optional[str] = None
    transmission_time: Optional[str] = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "PayPalWebhookHeaders":
        """
        Extract PayPal transmission headers case-insensitively from Starlette / FastAPI request headers.
        """
        # Case-insensitive extraction with common variations
        def get_header(key: str) -> Optional[str]:
            return (
                headers.get(key)
                or headers.get(key.lower())
                or headers.get(key.upper())
                or headers.get(key.replace("-", "_"))
                or headers.get(key.lower().replace("-", "_"))
            )

        return cls(
            auth_algo=get_header("PAYPAL-AUTH-ALGO"),
            cert_url=get_header("PAYPAL-CERT-URL"),
            transmission_id=get_header("PAYPAL-TRANSMISSION-ID"),
            transmission_sig=get_header("PAYPAL-TRANSMISSION-SIG"),
            transmission_time=get_header("PAYPAL-TRANSMISSION-TIME"),
        )

    def is_complete(self) -> bool:
        """Returns True if all 5 PayPal transmission headers required for signature verification are present."""
        return bool(
            self.auth_algo
            and self.cert_url
            and self.transmission_id
            and self.transmission_sig
            and self.transmission_time
        )

    def missing_headers(self) -> List[str]:
        """List any missing required PayPal transmission header names."""
        missing = []
        if not self.auth_algo:
            missing.append("PAYPAL-AUTH-ALGO")
        if not self.cert_url:
            missing.append("PAYPAL-CERT-URL")
        if not self.transmission_id:
            missing.append("PAYPAL-TRANSMISSION-ID")
        if not self.transmission_sig:
            missing.append("PAYPAL-TRANSMISSION-SIG")
        if not self.transmission_time:
            missing.append("PAYPAL-TRANSMISSION-TIME")
        return missing

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Non-sensitive representation of extracted transmission headers for logging and verification."""
        return {
            "auth_algo": self.auth_algo,
            "cert_url": self.cert_url,
            "transmission_id": self.transmission_id,
            "transmission_sig_present": bool(self.transmission_sig),
            "transmission_time": self.transmission_time,
        }


@dataclass
class PayPalWebhookRawRequest:
    """
    Container capturing immutable raw request data before parsing or business processing.
    Preserves exact byte-level representation for signature verification (Acceptance #1).
    """

    raw_body: bytes
    headers: PayPalWebhookHeaders
    parsed_json: Dict[str, Any]
    event_id: str
    event_type: str
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    summary: Optional[str] = None
    create_time: Optional[str] = None


class PayPalWebhookResponse(BaseModel):
    """Safe standard HTTP response payload for webhook receiver."""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(description="'received' | 'duplicate' | 'rejected'")
    event_id: str = Field(description="PayPal event ID (WH-...)")
    event_type: str = Field(description="Webhook event type string")
    duplicate: bool = Field(default=False, description="True if event was already recorded (idempotent 200)")
