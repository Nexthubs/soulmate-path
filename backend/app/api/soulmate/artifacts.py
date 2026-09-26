"""
Sketch artifact endpoints (DEV-SPEC §15.10; Decisions: ASSET-01, TIME-01, PAY-AUTH-01; SP-603).

POST /artifacts/sketch/generate — on_demand trigger (§11.4): enqueues one logical,
idempotent generation job that the worker processes independently of the request
lifecycle. Auth and ownership follow the Result aggregate pattern (SP-503).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenOwnershipError, NotFoundError
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import SketchGenerationResponse
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.services.session_service import SessionService
from app.soulmate.services.sketch_generation_service import SketchGenerationService
from app.soulmate.services.status_service import ArtifactStatusService

router = APIRouter()


async def _resolve_authorized_session(
    request: Request,
    session_id: Optional[str],
    db: AsyncSession,
) -> SoulmateSession:
    """Same authorization pattern as the Result aggregate endpoint (SP-503, §20)."""
    if session_id:
        authenticated_id = get_authenticated_session_public_id(request)
        verify_session_ownership(requested_public_id=session_id, authenticated_public_id=authenticated_id)
        session = await SessionService.get_session_by_public_id(db, session_id)
        if not session:
            raise NotFoundError(f"Session with ID '{session_id}' not found.")
        return session

    token = extract_session_token(request)
    if not token:
        raise ForbiddenOwnershipError("Active session required to trigger sketch generation.")
    try:
        authenticated_id = verify_session_token(token)
        session = await SessionService.get_session_by_public_id(db, authenticated_id)
        if not session:
            raise NotFoundError("Authenticated session not found.")
        return session
    except ForbiddenOwnershipError:
        raise
    except Exception:
        raise ForbiddenOwnershipError("Invalid or expired session credentials.")


@router.post(
    "/sketch/generate",
    response_model=SketchGenerationResponse,
    summary="Trigger sketch generation (on_demand, DEV-SPEC §11.4, §15.10, SP-603)",
)
async def generate_sketch_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> SketchGenerationResponse:
    """
    Enqueue one logical sketch generation for the authenticated entitled session.
    Idempotent: a completed artifact is returned as-is; concurrent triggers converge
    on one durable job (§11.6). The worker processes the job after this request ends.
    """
    session = await _resolve_authorized_session(request, session_id, db)
    outcome = await SketchGenerationService.enqueue_sketch_generation(db, session)

    statuses = await ArtifactStatusService.get_artifact_statuses(db, session.id)

    return SketchGenerationResponse(
        server_time=statuses.server_time,
        sketch=statuses.sketch,
        job_status=outcome.job.status if outcome.job is not None else None,
    )
