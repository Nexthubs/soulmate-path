"""
Subscription endpoints (DEV-SPEC §9.1–9.2, §15.6, §21–22, Decisions: PAY-01, PAY-02).
Exposes subscription checkout offer, renewal disclosures, and safe PayPal client configuration.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import SubscriptionOfferResponse
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.services.offer_service import OfferService
from app.soulmate.services.session_service import SessionService

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
