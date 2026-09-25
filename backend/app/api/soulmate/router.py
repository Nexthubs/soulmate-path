from fastapi import APIRouter
from app.api.soulmate.guard import router as guard_router
from app.api.soulmate.health import router as health_router
from app.api.soulmate.quiz import router as quiz_router
from app.api.soulmate.sessions import router as sessions_router
from app.api.soulmate.subscription import (
    cancel_subscription_endpoint,
    confirm_paypal_subscription_endpoint,
    get_subscription_offer,
    get_subscription_status_endpoint,
    router as subscription_router,
)
from app.api.soulmate.ledger import router as ledger_router
from app.api.soulmate.webhooks import router as webhooks_router
from app.soulmate.schema import (
    PayPalConfirmResponse,
    SubscriptionCancelResponse,
    SubscriptionOfferResponse,
    SubscriptionStatusResponse,
)

api_router = APIRouter()

# Mount health check endpoint
api_router.include_router(health_router, tags=["Health"])

# Mount quiz config endpoint (DEV-SPEC §15.2)
api_router.include_router(quiz_router, prefix="/quiz", tags=["Quiz"])

# Mount sessions endpoints (DEV-SPEC §15.1, SP-201, SP-301, SP-302)
api_router.include_router(sessions_router, prefix="/sessions", tags=["Sessions"])

# Mount subscription endpoints (DEV-SPEC §9.1–9.4, §15.6–15.8, SP-303, SP-403)
api_router.include_router(subscription_router, prefix="/subscription", tags=["Subscription"])

# Mount route guard endpoint (DEV-SPEC §3, §10, §20, SP-304)
api_router.include_router(guard_router, prefix="/guard", tags=["Route Guard"])

# Mount webhook endpoints (DEV-SPEC §9.5–9.6, §15.12, SP-404)
api_router.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])

# Mount payment ledger endpoints (DEV-SPEC §9.4–9.7, §14, SP-407)
api_router.include_router(ledger_router, prefix="/ledger", tags=["Payment Ledger"])

# Also mount aliases per DEV-SPEC §15 router table
api_router.add_api_route(
    "/checkout/config",
    get_subscription_offer,
    methods=["GET"],
    response_model=SubscriptionOfferResponse,
    tags=["Subscription"],
    summary="Checkout offer config alias (DEV-SPEC §15.6)",
)

api_router.add_api_route(
    "/paypal/confirm",
    confirm_paypal_subscription_endpoint,
    methods=["POST"],
    response_model=PayPalConfirmResponse,
    tags=["Subscription"],
    summary="PayPal confirm alias (DEV-SPEC §9.3)",
)

api_router.add_api_route(
    "/payments/paypal/confirm",
    confirm_paypal_subscription_endpoint,
    methods=["POST"],
    response_model=PayPalConfirmResponse,
    tags=["Subscription"],
    summary="PayPal confirm payments alias (DEV-SPEC §15.7)",
)

api_router.add_api_route(
    "/subscriptions/me",
    get_subscription_status_endpoint,
    methods=["GET"],
    response_model=SubscriptionStatusResponse,
    tags=["Subscription"],
    summary="Subscription status me alias (DEV-SPEC §15.8)",
)

api_router.add_api_route(
    "/subscriptions/cancel",
    cancel_subscription_endpoint,
    methods=["POST"],
    response_model=SubscriptionCancelResponse,
    tags=["Subscription"],
    summary="Cancel subscription alias (DEV-SPEC §15.9)",
)

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
