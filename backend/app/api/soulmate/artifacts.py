"""
Sketch & report artifact endpoints (DEV-SPEC §15.10, §15.11; Decisions: ASSET-01, TIME-01, PAY-AUTH-01, RECOVERY-01; SP-603, SP-702).

POST /artifacts/sketch/generate — on_demand trigger (§11.4): enqueues one logical,
idempotent generation job that the worker processes independently of the request
lifecycle. Auth and ownership follow the Result aggregate pattern (SP-503).
GET /artifacts/report — authorized, unlocked retrieval of the persisted
SoulmateReportV1 content (§15.11; SP-702). POST /artifacts/report/generate —
on_demand trigger for the entitled, unlocked session (§13.4/§15.11; SP-706),
refused while the production switch is off (REPORT-01/02).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenOwnershipError, NotFoundError
from app.db.base import utc_now
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.domain.guard import is_paid_access_ended
from app.soulmate.schema import (
    ReportGenerationResponse,
    ReportResponse,
    SketchAssetResponse,
    SketchGenerationResponse,
)
from app.soulmate.security import (
    extract_session_token,
    get_authenticated_session_public_id,
    verify_session_ownership,
    verify_session_token,
)
from app.soulmate.services.object_storage_sink import build_sketch_image_url
from app.soulmate.services.report_generation_service import ReportGenerationService
from app.soulmate.services.report_service import ReportService
from app.soulmate.services.session_service import SessionService
from app.soulmate.services.sketch_generation_service import (
    JOB_FAILED_RETRYABLE,
    SketchGenerationService,
    hard_attempt_cap,
)
from app.soulmate.services.status_service import ArtifactStatusService
from app.soulmate.services.subscription_service import SubscriptionService

router = APIRouter()


async def _paid_window_ended(db: AsyncSession, session: SoulmateSession) -> bool:
    """PAID-THROUGH-01: True when the session's known paid window has ended."""
    sub = await SubscriptionService.get_latest_subscription(db, session)
    if sub is not None:
        sub = await SubscriptionService.refresh_paid_access_at_boundary(db, sub, utc_now())
    return sub is not None and is_paid_access_ended(
        sub.paid_through_at
    )


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
        session_id=session.public_id,
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
    when COMPLETED, the persisted artifact version and display URL. Reads never
    cross sessions (Decision RECOVERY-01); the display URL is derived from the
    project-owned storage key (ASSET-01) and never from a provider temporary URL.

    PAID-THROUGH-01: after a known-and-passed paid window, only a COMPLETED
    sketch remains retrievable (§9.8 retention promise — "keep what you
    received"); every other state is refused.
    """
    session = await _resolve_authorized_session(request, session_id, db)

    statuses = await ArtifactStatusService.get_artifact_statuses(db, session.id)

    if statuses.sketch.status != "COMPLETED" and await _paid_window_ended(db, session):
        raise ForbiddenOwnershipError(
            "Paid access period has ended. Re-subscribe to regain access."
        )

    image_url: Optional[str] = None
    storage_key: Optional[str] = None
    artifact_version: Optional[str] = None
    retry_available: Optional[bool] = None
    if statuses.sketch.status == "COMPLETED":
        stmt = select(
            SoulmateArtifact.storage_key,
            SoulmateArtifact.generation_status,
            SoulmateArtifact.artifact_version,
        ).where(
            SoulmateArtifact.session_id == session.id,
            SoulmateArtifact.artifact_type == "SKETCH",
            SoulmateArtifact.artifact_version == "v1",
        )
        row = (await db.execute(stmt)).first()
        if row is not None and row.generation_status == "COMPLETED":
            storage_key = row.storage_key
            artifact_version = row.artifact_version
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
        session_id=session.public_id,
        server_time=statuses.server_time,
        sketch=statuses.sketch,
        image_url=image_url,
        storage_key=storage_key,
        artifact_version=artifact_version,
        retry_available=retry_available,
    )


@router.get(
    "/report",
    response_model=ReportResponse,
    summary="Authorized report retrieval (DEV-SPEC §15.11, SP-702)",
)
async def get_report_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """
    Authoritative session-scoped report state plus, when the combined §10.3 state is
    COMPLETED (unlocked past report_unlock_at AND generation finished), the persisted
    SoulmateReportV1 content as validated camelCase JSON. The stored payload is
    re-validated on every read (SP-701 contract) and the read fails closed: content
    is never served for LOCKED/READY/GENERATING/FAILED rows. REPORT is strictly
    session-scoped (Decision RECOVERY-01) — no email-scoped fallback.

    PAID-THROUGH-01: after a known-and-passed paid window, only a COMPLETED
    report remains retrievable (§9.8 retention promise — "keep what you
    received"); every other state is refused.
    """
    session = await _resolve_authorized_session(request, session_id, db)

    statuses = await ArtifactStatusService.get_artifact_statuses(db, session.id)

    if statuses.report.status != "COMPLETED" and await _paid_window_ended(db, session):
        raise ForbiddenOwnershipError(
            "Paid access period has ended. Re-subscribe to regain access."
        )

    content = None
    if statuses.report.status == "COMPLETED":
        artifact = await ReportService.get_report_artifact(db, session.id)
        if artifact is not None:
            content = ReportService.get_report_content(artifact)

    return ReportResponse(
        session_id=session.public_id,
        server_time=statuses.server_time,
        report=statuses.report,
        content=content,
    )


@router.post(
    "/report/generate",
    response_model=ReportGenerationResponse,
    summary="Trigger on_demand report generation (DEV-SPEC §13.4, §15.11, SP-706)",
)
async def generate_report_endpoint(
    request: Request,
    session_id: Optional[str] = Query(default=None, description="Optional public session ID"),
    db: AsyncSession = Depends(get_db),
) -> ReportGenerationResponse:
    """
    Enqueue one logical V1 report generation for the authenticated entitled,
    unlocked session (on_demand, REPORT-01). Idempotent: a completed report is
    returned as-is and concurrent triggers converge on one durable job; the
    provider switch (REPORT-01/02) must be enabled or the request fails with 503.
    The worker processes the job after this request ends.
    """
    session = await _resolve_authorized_session(request, session_id, db)
    outcome = await ReportGenerationService.enqueue_report_generation(db, session)

    statuses = await ArtifactStatusService.get_artifact_statuses(db, session.id)

    return ReportGenerationResponse(
        session_id=session.public_id,
        server_time=statuses.server_time,
        report=statuses.report,
        job_status=outcome.job.status if outcome.job is not None else None,
    )
