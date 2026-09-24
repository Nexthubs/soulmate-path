"""Soulmate Session API Endpoints (DEV-SPEC §6, §15.1, §20)."""

from typing import Optional
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.errors import NotFoundError
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.soulmate.schema import (
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    FlowStateResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionCurrentResponse,
    TransitionContinueResponse,
)
from app.soulmate.security import (
    get_authenticated_session_public_id,
    get_current_session,
    verify_session_ownership,
)
from app.soulmate.domain.profile import SoulmateProfileV1
from app.soulmate.services.answer_service import AnswerService
from app.soulmate.services.flow_service import FlowService
from app.soulmate.services.profile_service import ProfileService
from app.soulmate.services.session_service import SessionService


router = APIRouter()


@router.post(
    "",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create anonymous Soulmate session",
    description="Initializes a new anonymous quiz session, pins quiz_version, and sets HttpOnly soulmate_sid cookie.",
)
async def create_session(
    response: Response,
    request_data: Optional[SessionCreateRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> SessionCreateResponse:
    utm_json = request_data.utm_json if request_data else {}
    session, token = await SessionService.create_session(db=db, utm_json=utm_json)

    # Set secure HttpOnly session cookie per DEV-SPEC §6.1
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_cookie_max_age_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )

    # Expose token in custom header for non-browser/test clients
    response.headers["X-Soulmate-Session-Token"] = token

    return SessionService.format_create_response(session)


@router.get(
    "/current",
    response_model=SessionCurrentResponse,
    summary="Recover current Soulmate session",
    description="Recovers caller's active session, returning status, current_step, and saved answers for UI restoration.",
)
async def get_current_session_endpoint(
    session: SoulmateSession = Depends(get_current_session),
) -> SessionCurrentResponse:
    return SessionService.format_current_response(session)


@router.get(
    "/{public_id}",
    response_model=SessionCurrentResponse,
    summary="Get Soulmate session by public ID",
    description="Fetches session state by public ID. Enforces ownership verification to prevent IDOR access.",
)
async def get_session_by_id_endpoint(
    public_id: str,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> SessionCurrentResponse:
    # IDOR Guard (DEV-SPEC §20)
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return SessionService.format_current_response(session)


@router.put(
    "/{public_id}/answers/{question_code}",
    response_model=AnswerSubmitResponse,
    summary="Submit or edit question answer",
    description="Validates and atomically upserts question answer, advancing current step (DEV-SPEC §15.3).",
)
async def submit_answer_endpoint(
    public_id: str,
    question_code: str,
    request_data: AnswerSubmitRequest,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> AnswerSubmitResponse:
    # IDOR Guard (DEV-SPEC §20)
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await AnswerService.submit_answer(
        db=db,
        session=session,
        question_code=question_code,
        req=request_data,
    )


@router.get(
    "/{public_id}/flow/state",
    response_model=FlowStateResponse,
    summary="Get authoritative flow state",
    description="Resolves server-authoritative current step, next step, previous step, progress percent, and step metadata (DEV-SPEC §1.1, §4, §15.3, SP-203).",
)
async def get_flow_state_endpoint(
    public_id: str,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> FlowStateResponse:
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await FlowService.get_flow_state(db=db, session=session)


@router.post(
    "/{public_id}/transitions/{transition_code}/continue",
    response_model=TransitionContinueResponse,
    summary="Continue through transition screen",
    description="Validates prerequisite questions, updates session current_step to the subsequent step, and returns new flow state.",
)
async def continue_transition_endpoint(
    public_id: str,
    transition_code: str,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> TransitionContinueResponse:
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await FlowService.continue_transition(
        db=db,
        session=session,
        transition_code=transition_code,
    )


@router.post(
    "/{public_id}/step/back",
    response_model=FlowStateResponse,
    summary="Navigate to previous step",
    description="Navigates the session to the previous canonical step while preserving all saved answers intact.",
)
async def navigate_back_endpoint(
    public_id: str,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> FlowStateResponse:
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await FlowService.navigate_back(db=db, session=session)


@router.get(
    "/{public_id}/profile",
    response_model=SoulmateProfileV1,
    summary="Get normalized Soulmate Profile",
    description="Returns canonical SoulmateProfileV1 built from completed quiz answers (DEV-SPEC §7, Decisions: QUIZ-01).",
)
async def get_session_profile_endpoint(
    public_id: str,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> SoulmateProfileV1:
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    profile = await ProfileService.get_profile_by_session_id(db, session.id)
    if not profile:
        profile = await ProfileService.sync_profile_for_session(db, session)

    if not profile:
        raise NotFoundError(
            f"Normalized profile not available for session '{public_id}'. Complete quiz questions (q02-q18) first."
        )

    return SoulmateProfileV1.model_validate(profile)


