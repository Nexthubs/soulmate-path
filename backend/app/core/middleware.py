"""Request correlation and latency measurement middleware (DEV-SPEC §19, SP-005)."""

import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from app.core.logging import log_event, request_id_ctx


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """
    Ensures every incoming HTTP request is assigned a unique correlation ID.
    - Preserves client-supplied X-Request-ID if provided and non-empty.
    - Generates a UUID4 if absent.
    - Stores the ID in request context for structured logging and downstream handlers.
    - Echoes X-Request-ID in the HTTP response headers.
    - Measures request duration (latency_ms) and emits a structured access log.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Extract or generate correlation ID
        incoming_id = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming_id if incoming_id else str(uuid.uuid4())

        # Bind to contextvar for the duration of this request
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Latency and logging for unhandled exceptions will also be captured
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log_event(
                event_type="http_request_exception",
                message=f"{request.method} {request.url.path} failed internally",
                level=40,  # ERROR
                latency_ms=latency_ms,
                extra_data={"method": request.method, "path": request.url.path},
            )
            request_id_ctx.reset(token)
            raise

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Attach correlation ID to response headers
        response.headers["X-Request-ID"] = request_id

        # Emit structured HTTP access log
        log_event(
            event_type="http_request",
            message=f"{request.method} {request.url.path} {response.status_code} ({latency_ms}ms)",
            latency_ms=latency_ms,
            extra_data={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )

        request_id_ctx.reset(token)
        return response
