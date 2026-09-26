"""
Result aggregate endpoint (DEV-SPEC §10.4, §15.8, Decisions: TIME-01, PAY-AUTH-01, SP-503).
Single API supplying the Result page with subscription + sketch + report status and server time.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenOwnershipError, NotFoundError
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import ResultAggregateResponse
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.services.result_service import ResultService
from app.soulmate.services.session_service import SessionService

router = APIRouter()


@router.get(
    "",
    response_model=ResultAggregateResponse,
    summary="Result page aggregate: subscription + sketch + report status + server time (DEV-SPEC §10.4, SP-503)",
)
async def get_result_aggregate_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> ResultAggregateResponse:
    """
    Single authoritative aggregate for the Result page (SP-106, SP-504 countdown, SP-505 polling).
    Requires an authenticated session with a confirmed first payment (PAY-AUTH-01);
    all statuses derive from persisted timestamps and the server clock (TIME-01).
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
            raise ForbiddenOwnershipError("Active session required to access the Result page.")
        try:
            authenticated_id = verify_session_token(token)
            session = await SessionService.get_session_by_public_id(db, authenticated_id)
            if not session:
                raise NotFoundError("Authenticated session not found.")
        except ForbiddenOwnershipError:
            raise
        except Exception:
            raise ForbiddenOwnershipError("Invalid or expired session credentials.")

    return await ResultService.get_result_aggregate(db=db, session=session)
