"""Session Cryptographic Security, Token Signing, and IDOR Ownership Guard (DEV-SPEC §6, §20)."""

import hashlib
import hmac
import secrets
import time
from typing import Optional
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.config import settings
from app.core.errors import ForbiddenOwnershipError, NotFoundError
from app.db.models.session import SoulmateSession
from app.db.session import get_db


def generate_public_id() -> str:
    """Generates an unguessable URL-safe public session identifier."""
    return f"ses_{secrets.token_hex(16)}"


def generate_session_token(public_id: str, timestamp: Optional[int] = None) -> str:
    """
    Creates an HMAC-SHA256 signed session token for the soulmate_sid cookie/bearer.
    Format: <public_id>.<timestamp>.<signature>
    """
    if timestamp is None:
        timestamp = int(time.time())

    payload = f"{public_id}:{timestamp}".encode("utf-8")
    signature = hmac.new(
        settings.session_secret_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return f"{public_id}.{timestamp}.{signature}"


def verify_session_token(
    token: str,
    max_age_seconds: Optional[int] = None,
) -> str:
    """
    Verifies token integrity and expiration using constant-time comparison.
    Returns the authenticated public_id on success.
    Raises ForbiddenOwnershipError on tampering, format error, or expiration.
    """
    if not token or not isinstance(token, str):
        raise ForbiddenOwnershipError("Missing or invalid session credentials.")

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ForbiddenOwnershipError("Invalid session token format.")

    public_id, ts_str, signature = parts

    try:
        token_time = int(ts_str)
    except ValueError:
        raise ForbiddenOwnershipError("Invalid session token timestamp.")

    # Re-compute expected signature
    expected_payload = f"{public_id}:{token_time}".encode("utf-8")
    expected_sig = hmac.new(
        settings.session_secret_key.encode("utf-8"),
        expected_payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signature, expected_sig):
        raise ForbiddenOwnershipError("Invalid session signature.")

    # Expiration check
    if max_age_seconds is None:
        max_age_seconds = settings.session_cookie_max_age_days * 86400

    now = int(time.time())
    # Reject timestamps too far in the future (clock skew tolerance: 60s)
    if token_time > now + 60:
        raise ForbiddenOwnershipError("Session token timestamp is invalid.")

    if now - token_time > max_age_seconds:
        raise ForbiddenOwnershipError("Session credentials have expired.")

    return public_id


def extract_session_token(request: Request) -> Optional[str]:
    """
    Extracts session token from HttpOnly cookie (primary) or auth headers (API/fallback).
    """
    # 1. Primary: HttpOnly cookie 'soulmate_sid' (DEV-SPEC §6.1)
    cookie_token = request.cookies.get(settings.session_cookie_name)
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()

    # 2. Secondary: Custom header X-Soulmate-Session-Token
    header_token = request.headers.get("X-Soulmate-Session-Token")
    if header_token and header_token.strip():
        return header_token.strip()

    # 3. Tertiary: Authorization Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
        if bearer_token:
            return bearer_token

    return None


def get_authenticated_session_public_id(request: Request) -> str:
    """
    FastAPI dependency that extracts and validates the caller's session token.
    Raises ForbiddenOwnershipError if credentials are missing or invalid.
    """
    token = extract_session_token(request)
    if not token:
        raise ForbiddenOwnershipError("Session authentication required.")
    return verify_session_token(token)


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SoulmateSession:
    """
    FastAPI dependency that resolves the current authenticated SoulmateSession.
    Eagerly loads answers to restore full user state.
    """
    public_id = get_authenticated_session_public_id(request)

    query = (
        select(SoulmateSession)
        .options(selectinload(SoulmateSession.answers))
        .where(SoulmateSession.public_id == public_id)
    )
    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise NotFoundError("Session not found.")

    return session


def verify_session_ownership(
    requested_public_id: str,
    authenticated_public_id: str,
) -> None:
    """
    IDOR Guard (DEV-SPEC §20): Ensures the authenticated caller can only
    access their own session data.
    """
    if requested_public_id != authenticated_public_id:
        raise ForbiddenOwnershipError("Access to the requested session is forbidden.")
