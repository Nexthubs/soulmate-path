"""Automated tests for error codes, request correlation, and observability (SP-005)."""

import json
import logging
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from starlette.testclient import TestClient

from app.main import app
from app.core.errors import (
    SoulmateErrorCode,
    SoulmateAppError,
    ValidationError,
    InvalidFlowStateError,
    PaymentPendingError,
    LockedAssetError,
    GenerationFailedError,
    ForbiddenOwnershipError,
    NotFoundError,
    ProviderUnavailableError,
    ProviderName,
    OpenAIErrorCode,
    PayPalErrorCode,
    map_provider_error,
)
from app.core.middleware import RequestCorrelationMiddleware
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import (
    StructuredJsonFormatter,
    log_event,
    request_id_ctx,
    session_id_ctx,
)

# Test router for verifying domain exceptions and unhandled errors
error_test_router = APIRouter(prefix="/test/errors", tags=["TestErrors"])


@error_test_router.get("/validation")
def raise_validation():
    raise ValidationError("Option code is invalid for question q02.", details={"field": "option_code"})


@error_test_router.get("/invalid-flow")
def raise_invalid_flow():
    raise InvalidFlowStateError("Cannot answer q05 before completing q04.")


@error_test_router.get("/payment-pending")
def raise_payment_pending():
    raise PaymentPendingError()


@error_test_router.get("/locked-asset")
def raise_locked_asset():
    raise LockedAssetError("Portrait unlocked in 12 hours.")


@error_test_router.get("/generation-failed")
def raise_generation_failed():
    raise GenerationFailedError()


@error_test_router.get("/forbidden-ownership")
def raise_forbidden_ownership():
    raise ForbiddenOwnershipError("Session does not belong to caller.")


@error_test_router.get("/not-found")
def raise_not_found():
    raise NotFoundError("Session not found.")


@error_test_router.get("/provider-unavailable")
def raise_provider_unavailable():
    raise ProviderUnavailableError()


@error_test_router.get("/provider-openai-429")
def raise_provider_openai_429():
    raise map_provider_error(
        provider="openai",
        raw_code="429_RATE_LIMIT",
        raw_message="Rate limit exceeded for api_key sk-live-SECRETKEY998811",
        provider_request_id="req-openai-xyz",
    )


@error_test_router.get("/provider-paypal-500")
def raise_provider_paypal_500():
    raise map_provider_error(
        provider="paypal",
        raw_code="500_SYSTEM_ERROR",
        raw_message="PayPal internal gateway failed with secret token secret_token_123",
        provider_request_id="paypal-dbg-id-456",
    )


@error_test_router.get("/unhandled-crash")
def raise_unhandled_crash():
    # Emulate internal crash leaking sensitive DB connection string
    raise RuntimeError("Internal DB connection error: postgresql://admin:super_secret_db_pass@db.internal:5432")


class BodySchema(BaseModel):
    value: str
    duration_ms: int


@error_test_router.post("/schema-validation")
def post_schema_validation(body: BodySchema):
    return {"status": "ok", "value": body.value}


# ------------------------------------------------------------------------------
# Isolated Test Application (Fix M-2: Do not pollute production app)
# ------------------------------------------------------------------------------

@pytest.fixture
def error_app() -> FastAPI:
    """Isolated test application with error handling and test routes, leaving production app pristine."""
    isolated = FastAPI(title="Error Test App")
    isolated.add_middleware(RequestCorrelationMiddleware)
    register_exception_handlers(isolated)
    isolated.include_router(error_test_router)
    return isolated


def test_production_app_is_not_polluted_by_test_routes():
    """Verify production app instance is not modified by test routes (M-2 fix)."""
    route_paths = [getattr(r, "path", getattr(r, "prefix", "")) for r in app.routes]
    assert not any(p.startswith("/test/errors") for p in route_paths)


def test_request_id_generated_when_missing():
    """Verify incoming request without X-Request-ID gets assigned a new UUID and returns it in headers."""
    with TestClient(app) as client:
        response = client.get("/api/soulmate/health")
        assert response.status_code == 200
        req_id = response.headers.get("X-Request-ID")
        assert req_id is not None
        assert len(req_id) >= 16


def test_request_id_preserved_when_provided():
    """Verify incoming client X-Request-ID is preserved and echoed back."""
    custom_id = "client-assigned-req-9999"
    with TestClient(app) as client:
        response = client.get("/api/soulmate/health", headers={"X-Request-ID": custom_id})
        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == custom_id


@pytest.mark.parametrize(
    "endpoint,expected_status,expected_code",
    [
        ("/test/errors/validation", 400, SoulmateErrorCode.VALIDATION_ERROR.value),
        ("/test/errors/invalid-flow", 409, SoulmateErrorCode.INVALID_FLOW_STATE.value),
        ("/test/errors/payment-pending", 409, SoulmateErrorCode.PAYMENT_PENDING.value),
        ("/test/errors/locked-asset", 423, SoulmateErrorCode.LOCKED_ASSET.value),
        ("/test/errors/generation-failed", 502, SoulmateErrorCode.GENERATION_FAILED.value),
        ("/test/errors/forbidden-ownership", 403, SoulmateErrorCode.FORBIDDEN_OWNERSHIP.value),
        ("/test/errors/not-found", 404, SoulmateErrorCode.NOT_FOUND.value),
        ("/test/errors/provider-unavailable", 503, SoulmateErrorCode.PROVIDER_UNAVAILABLE.value),
    ],
)
def test_all_domain_errors_return_standard_machine_readable_payload(endpoint, expected_status, expected_code, error_app):
    """Acceptance criterion: API errors are machine-readable enough for frontend states."""
    custom_req_id = f"test-req-{expected_code.lower()}"
    with TestClient(error_app) as client:
        response = client.get(endpoint, headers={"X-Request-ID": custom_req_id})
        assert response.status_code == expected_status
        assert response.headers.get("X-Request-ID") == custom_req_id

        data = response.json()
        assert data["error_code"] == expected_code
        assert "message" in data
        assert isinstance(data["message"], str)
        assert data["request_id"] == custom_req_id
        assert "details" in data


