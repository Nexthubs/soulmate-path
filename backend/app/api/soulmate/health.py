from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    module: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Soulmate module health check endpoint."""
    return HealthResponse(
        status="ok",
        module="soulmate",
        version="v1",
    )
