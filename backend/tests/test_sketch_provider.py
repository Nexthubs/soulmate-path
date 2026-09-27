"""
Tests for the OpenAI image provider adapter (DEV-SPEC §11, §22, §25; SP-602).

Covers the SP-602 acceptance criteria without live provider calls:
- provider call isolated behind the app-owned SketchImageProvider interface;
- configured model defaults to the spec target `gpt-image-2`;
- the API key never leaks into results, errors, or request bodies;
- provider error categories map to domain errors (retryable vs permanent, §11.6);
- tracing metadata (request id, created, duration) is recorded safely.
"""

import base64
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.core.errors import SoulmateErrorCode
from app.soulmate.domain.sketch_models import (
    SketchGenerationResult,
    SketchImageProvider,
    SketchProviderError,
)
from app.soulmate.services.openai_image_provider import (
    OPENAI_DEFAULT_BASE_URL,
    OpenAIImageProvider,
    images_generations_url,
)

FAKE_API_KEY = "sk-test-secret-key-12345-do-not-leak"
FAKE_IMAGE_BYTES = b"fake-webp-image-bytes-0xdeadbeef"
GEN_URL = images_generations_url(OPENAI_DEFAULT_BASE_URL)


def _b64_payload() -> str:
    return base64.b64encode(FAKE_IMAGE_BYTES).decode("ascii")


def _make_provider(captured: dict, handler) -> OpenAIImageProvider:
    transport = httpx.MockTransport(handler)
    return OpenAIImageProvider(
        api_key=FAKE_API_KEY,
        http_client=httpx.AsyncClient(transport=transport),
    )


@pytest.mark.asyncio
async def test_adapter_satisfies_app_owned_interface():
    provider = OpenAIImageProvider(api_key=FAKE_API_KEY)
    assert isinstance(provider, SketchImageProvider)
    assert provider.provider_name == "openai"
    await provider.close()


@pytest.mark.asyncio
async def test_swappable_fake_provider_satisfies_interface():
    """Business code (SP-603) must be able to program against the interface, not OpenAI."""

    class FakeProvider:
        provider_name = "fake"

        async def generate_image(self, prompt: str) -> SketchGenerationResult:
            return SketchGenerationResult(
                provider="fake",
                model="fake-model",
                image_bytes=b"x",
                image_format="webp",
                size="1024x1536",
                quality="medium",
                duration_ms=1,
            )

    assert isinstance(FakeProvider(), SketchImageProvider)


def test_images_generations_url_strips_trailing_slash():
    assert images_generations_url("https://gw.test/v1") == "https://gw.test/v1/images/generations"
    assert images_generations_url("https://gw.test/v1/") == "https://gw.test/v1/images/generations"


@pytest.mark.asyncio
async def test_custom_compatible_endpoint_base_url_is_used():
    """OPENAI_BASE_URL must target any OpenAI-compatible gateway's API root."""
    captured: dict = {}
    gateway_root = "https://gw.internal.test/v1"

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": _b64_payload()}]})

    transport = httpx.MockTransport(handler)
    provider = OpenAIImageProvider(
        api_key=FAKE_API_KEY,
        base_url=gateway_root + "/",  # trailing slash must be normalized away
        http_client=httpx.AsyncClient(transport=transport),
    )
    result = await provider.generate_image("portrait prompt")
    await provider.close()

    assert captured["url"] == images_generations_url(gateway_root)
    assert result.provider_request_id is None  # gateway sent no x-request-id; tolerated


