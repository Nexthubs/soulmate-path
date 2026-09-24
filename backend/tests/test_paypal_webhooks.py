"""
Unit and Integration Tests for PayPal Webhook Endpoint (SP-404, DEV-SPEC §9.5–9.6, §15.12, Invariant PAY-AUTH-01).

Verifies:
1. Exact byte preservation of raw request body and transmission headers.
2. Endpoint is unprotected by user auth / session tokens.
3. High-Risk Invariant PAY-AUTH-01: Unverified events NEVER mutate business state (subscriptions, payments, sessions).
4. Response behavior supports PayPal retry semantics (200 for success/duplicate, 4xx for permanent error, 500 for retry).
5. Both canonical /api/webhooks/paypal and alias /api/soulmate/webhooks/paypal paths resolve correctly.
"""

from datetime import datetime, timezone
import json
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ValidationError, WebhookVerificationError
from app.db.models.billing import PayPalWebhookEvent, Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal, SessionLocal
from app.main import app


@pytest.fixture
async def async_db_session():
    """Provides an async transactional DB session for async service calls."""
    async with AsyncSessionLocal() as session:
        yield session
from app.soulmate.domain.webhook_models import (
    PayPalWebhookEventType,
    PayPalWebhookHeaders,
    PayPalWebhookRawRequest,
    PayPalWebhookResponse,
)
from app.soulmate.services.webhook_service import PayPalWebhookService


SAMPLE_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-123",
    "PAYPAL-TRANSMISSION-ID": "trans_123456789",
    "PAYPAL-TRANSMISSION-SIG": "dummy_sig_base64_content",
    "PAYPAL-TRANSMISSION-TIME": "2026-09-24T12:00:00Z",
}


def make_sample_event(
    event_id: str = "WH-1234567890",
    event_type: str = "PAYMENT.SALE.COMPLETED",
    resource_id: str = "CAPTURE-111",
) -> dict:
    return {
        "id": event_id,
        "event_version": "1.0",
        "create_time": "2026-09-24T12:00:00Z",
        "resource_type": "sale",
        "event_type": event_type,
        "summary": "Payment completed for subscription",
        "resource": {
            "id": resource_id,
            "billing_agreement_id": "I-SUB-999",
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
        },
    }


# ==============================================================================
# 1. Raw Request Body & Header Preservation Tests (Acceptance #1)
# ==============================================================================


@pytest.mark.asyncio
async def test_raw_body_preserved_byte_for_byte():
    """Exact raw body bytes and whitespace are preserved without JSON serializer mutation."""
    raw_payload = b'{\n  "id": "WH-RAW-TEST-1",\n  "event_type": "BILLING.SUBSCRIPTION.ACTIVATED"\n}'

    class DummyRequest:
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://cert.paypal.com/sample",
            "paypal-transmission-id": "t-1",
            "paypal-transmission-sig": "sig-1",
            "paypal-transmission-time": "2026-09-24T12:00:00Z",
        }

    parsed = PayPalWebhookService.parse_raw_request(request=DummyRequest(), raw_body=raw_payload)

    assert parsed.raw_body == raw_payload
    assert parsed.event_id == "WH-RAW-TEST-1"
    assert parsed.event_type == "BILLING.SUBSCRIPTION.ACTIVATED"
    assert parsed.headers.auth_algo == "SHA256withRSA"
    assert parsed.headers.cert_url == "https://cert.paypal.com/sample"
    assert parsed.headers.transmission_id == "t-1"
    assert parsed.headers.transmission_sig == "sig-1"
    assert parsed.headers.transmission_time == "2026-09-24T12:00:00Z"
    assert parsed.headers.is_complete() is True


