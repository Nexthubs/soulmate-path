"""Structured logging and correlation context for Soulmate Path (DEV-SPEC §19.1, SP-005)."""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variables for request and business correlation
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="")
session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id_ctx", default=None)
user_id_ctx: ContextVar[Optional[str]] = ContextVar("user_id_ctx", default=None)
paypal_subscription_id_ctx: ContextVar[Optional[str]] = ContextVar("paypal_subscription_id_ctx", default=None)
artifact_id_ctx: ContextVar[Optional[str]] = ContextVar("artifact_id_ctx", default=None)
job_id_ctx: ContextVar[Optional[str]] = ContextVar("job_id_ctx", default=None)
provider_request_id_ctx: ContextVar[Optional[str]] = ContextVar("provider_request_id_ctx", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON log formatter strictly complying with DEV-SPEC §19.1 required fields:
    - request_id
    - session_id
    - user_id nullable
    - paypal_subscription_id nullable
    - artifact_id nullable
    - job_id nullable
    - provider_request_id nullable
    - event_type
    - error_code
    - latency_ms
    """

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            # DEV-SPEC §19.1 mandatory fields:
            "request_id": getattr(record, "request_id", None) or request_id_ctx.get(),
            "session_id": getattr(record, "session_id", None) or session_id_ctx.get(),
            "user_id": getattr(record, "user_id", None) or user_id_ctx.get(),
            "paypal_subscription_id": getattr(record, "paypal_subscription_id", None) or paypal_subscription_id_ctx.get(),
            "artifact_id": getattr(record, "artifact_id", None) or artifact_id_ctx.get(),
            "job_id": getattr(record, "job_id", None) or job_id_ctx.get(),
            "provider_request_id": getattr(record, "provider_request_id", None) or provider_request_id_ctx.get(),
            "event_type": getattr(record, "event_type", "general"),
            "error_code": getattr(record, "error_code", None),
            "latency_ms": getattr(record, "latency_ms", None),
        }

        # Include additional extra attributes if provided
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_payload["data"] = record.extra_data

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


def setup_structured_logging(level: int = logging.INFO) -> None:
    """Configures root logger with structured JSON logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())

    root_logger = logging.getLogger()
    # Remove existing stream handlers to avoid double output
    for h in root_logger.handlers[:]:
        if isinstance(h, logging.StreamHandler):
            root_logger.removeHandler(h)

    root_logger.addHandler(handler)
    root_logger.setLevel(level)


logger = logging.getLogger("soulmate")


def log_event(
    event_type: str,
    message: str,
    level: int = logging.INFO,
    error_code: Optional[str] = None,
    latency_ms: Optional[float] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    paypal_subscription_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    job_id: Optional[str] = None,
    provider_request_id: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Helper to emit a structured log record with context and extra fields."""
    extra: Dict[str, Any] = {
        "request_id": request_id or request_id_ctx.get(),
        "session_id": session_id or session_id_ctx.get(),
        "user_id": user_id or user_id_ctx.get(),
        "paypal_subscription_id": paypal_subscription_id or paypal_subscription_id_ctx.get(),
        "artifact_id": artifact_id or artifact_id_ctx.get(),
        "job_id": job_id or job_id_ctx.get(),
        "provider_request_id": provider_request_id or provider_request_id_ctx.get(),
        "event_type": event_type,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "extra_data": extra_data,
        **kwargs,
    }
    logger.log(level, message, extra=extra)
