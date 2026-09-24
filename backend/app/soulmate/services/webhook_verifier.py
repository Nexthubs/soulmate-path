"""
PayPal Webhook Signature Verifier (DEV-SPEC §9.6, SP-405, Decisions: PAY-AUTH-01).

Implements official PayPal signature verification mechanism via /v1/notifications/verify-webhook-signature,
validates cert_url origin to prevent SSRF/spoofing, and ensures verification failures are logged safely.
"""

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.core.config import settings
from app.core.logging import log_event
from app.soulmate.domain.webhook_models import PayPalWebhookHeaders
from app.soulmate.services.paypal_client import PayPalClient

logger = logging.getLogger(__name__)


def is_valid_paypal_cert_url(cert_url: Optional[str]) -> bool:
    """
    Validate cert_url origin (Defense-in-Depth against forged certificate injection and SSRF).
    Must use HTTPS scheme, standard port (None or 443), and trusted paypal.com domain.
    """
    if not cert_url or not isinstance(cert_url, str):
        return False
    try:
        parsed = urlparse(cert_url.strip())
        if parsed.scheme.lower() != "https":
            return False
        if parsed.port is not None and parsed.port != 443:
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        # Must strictly be paypal.com or a subdomain of paypal.com
        if hostname == "paypal.com" or hostname.endswith(".paypal.com"):
            return True
        return False
    except Exception:
        return False


class PayPalWebhookVerifier:
    """
    Official PayPal signature verification service (DEV-SPEC §9.6, SP-405).
    Calls PayPal's /v1/notifications/verify-webhook-signature REST API.
    """

    def __init__(
        self,
        client: Optional[PayPalClient] = None,
        webhook_id: Optional[str] = None,
    ):
        self._client = client
        self._webhook_id = webhook_id

    def _get_client(self) -> PayPalClient:
        if self._client is not None:
            return self._client
        return PayPalClient(
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            environment=settings.paypal_env,
        )

    def _get_webhook_id(self) -> Optional[str]:
        return self._webhook_id or settings.paypal_webhook_id

    async def verify(
        self,
        raw_body: bytes,
        headers: PayPalWebhookHeaders,
        webhook_event: Optional[Dict[str, Any]] = None,
        webhook_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """
        Verify incoming webhook signature using official PayPal API.
        Enforces:
        1. Complete transmission headers.
        2. Valid cert_url (must be https://*.paypal.com).
        3. Configured webhook_id.
        4. Official PayPal verification_status == 'SUCCESS'.
        All failure branches log safe diagnostics without exposing secrets.
        """
        event_dict = webhook_event or {}
        event_id = event_dict.get("id", "UNKNOWN")
        event_type = event_dict.get("event_type", "UNKNOWN")

        # 1. Check transmission headers completeness
        if not headers.is_complete():
            log_event(
                event_type="paypal_webhook_verification_failed",
                message=f"Missing required PayPal transmission headers for event {event_id}",
                level=logging.WARNING,
                error_code="VALIDATION_ERROR",
                extra_data={
                    "event_id": event_id,
                    "event_type": event_type,
                    "missing_headers": headers.missing_headers(),
                },
            )
            return False

        # 2. Cert URL origin security validation (Defense-in-Depth)
        if not is_valid_paypal_cert_url(headers.cert_url):
            log_event(
                event_type="paypal_webhook_verification_failed",
                message=f"Untrusted or invalid cert_url '{headers.cert_url}' rejected for event {event_id}",
                level=logging.WARNING,
                error_code="VALIDATION_ERROR",
                extra_data={
                    "event_id": event_id,
                    "event_type": event_type,
                    "cert_url": headers.cert_url,
                },
            )
            return False

        # 3. Resolve configured webhook ID
        effective_webhook_id = webhook_id or self._get_webhook_id()
        if not effective_webhook_id:
            log_event(
                event_type="paypal_webhook_verification_failed",
                message=f"PAYPAL_WEBHOOK_ID not configured; rejecting verification for event {event_id}",
                level=logging.WARNING,
                error_code="VALIDATION_ERROR",
                extra_data={"event_id": event_id, "event_type": event_type},
            )
            return False

        # 4. Invoke official PayPal REST verification endpoint
        client = self._get_client()
        try:
            is_valid = await client.verify_webhook_signature(
                auth_algo=headers.auth_algo,  # type: ignore[arg-type]
                cert_url=headers.cert_url,  # type: ignore[arg-type]
                transmission_id=headers.transmission_id,  # type: ignore[arg-type]
                transmission_sig=headers.transmission_sig,  # type: ignore[arg-type]
                transmission_time=headers.transmission_time,  # type: ignore[arg-type]
                webhook_id=effective_webhook_id,
                webhook_event=event_dict,
            )
        except Exception as e:
            log_event(
                event_type="paypal_webhook_verification_failed",
                message=f"Exception during PayPal signature verification for event {event_id}: {e}",
                level=logging.ERROR,
                error_code="PROVIDER_UNAVAILABLE",
                extra_data={"event_id": event_id, "event_type": event_type, "error": str(e)},
            )
            return False

        if not is_valid:
            log_event(
                event_type="paypal_webhook_verification_failed",
                message=f"Official PayPal verification returned FAILURE for event {event_id}",
                level=logging.WARNING,
                error_code="VALIDATION_ERROR",
                extra_data={
                    "event_id": event_id,
                    "event_type": event_type,
                    "transmission_id": headers.transmission_id,
                },
            )
            return False

        log_event(
            event_type="paypal_webhook_verified",
            message=f"Successfully verified PayPal signature for event {event_id} ({event_type})",
            level=logging.INFO,
            extra_data={"event_id": event_id, "event_type": event_type},
        )
        return True


# Global default verifier singleton
_default_verifier: Optional[PayPalWebhookVerifier] = None


def get_webhook_verifier() -> PayPalWebhookVerifier:
    """FastAPI dependency for injecting PayPal webhook signature verifier."""
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = PayPalWebhookVerifier()
    return _default_verifier
