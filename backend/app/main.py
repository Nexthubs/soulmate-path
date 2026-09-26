import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import setup_structured_logging
from app.core.middleware import RequestCorrelationMiddleware
from app.core.exception_handlers import register_exception_handlers
from app.api.soulmate.router import api_router
from app.api.soulmate.subscription import cancel_subscription_endpoint
from app.api.soulmate.webhooks import router as webhooks_router
from app.soulmate.schema import SubscriptionCancelResponse
from app.soulmate.services.sketch_generation_service import (
    start_sketch_workers,
    stop_sketch_workers,
)

# Configure structured JSON logging per DEV-SPEC §19.1 & SP-005
setup_structured_logging(level=logging.DEBUG if settings.debug else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate mandatory configuration in production fail-fast (SP-004 Acceptance #3)
    settings.validate_production_config()
    # In-process sketch generation workers (DB-backed queue, §11.6; SP-603)
    worker_tasks = start_sketch_workers()
    try:
        yield
    finally:
        await stop_sketch_workers(worker_tasks)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# Request correlation and latency measurement middleware (SP-005)
app.add_middleware(RequestCorrelationMiddleware)

# CORS middleware with explicit origin list from settings (H1 fix)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Register global exception handlers for standardized error payloads (SP-005)
register_exception_handlers(app)

# Mount /api/soulmate route namespace
app.include_router(api_router, prefix=settings.api_prefix)

# Mount canonical /api/webhooks router (DEV-SPEC §9.6)
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])

# Mount canonical account subscription cancel alias per DEV-SPEC §15.9
app.add_api_route(
    "/api/account/subscription/cancel",
    cancel_subscription_endpoint,
    methods=["POST"],
    response_model=SubscriptionCancelResponse,
    tags=["Subscription"],
    summary="Account subscription cancel alias (DEV-SPEC §15.9)",
)



@app.get("/")
async def root():
    return {
        "message": "Soulmate Path Backend",
        "docs": "/docs",
        "soulmate_api": settings.api_prefix,
    }
