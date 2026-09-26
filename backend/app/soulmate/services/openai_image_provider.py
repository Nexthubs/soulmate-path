"""
OpenAI image provider adapter (DEV-SPEC §11, §22, §25; Decisions: ASSET-01, SP-602).

Implements the app-owned `SketchImageProvider` interface against
`POST /v1/images/generations` (spec target model `gpt-image-2`). All request
parameters come from server configuration (§22); the API key never leaves this
module, is never logged, and never appears in error details or result payloads.
"""

import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.soulmate.domain.sketch_models import (
    SketchGenerationResult,
    SketchProviderError,
    is_retryable_provider_status,
    provider_code_for_status,
)

logger = logging.getLogger(__name__)

OPENAI_IMAGES_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"

_NETWORK_ERROR_CODE = "NETWORK_ERROR"
_TIMEOUT_ERROR_CODE = "TIMEOUT"


class OpenAIImageProvider:
    """
    Async OpenAI images adapter satisfying `SketchImageProvider`.

    Model/size/quality/format default to §22 configuration; explicit constructor
    arguments exist for tests and future per-call overrides only.
    """

    provider_name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        output_format: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 120.0,
    ):
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.soulmate_image_model
        self.size = size or settings.soulmate_image_size
        self.quality = quality or settings.soulmate_image_quality
        self.output_format = output_format or settings.soulmate_image_format
        self.timeout = timeout

        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_http_client = True
        return self._http_client

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_http_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self) -> "OpenAIImageProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # SketchImageProvider interface
    # ------------------------------------------------------------------

    async def generate_image(self, prompt: str) -> SketchGenerationResult:
        """Generate one sketch image for a fully rendered prompt (§12 output)."""
        if not self.api_key or not self.api_key.strip():
            # Permanent until configuration is fixed — retrying cannot help.
            raise SketchProviderError(
                "OPENAI_API_KEY is not configured; sketch generation is unavailable.",
                retryable=False,
                provider_code=provider_code_for_status(401),
            )
        if not isinstance(prompt, str) or not prompt.strip():
            raise SketchProviderError(
                "Sketch prompt is empty; refusing to call the image provider.",
                retryable=False,
                provider_code=provider_code_for_status(400),
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": self.size,
            "quality": self.quality,
            "output_format": self.output_format,
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
                OPENAI_IMAGES_GENERATIONS_URL,
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise self._network_error(
                "OpenAI image generation timed out.",
                code=_TIMEOUT_ERROR_CODE,
                exc=exc,
                started=started,
            ) from exc
        except httpx.TransportError as exc:
            raise self._network_error(
                "Network error communicating with the OpenAI image API.",
                code=_NETWORK_ERROR_CODE,
                exc=exc,
                started=started,
            ) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        request_id = resp.headers.get("x-request-id")

        if resp.status_code != 200:
            raise self._http_error(resp, request_id=request_id)

        body = self._parse_success_body(resp, request_id=request_id)

        created_raw = body.get("created")
        provider_created_at = None
        if isinstance(created_raw, (int, float)):
            provider_created_at = datetime.fromtimestamp(created_raw, tz=timezone.utc)

        return await self._build_result(
            body,
            request_id=request_id,
            duration_ms=duration_ms,
            provider_created_at=provider_created_at,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _network_error(
        self,
        message: str,
        *,
        code: str,
        exc: Exception,
        started: float,
    ) -> SketchProviderError:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "OpenAI image request failed after %sms: %s (%s)",
            duration_ms,
            message,
            type(exc).__name__,
        )
        return SketchProviderError(
            message,
            retryable=True,
            provider_code=code,
            internal_error=f"{type(exc).__name__}: {exc}",
            details={"duration_ms": duration_ms},
        )

    def _http_error(self, resp: httpx.Response, *, request_id: Optional[str]) -> SketchProviderError:
        retryable = is_retryable_provider_status(resp.status_code)
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}

        error_field = body.get("error") if isinstance(body, dict) else None
        provider_type = code = None
        safe_message = "OpenAI image API error"
        if isinstance(error_field, dict):
            provider_type = error_field.get("type")
            code = error_field.get("code")
            raw_message = error_field.get("message")
            if isinstance(raw_message, str) and raw_message.strip():
                safe_message = raw_message.strip()[:300]

        logger.warning(
            "OpenAI image API returned HTTP %s (retryable=%s, type=%s, code=%s, request_id=%s)",
            resp.status_code,
            retryable,
            provider_type,
            code,
            request_id,
        )
        return SketchProviderError(
            f"OpenAI image generation failed (HTTP {resp.status_code}): {safe_message}",
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

    def _parse_success_body(self, resp: httpx.Response, *, request_id: Optional[str]) -> Dict[str, Any]:
        try:
            body = resp.json()
        except Exception as exc:
            raise SketchProviderError(
                "OpenAI image API returned a non-JSON success response.",
                retryable=False,
                provider_code=provider_code_for_status(resp.status_code),
                provider_request_id=request_id,
                internal_error=f"{type(exc).__name__}: {exc}",
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("data"), list) or not body["data"]:
            raise SketchProviderError(
                "OpenAI image API response has no image data.",
                retryable=False,
                provider_code=provider_code_for_status(resp.status_code),
                provider_request_id=request_id,
                internal_error=str(body)[:2000],
            )
        return body

    async def _build_result(
        self,
        body: Dict[str, Any],
        *,
        request_id: Optional[str],
        duration_ms: int,
        provider_created_at: Optional[datetime],
    ) -> SketchGenerationResult:
        first = body["data"][0]
        if not isinstance(first, dict):
            raise SketchProviderError(
                "OpenAI image API response entry is malformed.",
                retryable=False,
                provider_request_id=request_id,
                internal_error=str(first)[:500],
            )

        b64 = first.get("b64_json")
        if isinstance(b64, str) and b64.strip():
            try:
                image_bytes = base64.b64decode(b64, validate=True)
            except Exception as exc:
                raise SketchProviderError(
                    "OpenAI image API returned an undecodable image payload.",
                    retryable=False,
                    provider_request_id=request_id,
                    internal_error=f"{type(exc).__name__}: {exc}",
                ) from exc
            return self._result(
                image_bytes,
                request_id=request_id,
                duration_ms=duration_ms,
                provider_created_at=provider_created_at,
            )

        # ASSET-01: provider URLs are temporary; download the bytes immediately so the
        # interface always yields bytes that can be persisted to owned storage. The
        # URL is kept on the result for tracing only.
        url = first.get("url")
        if isinstance(url, str) and url.strip():
            image_bytes = await self._download(url, request_id=request_id)
            return self._result(
                image_bytes,
                request_id=request_id,
                duration_ms=duration_ms,
                provider_created_at=provider_created_at,
                source_url=url,
            )

        raise SketchProviderError(
            "OpenAI image API response contains neither b64_json nor url.",
            retryable=False,
            provider_request_id=request_id,
            internal_error=str(list(first.keys())),
        )

    def _result(
        self,
        image_bytes: bytes,
        *,
        request_id: Optional[str],
        duration_ms: int,
        provider_created_at: Optional[datetime],
        source_url: Optional[str] = None,
    ) -> SketchGenerationResult:
        return SketchGenerationResult(
            provider=self.provider_name,
            model=self.model,
            image_bytes=image_bytes,
            image_format=self.output_format,
            size=self.size,
            quality=self.quality,
            provider_request_id=request_id,
            provider_created_at=provider_created_at,
            duration_ms=duration_ms,
            source_url=source_url,
        )

    async def _download(self, url: str, *, request_id: Optional[str]) -> bytes:
        """Fetch image bytes from a provider temporary URL (defensive non-b64 path)."""
        client = await self._get_client()
        started = time.monotonic()
        try:
            resp = await client.get(url)
        except httpx.TimeoutException as exc:
            raise self._network_error(
                "Timed out downloading image bytes from the provider URL.",
                code=_TIMEOUT_ERROR_CODE,
                exc=exc,
                started=started,
            ) from exc
        except httpx.TransportError as exc:
            raise self._network_error(
                "Network error downloading image bytes from the provider URL.",
                code=_NETWORK_ERROR_CODE,
                exc=exc,
                started=started,
            ) from exc
        if resp.status_code != 200:
            raise SketchProviderError(
                f"Provider image URL download failed (HTTP {resp.status_code}).",
                retryable=True,
                provider_request_id=request_id,
                details={"http_status": resp.status_code},
                internal_error=resp.text[:500],
            )
        if not resp.content:
            raise SketchProviderError(
                "Provider image URL returned an empty payload.",
                retryable=False,
                provider_request_id=request_id,
            )
        return resp.content
