from fastapi import APIRouter
from app.api.soulmate.health import router as health_router
from app.api.soulmate.quiz import router as quiz_router
from app.api.soulmate.sessions import router as sessions_router

from app.api.soulmate.subscription import (
    get_subscription_offer,
    router as subscription_router,
)
from app.soulmate.schema import SubscriptionOfferResponse

api_router = APIRouter()


# Mount health check endpoint
api_router.include_router(health_router, tags=["Health"])

# Mount quiz config endpoint (DEV-SPEC §15.2)
api_router.include_router(quiz_router, prefix="/quiz", tags=["Quiz"])

# Mount sessions endpoints (DEV-SPEC §15.1, SP-201)
api_router.include_router(sessions_router, prefix="/sessions", tags=["Sessions"])

# Future route registrations per Soulmate-Path-DEV-SPEC-v1.md §15:
# - §15.2 Quiz Config:           GET /quiz/config
# - §15.3 Answers:               PUT /sessions/{public_id}/answers/{question_code}
# - §15.4 Interstitial Answers:  PUT /sessions/{public_id}/interstitials/{interstitial_code}
# - §15.5 Email:                 PUT /sessions/{public_id}/email
# - §15.6 Checkout Config:       GET /checkout/config
# - §15.7 PayPal Confirm:        POST /payments/paypal/confirm
# - §15.8 Subscription Status:   GET /subscriptions/me
# - §15.9 Cancel Subscription:   POST /subscriptions/cancel
# - §15.10 Sketch Artifact:      GET /artifacts/sketch, POST /artifacts/sketch/generate
# - §15.11 Report Artifact:      GET /artifacts/report
# - §15.12 PayPal Webhooks:      POST /webhooks/paypal

# Mount subscription offer endpoint (DEV-SPEC §9.1–9.2, §15.6, SP-303)
api_router.include_router(subscription_router, prefix="/subscription", tags=["Subscription"])

# Also mount /checkout/config alias per DEV-SPEC §15.6 router table
api_router.add_api_route(
    "/checkout/config",
    get_subscription_offer,
    methods=["GET"],
    response_model=SubscriptionOfferResponse,
    tags=["Subscription"],
    summary="Checkout offer config alias (DEV-SPEC §15.6)",
)