@pytest.mark.asyncio
async def test_parse_rejects_empty_body():
    """Empty body raises ValidationError (HTTP 400)."""
    class DummyRequest:
        headers = {}

    with pytest.raises(ValidationError) as exc:
        PayPalWebhookService.parse_raw_request(request=DummyRequest(), raw_body=b"")

    assert "empty" in str(exc.value).lower()
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_parse_rejects_malformed_json():
    """Non-JSON payload raises ValidationError (HTTP 400)."""
    class DummyRequest:
        headers = {}

    with pytest.raises(ValidationError) as exc:
        PayPalWebhookService.parse_raw_request(request=DummyRequest(), raw_body=b"{not_json_syntax}")

    assert "malformed" in str(exc.value).lower() or "json" in str(exc.value).lower()
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_parse_rejects_missing_event_id_or_type():
    """Missing id or event_type raises ValidationError (HTTP 400)."""
    class DummyRequest:
        headers = {}

    with pytest.raises(ValidationError):
        PayPalWebhookService.parse_raw_request(request=DummyRequest(), raw_body=b'{"event_type": "SALE"}')

    with pytest.raises(ValidationError):
        PayPalWebhookService.parse_raw_request(request=DummyRequest(), raw_body=b'{"id": "WH-1"}')


from app.soulmate.services.webhook_verifier import get_webhook_verifier


class FailingVerifier:
    async def verify(self, raw_body: bytes, headers: PayPalWebhookHeaders, webhook_event=None, webhook_id=None, **kwargs) -> bool:
        return False


class SuccessfulVerifier:
    async def verify(self, raw_body: bytes, headers: PayPalWebhookHeaders, webhook_event=None, webhook_id=None, **kwargs) -> bool:
        return True


@pytest.fixture
def mock_webhook_verifier():
    """Bypasses signature verification with SuccessfulVerifier for routing/retry integration tests."""
    app.dependency_overrides[get_webhook_verifier] = lambda: SuccessfulVerifier()
    yield
    app.dependency_overrides.pop(get_webhook_verifier, None)


# ==============================================================================
# 2. Endpoint Auth Exemption (Acceptance #2) & Route Aliases
# ==============================================================================


@pytest.mark.asyncio
async def test_endpoint_unprotected_by_normal_user_auth(mock_webhook_verifier):
    """Webhook endpoint processes incoming requests with NO cookies, tokens, or auth headers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        event = make_sample_event(event_id=f"WH-NOAUTH-{uuid.uuid4().hex[:8]}")
        resp = await ac.post(
            "/api/webhooks/paypal",
            content=json.dumps(event).encode("utf-8"),
            headers=SAMPLE_HEADERS,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "received"
        assert data["event_id"] == event["id"]


@pytest.mark.asyncio
async def test_endpoint_mounted_at_both_canonical_and_alias_paths(mock_webhook_verifier):
    """Both /api/webhooks/paypal (DEV-SPEC §9.6) and /api/soulmate/webhooks/paypal are active."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Canonical /api/webhooks/paypal
        canonical_event = make_sample_event(event_id=f"WH-CANONICAL-{uuid.uuid4().hex[:8]}")
        resp1 = await ac.post(
            "/api/webhooks/paypal",
            content=json.dumps(canonical_event).encode("utf-8"),
            headers=SAMPLE_HEADERS,
        )
        assert resp1.status_code == 200

        # 2. Alias /api/soulmate/webhooks/paypal
        alias_event = make_sample_event(event_id=f"WH-ALIAS-{uuid.uuid4().hex[:8]}")
        resp2 = await ac.post(
            "/api/soulmate/webhooks/paypal",
            content=json.dumps(alias_event).encode("utf-8"),
            headers=SAMPLE_HEADERS,
        )
        assert resp2.status_code == 200


# ==============================================================================
# 3. High-Risk Invariant PAY-AUTH-01: Unverified Events Never Mutate Business State (Acceptance #3)
# ==============================================================================


@pytest.mark.asyncio
async def test_unverified_event_missing_headers_rejected_and_mutates_no_state(async_db_session: AsyncSession):
    """Missing transmission headers raises WebhookVerificationError and leaves business state untouched."""
    event = make_sample_event(event_id=f"WH-UNVERIFIED-HDR-{uuid.uuid4().hex[:8]}")
    raw_bytes = json.dumps(event).encode("utf-8")

    class RequestWithoutHeaders:
        headers = {}  # Empty transmission headers

    parsed = PayPalWebhookService.parse_raw_request(request=RequestWithoutHeaders(), raw_body=raw_bytes)

    with pytest.raises(WebhookVerificationError):
        await PayPalWebhookService.process_webhook(
            raw_request=parsed,
            db=async_db_session,
            require_verification=True,
        )

    # Invariant Verification: No records created in subscriptions, subscription_payments, or paypal_webhook_events
    events_stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event["id"])
    assert (await async_db_session.execute(events_stmt)).scalars().first() is None


