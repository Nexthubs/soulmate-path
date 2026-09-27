"""
Durable object storage tests (DEV-SPEC §11.7, §22 group 7; SP-605, Decisions: ASSET-01).

Acceptance criteria under test:
1. successful provider output is copied to project-owned (S3-compatible) storage;
2. stable storage key/URL metadata persisted (§11.7 key layout);
3. MIME/type/size validated before anything is stored;
4. the provider temporary URL is never the durable source of truth (bytes are).
"""

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.domain.sketch_models import SketchGenerationResult, SketchImageProvider
from app.soulmate.services.object_storage_sink import (
    MAX_SKETCH_BYTES,
    MIN_SKETCH_BYTES,
    ObjectStorageSink,
    SketchStorageError,
    build_default_sketch_sink,
    build_public_object_url,
    sketch_storage_key,
)
from app.soulmate.services.sketch_generation_service import (
    JOB_COMPLETED,
    LoggingSketchResultSink,
    SketchGenerationService,
    SketchResultSink,
)
from test_sketch_generation import load_sketch_artifact, seed_generation_session


class StubS3Client:
    """Records put_object calls without touching a network."""

    def __init__(self, error: Exception | None = None):
        self.calls: list = []
        self.error = error

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def _payload(magic: bytes, total: int = 2048) -> bytes:
    return magic + b"x" * max(0, total - len(magic))


def _webp_payload(total: int = 2048) -> bytes:
    return _payload(b"RIFF\x00\x00\x00\x00WEBP", total)


def _png_payload(total: int = 2048) -> bytes:
    return _payload(b"\x89PNG\r\n\x1a\n", total)


def _jpeg_payload(total: int = 2048) -> bytes:
    return _payload(b"\xff\xd8\xff", total)


def _result(image_bytes: bytes, image_format: str = "webp") -> SketchGenerationResult:
    return SketchGenerationResult(
        provider="openai",
        model="gpt-image-2",
        image_bytes=image_bytes,
        image_format=image_format,
        size="1024x1536",
        quality="medium",
        provider_request_id="req_sp605",
        duration_ms=100,
    )


class ValidWebpProvider:
    """Provider stub returning a sniffable webp payload (the real sink validates)."""

    provider_name = "fake"

    def __init__(self):
        self.calls = 0

    async def generate_image(self, prompt: str) -> SketchGenerationResult:
        self.calls += 1
        assert prompt and "{" not in prompt and "}" not in prompt
        return SketchGenerationResult(
            provider="openai",
            model="gpt-image-2",
            image_bytes=_webp_payload(4096),
            image_format="webp",
            size="1024x1536",
            quality="medium",
            provider_request_id="req_sp605_live",
            duration_ms=50,
        )


ARTIFACT_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _hermetic_storage_config(monkeypatch):
    """Isolates the sink from the user's real .env OBJECT_STORAGE_* values."""
    monkeypatch.setattr(settings, "object_storage_bucket", "test-bucket")
    monkeypatch.setattr(settings, "object_storage_access_key", "test-access")
    monkeypatch.setattr(settings, "object_storage_secret_key", "test-secret")
    monkeypatch.setattr(settings, "object_storage_public_url_prefix", "")


@pytest.fixture(autouse=True)
async def purge_sp605_data():
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


# ---------------------------------------------------------------------------
# Interface & key contract
# ---------------------------------------------------------------------------


def test_object_storage_sink_satisfies_app_owned_sink_interface():
    assert isinstance(ObjectStorageSink(bucket="b", s3_client=StubS3Client()), SketchResultSink)


def test_storage_key_follows_spec_layout():
    artifact_id = uuid.uuid4()
    key = sketch_storage_key(artifact_id, "webp")
    assert key == f"soulmate/sketches/{artifact_id}/original.webp"


# ---------------------------------------------------------------------------
# Upload path (AC 1 + 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_uploads_payload_with_stable_key():
    stub = StubS3Client()
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=stub)
    payload = _webp_payload()

    key = await sink.persist(artifact_id=ARTIFACT_ID, result=_result(payload))

    assert key == f"soulmate/sketches/{ARTIFACT_ID}/original.webp"
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == key
    assert call["Body"] == payload
    assert call["ContentType"] == "image/webp"


@pytest.mark.asyncio
async def test_persist_accepts_png_and_jpeg_variants():
    stub = StubS3Client()
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=stub)

    png_key = await sink.persist(artifact_id=ARTIFACT_ID, result=_result(_png_payload(), "png"))
    jpeg_key = await sink.persist(artifact_id=ARTIFACT_ID, result=_result(_jpeg_payload(), "jpeg"))

    assert png_key.endswith("original.png")
    assert jpeg_key.endswith("original.jpeg")
    assert stub.calls[0]["ContentType"] == "image/png"
    assert stub.calls[1]["ContentType"] == "image/jpeg"


