"""
Sketch artifact endpoints (DEV-SPEC §15.10; Decisions: ASSET-01, TIME-01, PAY-AUTH-01; SP-603).

POST /artifacts/sketch/generate — on_demand trigger (§11.4): enqueues one logical,
idempotent generation job that the worker processes independently of the request
lifecycle. Auth and ownership follow the Result aggregate pattern (SP-503).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenOwnershipError, NotFoundError
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import SketchAssetResponse, SketchGenerationResponse
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.services.object_storage_sink import build_sketch_image_url
from app.soulmate.services.session_service import SessionService
from app.soulmate.services.sketch_generation_service import (
    JOB_FAILED_RETRYABLE,
    SketchGenerationService,
    hard_attempt_cap,
)
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


@router.get(
    "/sketch",
    response_model=SketchAssetResponse,
    summary="Sketch asset status + persisted display URL (DEV-SPEC §15.10, SP-607)",
)
async def get_sketch_asset_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> SketchAssetResponse:
    """
    Authoritative session-scoped sketch state for the Sketch page (§10.3) plus,
    when COMPLETED, the display URL of the persisted durable asset. Reads never
    cross sessions (Decision RECOVERY-01); the display URL is derived from the
    project-owned storage key (ASSET-01) and never from a provider temporary URL.
    """
    session = await _resolve_authorized_session(request, session_id, db)

    statuses = await ArtifactStatusService.get_artifact_statuses(db, session.id)

    image_url: Optional[str] = None
    storage_key: Optional[str] = None
    retry_available: Optional[bool] = None
    if statuses.sketch.status == "COMPLETED":
        stmt = select(SoulmateArtifact.storage_key, SoulmateArtifact.generation_status).where(
            SoulmateArtifact.session_id == session.id,
            SoulmateArtifact.artifact_type == "SKETCH",
        )
        row = (await db.execute(stmt)).first()
        if row is not None and row.generation_status == "COMPLETED":
            storage_key = row.storage_key
            image_url = build_sketch_image_url(storage_key)
    elif statuses.sketch.status == "FAILED":
        # §10.3 Retry/Support split: a FAILED artifact is user-retryable only while
        # its terminal job is FAILED_RETRYABLE and under the hard attempt cap.
        stmt = select(SoulmateArtifact.id).where(
            SoulmateArtifact.session_id == session.id,
            SoulmateArtifact.artifact_type == "SKETCH",
        )
        artifact_row = (await db.execute(stmt)).first()
        if artifact_row is not None:
            job_stmt = (
                select(AIGenerationJob.status, AIGenerationJob.attempt)
                .where(AIGenerationJob.artifact_id == artifact_row.id)
                .order_by(AIGenerationJob.created_at.desc())
                .limit(1)
            )
            job_row = (await db.execute(job_stmt)).first()
            if job_row is not None:
                retry_available = (
                    job_row.status == JOB_FAILED_RETRYABLE
                    and (job_row.attempt or 0) < hard_attempt_cap()
                )

    return SketchAssetResponse(
        server_time=statuses.server_time,
        sketch=statuses.sketch,
        image_url=image_url,
        storage_key=storage_key,
        retry_available=retry_available,
    )