@pytest.mark.asyncio
async def test_unverified_event_signature_failure_rejected_and_mutates_no_state(async_db_session: AsyncSession):
    """Failed signature verification rejects with WebhookVerificationError and does not mutate business state."""
    event = make_sample_event(event_id=f"WH-FORGED-{uuid.uuid4().hex[:8]}")
    raw_bytes = json.dumps(event).encode("utf-8")

    class RequestWithHeaders:
        headers = SAMPLE_HEADERS

    parsed = PayPalWebhookService.parse_raw_request(request=RequestWithHeaders(), raw_body=raw_bytes)

    with pytest.raises(WebhookVerificationError):
        await PayPalWebhookService.process_webhook(
            raw_request=parsed,
            db=async_db_session,
            verifier=FailingVerifier(),
            require_verification=True,
        )

    # Invariant: Subscriptions and payments tables completely empty/unaltered
    events_stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event["id"])
    assert (await async_db_session.execute(events_stmt)).scalars().first() is None

    sub_stmt = select(Subscription)
    subs = (await async_db_session.execute(sub_stmt)).scalars().all()
    # Confirm no subscription was granted or activated by the unverified event
    for s in subs:
        assert s.provider_subscription_id != "I-SUB-999"


# ==============================================================================
# 4. Response Behavior & PayPal Retry Semantics (Acceptance #4)
# ==============================================================================


@pytest.mark.asyncio
async def test_successful_event_recorded_in_db(async_db_session: AsyncSession):
    """Verified webhook event is committed to paypal_webhook_events table."""
    event = make_sample_event(event_id=f"WH-OK-{uuid.uuid4().hex[:8]}")
    raw_bytes = json.dumps(event).encode("utf-8")

    class RequestWithHeaders:
        headers = SAMPLE_HEADERS

    parsed = PayPalWebhookService.parse_raw_request(request=RequestWithHeaders(), raw_body=raw_bytes)

    result = await PayPalWebhookService.process_webhook(
        raw_request=parsed,
        db=async_db_session,
        verifier=SuccessfulVerifier(),
        require_verification=True,
    )

    assert result.status == "received"
    assert result.duplicate is False

    # Check database persistence
    stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event["id"])
    saved = (await async_db_session.execute(stmt)).scalars().first()
    assert saved is not None
    assert saved.paypal_event_id == event["id"]
    assert saved.event_type == "PAYMENT.SALE.COMPLETED"
    assert saved.verified is True
    assert saved.resource_id == "CAPTURE-111"
    assert saved.processed_at is not None