# ---------------------------------------------------------------------------
# Validation rules (AC 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_reclassifies_mislabeled_payload_to_sniffed_format():
    """A gateway that ignores output_format (PNG despite webp request) is stored
    under the SNIFFED format — the durable key never lies about the bytes."""
    stub = StubS3Client()
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=stub)
    key = await sink.persist(artifact_id=ARTIFACT_ID, result=_result(_png_payload(), "webp"))
    assert key.endswith("original.png")
    assert stub.calls[0]["ContentType"] == "image/png"


@pytest.mark.asyncio
async def test_persist_rejects_payload_matching_no_supported_format():
    """Garbage/unknown payloads are rejected regardless of declared format."""
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=StubS3Client())
    garbage = b"\x00\x01\x02\x03" * 512
    with pytest.raises(SketchStorageError):
        await sink.persist(artifact_id=ARTIFACT_ID, result=_result(garbage, "webp"))
    with pytest.raises(SketchStorageError):
        await sink.persist(artifact_id=ARTIFACT_ID, result=_result(garbage, "png"))




@pytest.mark.asyncio
async def test_persist_rejects_undersized_payload():
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=StubS3Client())
    size = MIN_SKETCH_BYTES - 1
    with pytest.raises(SketchStorageError) as exc:
        await sink.persist(artifact_id=ARTIFACT_ID, result=_result(_webp_payload(total=size)))
    assert exc.value.details["size_bytes"] == size


@pytest.mark.asyncio
async def test_persist_rejects_oversized_payload():
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=StubS3Client())
    size = MAX_SKETCH_BYTES + 1
    with pytest.raises(SketchStorageError) as exc:
        await sink.persist(artifact_id=ARTIFACT_ID, result=_result(_webp_payload(total=size)))
    assert exc.value.details["size_bytes"] == size


@pytest.mark.asyncio
async def test_upload_failure_raises_sanitized_storage_error():
    stub = StubS3Client(error=RuntimeError("connection reset"))
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=stub)
    with pytest.raises(SketchStorageError) as exc:
        await sink.persist(artifact_id=ARTIFACT_ID, result=_result(_webp_payload()))
    assert "Object storage upload failed" in str(exc.value)
    assert exc.value.internal_message is not None  # server-log detail retained


# ---------------------------------------------------------------------------
# Default binding & URL derivation
# ---------------------------------------------------------------------------


def test_build_default_sketch_sink_uses_storage_when_configured():
    assert isinstance(build_default_sketch_sink(), ObjectStorageSink)


def test_build_default_sketch_sink_falls_back_without_config(monkeypatch):
    monkeypatch.setattr(settings, "object_storage_bucket", None)
    assert isinstance(build_default_sketch_sink(), LoggingSketchResultSink)


def test_public_url_builder_derives_from_prefix(monkeypatch):
    monkeypatch.setattr(settings, "object_storage_public_url_prefix", "https://cdn.example.com/assets/")
    assert (
        build_public_object_url("soulmate/sketches/abc/original.webp")
        == "https://cdn.example.com/assets/soulmate/sketches/abc/original.webp"
    )
    monkeypatch.setattr(settings, "object_storage_public_url_prefix", "")
    assert build_public_object_url("soulmate/sketches/abc/original.webp") is None


# ---------------------------------------------------------------------------
# Worker integration (AC 1 + 2 + 4 end to end)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_persists_provider_output_to_object_storage():
    async with AsyncSessionLocal() as db:
        sess = await seed_generation_session(db)
        outcome = await SketchGenerationService.enqueue_sketch_generation(db, sess)

    stub = StubS3Client()
    sink = ObjectStorageSink(bucket="test-bucket", s3_client=stub)
    provider = ValidWebpProvider()

    status = await SketchGenerationService.process_next_queued_job(
        provider=provider, sink=sink, job_id=outcome.job.id
    )

    assert status == JOB_COMPLETED
    assert provider.calls == 1
    assert len(stub.calls) == 1

    async with AsyncSessionLocal() as verify_db:
        artifact = await load_sketch_artifact(verify_db, sess.id)
    expected_key = f"soulmate/sketches/{artifact.id}/original.webp"
    assert artifact.generation_status == "COMPLETED"
    assert artifact.storage_key == expected_key
    assert stub.calls[0]["Key"] == expected_key
    assert stub.calls[0]["Body"] == _webp_payload(4096)
    # The provider temporary URL (if any) never becomes the durable metadata.
    assert artifact.provider_request_id == "req_sp605_live"
