"""
Sketch asset API tests (DEV-SPEC §15.10, §10.3; SP-607; Decisions: ASSET-01, RECOVERY-01, TIME-01).

Acceptance criteria under test:
- authoritative session-scoped sketch state for the Sketch page (§10.3);
- COMPLETED artifacts expose the persisted durable asset's display URL (ASSET-01:
  derived from the project-owned storage key, never a provider temporary URL);
- authorization/IDOR identical to the Result aggregate (§20);
- URL resolution: stable public prefix first, presigned read URL fallback, None
  when nothing is stored.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token
from app.soulmate.services.sketch_generation_service import SketchGenerationService
from test_sketch_generation import load_sketch_artifact, seed_generation_session

SKETCH_URL = "/api/soulmate/artifacts/sketch"


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
def _hermetic_storage_config(monkeypatch):
    """Isolates URL resolution from the user's real .env OBJECT_STORAGE_*/values."""
    monkeypatch.setattr(settings, "object_storage_bucket", "test-bucket")
    monkeypatch.setattr(settings, "object_storage_access_key", "test-access")
    monkeypatch.setattr(settings, "object_storage_secret_key", "test-secret")
    monkeypatch.setattr(settings, "object_storage_public_url_prefix", "")


@pytest.fixture(autouse=True)
async def purge_sp607_data():
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp603_%"))
        await db.execute(
            delete(AIGenerationJob).where(
                AIGenerationJob.artifact_id.in_(select(SoulmateArtifact.id).where(SoulmateArtifact.session_id.in_(sess_ids)))
            )
        )
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp603_%")))
        await db.commit()


def _webp_bytes(n: int = 4096) -> bytes:
    return b"RIFF\x00\x00\x00\x00WEBP" + b"x" * (n - 12)


async def seed_completed_sketch(
    db: AsyncSession,
    storage_key: str | None,
    email: str | None = None,
):
    """Entitled session whose sketch artifact is COMPLETED (optionally with a key)."""
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(hours=2)
    email = email or f"sp603_{uuid.uuid4().hex[:8]}@example.com"
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=email,
        email_normalized=email,
        subscription_success_at=paid_at,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    db.add(
        Subscription(
            session_id=sess.id,
            provider="paypal",
            provider_subscription_id=f"I-SP607-{uuid.uuid4().hex[:8].upper()}",
            provider_plan_id="P-SOULMATE-INTRO",
            provider_status="ACTIVE",
            currency="USD",
            intro_price=Decimal("19.00"),
            regular_price=Decimal("29.00"),
            first_payment_at=paid_at,
        )
    )
    db.add(
        SoulmateArtifact(
            session_id=sess.id,
            email_normalized=email,
            artifact_type="SKETCH",
            artifact_version="v1",
            unlock_at=now - timedelta(hours=1),
            generation_status="COMPLETED",
            storage_key=storage_key,
            provider="openai",
            model="gpt-image-2",
            prompt_version="v1",
            input_json={"gender": "male", "age_range": "20-30", "ethnicity": "Asian", "features": "Loyalty"},
            completed_at=now,
        )
    )
    await db.commit()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Authorization (§20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sketch_asset_requires_authentication(async_db):
    sess = await seed_completed_sketch(async_db, storage_key="soulmate/sketches/x/original.webp")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(SKETCH_URL)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sketch_asset_rejects_cross_session_idor(async_db):
    sess_a = await seed_completed_sketch(async_db, storage_key="soulmate/sketches/a/original.webp")
    sess_b = await seed_completed_sketch(async_db, storage_key="soulmate/sketches/b/original.webp")
    token_a = generate_session_token(sess_a.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token_a)
        resp = await client.get(f"{SKETCH_URL}?session_id={sess_b.public_id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Status + URL resolution (ASSET-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locked_sketch_returns_status_without_image(async_db):
    sess = await seed_generation_session(async_db, unlocked=False)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sess.public_id
    assert data["sketch"]["status"] == "LOCKED"
    assert data["image_url"] is None
    assert data["storage_key"] is None
    assert data["server_time"] is not None


@pytest.mark.asyncio
async def test_generating_sketch_returns_status_without_image(async_db):
    sess = await seed_generation_session(async_db, sketch_generation="PROCESSING")
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] == "GENERATING"
    assert data["image_url"] is None


@pytest.mark.asyncio
async def test_completed_sketch_exposes_public_prefix_url(async_db, monkeypatch):
    monkeypatch.setattr(settings, "object_storage_public_url_prefix", "https://cdn.example.com/assets")
    sess = await seed_completed_sketch(async_db, storage_key="soulmate/sketches/abc/original.webp")
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] == "COMPLETED"
    assert data["storage_key"] == "soulmate/sketches/abc/original.webp"
    assert data["image_url"] == "https://cdn.example.com/assets/soulmate/sketches/abc/original.webp"


@pytest.mark.asyncio
async def test_completed_sketch_returns_persisted_artifact_version(async_db):
    sess = await seed_completed_sketch(
        async_db,
        storage_key="soulmate/sketches/versioned/original.webp",
    )
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    assert resp.status_code == 200
    assert resp.json()["session_id"] == sess.public_id
    assert resp.json()["artifact_version"] == "v1"


