"""Global exception handlers for standardizing API error responses (DEV-SPEC §19, SP-005)."""

import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.core.errors import SoulmateAppError, SoulmateErrorCode
from app.core.logging import log_event, request_id_ctx


def _get_request_id(request: Request) -> str:
    """Safely obtain request correlation ID from request state or contextvar."""
    req_id = getattr(request.state, "request_id", None)
    if not req_id:
        req_id = request_id_ctx.get()
    return req_id or ""


async def soulmate_app_error_handler(request: Request, exc: SoulmateAppError) -> JSONResponse:
    """Handles domain-specific Soulmate errors with machine-readable codes and safe messages."""
    req_id = _get_request_id(request)

    # Log error internally including sensitive provider details
    log_event(
        event_type="domain_error",
        message=f"Domain error {exc.error_code.value}: {exc.message}",
        level=logging.WARNING if exc.status_code < 500 else logging.ERROR,
        error_code=exc.error_code.value,
        extra_data={
            "status_code": exc.status_code,
            "internal_error": exc.internal_error,
            "provider_code": exc.provider_code,
            "provider_request_id": exc.provider_request_id,
            "details": exc.details,
        },
    )

    response_payload = exc.to_client_dict(request_id=req_id)
    return JSONResponse(
        status_code=exc.status_code,
        content=response_payload,
        headers={"X-Request-ID": req_id},
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Normalizes FastAPI / Pydantic validation errors into standard Soulmate error format."""
    req_id = _get_request_id(request)

    log_event(
        event_type="validation_error",
        message="Request schema validation failed",
        level=logging.INFO,
        error_code=SoulmateErrorCode.VALIDATION_ERROR.value,
        extra_data={"errors": exc.errors()},
    )

    return JSONResponse(
        status_code=422,
        content={
            "error_code": SoulmateErrorCode.VALIDATION_ERROR.value,
            "message": "Invalid request payload or query parameters.",
            "request_id": req_id,
            "details": {"errors": exc.errors()},
        },
        headers={"X-Request-ID": req_id},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catches all unexpected internal exceptions, guarantees no raw traces or secrets leak,
    and returns a safe machine-readable 500 error payload.
    """
    req_id = _get_request_id(request)

    # Log full traceback internally with correlation ID
    log_event(
        event_type="unhandled_internal_error",
        message=f"Unhandled internal exception on {request.method} {request.url.path}: {str(exc)}",
        level=logging.ERROR,
        error_code=SoulmateErrorCode.INTERNAL_SERVER_ERROR.value,
        extra_data={
            "exception_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        },
    )

    return JSONResponse(
        status_code=500,
        content={
            "error_code": SoulmateErrorCode.INTERNAL_SERVER_ERROR.value,
            "message": "An unexpected server error occurred. Please try again later.",
            "request_id": req_id,
            "details": {},
        },
        headers={"X-Request-ID": req_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registers all custom exception handlers on the FastAPI application."""
    app.add_exception_handler(SoulmateAppError, soulmate_app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
