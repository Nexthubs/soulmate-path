"""
Sketch image generation contracts (DEV-SPEC §11, §25; Decisions: ASSET-01, PROMPT-01).

Owns the app-owned provider interface the generation pipeline (SP-603+) programs
against, so the OpenAI adapter is swappable and never leaks into business code:

- `SketchImageProvider` — structural interface: `generate_image(prompt) -> result`;
- `SketchGenerationResult` — image BYTES plus §11.3/§25 tracing metadata. Per
  ASSET-01, provider temporary URLs are not durable storage; callers must persist
  `image_bytes` into project-owned object storage (SP-605);
- `SketchProviderError` — provider failures already mapped to domain error
  categories: `retryable` failures (rate limit, 5xx, network/timeout) map to
  PROVIDER_UNAVAILABLE; permanent failures (invalid request / policy rejection,
  auth, malformed response) map to GENERATION_FAILED (DEV-SPEC §11.6
  FAILED_RETRYABLE / FAILED_PERMANENT).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import OpenAIErrorCode, SoulmateAppError, SoulmateErrorCode


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SketchProviderError(SoulmateAppError):
    """
    A provider-side failure, already mapped to its domain error category.

    `retryable` is the contract SP-603/604 rely on for FAILED_RETRYABLE vs
    FAILED_PERMANENT; provider_code/provider_request_id carry safe tracing
    metadata (never credentials).
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        provider_code: Optional[str] = None,
        provider_request_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        internal_error: Optional[str] = None,
    ):
        error_code = (
            SoulmateErrorCode.PROVIDER_UNAVAILABLE
            if retryable
            else SoulmateErrorCode.GENERATION_FAILED
        )
        status_code = 503 if retryable else 502
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details or {},
            internal_error=internal_error,
            provider_code=provider_code,
            provider_request_id=provider_request_id,
        )
        self.retryable = retryable


@runtime_checkable
class SketchImageProvider(Protocol):
    """
    App-owned interface for sketch image generation (DEV-SPEC §11, SP-602).

    Implementations must:
    - resolve model/size/quality/format from configuration (§22), never from clients;
    - return raw image bytes (ASSET-01: bytes are persisted to owned storage);
    - raise SketchProviderError with the correct retryable category on failure.
    """

    provider_name: str

    async def generate_image(self, prompt: str) -> "SketchGenerationResult": ...


class SketchGenerationResult(BaseModel):
    """
    Successful generation output: decoded image bytes + provider tracing metadata.

    `source_url` is only set when the provider returned a temporary URL instead of
    inline data; it is recorded for traceability and must NOT be used as storage
    (ASSET-01).
    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(..., description="Provider identifier, e.g. 'openai'")
    model: str = Field(..., description="Model id used for this generation (§11.3)")
    image_bytes: bytes = Field(..., description="Decoded image payload")
    image_format: str = Field(..., description="Image format, e.g. 'webp' (§22)")
    size: str = Field(..., description="Requested image size, e.g. '1024x1536'")
    quality: str = Field(..., description="Requested quality tier, e.g. 'medium'")

    provider_request_id: Optional[str] = Field(
        default=None,
        description="Provider request/correlation id for tracing (§11.3)",
    )
    provider_created_at: Optional[datetime] = Field(
        default=None,
        description="Provider-reported creation timestamp, if any",
    )
    generated_at: datetime = Field(
        default_factory=_utc_now,
        description="Server-side UTC completion time (§11.3 generation time)",
    )
    duration_ms: int = Field(..., ge=0, description="End-to-end provider call duration")
    source_url: Optional[str] = Field(
        default=None,
        description="Provider temporary URL when bytes were fetched from one (not durable, ASSET-01)",
    )


def provider_code_for_status(status_code: int) -> Optional[str]:
    """Maps an HTTP status to the shared OpenAI provider error-code vocabulary."""
    try:
        return OpenAIErrorCode(str(status_code)).value
    except ValueError:
        return None


def is_retryable_provider_status(status_code: int) -> bool:
    """
    Classifies provider HTTP statuses for §11.6 retry policy:
    - permanent: 400/401/403/404/422 (invalid request, policy rejection, auth, bad path);
    - retryable: 408/409/429 and all 5xx (rate limit, overload, transient upstream).
    """
    return status_code not in (400, 401, 403, 404, 422)
