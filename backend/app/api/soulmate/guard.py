"""
Route Guard API Endpoints (DEV-SPEC §3, §10, §20, Decisions: PAY-AUTH-01, TIME-01).
Authoritative server endpoint for evaluating route access and redirection guidance.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import RouteGuardResponse
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.services.guard_service import GuardService
from app.soulmate.services.session_service import SessionService

router = APIRouter()


@router.get(
    "/check",
    response_model=RouteGuardResponse,
    summary="Evaluate server route guard access",
    description="Returns server-authoritative verdict and redirect target for a given route per DEV-SPEC §3.",
)
async def check_route_guard_endpoint(
    request: Request,
    target_route: str = Query(..., description="Target route path to check, e.g. /soulmate/email"),
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> RouteGuardResponse:
    session: Optional[SoulmateSession] = None

    if session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, session_id)
        if not session:
            raise NotFoundError(f"Session with ID '{session_id}' not found.")
    else:
        token = extract_session_token(request)
        if token:
            try:
                authenticated_id = verify_session_token(token)
                session = await SessionService.get_session_by_public_id(db, authenticated_id)
            except Exception:
                session = None

    return await GuardService.evaluate_guard(
        db=db,
        target_route=target_route,
        session=session,
    )
