"""
Report generation providers (DEV-SPEC §13.2–13.4; Decisions: REPORT-01, REPORT-02; SP-704).

Pluggable providers behind the app-owned `SoulmateReportGenerator` interface:

- `MockReportProvider` — deterministic, clearly non-production test fixture output
  ("[MOCK]"-labeled, echoes the normalized profile so E2E tests can prove the input
  contract). Never calls an external service.
- `OpenAICompatibleReportProvider` — the owner-directed (2026-09-27, DECISIONS
  REPORT-01) production-shaped adapter for any OpenAI-compatible
  `POST {base_url}/chat/completions` endpoint. Endpoint URL, API key, and model
  come exclusively from §13.3 configuration (`SOULMATE_REPORT_API_BASE_URL` /
  `SOULMATE_REPORT_API_KEY` / `SOULMATE_REPORT_MODEL`, with shared `OPENAI_*`
  fallback). The prompt is rendered from a **versioned prompt template**
  (`config/prompts/soulmate-report/<version>.txt`, SP-601 pattern) against the
  normalized profile — NO production template ships in this repository, so a
  configured version without a template file fails closed (REPORT-02: the
  production prompt is an unresolved decision and must not be invented here).
- `build_report_provider` — factory reading the `SOULMATE_REPORT_PROVIDER` switch;
  empty/unset (the default) raises `ReportGenerationDisabledError`, keeping
  production generation off until REPORT-01/REPORT-02 close.

Every provider output is validated against the SoulmateReportV1 contract before it
leaves this module; persistence re-validates again (SP-702).
"""

import hashlib
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.soulmate.domain.report import SoulmateReportV1, parse_soulmate_report_v1
from app.soulmate.domain.report_models import (
    ReportGenerationDisabledError,
    ReportGenerationInput,
    ReportGenerationResult,
    ReportProviderError,
    is_retryable_provider_status,
    provider_code_for_status,
)

logger = logging.getLogger(__name__)

REPORT_PROVIDER_MOCK = "mock"
REPORT_PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"

_NETWORK_ERROR_CODE = "NETWORK_ERROR"
_TIMEOUT_ERROR_CODE = "TIMEOUT"

# Repository layout: backend/app/soulmate/services/report_providers.py -> repo root is parents[4].
REPORT_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "config" / "prompts"
REPORT_PROMPT_NAME = "soulmate_report"

# The only template variables allowed in a report prompt template (SP-601 whitelist
# pattern): the normalized profile JSON and the ReportV1 JSON schema. Any other
# braces in the template are rejected, so prompt content cannot smuggle format
# directives or client-influenced text.
ALLOWED_REPORT_PROMPT_VARIABLES = frozenset({"profile_json", "report_schema_json"})

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


# ---------------------------------------------------------------------------
# Versioned prompt template (REPORT-02 slot: infrastructure only, no content)
# ---------------------------------------------------------------------------


