"""
Unit and Integration Tests for PayPal Webhook Signature Verification (SP-405, DEV-SPEC §9.6, Invariant PAY-AUTH-01).

Acceptance Criteria:
1. Official verification mechanism is used (POST /v1/notifications/verify-webhook-signature).
2. Verification failure is logged safely (no secrets/PII leaked) and rejected (HTTP 400 WebhookVerificationError).
3. Tests include forged/invalid signature paths (malicious cert URL, tampered signatures, incomplete headers, unverified state mutating no business entities).
4. Preserve High-Risk Invariant PAY-AUTH-01 (unverified events NEVER mutate Subscription, SubscriptionPayment, or SoulmateSession).
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import WebhookVerificationError
from app.db.models.billing import PayPalWebhookEvent, Subscription, SubscriptionPayment
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.domain.webhook_models import PayPalWebhookHeaders, PayPalWebhookRawRequest
from app.soulmate.services.paypal_client import PayPalAPIError, PayPalClient
from app.soulmate.services.webhook_verifier import (
    PayPalWebhookVerifier,
    get_webhook_verifier,
    is_valid_paypal_cert_url,
)


@pytest.fixture
async def async_db_session():
    """Provides an async transactional DB session for database checks."""
    async with AsyncSessionLocal() as session:
        yield session


VALID_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-12345",
    "PAYPAL-TRANSMISSION-ID": "trans_123456789",
    "PAYPAL-TRANSMISSION-SIG": "valid_signature_base64_hash",
    "PAYPAL-TRANSMISSION-TIME": "2026-09-24T12:00:00Z",
}


def make_sample_event(
    event_id: str = "WH-VERIF-TEST-1",
    event_type: str = "PAYMENT.SALE.COMPLETED",
    resource_id: str = "CAPTURE-999",
) -> Dict[str, Any]:
    return {
        "id": event_id,
        "event_version": "1.0",
        "create_time": "2026-09-24T12:00:00Z",
        "resource_type": "sale",
        "event_type": event_type,
        "summary": "Payment completed for subscription",
        "resource": {
            "id": resource_id,
            "billing_agreement_id": "I-SUB-VERIF-1",
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
        },
    }


# ==============================================================================
# 1. Cert URL Origin Validation Tests (Defense-in-Depth against SSRF / Spoofing)
# ==============================================================================


@pytest.mark.parametrize(
    "cert_url,expected",
    [
        # Valid official PayPal endpoints
        ("https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1", True),
        ("https://api.paypal.com/v1/notifications/certs/CERT-2", True),
        ("https://notify.paypal.com/cert.pem", True),
        ("https://paypal.com/cert.pem", True),
        ("https://sub.sub2.paypal.com/certs/cert", True),
        # Insecure scheme (HTTP)
        ("http://api.paypal.com/v1/notifications/certs/CERT-1", False),
        ("ftp://api.paypal.com/cert", False),
        # Domain spoofing & phishing attempts
        ("https://evil-hacker.com/cert.pem", False),
        ("https://paypal.com.attacker.com/cert.pem", False),
        ("https://attackerpaypal.com/cert.pem", False),
        ("https://notpaypal.com/cert.pem", False),
        ("https://evil-paypal.com/cert.pem", False),
        # Malicious non-standard port attempts
        ("https://api.paypal.com:8443/cert.pem", False),
        ("https://api.paypal.com:22/cert.pem", False),
        # Malformed / empty inputs
        ("", False),
        ("   ", False),
        (None, False),
        ("not_a_valid_url", False),
    ],
)
def test_cert_url_validation(cert_url: Optional[str], expected: bool):
    assert is_valid_paypal_cert_url(cert_url) == expected


# ==============================================================================
# 2. PayPalClient.verify_webhook_signature Official REST API Tests (Acceptance #1)
# ==============================================================================


@pytest.mark.asyncio
async def test_paypal_client_verify_signature_payload_and_success():
    """PayPalClient calls POST /v1/notifications/verify-webhook-signature with expected payload."""
    client = PayPalClient(client_id="test_id", client_secret="test_secret", environment="sandbox")

    mock_resp = Response(
        status_code=200,
        json={"verification_status": "SUCCESS"},
        request=MagicMock(),
    )

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_resp

        event_payload = make_sample_event(event_id="WH-CLI-1")
        result = await client.verify_webhook_signature(
            auth_algo="SHA256withRSA",
            cert_url="https://api.sandbox.paypal.com/certs/c1",
            transmission_id="trans_abc",
            transmission_sig="sig_xyz",
            transmission_time="2026-09-24T12:00:00Z",
            webhook_id="WH-REG-ID-123",
            webhook_event=event_payload,
        )

        assert result is True
        mock_request.assert_called_once_with(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json_body={
                "auth_algo": "SHA256withRSA",
                "cert_url": "https://api.sandbox.paypal.com/certs/c1",
                "transmission_id": "trans_abc",
                "transmission_sig": "sig_xyz",
                "transmission_time": "2026-09-24T12:00:00Z",
                "webhook_id": "WH-REG-ID-123",
                "webhook_event": event_payload,
            },
        )


@pytest.mark.asyncio
async def test_paypal_client_verify_signature_failure_status():
    """When PayPal returns verification_status: 'FAILURE', verify_webhook_signature returns False."""
    client = PayPalClient(client_id="test_id", client_secret="test_secret", environment="sandbox")

    mock_resp = Response(
        status_code=200,
        json={"verification_status": "FAILURE"},
        request=MagicMock(),
    )

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_resp

        result = await client.verify_webhook_signature(
            auth_algo="SHA256withRSA",
            cert_url="https://api.sandbox.paypal.com/certs/c1",
            transmission_id="trans_tampered",
            transmission_sig="sig_tampered",
            transmission_time="2026-09-24T12:00:00Z",
            webhook_id="WH-REG-ID-123",
            webhook_event=make_sample_event(),
        )

        assert result is False


@pytest.mark.asyncio
async def test_paypal_client_verify_signature_api_error_returns_false():
    """When PayPal returns HTTP 400 or 500, verify_webhook_signature returns False gracefully."""
    client = PayPalClient(client_id="test_id", client_secret="test_secret", environment="sandbox")

    mock_resp = Response(
        status_code=400,
        text='{"name":"VALIDATION_ERROR","message":"Invalid webhook signature"}',
        request=MagicMock(),
    )

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_resp

        result = await client.verify_webhook_signature(
            auth_algo="SHA256withRSA",
            cert_url="https://api.sandbox.paypal.com/certs/c1",
            transmission_id="trans_err",
            transmission_sig="sig_err",
            transmission_time="2026-09-24T12:00:00Z",
            webhook_id="WH-REG-ID-123",
            webhook_event=make_sample_event(),
        )

        assert result is False


# ==============================================================================
# 3. PayPalWebhookVerifier Service Unit Tests (Acceptance #1, #2, #3)
# ==============================================================================


@pytest.mark.asyncio
async def test_verifier_rejects_incomplete_transmission_headers():
    """Missing any required header aborts verification immediately without network roundtrip."""
    mock_client = AsyncMock(spec=PayPalClient)
    verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-1")

    # Missing transmission_sig
    incomplete_headers = PayPalWebhookHeaders(
        auth_algo="SHA256withRSA",
        cert_url="https://api.sandbox.paypal.com/certs/c1",
        transmission_id="trans_1",
        transmission_sig=None,
        transmission_time="2026-09-24T12:00:00Z",
    )

    result = await verifier.verify(
        raw_body=b'{"id":"WH-1"}',
        headers=incomplete_headers,
        webhook_event={"id": "WH-1"},
    )

    assert result is False
    # Verify no external call made
    mock_client.verify_webhook_signature.assert_not_called()


@pytest.mark.asyncio
async def test_verifier_rejects_untrusted_cert_url():
    """Untrusted cert_url domain aborts verification immediately (anti-SSRF / spoofing)."""
    mock_client = AsyncMock(spec=PayPalClient)
    verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-1")

    malicious_headers = PayPalWebhookHeaders(
        auth_algo="SHA256withRSA",
        cert_url="https://evil-attacker.com/malicious_cert.pem",
        transmission_id="trans_1",
        transmission_sig="sig_fake",
        transmission_time="2026-09-24T12:00:00Z",
    )

    result = await verifier.verify(
        raw_body=b'{"id":"WH-2"}',
        headers=malicious_headers,
        webhook_event={"id": "WH-2"},
    )

    assert result is False
    mock_client.verify_webhook_signature.assert_not_called()


@pytest.mark.asyncio
async def test_verifier_rejects_unconfigured_webhook_id(monkeypatch):
    """Missing configured PAYPAL_WEBHOOK_ID aborts verification safely."""
    monkeypatch.setattr(settings, "paypal_webhook_id", "")
    mock_client = AsyncMock(spec=PayPalClient)
    verifier = PayPalWebhookVerifier(client=mock_client, webhook_id=None)

    valid_headers = PayPalWebhookHeaders(
        auth_algo=VALID_HEADERS["PAYPAL-AUTH-ALGO"],
        cert_url=VALID_HEADERS["PAYPAL-CERT-URL"],
        transmission_id=VALID_HEADERS["PAYPAL-TRANSMISSION-ID"],
        transmission_sig=VALID_HEADERS["PAYPAL-TRANSMISSION-SIG"],
        transmission_time=VALID_HEADERS["PAYPAL-TRANSMISSION-TIME"],
    )

    result = await verifier.verify(
        raw_body=b'{"id":"WH-3"}',
        headers=valid_headers,
        webhook_event={"id": "WH-3"},
    )

    assert result is False
    mock_client.verify_webhook_signature.assert_not_called()


@pytest.mark.asyncio
async def test_verifier_network_exception_fails_safely():
    """Network exception during verification call is caught, logged, and returns False safely."""
    mock_client = AsyncMock(spec=PayPalClient)
    mock_client.verify_webhook_signature.side_effect = Exception("PayPal API connection timeout")
    verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-1")

    valid_headers = PayPalWebhookHeaders(
        auth_algo=VALID_HEADERS["PAYPAL-AUTH-ALGO"],
        cert_url=VALID_HEADERS["PAYPAL-CERT-URL"],
        transmission_id=VALID_HEADERS["PAYPAL-TRANSMISSION-ID"],
        transmission_sig=VALID_HEADERS["PAYPAL-TRANSMISSION-SIG"],
        transmission_time=VALID_HEADERS["PAYPAL-TRANSMISSION-TIME"],
    )

    result = await verifier.verify(
        raw_body=b'{"id":"WH-TIMEOUT"}',
        headers=valid_headers,
        webhook_event={"id": "WH-TIMEOUT"},
    )

    assert result is False


# ==============================================================================
# 4. HTTP Endpoint Integration & Invariant PAY-AUTH-01 (Acceptance #2, #3, #4)
# ==============================================================================


@pytest.mark.asyncio
async def test_http_endpoint_rejects_forged_cert_url_with_400():
    """HTTP endpoint with real verifier rejects untrusted cert URL with HTTP 400 WebhookVerificationError."""
    # Create verifier with mock client that should never be reached
    mock_client = AsyncMock(spec=PayPalClient)
    test_verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-MOCK")

    app.dependency_overrides[get_webhook_verifier] = lambda: test_verifier
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = dict(VALID_HEADERS)
            headers["PAYPAL-CERT-URL"] = "https://evil-spoof.com/cert.pem"

            event = make_sample_event(event_id=f"WH-FORGED-CERT-{uuid.uuid4().hex[:8]}")
            resp = await ac.post(
                "/api/webhooks/paypal",
                content=json.dumps(event).encode("utf-8"),
                headers=headers,
            )

            assert resp.status_code == 400
            data = resp.json()
            assert data["error_code"] == "VALIDATION_ERROR"
            assert "verification failed" in data["message"].lower()

            # Ensure mock client was never called
            mock_client.verify_webhook_signature.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_webhook_verifier, None)


@pytest.mark.asyncio
async def test_http_endpoint_rejects_tampered_signature_with_400():
    """HTTP endpoint rejects request when PayPal API returns FAILURE."""
    mock_client = AsyncMock(spec=PayPalClient)
    mock_client.verify_webhook_signature.return_value = False
    test_verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-MOCK")

    app.dependency_overrides[get_webhook_verifier] = lambda: test_verifier
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            event = make_sample_event(event_id=f"WH-TAMPERED-SIG-{uuid.uuid4().hex[:8]}")
            resp = await ac.post(
                "/api/webhooks/paypal",
                content=json.dumps(event).encode("utf-8"),
                headers=VALID_HEADERS,
            )

            assert resp.status_code == 400
            data = resp.json()
            assert data["error_code"] == "VALIDATION_ERROR"
            assert "verification failed" in data["message"].lower()
            mock_client.verify_webhook_signature.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_webhook_verifier, None)


@pytest.mark.asyncio
async def test_invariant_pay_auth_01_forged_webhook_mutates_no_entities(async_db_session: AsyncSession):
    """
    High-Risk Invariant PAY-AUTH-01:
    A forged PAYMENT.SALE.COMPLETED notification sent by an attacker MUST NOT:
    1. Update SoulmateSession.subscription_success_at
    2. Insert an active Subscription
    3. Insert a SubscriptionPayment ledger entry
    4. Store a verified record in paypal_webhook_events
    """
    # 1. Setup existing user session pending payment
    public_id = f"test_invar_{uuid.uuid4().hex[:12]}"
    session = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email="victim@example.com",
        email_normalized="victim@example.com",
        subscription_success_at=None,
    )
    async_db_session.add(session)
    await async_db_session.commit()
    await async_db_session.refresh(session)
    assert session.subscription_success_at is None

    # 2. Configure verifier where PayPal reports verification failure
    mock_client = AsyncMock(spec=PayPalClient)
    mock_client.verify_webhook_signature.return_value = False
    test_verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-MOCK")

    app.dependency_overrides[get_webhook_verifier] = lambda: test_verifier
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            forged_event_id = f"WH-FORGE-ATTACK-{uuid.uuid4().hex[:8]}"
            event = make_sample_event(
                event_id=forged_event_id,
                event_type="PAYMENT.SALE.COMPLETED",
                resource_id="FORGED-PAYMENT-ID",
            )
            # Inject session public id into event summary or agreement
            event["resource"]["billing_agreement_id"] = f"I-FORGED-{public_id}"

            headers = dict(VALID_HEADERS)
            headers["PAYPAL-TRANSMISSION-SIG"] = "forged_invalid_signature"

            resp = await ac.post(
                "/api/webhooks/paypal",
                content=json.dumps(event).encode("utf-8"),
                headers=headers,
            )
            assert resp.status_code == 400

        # 3. Invariant Verification: No business entities mutated
        # Session must remain unmutated
        sess_stmt = select(SoulmateSession).where(SoulmateSession.public_id == public_id)
        reloaded_sess = (await async_db_session.execute(sess_stmt)).scalars().first()
        assert reloaded_sess is not None
        assert reloaded_sess.subscription_success_at is None
        assert reloaded_sess.status == "email_captured"

        # No Subscription created for forged billing agreement
        sub_stmt = select(Subscription).where(
            Subscription.provider_subscription_id == f"I-FORGED-{public_id}"
        )
        sub = (await async_db_session.execute(sub_stmt)).scalars().first()
        assert sub is None

        # No SubscriptionPayment created for forged payment
        pay_stmt = select(SubscriptionPayment).where(
            SubscriptionPayment.provider_payment_id == "FORGED-PAYMENT-ID"
        )
        pay = (await async_db_session.execute(pay_stmt)).scalars().first()
        assert pay is None

        # No record saved in paypal_webhook_events
        evt_stmt = select(PayPalWebhookEvent).where(
            PayPalWebhookEvent.paypal_event_id == forged_event_id
        )
        evt = (await async_db_session.execute(evt_stmt)).scalars().first()
        assert evt is None

    finally:
        app.dependency_overrides.pop(get_webhook_verifier, None)


@pytest.mark.asyncio
async def test_http_endpoint_verified_webhook_succeeds_and_persists(async_db_session: AsyncSession):
    """
    When PayPal signature verification succeeds:
    - HTTP endpoint returns 200 OK with status="received"
    - Database record is created in paypal_webhook_events with verified=True
    """
    mock_client = AsyncMock(spec=PayPalClient)
    mock_client.verify_webhook_signature.return_value = True
    test_verifier = PayPalWebhookVerifier(client=mock_client, webhook_id="WH-REG-MOCK")

    app.dependency_overrides[get_webhook_verifier] = lambda: test_verifier
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            event_id = f"WH-LEGIT-{uuid.uuid4().hex[:8]}"
            event = make_sample_event(
                event_id=event_id,
                event_type="PAYMENT.SALE.COMPLETED",
                resource_id="LEGIT-PAY-123",
            )

            resp = await ac.post(
                "/api/webhooks/paypal",
                content=json.dumps(event).encode("utf-8"),
                headers=VALID_HEADERS,
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "received"
            assert data["event_id"] == event_id
            assert data["duplicate"] is False

        # Database verification
        evt_stmt = select(PayPalWebhookEvent).where(
            PayPalWebhookEvent.paypal_event_id == event_id
        )
        evt = (await async_db_session.execute(evt_stmt)).scalars().first()
        assert evt is not None
        assert evt.paypal_event_id == event_id
        assert evt.verified is True
        assert evt.event_type == "PAYMENT.SALE.COMPLETED"
        assert evt.resource_id == "LEGIT-PAY-123"

    finally:
        app.dependency_overrides.pop(get_webhook_verifier, None)


@pytest.mark.asyncio
async def test_webhook_service_fails_closed_when_verifier_missing(async_db_session: AsyncSession):
    """
    H-1 Fix: If require_verification=True but verifier is None,
    PayPalWebhookService MUST reject with WebhookVerificationError (fail-closed).
    """
    from app.soulmate.services.webhook_service import PayPalWebhookService

    event = make_sample_event(event_id=f"WH-FAILCLOSED-{uuid.uuid4().hex[:8]}")
    raw_bytes = json.dumps(event).encode("utf-8")

    class RequestWithHeaders:
        headers = VALID_HEADERS

    parsed = PayPalWebhookService.parse_raw_request(request=RequestWithHeaders(), raw_body=raw_bytes)

    with pytest.raises(WebhookVerificationError) as exc_info:
        await PayPalWebhookService.process_webhook(
            raw_request=parsed,
            db=async_db_session,
            verifier=None,  # Missing verifier
            require_verification=True,
        )

    assert "verifier is not configured or provided" in str(exc_info.value).lower()