@pytest.mark.asyncio
async def test_request_uses_config_defaults_and_spec_target_model(monkeypatch):
    # Hermetic: pin the §22 defaults explicitly (a real .env may exist in the repo
    # root when pytest runs); the test's intent is "the adapter consumes config".
    monkeypatch.setattr(settings, "openai_base_url", OPENAI_DEFAULT_BASE_URL)
    monkeypatch.setattr(settings, "soulmate_image_model", "gpt-image-2")
    monkeypatch.setattr(settings, "soulmate_image_size", "1024x1536")
    monkeypatch.setattr(settings, "soulmate_image_quality", "medium")
    monkeypatch.setattr(settings, "soulmate_image_format", "webp")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={"created": 1727300000, "data": [{"b64_json": _b64_payload()}]},
            headers={"x-request-id": "req_meta_1"},
        )

    provider = _make_provider(captured, handler)
    result = await provider.generate_image("A pencil portrait of {nothing}.")
    await provider.close()

    assert captured["url"] == images_generations_url(settings.openai_base_url)
    # Settings defaults (§22): model defaults to the spec target gpt-image-2.
    assert provider.model == settings.soulmate_image_model == "gpt-image-2"
    assert provider.size == settings.soulmate_image_size == "1024x1536"
    assert provider.quality == settings.soulmate_image_quality == "medium"
    assert provider.output_format == settings.soulmate_image_format == "webp"

    import json

    sent = json.loads(captured["body"])
    assert sent["model"] == "gpt-image-2"
    assert sent["size"] == "1024x1536"
    assert sent["quality"] == "medium"
    assert sent["output_format"] == "webp"
    assert sent["n"] == 1
    assert sent["prompt"] == "A pencil portrait of {nothing}."
    # API key travels in the Authorization header only — never in the body.
    assert FAKE_API_KEY not in captured["body"].decode()


@pytest.mark.asyncio
async def test_happy_path_returns_bytes_and_tracing_metadata(monkeypatch):
    # Hermetic: pin the §22 image settings (a real .env may configure a different
    # format — e.g. png to match a compatible gateway that ignores output_format).
    monkeypatch.setattr(settings, "soulmate_image_model", "gpt-image-2")
    monkeypatch.setattr(settings, "soulmate_image_size", "1024x1536")
    monkeypatch.setattr(settings, "soulmate_image_quality", "medium")
    monkeypatch.setattr(settings, "soulmate_image_format", "webp")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "created": 1727300000,
                "data": [{"b64_json": _b64_payload()}],
            },
            headers={"x-request-id": "req_trace_42"},
        )

    provider = _make_provider(captured, handler)
    result = await provider.generate_image("portrait prompt")
    await provider.close()

    assert result.provider == "openai"
    assert result.model == "gpt-image-2"
    assert result.image_bytes == FAKE_IMAGE_BYTES
    assert result.image_format == "webp"
    assert result.size == "1024x1536"
    assert result.quality == "medium"
    assert result.provider_request_id == "req_trace_42"
    assert result.provider_created_at == datetime.fromtimestamp(1727300000, tz=timezone.utc)
    assert result.duration_ms >= 0
    assert result.generated_at.tzinfo is not None
    assert result.source_url is None


@pytest.mark.asyncio
async def test_api_key_never_leaks_into_result_surfaces():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": _b64_payload()}]})

    provider = _make_provider({}, handler)
    result = await provider.generate_image("portrait prompt")
    await provider.close()

    serialized = str(result.model_dump())
    assert FAKE_API_KEY not in serialized
    assert "Bearer" not in serialized


@pytest.mark.parametrize(
    "status,expected_retryable,expected_error_code,expected_provider_code",
    [
        (429, True, SoulmateErrorCode.PROVIDER_UNAVAILABLE, "429"),
        (500, True, SoulmateErrorCode.PROVIDER_UNAVAILABLE, "500"),
        (502, True, SoulmateErrorCode.PROVIDER_UNAVAILABLE, "502"),
        (503, True, SoulmateErrorCode.PROVIDER_UNAVAILABLE, "503"),
        (504, True, SoulmateErrorCode.PROVIDER_UNAVAILABLE, "504"),
        (400, False, SoulmateErrorCode.GENERATION_FAILED, "400"),
        (401, False, SoulmateErrorCode.GENERATION_FAILED, "401"),
        (403, False, SoulmateErrorCode.GENERATION_FAILED, "403"),
        (404, False, SoulmateErrorCode.GENERATION_FAILED, "404"),
        (422, False, SoulmateErrorCode.GENERATION_FAILED, "422"),
    ],
)
@pytest.mark.asyncio
async def test_http_error_categories_map_to_domain_errors(
    status, expected_retryable, expected_error_code, expected_provider_code
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": {"message": "provider said no", "type": "invalid_request_error", "code": "x"}},
            headers={"x-request-id": f"req_{status}"},
        )

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    err = exc.value
    assert err.retryable is expected_retryable
    assert err.error_code is expected_error_code
    assert err.provider_code == expected_provider_code
    assert err.provider_request_id == f"req_{status}"
    assert err.status_code == (503 if expected_retryable else 502)
    assert err.details["http_status"] == status
    assert err.details["provider_error_type"] == "invalid_request_error"
    # Secrets never surface in error payloads.
    assert FAKE_API_KEY not in str(err.message)
    assert FAKE_API_KEY not in str(err.details)


