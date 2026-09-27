import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin, utc_now


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soulmate_sessions.id"),
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        default="paypal",
        nullable=False,
    )
    provider_subscription_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
    )
    provider_plan_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    provider_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    intro_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    regular_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    # SP-803/804 RV remediation: provider-verified price snapshot provenance.
    # Set when the PayPal plan's currency/regular price was fetched and stored
    # into currency/regular_price; NULL means the price is provisional config
    # data that the provider has not confirmed.
    price_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    first_payment_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_billing_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    paid_through_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    suspended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_payments_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        server_default="0",
    )
    billing_issue_detected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    provider_status_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    billing_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    payments: Mapped[List["SubscriptionPayment"]] = relationship(
        "SubscriptionPayment",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_subscriptions_session_id", "session_id"),
    )



class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id"),
        nullable=False,
    )
    provider_payment_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
    )
    provider_event_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    cycle_no: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    refunded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    raw_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    subscription: Mapped["Subscription"] = relationship(
        "Subscription",
        back_populates="payments",
    )

    __table_args__ = (
        Index("idx_subscription_payments_subscription_id", "subscription_id"),
    )



class PayPalWebhookEvent(Base):
    __tablename__ = "paypal_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    paypal_event_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    resource_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    payload_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
