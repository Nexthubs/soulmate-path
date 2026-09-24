"""Soulmate Quiz Configuration API (DEV-SPEC §15.2)."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.quiz import SoulmateQuizVersion
from app.db.models.session import SoulmateSession
from app.db.session import get_db
from app.quiz.constants import CANONICAL_QUIZ_VERSION
from app.quiz.loader import get_cached_quiz_config
from app.quiz.schema import QuizConfig
from app.soulmate.security import extract_session_token, verify_session_token

router = APIRouter()


@router.get(
    "/config",
    response_model=QuizConfig,
    summary="Get immutable Quiz configuration",
    description="Returns the immutable QuizConfig corresponding to a specific version or the active session (DEV-SPEC §15.2).",
)
async def get_quiz_config_endpoint(
    request: Request,
    version: Optional[str] = Query(None, description="Explicit quiz version identifier"),
    db: AsyncSession = Depends(get_db),
) -> QuizConfig:
    target_version = version

    # If no explicit version provided, try resolving from authenticated session cookie/token
    if not target_version:
        token = extract_session_token(request)
        if token:
            public_id = verify_session_token(token)
            if public_id:
                stmt = select(SoulmateSession.quiz_version).where(SoulmateSession.public_id == public_id)
                res = await db.execute(stmt)
                sess_version = res.scalar_one_or_none()
                if sess_version:
                    target_version = sess_version

    # Fallback to active canonical version
    if not target_version or target_version == CANONICAL_QUIZ_VERSION:
        return get_cached_quiz_config()

    # Query immutable version from database
    stmt = select(SoulmateQuizVersion).where(SoulmateQuizVersion.version == target_version)
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    if not record or not record.config_json:
        raise NotFoundError(f"Quiz version '{target_version}' not found.")

    return QuizConfig.model_validate(record.config_json)
