from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.soulmate.router import api_router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
)

# CORS middleware with explicit origin list from settings (H1 fix)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount /api/soulmate route namespace
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root():
    return {
        "message": "Soulmate Path Backend",
        "docs": "/docs",
        "soulmate_api": settings.api_prefix,
    }