@pytest.mark.asyncio
async def test_timeout_maps_to_retryable_domain_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is True
    assert exc.value.error_code is SoulmateErrorCode.PROVIDER_UNAVAILABLE
    assert exc.value.provider_code == "TIMEOUT"


@pytest.mark.asyncio
async def test_transport_error_maps_to_retryable_domain_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is True
    assert exc.value.provider_code == "NETWORK_ERROR"


@pytest.mark.asyncio
async def test_content_policy_violation_is_permanent_with_provider_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Your request was rejected by the safety system.",
                    "type": "invalid_request_error",
                    "code": "content_policy_violation",
                }
            },
        )

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is False
    assert exc.value.details["provider_error_code"] == "content_policy_violation"


@pytest.mark.asyncio
async def test_missing_api_key_fails_fast_without_http_call(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider must not be called without an API key")

    transport = httpx.MockTransport(handler)
    provider = OpenAIImageProvider(api_key=None, http_client=httpx.AsyncClient(transport=transport))
    try:
        with pytest.raises(SketchProviderError) as exc:
            await provider.generate_image("portrait prompt")
    finally:
        await provider.close()

    assert exc.value.retryable is False
    assert exc.value.provider_code == "401"


@pytest.mark.asyncio
async def test_missing_api_key_via_settings(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    provider = OpenAIImageProvider(http_client=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("no call expected"))
    )))
    try:
        with pytest.raises(SketchProviderError):
            await provider.generate_image("portrait prompt")
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_empty_prompt_refused_without_http_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider must not be called with an empty prompt")

    provider = OpenAIImageProvider(
        api_key=FAKE_API_KEY,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(SketchProviderError) as exc:
            await provider.generate_image("   ")
    finally:
        await provider.close()

    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_url_fallback_downloads_bytes_immediately():
    """ASSET-01: temporary provider URLs are fetched to bytes, kept for tracing only."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/images/generations"):
            return httpx.Response(
                200,
                json={"created": 1, "data": [{"url": "https://tmp.openai.test/img.webp"}]},
                headers={"x-request-id": "req_url_1"},
            )
        return httpx.Response(200, content=FAKE_IMAGE_BYTES)

    provider = _make_provider({}, handler)
    result = await provider.generate_image("portrait prompt")
    await provider.close()

    assert result.image_bytes == FAKE_IMAGE_BYTES
    assert result.source_url == "https://tmp.openai.test/img.webp"
    assert result.provider_request_id == "req_url_1"


@pytest.mark.asyncio
async def test_response_without_image_data_is_permanent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1, "data": []})

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_response_with_neither_b64_nor_url_is_permanent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1, "data": [{"revised_prompt": "x"}]})

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_undecodable_b64_is_permanent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": "!!!not-base64!!!"}]})

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_url_download_failure_is_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/images/generations"):
            return httpx.Response(200, json={"created": 1, "data": [{"url": "https://tmp.openai.test/img.webp"}]})
        return httpx.Response(503, text="slow down")

    provider = _make_provider({}, handler)
    with pytest.raises(SketchProviderError) as exc:
        await provider.generate_image("portrait prompt")
    await provider.close()

    assert exc.value.retryable is True