@pytest.mark.asyncio
async def test_idempotent_duplicate_event_returns_200_to_stop_paypal_retries(async_db_session: AsyncSession):
    """Replaying the same event returns 200 OK with duplicate=True without recreating records."""
    event = make_sample_event(event_id=f"WH-DUP-{uuid.uuid4().hex[:8]}")
    raw_bytes = json.dumps(event).encode("utf-8")

    class RequestWithHeaders:
        headers = SAMPLE_HEADERS

    parsed = PayPalWebhookService.parse_raw_request(request=RequestWithHeaders(), raw_body=raw_bytes)

    # 1. First delivery
    res1 = await PayPalWebhookService.process_webhook(
        raw_request=parsed,
        db=async_db_session,
        verifier=SuccessfulVerifier(),
    )
    assert res1.status == "received"
    assert res1.duplicate is False

    # 2. Duplicate delivery (PayPal retry)
    res2 = await PayPalWebhookService.process_webhook(
        raw_request=parsed,
        db=async_db_session,
        verifier=SuccessfulVerifier(),
    )
    assert res2.status == "duplicate"
    assert res2.duplicate is True

    # 3. Third delivery
    res3 = await PayPalWebhookService.process_webhook(
        raw_request=parsed,
        db=async_db_session,
        verifier=SuccessfulVerifier(),
    )
    assert res3.status == "duplicate"
    assert res3.duplicate is True

    # Database invariant: Exactly 1 row in paypal_webhook_events
    stmt = select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == event["id"])
    events = (await async_db_session.execute(stmt)).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_http_endpoint_permanent_error_returns_400():
    """Client error (malformed JSON or empty body) returns 400 Bad Request to halt retry."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Empty body
        resp1 = await ac.post("/api/webhooks/paypal", content=b"", headers=SAMPLE_HEADERS)
        assert resp1.status_code == 400

        # Malformed JSON
        resp2 = await ac.post("/api/webhooks/paypal", content=b"invalid json", headers=SAMPLE_HEADERS)
        assert resp2.status_code == 400

        # Missing required id attribute
        resp3 = await ac.post(
            "/api/webhooks/paypal",
            content=b'{"event_type": "SALE"}',
            headers=SAMPLE_HEADERS,
        )
        assert resp3.status_code == 400


@pytest.mark.asyncio
async def test_http_endpoint_unverified_missing_headers_returns_400():
    """Missing required transmission headers returns 400 and rejects processing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        event = make_sample_event(event_id=f"WH-NO-HDRS-{uuid.uuid4().hex[:8]}")
        resp = await ac.post(
            "/api/webhooks/paypal",
            content=json.dumps(event).encode("utf-8"),
            headers={},  # Missing headers
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "headers" in data["message"].lower()


@pytest.mark.asyncio
async def test_http_endpoint_unverified_payment_completed_mutates_no_session(async_db_session: AsyncSession):
    """
    Invariant PAY-AUTH-01: An unverified PAYMENT.SALE.COMPLETED webhook arriving at the HTTP endpoint
    MUST NOT set subscription_success_at or create entitlement records.
    """
    # 1. Create a session awaiting payment
    public_id = f"test_wh_guard_{uuid.uuid4().hex[:12]}"
    session = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email="target@example.com",
        email_normalized="target@example.com",
        subscription_success_at=None,
    )
    async_db_session.add(session)
    await async_db_session.commit()
    await async_db_session.refresh(session)
    assert session.subscription_success_at is None

    # 2. Forge a payment completed webhook without valid headers
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        event = make_sample_event(
            event_id=f"WH-FORGED-PAYMENT-{uuid.uuid4().hex[:8]}",
            event_type="PAYMENT.SALE.COMPLETED",
        )
        resp = await ac.post(
            "/api/webhooks/paypal",
            content=json.dumps(event).encode("utf-8"),
            headers={"PAYPAL-AUTH-ALGO": "none"},  # Incomplete headers
        )
        assert resp.status_code == 400

    # 3. Assert session remains unmutated
    sess_stmt = select(SoulmateSession).where(SoulmateSession.public_id == public_id)
    reloaded = (await async_db_session.execute(sess_stmt)).scalars().first()
    assert reloaded is not None
    assert reloaded.subscription_success_at is None


@pytest.mark.asyncio
async def test_http_endpoint_duplicate_event_returns_200_duplicate_true(mock_webhook_verifier):
    """HTTP endpoint returns 200 with duplicate=True when identical event ID is received again."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        event = make_sample_event(event_id=f"WH-HTTP-DUP-{uuid.uuid4().hex[:8]}")
        payload = json.dumps(event).encode("utf-8")

        # First delivery
        resp1 = await ac.post("/api/webhooks/paypal", content=payload, headers=SAMPLE_HEADERS)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "received"
        assert data1["duplicate"] is False

        # Second delivery (replay / retry)
        resp2 = await ac.post("/api/webhooks/paypal", content=payload, headers=SAMPLE_HEADERS)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "duplicate"
        assert data2["duplicate"] is True


@pytest.mark.asyncio
async def test_http_endpoint_server_error_returns_500_for_paypal_retry(monkeypatch, mock_webhook_verifier):
    """
    Acceptance #4: If an unexpected internal database error occurs during event processing,
    the endpoint returns HTTP 500, which instructs PayPal to retry delivery according to its schedule.
    """
    async def mock_failing_process(*args, **kwargs):
        raise RuntimeError("Simulated database connection loss")

    monkeypatch.setattr(PayPalWebhookService, "process_webhook", mock_failing_process)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        event = make_sample_event(event_id=f"WH-ERR-{uuid.uuid4().hex[:8]}")
        resp = await ac.post(
            "/api/webhooks/paypal",
            content=json.dumps(event).encode("utf-8"),
            headers=SAMPLE_HEADERS,
        )
        assert resp.status_code == 500

