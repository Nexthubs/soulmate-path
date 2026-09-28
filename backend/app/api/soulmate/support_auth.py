"""Shared authentication dependency for internal customer-support endpoints."""

import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


def verify_support_access(
    x_support_key: Optional[str] = Header(default=None, alias="X-Support-Key"),
) -> None:
    """Require the dedicated support credential in every environment."""
    expected_key = (settings.support_api_key or "").strip()
    session_key = (settings.session_secret_key or "").strip()
    if len(expected_key) < 32 or expected_key == session_key:
        logger.error("Support endpoints are disabled because SUPPORT_API_KEY is not configured securely")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Support access is not configured",
        )

    if not x_support_key or not hmac.compare_digest(
        x_support_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        logger.warning("Unauthorized access attempt to customer support endpoints")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing support authorization key",
        )
