from fastapi import APIRouter
from app.api.soulmate.health import router as health_router
from app.api.soulmate.sessions import router as sessions_router

api_router = APIRouter()

# Mount health check endpoint
api_router.include_router(health_router, tags=["Health"])

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