@pytest.mark.asyncio
async def test_completed_sketch_falls_back_to_presigned_url(async_db):
    """No public prefix configured: presigned read URL against private storage (e.g. R2)."""
    captured = {}

    def fake_presign(self, storage_key, expires_in=3600):
        captured["key"] = storage_key
        captured["expires_in"] = expires_in
        return f"https://r2.example.com/{storage_key}?X-Amz-Signature=fake"

    from app.soulmate.services.object_storage_sink import ObjectStorageSink

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(ObjectStorageSink, "presigned_read_url", fake_presign)
        sess = await seed_completed_sketch(async_db, storage_key="soulmate/sketches/presign/original.webp")
        token = generate_session_token(sess.public_id)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set("soulmate_sid", token)
            resp = await client.get(SKETCH_URL)
    finally:
        monkey.undo()

    data = resp.json()
    assert data["sketch"]["status"] == "COMPLETED"
    assert data["image_url"] == "https://r2.example.com/soulmate/sketches/presign/original.webp?X-Amz-Signature=fake"
    assert captured["key"] == "soulmate/sketches/presign/original.webp"
    assert captured["expires_in"] == 3600


@pytest.mark.asyncio
async def test_completed_sketch_without_storage_key_has_no_image_url(async_db):
    sess = await seed_completed_sketch(async_db, storage_key=None)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] == "COMPLETED"
    assert data["storage_key"] is None
    assert data["image_url"] is None


# ---------------------------------------------------------------------------
# End-to-end: generate → worker → GET returns the durable asset URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_generate_then_fetch_displays_persisted_asset(async_db, monkeypatch):
    monkeypatch.setattr(settings, "object_storage_public_url_prefix", "https://cdn.example.com/assets")
    sess = await seed_generation_session(async_db)

    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        gen = await client.post("/api/soulmate/artifacts/sketch/generate")
    assert gen.status_code == 200

    # Drive the worker with a valid webp payload and a recording storage sink,
    # scoped to this test's identity job (shared dev DB hygiene).
    from test_object_storage import StubS3Client, ValidWebpProvider
    from app.soulmate.services.object_storage_sink import ObjectStorageSink
    from app.soulmate.services.sketch_generation_service import sketch_idempotency_key

    job = (
        await async_db.execute(
            select(AIGenerationJob).where(
                AIGenerationJob.idempotency_key == sketch_idempotency_key(sess.email_normalized, "v1")
            )
        )
    ).scalar_one()

    stub = StubS3Client()

    class RecordingSink(ObjectStorageSink):
        async def persist(self, *, artifact_id, result):
            from app.soulmate.services.object_storage_sink import sketch_storage_key, validate_sketch_payload

            fmt = validate_sketch_payload(result)
            key = sketch_storage_key(artifact_id, fmt)
            stub.calls.append({"Bucket": self.bucket, "Key": key, "Body": result.image_bytes})
            return key

    provider = ValidWebpProvider()
    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=RecordingSink(bucket="test-bucket"), job_id=job.id
    )
    assert status == "COMPLETED"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] == "COMPLETED"
    assert data["storage_key"] is not None
    assert data["image_url"] == f"https://cdn.example.com/assets/{data['storage_key']}"


# ---------------------------------------------------------------------------
# R1 fix: §10.3 Retry/Support split surfaced as retry_available
# ---------------------------------------------------------------------------


async def _seed_failed_sketch(db: AsyncSession, job_status: str, attempt: int):
    sess = await seed_generation_session(db)
    artifact = await load_sketch_artifact(db, sess.id)
    artifact.generation_status = "FAILED"
    artifact.last_error_code = "PROVIDER_UNAVAILABLE"
    await db.commit()
    from app.soulmate.services.sketch_generation_service import sketch_idempotency_key

    job = AIGenerationJob(
        artifact_id=artifact.id,
        job_type="SOULMATE_SKETCH",
        idempotency_key=sketch_idempotency_key(sess.email_normalized, "v1"),
        status=job_status,
        attempt=attempt,
    )
    db.add(job)
    await db.commit()
    return sess


@pytest.mark.asyncio
async def test_failed_retryable_job_reports_retry_available(async_db, monkeypatch):
    monkeypatch.setattr(settings, "job_retry_base_backoff_seconds", 0.0)
    sess = await _seed_failed_sketch(async_db, "FAILED_RETRYABLE", 3)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] == "FAILED"
    assert data["retry_available"] is True


@pytest.mark.asyncio
async def test_failed_permanent_job_reports_support_only(async_db):
    sess = await _seed_failed_sketch(async_db, "FAILED_PERMANENT", 3)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] == "FAILED"
    assert data["retry_available"] is False


@pytest.mark.asyncio
async def test_retry_available_none_for_non_failed_states(async_db):
    sess = await seed_generation_session(async_db)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get(SKETCH_URL)
    data = resp.json()
    assert data["sketch"]["status"] in ("READY", "LOCKED")
    assert data["retry_available"] is None


@pytest.mark.asyncio
async def test_user_retry_endpoint_roundtrip(async_db, monkeypatch):
    """POST generate on a FAILED_RETRYABLE terminal job requeues it (§10.3 Retry)."""
    monkeypatch.setattr(settings, "job_retry_base_backoff_seconds", 0.0)
    sess = await _seed_failed_sketch(async_db, "FAILED_RETRYABLE", 3)
    token = generate_session_token(sess.public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        gen = await client.post("/api/soulmate/artifacts/sketch/generate")
    assert gen.status_code == 200
    data = gen.json()
    assert data["job_status"] == "QUEUED"
    assert data["sketch"]["generation"] == "QUEUED"
    assert data["sketch"]["status"] == "GENERATING"
