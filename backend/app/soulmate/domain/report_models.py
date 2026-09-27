"""
Report generation provider contracts (DEV-SPEC §13.3–13.4; Decisions: REPORT-01, REPORT-02; SP-704).

Owns the app-owned provider interface the report pipeline (SP-706+) programs against,
so the OpenAI-compatible adapter (owner direction 2026-09-27) and the mock provider
are swappable and never leak into business code:

- `SoulmateReportGenerator` — structural interface adapting §13.3's
  `generate({profile, promptVersion}) -> SoulmateReportV1`: the method returns a
  `ReportGenerationResult` wrapping the validated `SoulmateReportV1` plus provider
  tracing metadata (same accepted deviation as the sketch provider, SP-602);
- `ReportGenerationInput` — normalized profile + versioned prompt context (§13.3);
  no raw quiz answers and no client-supplied prompt text can enter a provider;
- `ReportProviderError` — provider failures already mapped to domain error
  categories (retryable → PROVIDER_UNAVAILABLE, permanent → GENERATION_FAILED),
  reusing the shared HTTP-status classification from the sketch contracts.

REPORT-01/REPORT-02 stay OPEN: this module authors no production reading content.
Production generation remains disabled until they close (SP-706 is BLOCKED on both).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import SoulmateAppError, SoulmateErrorCode
from app.soulmate.domain.profile import SoulmateProfileV1
from app.soulmate.domain.report import SoulmateReportV1

# Shared HTTP-status classification (§11.6 vocabulary, reused for report providers):
# permanent: 400/401/403/404/422; retryable: 408/409/429 and 5xx.
from app.soulmate.domain.sketch_models import (  # noqa: F401  (re-exported for callers)
    is_retryable_provider_status,
    provider_code_for_status,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReportProviderError(SoulmateAppError):
    """
    A provider-side failure, already mapped to its domain error category.

    `retryable` is the contract future job/retry plumbing (SP-706) relies on for
    FAILED_RETRYABLE vs FAILED_PERMANENT; provider_code/provider_request_id carry
    safe tracing metadata (never credentials).
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


class ReportGenerationDisabledError(SoulmateAppError):
    """
    Raised when report generation is requested while the production switch is off.

    `SOULMATE_REPORT_PROVIDER` empty/unset means REPORT-01/REPORT-02 still gate
    production generation (DECISIONS.md); failing closed here makes the disabled
    state explicit for future trigger paths (SP-706) instead of silently choosing
    a provider.
    """

    def __init__(self, message: str = "Report generation is disabled (REPORT-01/02 pending)."):
        super().__init__(
            error_code=SoulmateErrorCode.PROVIDER_UNAVAILABLE,
            message=message,
            status_code=503,
            details={"reason": "REPORT_GENERATION_DISABLED"},
        )


class ReportGenerationInput(BaseModel):
    """
    Versioned generation input per DEV-SPEC §13.3: the normalized profile plus the
    prompt version. The profile is the canonical `SoulmateProfileV1` (SP-205) —
    providers consume normalized context, never raw quiz answers or client text.
    """

    model_config = ConfigDict(frozen=True)

    profile: SoulmateProfileV1 = Field(..., description="Normalized SoulmateProfileV1 (§7)")
    prompt_version: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Versioned report prompt template identifier (§13.3)",
    )


class ReportGenerationResult(BaseModel):
    """
    Successful generation output: the validated `SoulmateReportV1` plus tracing
    metadata. Callers persist `report` through `ReportService.save_completed_report`
    (SP-702), which re-validates and enforces the no-clobber canonical rule.
    """

    model_config = ConfigDict(frozen=True)

    report: SoulmateReportV1 = Field(..., description="Validated report content (§13.2)")
    provider: str = Field(..., description="Provider identifier, e.g. 'openai_compatible' or 'mock'")
    model: str = Field(..., description="Model id used for this generation")
    prompt_version: str = Field(..., description="Prompt template version used (§13.3)")
    prompt_sha256: Optional[str] = Field(
        default=None,
        description="Rendered prompt template content hash, when the provider uses a template",
    )
    provider_request_id: Optional[str] = Field(
        default=None,
        description="Provider request/correlation id for tracing",
    )
    generated_at: datetime = Field(
        default_factory=_utc_now,
        description="Server-side UTC completion time",
    )
    duration_ms: int = Field(..., ge=0, description="End-to-end provider call duration")


@runtime_checkable
class SoulmateReportGenerator(Protocol):
    """
    App-owned interface for report generation (DEV-SPEC §13.3, SP-704).

    Implementations must:
    - consume only `ReportGenerationInput` (normalized profile + prompt version);
    - return a `ReportGenerationResult` whose `report` validates against the
      SoulmateReportV1 contract (validated again by persistence, SP-702);
    - raise `ReportProviderError` with the correct retryable category on failure.
    """

    provider_name: str

    async def generate(self, input: ReportGenerationInput) -> ReportGenerationResult: ...
