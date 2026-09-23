"""Soulmate Path Domain Error Codes & Exceptions (DEV-SPEC §19, SP-005)."""

from enum import Enum
from typing import Any, Dict, Optional, Union


class ProviderName(str, Enum):
    """External third-party service provider identifiers."""
    OPENAI = "openai"
    PAYPAL = "paypal"
    STORAGE = "storage"


class OpenAIErrorCode(str, Enum):
    """Standard OpenAI API error codes."""
    RATE_LIMIT_EXCEEDED = "429"
    SERVER_ERROR = "500"
    BAD_GATEWAY = "502"
    SERVICE_UNAVAILABLE = "503"
    GATEWAY_TIMEOUT = "504"
    INVALID_REQUEST = "400"
    UNAUTHORIZED = "401"


class PayPalErrorCode(str, Enum):
    """Standard PayPal API error codes."""
    SERVICE_UNAVAILABLE = "503"
    INTERNAL_SERVER_ERROR = "500"
    GATEWAY_TIMEOUT = "504"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    INSTRUMENT_DECLINED = "INSTRUMENT_DECLINED"
    PAYMENT_ALREADY_DONE = "PAYMENT_ALREADY_DONE"


class SoulmateErrorCode(str, Enum):
    """Machine-readable error codes for API contract and frontend state handling."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_FLOW_STATE = "INVALID_FLOW_STATE"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    LOCKED_ASSET = "LOCKED_ASSET"
    GENERATION_FAILED = "GENERATION_FAILED"
    FORBIDDEN_OWNERSHIP = "FORBIDDEN_OWNERSHIP"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class SoulmateAppError(Exception):
    """Base application exception for all Soulmate domain errors."""

    def __init__(
        self,
        error_code: SoulmateErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        internal_error: Optional[str] = None,
        provider_code: Optional[str] = None,
        provider_request_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        # Sensitive diagnostics retained ONLY for server-side logs, never serialized to clients
        self.internal_error = internal_error
        self.provider_code = provider_code
        self.provider_request_id = provider_request_id

    def to_client_dict(self, request_id: str) -> Dict[str, Any]:
        """Convert to safe user-facing API response body."""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "request_id": request_id,
            "details": self.details,
        }


class ValidationError(SoulmateAppError):
    """Invalid input payload, option code, date boundary, or schema mismatch."""

    def __init__(
        self,
        message: str = "Invalid request parameters.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=400,
            details=details,
            **kwargs,
        )


class InvalidFlowStateError(SoulmateAppError):
    """Session is in an invalid state for the attempted action or step transition."""

    def __init__(
        self,
        message: str = "Action cannot be performed in the current flow state.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.INVALID_FLOW_STATE,
            message=message,
            status_code=409,
            details=details,
            **kwargs,
        )


class PaymentPendingError(SoulmateAppError):
    """Payment is currently being processed or confirmed; entitlement not yet granted."""

    def __init__(
        self,
        message: str = "We’re still confirming your payment.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.PAYMENT_PENDING,
            message=message,
            status_code=409,
            details=details,
            **kwargs,
        )


class LockedAssetError(SoulmateAppError):
    """Asset (sketch or report) is locked pending server unlock duration (Spec §10, TIME-01)."""

    def __init__(
        self,
        message: str = "This artifact is locked pending scheduled unlock.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.LOCKED_ASSET,
            message=message,
            status_code=423,  # 423 Locked
            details=details,
            **kwargs,
        )


class GenerationFailedError(SoulmateAppError):
    """AI asset generation job failed or exceeded retry limit."""

    def __init__(
        self,
        message: str = "Image generation failed. Please try again later.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.GENERATION_FAILED,
            message=message,
            status_code=502,
            details=details,
            **kwargs,
        )


class ForbiddenOwnershipError(SoulmateAppError):
    """Request lacks valid ownership of the target resource (IDOR guard, Spec §20)."""

    def __init__(
        self,
        message: str = "Access forbidden.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.FORBIDDEN_OWNERSHIP,
            message=message,
            status_code=403,
            details=details,
            **kwargs,
        )


class NotFoundError(SoulmateAppError):
    """Requested resource (session, artifact, order) does not exist."""

    def __init__(
        self,
        message: str = "Requested resource not found.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.NOT_FOUND,
            message=message,
            status_code=404,
            details=details,
            **kwargs,
        )


class ProviderUnavailableError(SoulmateAppError):
    """External provider (PayPal, OpenAI, S3) is rate-limited or unavailable (Spec §19.3)."""

    def __init__(
        self,
        message: str = "External provider service is temporarily unavailable.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.PROVIDER_UNAVAILABLE,
            message=message,
            status_code=503,
            details=details,
            **kwargs,
        )


class InternalServerError(SoulmateAppError):
    """Unexpected internal server error."""

    def __init__(
        self,
        message: str = "An unexpected server error occurred. Please try again later.",
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            error_code=SoulmateErrorCode.INTERNAL_SERVER_ERROR,
            message=message,
            status_code=500,
            details=details,
            **kwargs,
        )


def map_provider_error(
    provider: Union[ProviderName, str],
    raw_code: Union[OpenAIErrorCode, PayPalErrorCode, str, int],
    raw_message: str,
    provider_request_id: Optional[str] = None,
    internal_details: Optional[Dict[str, Any]] = None,
) -> SoulmateAppError:
    """
    Transforms raw third-party errors into sanitized user-facing domain exceptions (DEV-SPEC §19.3).
    Ensures internal secrets, stack traces, and provider raw bodies never leak to clients.
    """
    normalized_provider = (
        provider.value.lower() if isinstance(provider, ProviderName) else str(provider).lower().strip()
    )
    raw_code_str = raw_code.value if hasattr(raw_code, "value") else str(raw_code)
    normalized_code = raw_code_str.upper().strip()

    # OpenAI specific mappings (§19.3)
    if normalized_provider == "openai":
        if "429" in normalized_code or "RATE_LIMIT" in normalized_code:
            return ProviderUnavailableError(
                message="Your portrait is taking a little longer than expected.",
                internal_error=f"OpenAI rate limit: {raw_message}",
                provider_code=raw_code,
                provider_request_id=provider_request_id,
            )
        if normalized_code.startswith("5") or "SERVER_ERROR" in normalized_code:
            return ProviderUnavailableError(
                message="Your portrait is taking a little longer than expected.",
                internal_error=f"OpenAI upstream server error: {raw_message}",
                provider_code=raw_code,
                provider_request_id=provider_request_id,
            )
        return GenerationFailedError(
            message="Your portrait could not be created at this time. Please try again.",
            internal_error=f"OpenAI error: {raw_message}",
            provider_code=raw_code,
            provider_request_id=provider_request_id,
        )

    # PayPal specific mappings (§19.3)
    if normalized_provider == "paypal":
        if normalized_code.startswith("5") or "TIMEOUT" in normalized_code or "UNAVAILABLE" in normalized_code:
            return PaymentPendingError(
                message="We’re still confirming your payment.",
                internal_error=f"PayPal upstream error/timeout: {raw_message}",
                provider_code=raw_code,
                provider_request_id=provider_request_id,
            )
        if "RESOURCE_NOT_FOUND" in normalized_code:
            return NotFoundError(
                message="Payment record not found.",
                internal_error=f"PayPal resource not found: {raw_message}",
                provider_code=raw_code,
                provider_request_id=provider_request_id,
            )
        return PaymentPendingError(
            message="We’re still confirming your payment.",
            internal_error=f"PayPal processing issue: {raw_message}",
            provider_code=raw_code,
            provider_request_id=provider_request_id,
        )

    # Storage / generic provider fallback
    return ProviderUnavailableError(
        message="A required service is temporarily unavailable. Please try again later.",
        internal_error=f"{provider} error: {raw_message}",
        provider_code=raw_code,
        provider_request_id=provider_request_id,
    )