class ReportPromptTemplateError(ReportProviderError):
    """A report prompt template is missing or violates the variable whitelist (permanent)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, retryable=False, details=details)


def report_prompt_template_path(version: str) -> Path:
    if not _VERSION_RE.match(version or ""):
        raise ReportPromptTemplateError(
            f"Invalid report prompt version '{version}'.",
            details={"version": version},
        )
    return REPORT_PROMPTS_DIR / "soulmate-report" / f"{version}.txt"


class ReportPromptTemplate:
    """A loaded, validated report prompt template snapshot with content hash."""

    __slots__ = ("name", "version", "text", "placeholders", "sha256")

    def __init__(self, name: str, version: str, text: str):
        if "{{" in text or "}}" in text:
            raise ReportPromptTemplateError(
                "Report prompt template contains '{{...}}' escapes; only single-brace "
                "whitelisted variables are allowed.",
                details={"version": version},
            )
        found = set(_PLACEHOLDER_RE.findall(text))
        unknown = found - ALLOWED_REPORT_PROMPT_VARIABLES
        if unknown:
            raise ReportPromptTemplateError(
                f"Report prompt template uses disallowed placeholders: {sorted(unknown)}.",
                details={
                    "version": version,
                    "disallowed": sorted(unknown),
                    "allowed": sorted(ALLOWED_REPORT_PROMPT_VARIABLES),
                },
            )
        self.name = name
        self.version = version
        self.text = text
        self.placeholders = frozenset(found)
        self.sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def _load_report_template_cached(version: str) -> ReportPromptTemplate:
    path = report_prompt_template_path(version)
    if not path.exists():
        # Fail closed: REPORT-02 owns the production prompt; this module never
        # invents one. A configured version without a template file stays disabled.
        raise ReportPromptTemplateError(
            f"Report prompt template for version '{version}' not found at '{path}'; "
            "report prompt content is an unresolved REPORT-02 decision.",
            details={"version": version, "path": str(path)},
        )
    text = path.read_text(encoding="utf-8")
    return ReportPromptTemplate(name=REPORT_PROMPT_NAME, version=version, text=text)


def load_report_prompt_template(version: str) -> ReportPromptTemplate:
    """Loads (and caches) the versioned report prompt template."""
    return _load_report_template_cached(version)


def invalidate_report_prompt_template_cache() -> None:
    _load_report_template_cached.cache_clear()


def render_report_prompt(
    generation_input: ReportGenerationInput,
    template: Optional[ReportPromptTemplate] = None,
) -> tuple:
    """
    Renders the final prompt for one generation call.

    Substitutes only the whitelisted variables:
    - `{profile_json}`: the normalized profile, camelCase (the §13.3 input contract);
    - `{report_schema_json}`: the SoulmateReportV1 JSON schema the output must satisfy.
    """
    tpl = template or load_report_prompt_template(generation_input.prompt_version)
    profile_json = json.dumps(
        generation_input.profile.model_dump(by_alias=True, exclude_none=True),
        ensure_ascii=False,
    )
    schema_json = json.dumps(
        SoulmateReportV1.model_json_schema(),
        ensure_ascii=False,
    )
    try:
        rendered = tpl.text.format(profile_json=profile_json, report_schema_json=schema_json)
    except (KeyError, IndexError, ValueError) as exc:
        raise ReportPromptTemplateError(
            f"Failed to resolve report prompt template '{tpl.version}': {exc}.",
            details={"version": tpl.version},
        ) from exc
    return rendered, tpl


# ---------------------------------------------------------------------------
# Mock provider (clearly non-production)
# ---------------------------------------------------------------------------


class MockReportProvider:
    """
    Deterministic mock implementing `SoulmateReportGenerator`.

    Output is unmistakably test content ("[MOCK]" labels, no reading claims) that
    echoes normalized profile fields so tests can verify the §13.3 input contract
    end to end. SP-705 owns the polished canonical fixture content.
    """

    provider_name = REPORT_PROVIDER_MOCK

    async def generate(self, generation_input: ReportGenerationInput) -> ReportGenerationResult:
        started = time.monotonic()
        profile = generation_input.profile
        report = parse_soulmate_report_v1(
            {
                "schemaVersion": "v1",
                "title": "[MOCK] Soulmate Report — Test Fixture, Not a Real Reading",
                "intro": (
                    "Deterministic mock-provider output used only for renderer and E2E "
                    "testing. Production report generation stays disabled (REPORT-01/REPORT-02)."
                ),
                "sections": [
                    {
                        "index": "01.",
                        "title": "Mock Input Echo (Non-Production)",
                        "body": (
                            f"Normalized profile input received: preferred partner gender "
                            f"'{profile.preferred_partner_gender}', age range "
                            f"'{profile.preferred_partner_age_range}', key quality "
                            f"'{profile.key_soulmate_quality}'."
                        ),
                        "points": [
                            {
                                "title": "Deterministic",
                                "body": "Identical inputs produce identical structure; no external service is called.",
                            }
                        ],
                    },
                    {
                        "index": "02.",
                        "title": "Schema Conformance Check",
                        "body": (
                            "This section lets renderer and persistence tests verify the "
                            "ReportV1 contract end to end."
                        ),
                    },
                ],
                "closing": "[MOCK] End of test fixture.",
            }
        )
        return ReportGenerationResult(
            report=report,
            provider=self.provider_name,
            model="mock",
            prompt_version=generation_input.prompt_version,
            prompt_sha256=None,
            provider_request_id=None,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (owner-directed production shape, REPORT-01)
# ---------------------------------------------------------------------------


def chat_completions_url(base_url: str) -> str:
    """Builds the chat/completions URL from an API root (no trailing slash)."""
    return base_url.rstrip().rstrip("/") + "/chat/completions"


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n|\n```\s*$")


def _strip_code_fences(text: str) -> str:
    """Defensively strips a single surrounding markdown code fence, if present."""
    return _FENCE_RE.sub("", text.strip()).strip()


class OpenAICompatibleReportProvider:
    """
    Async OpenAI-chat-compatible adapter satisfying `SoulmateReportGenerator`.

    Base URL / API key / model default to the §13.3 report configuration (with the
    shared OPENAI_* fallback); explicit constructor arguments exist for tests and
    future per-call overrides only. The API key never leaves this module, is never
    logged, and never appears in error details or result payloads.
    """

    provider_name = REPORT_PROVIDER_OPENAI_COMPATIBLE

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 120.0,
    ):
        self.api_key = api_key if api_key is not None else settings.report_api_key
        self.base_url = (base_url or settings.report_api_base_url).rstrip("/")
        self.model = model or settings.soulmate_report_model
        self.timeout = timeout
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_http_client = True
        return self._http_client

    async def close(self) -> None:
        if self._owns_http_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self) -> "OpenAICompatibleReportProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # SoulmateReportGenerator interface
    # ------------------------------------------------------------------

    async def generate(self, generation_input: ReportGenerationInput) -> ReportGenerationResult:
        """Generate one report from the normalized profile + versioned template (§13.3)."""
        if not self.api_key or not self.api_key.strip():
            # Permanent until configuration is fixed — retrying cannot help.
            raise ReportProviderError(
                "Report provider API key is not configured; report generation is unavailable.",
                retryable=False,
                provider_code=provider_code_for_status(401),
            )
        if not self.model or not str(self.model).strip():
            raise ReportProviderError(
                "Report provider model is not configured (SOULMATE_REPORT_MODEL).",
                retryable=False,
                provider_code=provider_code_for_status(400),
            )

        rendered_prompt, template = render_report_prompt(generation_input)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": rendered_prompt}],
        }
        # Authorization header is built here and never copied into errors/results/logs.
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        started = time.monotonic()
        client = await self._get_client()
        try:
            resp = await client.post(
                chat_completions_url(self.base_url),
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise self._network_error(
                "Report generation request timed out.",
                code=_TIMEOUT_ERROR_CODE,
                exc=exc,
                started=started,
            ) from exc
        except httpx.TransportError as exc:
            raise self._network_error(
                "Network error communicating with the report provider.",
                code=_NETWORK_ERROR_CODE,
                exc=exc,
                started=started,
            ) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        request_id = resp.headers.get("x-request-id")

        if resp.status_code != 200:
            raise self._http_error(resp, request_id=request_id)

        content = self._extract_message_content(resp, request_id=request_id)
        report = self._parse_report_content(content, request_id=request_id)

        return ReportGenerationResult(
            report=report,
            provider=self.provider_name,
            model=self.model,
            prompt_version=template.version,
            prompt_sha256=template.sha256,
            provider_request_id=request_id,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _network_error(
        self, message: str, *, code: str, exc: Exception, started: float
    ) -> ReportProviderError:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "Report provider request failed after %sms: %s (%s)",
            duration_ms,
            message,
            type(exc).__name__,
        )
        return ReportProviderError(
            message,
            retryable=True,
            provider_code=code,
            internal_error=f"{type(exc).__name__}: {exc}",
            details={"duration_ms": duration_ms},
        )

    def _http_error(self, resp: httpx.Response, *, request_id: Optional[str]) -> ReportProviderError:
        retryable = is_retryable_provider_status(resp.status_code)
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}

        error_field = body.get("error") if isinstance(body, dict) else None
        provider_type = code = None
        safe_message = "Report provider API error"
        if isinstance(error_field, dict):
            provider_type = error_field.get("type")
            code = error_field.get("code")
            raw_message = error_field.get("message")
            if isinstance(raw_message, str) and raw_message.strip():
                safe_message = raw_message.strip()[:300]

        logger.warning(
            "Report provider returned HTTP %s (retryable=%s, type=%s, code=%s, request_id=%s)",
            resp.status_code,
            retryable,
            provider_type,
            code,
            request_id,
        )
        return ReportProviderError(
            f"Report generation failed (HTTP {resp.status_code}): {safe_message}",
            retryable=retryable,
            provider_code=provider_code_for_status(resp.status_code) or (str(code) if code else None),
            provider_request_id=request_id,
            details={
                "http_status": resp.status_code,
                "provider_error_type": provider_type,
                "provider_error_code": code,
            },
            internal_error=resp.text[:2000],
        )

    def _extract_message_content(
        self, resp: httpx.Response, *, request_id: Optional[str]
    ) -> str:
        try:
            body = resp.json()
        except Exception as exc:
            raise ReportProviderError(
                "Report provider returned a non-JSON success response.",
                retryable=False,
                provider_code=provider_code_for_status(resp.status_code),
                provider_request_id=request_id,
                internal_error=f"{type(exc).__name__}: {exc}",
            ) from exc

        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ReportProviderError(
                "Report provider response has no choices.",
                retryable=False,
                provider_request_id=request_id,
                internal_error=str(body)[:2000],
            )
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ReportProviderError(
                "Report provider response message has no content.",
                retryable=False,
                provider_request_id=request_id,
                internal_error=str(choices[0])[:1000],
            )
        return content

    def _parse_report_content(
        self, content: str, *, request_id: Optional[str]
    ) -> SoulmateReportV1:
        """
        Parses and validates the provider's JSON output against the ReportV1 contract.

        A response that is not valid JSON, or that violates the ReportV1 schema /
        plain-text content policy, is a permanent failure: the output must never
        reach persistence unvalidated (SP-702 re-validates as the final guard).
        """
        candidate = _strip_code_fences(content)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ReportProviderError(
                "Report provider output is not valid JSON.",
                retryable=False,
                provider_request_id=request_id,
                internal_error=f"{type(exc).__name__}: {exc}; head={candidate[:500]!r}",
            ) from exc
        try:
            return parse_soulmate_report_v1(data)
        except Exception as exc:
            raise ReportProviderError(
                "Report provider output does not conform to the ReportV1 contract.",
                retryable=False,
                provider_request_id=request_id,
                internal_error=str(exc)[:2000],
            ) from exc


# ---------------------------------------------------------------------------
# Factory (pluggable switch; default = disabled)
# ---------------------------------------------------------------------------


def build_report_provider(
    provider_code: Optional[str] = None,
    **openai_kwargs: Any,
) -> Any:
    """
    Builds the configured `SoulmateReportGenerator` (DEV-SPEC §13.3, REPORT-01).

    - unset/empty `SOULMATE_REPORT_PROVIDER` (the default) → `ReportGenerationDisabledError`:
      production generation stays off until REPORT-01/REPORT-02 close;
    - 'mock' → `MockReportProvider` (clearly non-production test content);
    - 'openai_compatible' → `OpenAICompatibleReportProvider` (owner-directed endpoint);
    - anything else → permanent `ReportProviderError` (misconfiguration).
    """
    code = (provider_code or settings.soulmate_report_provider or "").strip().lower()
    if not code:
        raise ReportGenerationDisabledError()
    if code == REPORT_PROVIDER_MOCK:
        return MockReportProvider()
    if code == REPORT_PROVIDER_OPENAI_COMPATIBLE:
        return OpenAICompatibleReportProvider(**openai_kwargs)
    raise ReportProviderError(
        f"Unknown report provider '{code}'; supported: '{REPORT_PROVIDER_MOCK}', "
        f"'{REPORT_PROVIDER_OPENAI_COMPATIBLE}'.",
        retryable=False,
        details={"provider_code": code},
    )
