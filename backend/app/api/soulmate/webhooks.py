"""
PayPal Webhook HTTP Endpoints (DEV-SPEC §9.5–9.6, §15.12, SP-404, Decisions: PAY-AUTH-01).

Receives unauthenticated PayPal webhook notifications, preserves raw body bytes,
enforces signature verification gating, and supports PayPal retry semantics.
"""

import logging
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.soulmate.domain.webhook_models import PayPalWebhookResponse
from app.soulmate.services.webhook_service import PayPalWebhookService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/paypal",
    response_model=PayPalWebhookResponse,
    status_code=200,
    summary="PayPal Webhook Receiver (DEV-SPEC §9.5–9.6)",
    description=(
        "Public endpoint for PayPal webhook delivery. Preserves exact raw request body "
        "for cryptographic signature verification without user authentication."
    ),
)
async def paypal_webhook_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PayPalWebhookResponse:
    """
    Ingest incoming PayPal webhook event.
    - Captures raw request bytes via await request.body().
    - Validates presence of PayPal transmission headers.
    - Rejects unverified or malformed payloads without mutating business state.
    - Idempotently returns 200 OK on replayed event delivery to stop retry loop.
    """
    # 1. Read and preserve immutable raw body bytes (Acceptance #1)
    raw_body = await request.body()

    # 2. Parse request container and extract transmission headers
    raw_request = PayPalWebhookService.parse_raw_request(request=request, raw_body=raw_body)

    # 3. Process verification gate and record event (Acceptance #3, #4)
    response = await PayPalWebhookService.process_webhook(
        raw_request=raw_request,
        db=db,
    )

    return response