def test_provider_raw_errors_never_reach_clients(error_app):
    """Acceptance criterion: provider raw errors/secrets never reach clients (DEV-SPEC §19.3)."""
    with TestClient(error_app) as client:
        # 1. OpenAI 429 rate limit
        res_openai = client.get("/test/errors/provider-openai-429")
        assert res_openai.status_code == 503
        data_openai = res_openai.json()
        assert data_openai["error_code"] == SoulmateErrorCode.PROVIDER_UNAVAILABLE.value
        # Safe message from DEV-SPEC §19.3
        assert data_openai["message"] == "Your portrait is taking a little longer than expected."
        # Verify NO secret or raw code leaked
        res_text = res_openai.text
        assert "sk-live" not in res_text
        assert "SECRETKEY" not in res_text
        assert "429_RATE_LIMIT" not in res_text

        # 2. PayPal 500 server error
        res_paypal = client.get("/test/errors/provider-paypal-500")
        assert res_paypal.status_code == 409
        data_paypal = res_paypal.json()
        assert data_paypal["error_code"] == SoulmateErrorCode.PAYMENT_PENDING.value
        # Safe message from DEV-SPEC §19.3
        assert data_paypal["message"] == "We’re still confirming your payment."
        # Verify NO secret or internal trace leaked
        res_text_paypal = res_paypal.text
        assert "secret_token_123" not in res_text_paypal
        assert "PayPal internal gateway" not in res_text_paypal


def test_map_provider_error_with_typed_enums():
    """Verify map_provider_error accepts typed ProviderName, OpenAIErrorCode, PayPalErrorCode enums (L-3 fix)."""
    err_openai = map_provider_error(
        provider=ProviderName.OPENAI,
        raw_code=OpenAIErrorCode.RATE_LIMIT_EXCEEDED,
        raw_message="Exceeded tokens per min",
        provider_request_id="req-openai-enum-test",
    )
    assert err_openai.status_code == 503
    assert err_openai.error_code == SoulmateErrorCode.PROVIDER_UNAVAILABLE
    assert err_openai.message == "Your portrait is taking a little longer than expected."
    assert err_openai.provider_request_id == "req-openai-enum-test"

    err_paypal = map_provider_error(
        provider=ProviderName.PAYPAL,
        raw_code=PayPalErrorCode.INTERNAL_SERVER_ERROR,
        raw_message="Internal crash in gateway",
    )
    assert err_paypal.status_code == 409
    assert err_paypal.error_code == SoulmateErrorCode.PAYMENT_PENDING
    assert err_paypal.message == "We’re still confirming your payment."


def test_unhandled_exception_sanitizes_internal_secrets(error_app):
    """Verify internal unhandled 500 error sanitizes traceback and secrets."""
    with TestClient(error_app, raise_server_exceptions=False) as client:
        response = client.get("/test/errors/unhandled-crash")
        assert response.status_code == 500
        data = response.json()
        assert data["error_code"] == SoulmateErrorCode.INTERNAL_SERVER_ERROR.value
        assert data["message"] == "An unexpected server error occurred. Please try again later."
        assert "super_secret_db_pass" not in response.text
        assert "RuntimeError" not in response.text
        assert response.headers.get("X-Request-ID") == data["request_id"]


def test_schema_validation_error_returns_standard_shape(error_app):
    """Verify FastAPI Pydantic schema validation failures are normalized to standard shape."""
    with TestClient(error_app) as client:
        # Missing required duration_ms and invalid type for value
        response = client.post("/test/errors/schema-validation", json={"value": 12345})
        assert response.status_code == 422
        data = response.json()
        assert data["error_code"] == SoulmateErrorCode.VALIDATION_ERROR.value
        assert "errors" in data["details"]
        assert "request_id" in data


def test_structured_json_logging_fields():
    """Acceptance criterion: logs include correlation/request IDs and DEV-SPEC §19.1 required fields."""
    formatter = StructuredJsonFormatter()

    record = logging.LogRecord(
        name="soulmate.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Test event occurred",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-12345"
    record.session_id = "sess-67890"
    record.event_type = "quiz_step_completed"
    record.error_code = None
    record.latency_ms = 45.2

    output = formatter.format(record)
    parsed = json.loads(output)

    # Verify DEV-SPEC §19.1 fields
    assert parsed["request_id"] == "req-12345"
    assert parsed["session_id"] == "sess-67890"
    assert parsed["event_type"] == "quiz_step_completed"
    assert parsed["error_code"] is None
    assert parsed["latency_ms"] == 45.2
    assert "user_id" in parsed
    assert "paypal_subscription_id" in parsed
    assert "artifact_id" in parsed
    assert "job_id" in parsed
    assert "provider_request_id" in parsed
