"""
Subscription endpoints (DEV-SPEC §9.1–9.4, §15.6–15.8, §21–22, Decisions: PAY-01, PAY-02, PAY-AUTH-01).
Exposes subscription checkout offer, PayPal confirmation, and subscription status polling.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenOwnershipError, NotFoundError
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import (
    PayPalConfirmRequest,
    PayPalConfirmResponse,
    SubscriptionOfferResponse,
    SubscriptionStatusResponse,
)
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.domain.ledger_models import PaymentLedgerRecord
from app.soulmate.services.ledger_service import PaymentLedgerService
from app.soulmate.services.offer_service import OfferService
from app.soulmate.services.session_service import SessionService
from app.soulmate.services.subscription_service import SubscriptionService

router = APIRouter()


@router.get("/offer", response_model=SubscriptionOfferResponse)
async def get_subscription_offer(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID for eligibility evaluation"),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOfferResponse:
    """
    Get the active subscription checkout offer, disclosures, and PayPal client metadata.
    Evaluates re-subscription eligibility under Decision PAY-02 if session or user has prior subscriptions.
    """
    session: Optional[SoulmateSession] = None
    if session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, session_id)
    else:
        token = extract_session_token(request)
        if token:
            try:
                authenticated_id = verify_session_token(token)
                session = await SessionService.get_session_by_public_id(db, authenticated_id)
            except Exception:
                session = None

    return await OfferService.get_subscription_offer(db=db, session=session)


@router.post(
    "/paypal/confirm",
    response_model=PayPalConfirmResponse,
    summary="Confirm approved PayPal subscription (DEV-SPEC §15.7, SP-403)",
)
async def confirm_paypal_subscription_endpoint(
    request: Request,
    payload: PayPalConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> PayPalConfirmResponse:
    """
    Associate an approved PayPal subscription with the authenticated session.
    Validates subscription ID server-side, prevents IDOR cross-session hijacking,
    ensures duplicate confirmations are idempotent, and keeps entitlement pending (PAY-AUTH-01).
    """
    session: Optional[SoulmateSession] = None
    if payload.session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=payload.session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, payload.session_id)
        if not session:
            raise NotFoundError(f"Session with ID '{payload.session_id}' not found.")
    else:
        token = extract_session_token(request)
        if not token:
            raise ForbiddenOwnershipError("Active session required to confirm subscription.")
        authenticated_id = verify_session_token(token)
        session = await SessionService.get_session_by_public_id(db, authenticated_id)
        if not session:
            raise NotFoundError("Authenticated session not found.")

    return await SubscriptionService.confirm_paypal_subscription(
        db=db,
        session=session,
        paypal_subscription_id=payload.paypal_subscription_id,
    )


@router.get(
    "/status",
    response_model=SubscriptionStatusResponse,
    summary="Poll subscription and entitlement status (DEV-SPEC §15.8, SP-403, SP-408)",
)
async def get_subscription_status_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    reconcile: bool = Query(default=False, description="Optionally trigger live reconciliation against PayPal API"),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """
    Get current subscription and payment confirmation status for the active session.
    Polled by /soulmate/payment-processing to detect when payment is confirmed.
    """
    session: Optional[SoulmateSession] = None
    if session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, session_id)
        if not session:
            raise NotFoundError(f"Session with ID '{session_id}' not found.")
    else:
        token = extract_session_token(request)
        if not token:
            return SubscriptionStatusResponse(status="NONE", is_paid=False)
        try:
            authenticated_id = verify_session_token(token)
            session = await SessionService.get_session_by_public_id(db, authenticated_id)
            if not session:
                return SubscriptionStatusResponse(status="NONE", is_paid=False)
        except Exception:
            return SubscriptionStatusResponse(status="NONE", is_paid=False)

    return await SubscriptionService.get_subscription_status(db=db, session=session, auto_reconcile=reconcile)


@router.post(
    "/reconcile",
    response_model=SubscriptionStatusResponse,
    summary="Explicitly reconcile subscription against PayPal REST API (DEV-SPEC §9.4, SP-408)",
)
async def reconcile_subscription_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """
    Explicitly query PayPal Subscriptions API to synchronize local billing and entitlement state.
    Used for ambiguous state, delayed/missed webhooks, or manual reconciliation.
    """
    session: Optional[SoulmateSession] = None
    if session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, session_id)
        if not session:
            raise NotFoundError(f"Session with ID '{session_id}' not found.")
    else:
        token = extract_session_token(request)
        if not token:
            return SubscriptionStatusResponse(status="NONE", is_paid=False)
        try:
            authenticated_id = verify_session_token(token)
            session = await SessionService.get_session_by_public_id(db, authenticated_id)
            if not session:
                return SubscriptionStatusResponse(status="NONE", is_paid=False)
        except Exception:
            return SubscriptionStatusResponse(status="NONE", is_paid=False)

    return await SubscriptionService.reconcile_session_subscription(db=db, session=session)


@router.get(
    "/payments",
    response_model=list[PaymentLedgerRecord],
    summary="Get payment history for authenticated session (SP-407)",
)
async def get_session_payments_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentLedgerRecord]:
    """
    Get payment history for the current authenticated session.
    Protected against IDOR: session ID must match signed session token.
    """
    session: Optional[SoulmateSession] = None
    if session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, session_id)
        if not session:
            raise NotFoundError(f"Session with ID '{session_id}' not found.")
    else:
        token = extract_session_token(request)
        if not token:
            return []
        try:
            authenticated_id = verify_session_token(token)
            session = await SessionService.get_session_by_public_id(db, authenticated_id)
            if not session:
                return []
        except Exception:
            return []

    return await PaymentLedgerService.get_payments_by_session_public_id(
        db=db,
        public_id=session.public_id,
    )
