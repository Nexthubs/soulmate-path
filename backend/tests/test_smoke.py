import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.soulmate.domain import CANONICAL_QUIZ_VERSION, SKETCH_UNLOCK_HOURS, REPORT_UNLOCK_HOURS


@pytest.mark.asyncio
async def test_root_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["soulmate_api"] == "/api/soulmate"


@pytest.mark.asyncio
async def test_soulmate_health_endpoint():
    """Verify /api/soulmate/health endpoint returns expected status (SP-001 acceptance)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/soulmate/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["module"] == "soulmate"
        assert data["version"] == "v1"


@pytest.mark.asyncio
async def test_cors_preflight_rejection_for_unauthorized_origin():
    """Verify CORS preflight does not echo unauthorized origins (H1 fix verification)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request with unauthorized origin
        response = await client.options(
            "/api/soulmate/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") != "https://evil.example"

        # Request with authorized origin
        allowed_response = await client.options(
            "/api/soulmate/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed_response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_canonical_domain_constants():
    """Verify core domain contracts are established."""
    assert CANONICAL_QUIZ_VERSION == "soulmate-quiz-v1"
    assert SKETCH_UNLOCK_HOURS == 12
    assert REPORT_UNLOCK_HOURS == 24
