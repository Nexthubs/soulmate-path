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
    EmailCaptureRequest,
    EmailCaptureResponse,
    EmailSummaryResponse,
    FlowStateResponse,
    InterstitialSubmitRequest,
    InterstitialSubmitResponse,
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
from app.soulmate.services.identity_service import IdentityService
from app.soulmate.services.interstitial_service import InterstitialService
from app.soulmate.services.profile_service import ProfileService
from app.soulmate.services.session_service import SessionService
from app.soulmate.services.summary_service import SummaryService


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
    "/current/email-summary",
    response_model=EmailSummaryResponse,
    summary="Get display-ready Email capture summary for current session",
    description="Returns display-ready Q3/Q5/Q6 summary view model without frontend guessing labels from raw codes (DEV-SPEC §8.1, SP-302, QUIZ-01).",
)
async def get_current_email_summary_endpoint(
    session: SoulmateSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> EmailSummaryResponse:
    return await SummaryService.get_email_summary_for_session(db=db, session=session)


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


@router.put(
    "/{public_id}/interstitials/{code}",
    response_model=InterstitialSubmitResponse,
    summary="Submit or edit post-quiz interstitial answer",
    description="Validates and atomically persists answer for spiritual_person, familiar_psychic_artistry, or warning_response (DEV-SPEC §5.7, §15.4, SP-206).",
)
async def submit_interstitial_endpoint(
    public_id: str,
    code: str,
    request_data: InterstitialSubmitRequest,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> InterstitialSubmitResponse:
    # IDOR Guard (DEV-SPEC §20)
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await InterstitialService.submit_interstitial(
        db=db,
        session=session,
        interstitial_code=code,
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
            "Profile is not available yet. Complete the quiz first."
        )

    return SoulmateProfileV1.model_validate(profile)


@router.post(
    "/{public_id}/email",
    response_model=EmailCaptureResponse,
    summary="Capture user email and bind session identity",
    description="Validates and normalizes email, binds anonymous session to consistent user identity using existing account model, and advances current step (DEV-SPEC §8.2, §15.5, §20, SP-301).",
)
async def capture_email_endpoint(
    public_id: str,
    request_data: EmailCaptureRequest,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> EmailCaptureResponse:
    # IDOR Guard (DEV-SPEC §20, SP-301 acceptance: user cannot bind another user's session by ID)
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await IdentityService.capture_and_bind_email(
        db=db,
        session=session,
        email_input=request_data.email,
    )


@router.get(
    "/{public_id}/email-summary",
    response_model=EmailSummaryResponse,
    summary="Get display-ready Email capture summary by public ID",
    description="Returns display-ready Q3/Q5/Q6 summary view model for the requested session with IDOR guard (DEV-SPEC §8.1, SP-302, QUIZ-01).",
)
async def get_session_email_summary_endpoint(
    public_id: str,
    authenticated_id: str = Depends(get_authenticated_session_public_id),
    db: AsyncSession = Depends(get_db),
) -> EmailSummaryResponse:
    # IDOR Guard (DEV-SPEC §20)
    verify_session_ownership(requested_public_id=public_id, authenticated_public_id=authenticated_id)

    session = await SessionService.get_session_by_public_id(db, public_id)
    if not session:
        raise NotFoundError(f"Session with ID '{public_id}' not found.")

    return await SummaryService.get_email_summary_for_session(db=db, session=session)


