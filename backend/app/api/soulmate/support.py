"""Internal status-only lookup for one customer support case."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.soulmate.support_auth import verify_support_access
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.soulmate.domain.support_lookup_models import SupportLookupRequest, SupportLookupResult
from app.soulmate.services.support_lookup_service import (
    AmbiguousSupportEmailError,
    InvalidSupportEmailError,
    SupportLookupService,
)

router = APIRouter()


@router.post(
    "/lookup",
    response_model=SupportLookupResult,
    summary="Trace one customer case by a precise identifier",
    dependencies=[Depends(verify_support_access)],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": SupportLookupRequest.model_json_schema(),
                }
            },
        }
    },
)
async def lookup_support_case(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SupportLookupResult:
    """Return status/timeline summaries without profile, payload, email, or storage data."""
    try:
        body = await request.json()
        query = SupportLookupRequest.model_validate(body)
    except (json.JSONDecodeError, PydanticValidationError, UnicodeDecodeError):
        # Do not echo or log request contents: a rejected body may contain an email.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid support lookup request",
        ) from None

    try:
        result = await SupportLookupService.lookup(db=db, query=query)
    except InvalidSupportEmailError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email lookup identifier",
        ) from None
    except AmbiguousSupportEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email matches multiple sessions; use a session or provider identifier",
        ) from None
    if result is None:
        raise NotFoundError("No matching support case was found.")
    return result
