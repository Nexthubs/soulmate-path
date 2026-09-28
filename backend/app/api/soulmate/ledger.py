"""
Payment ledger point lookups for authorized support and reconciliation (SP-407/SP-905).
"""

from datetime import datetime
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.session import get_db
from app.soulmate.domain.ledger_models import (
    LedgerSearchQuery,
    SupportLedgerSearchResult,
    SupportPaymentLedgerRecord,
    SupportPaymentLedgerSummary,
)
from app.soulmate.services.ledger_service import PaymentLedgerService
from app.api.soulmate.support_auth import verify_support_access

router = APIRouter()


@router.get(
    "/payments/{provider_payment_id}",
    response_model=SupportPaymentLedgerRecord,
    summary="Lookup payment by provider payment ID (DEV-SPEC §9.4, SP-407)",
)
async def get_payment_by_provider_id(
    provider_payment_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> SupportPaymentLedgerRecord:
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
    response_model=list[SupportPaymentLedgerRecord],
    summary="Lookup payments by provider subscription ID (DEV-SPEC §9.4, SP-407)",
)
async def get_payments_by_provider_sub(
    provider_subscription_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> list[SupportPaymentLedgerRecord]:
    """
    Lookup all payments associated with a PayPal subscription ID (e.g. I-...).
    """
    return await PaymentLedgerService.get_payments_by_provider_subscription_id(
        db=db,
        provider_sub_id=provider_subscription_id,
    )


@router.get(
    "/summary/{subscription_id}",
    response_model=SupportPaymentLedgerSummary,
    summary="Get billing and cycle summary for subscription (SP-407)",
)
async def get_subscription_summary(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> SupportPaymentLedgerSummary:
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
    response_model=SupportLedgerSearchResult,
    summary="Search payment ledger with filters (DEV-SPEC §9.4, SP-407)",
)
async def search_ledger(
    request: Request,
    provider_payment_id: Optional[str] = Query(default=None, description="PayPal sale/capture ID"),
    provider_subscription_id: Optional[str] = Query(default=None, description="PayPal subscription ID (I-...)"),
    subscription_id: Optional[uuid.UUID] = Query(default=None, description="Internal subscription UUID"),
    session_public_id: Optional[str] = Query(default=None, description="Public session ID"),
    status: Optional[str] = Query(default=None, description="Payment status (COMPLETED, FAILED, REFUNDED, REVERSED)"),
    start_date: Optional[datetime] = Query(default=None, description="Filter payments after start_date"),
    end_date: Optional[datetime] = Query(default=None, description="Filter payments before end_date"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_support_access),
) -> SupportLedgerSearchResult:
    """
    Search payments for an exact session, subscription, or payment identifier.
    Email lookup is available through POST /support/lookup so it is not put in a URL.
    """
    if "email" in request.query_params:
        raise HTTPException(
            status_code=422,
            detail="Email lookup requires POST /support/lookup with a JSON body.",
        )
    if not any((provider_payment_id, provider_subscription_id, subscription_id, session_public_id)):
        raise HTTPException(
            status_code=422,
            detail="Specify an exact session, subscription, or payment identifier; use POST /support/lookup for email.",
        )

    query = LedgerSearchQuery(
        provider_payment_id=provider_payment_id,
        provider_subscription_id=provider_subscription_id,
        subscription_id=subscription_id,
        session_public_id=session_public_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return await PaymentLedgerService.search_payments(db=db, query=query)
