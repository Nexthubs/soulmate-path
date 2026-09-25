"""
Payment Ledger Endpoints for Customer Support & Reconciliation (DEV-SPEC §9.4–9.7, §14, SP-407).
Provides secure lookup capabilities by provider payment ID, subscription ID, email, or date range.
"""

from datetime import datetime
import logging
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.soulmate.domain.ledger_models import (
    LedgerSearchQuery,
    LedgerSearchResult,
    PaymentLedgerRecord,
    PaymentLedgerSummary,
)
from app.soulmate.services.ledger_service import PaymentLedgerService

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_support_access(
    x_support_key: Optional[str] = Header(default=None, alias="X-Support-Key"),
) -> None:
    """
    Validate support/internal API access.
    In development and test environments, allows requests if no secret key is explicitly required.
    In staging/production, requires X-Support-Key to match configured secret.
    """
    if settings.environment in ("development", "test"):
        return

    # In production/staging, verify secret
    expected_key = getattr(settings, "support_api_key", None) or settings.session_secret_key
    if not x_support_key or x_support_key != expected_key:
        logger.warning("Unauthorized access attempt to customer support ledger endpoints")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing support authorization key",
        )


@router.get(
    "/payments/{provider_payment_id}",
    response_model=PaymentLedgerRecord,
    summary="Lookup payment by provider payment ID (DEV-SPEC §9.4, SP-407)",
)
async def get_payment_by_provider_id(
    provider_payment_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> PaymentLedgerRecord:
    """
    Lookup a specific payment in the ledger by provider payment ID (PayPal Capture / Sale ID).
    Used by customer support and automated reconciliation.
    """
    payment = await PaymentLedgerService.get_payment_by_provider_payment_id(
        db=db,
        provider_payment_id=provider_payment_id,
    )
    if not payment:
        raise NotFoundError(f"Payment with provider ID '{provider_payment_id}' was not found in the ledger.")
    return payment


@router.get(
    "/subscriptions/{provider_subscription_id}",
    response_model=list[PaymentLedgerRecord],
    summary="Lookup payments by provider subscription ID (DEV-SPEC §9.4, SP-407)",
)
async def get_payments_by_provider_sub(
    provider_subscription_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> list[PaymentLedgerRecord]:
    """
    Lookup all payments associated with a PayPal subscription ID (e.g. I-...).
    """
    return await PaymentLedgerService.get_payments_by_provider_subscription_id(
        db=db,
        provider_sub_id=provider_subscription_id,
    )


@router.get(
    "/summary/{subscription_id}",
    response_model=PaymentLedgerSummary,
    summary="Get billing and cycle summary for subscription (SP-407)",
)
async def get_subscription_summary(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> PaymentLedgerSummary:
    """
    Compute aggregate billing summary for a subscription (total paid, cycles, latest status).
    """
    summary = await PaymentLedgerService.get_subscription_ledger_summary(
        db=db,
        subscription_id=subscription_id,
    )
    if not summary:
        raise NotFoundError(f"Subscription with ID '{subscription_id}' was not found.")
    return summary


@router.get(
    "/search",
    response_model=LedgerSearchResult,
    summary="Search payment ledger with filters (DEV-SPEC §9.4, SP-407)",
)
async def search_ledger(
    provider_payment_id: Optional[str] = Query(default=None, description="PayPal sale/capture ID"),
    provider_subscription_id: Optional[str] = Query(default=None, description="PayPal subscription ID (I-...)"),
    subscription_id: Optional[uuid.UUID] = Query(default=None, description="Internal subscription UUID"),
    session_public_id: Optional[str] = Query(default=None, description="Public session ID"),
    email: Optional[str] = Query(default=None, description="Customer email address"),
    status: Optional[str] = Query(default=None, description="Payment status (COMPLETED, FAILED, REFUNDED, REVERSED)"),
    start_date: Optional[datetime] = Query(default=None, description="Filter payments after start_date"),
    end_date: Optional[datetime] = Query(default=None, description="Filter payments before end_date"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> LedgerSearchResult:
    """
    Search payments ledger by any combination of customer email, PayPal ID, session ID, status, or date range.
    """
    query = LedgerSearchQuery(
        provider_payment_id=provider_payment_id,
        provider_subscription_id=provider_subscription_id,
        subscription_id=subscription_id,
        session_public_id=session_public_id,
        email=email,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return await PaymentLedgerService.search_payments(db=db, query=query)
