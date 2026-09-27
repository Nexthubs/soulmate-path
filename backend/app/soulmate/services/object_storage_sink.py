"""
Durable object storage sink for sketch generation results
(DEV-SPEC §11.7, §22 group 7; Decisions: ASSET-01, IMGPROVIDER-01; SP-605).

Implements the app-owned `SketchResultSink` seam against project-owned,
S3-compatible object storage (AWS S3 or any endpoint-compatible service such as
MinIO via `OBJECT_STORAGE_ENDPOINT`). Per ASSET-01:
- the bytes returned by the provider are persisted immediately after generation;
- the stable §11.7 storage key (`soulmate/sketches/{artifact_id}/original.<fmt>`)
  is what the worker persists as `artifact.storage_key` — never a provider
  temporary URL (`result.source_url` is tracing metadata only);
- revisits return the same stored asset because the key is deterministic per
  artifact and the object is never rewritten after a successful upload.

Validation rules (the repo's first storage rules — established here):
- declared image format must be one of webp/png/jpeg (§22 `SOULMATE_IMAGE_FORMAT`);
- payload magic bytes must match the declared format (no relabeled payloads);
- payload size must be within [MIN_SKETCH_BYTES, MAX_SKETCH_BYTES].

boto3 is synchronous; uploads run through `asyncio.to_thread` so the worker
event loop is never blocked. Failures raise `SketchStorageError`, which the
worker treats as retryable (bounded by the §11.6 budget, alertable per §19.2).
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID

import boto3
from botocore.config import Config as BotoConfig

from app.core.config import settings
from app.soulmate.domain.sketch_models import SketchGenerationResult

logger = logging.getLogger(__name__)

# §11.7 recommended key layout.
SKETCH_STORAGE_KEY_TEMPLATE = "soulmate/sketches/{artifact_id}/original.{image_format}"

# Declared-format -> MIME type (§22 engineering defaults; PRD does not fix these).
IMAGE_CONTENT_TYPES = {
    "webp": "image/webp",
    "png": "image/png",
    "jpeg": "image/jpeg",
}

MIN_SKETCH_BYTES = 512
MAX_SKETCH_BYTES = 10 * 1024 * 1024  # 10 MiB — generous vs a ~1024x1536 sketch


class SketchStorageError(Exception):
    """
    Raised when sketch payload validation or object-storage upload fails.

    `message`/`details` are safe for durable error records; `internal_message`
    (SDK/exception internals) is for server logs only. `permanent=True` classifies
    the failure as never-retryable (e.g. storage unconfigured).
    """

    def __init__(
        self,
        message: str,
        details: Optional[dict] = None,
        internal_message: Optional[str] = None,
        permanent: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.internal_message = internal_message
        self.permanent = permanent


class SketchStorageUnavailableError(SketchStorageError):
    """Storage is not configured / unusable — retrying can never succeed."""

    def __init__(self, message: str, details: Optional[dict] = None, internal_message: Optional[str] = None):
        super().__init__(message, details=details, internal_message=internal_message, permanent=True)


def sketch_storage_key(artifact_id: UUID, image_format: str) -> str:
    """Deterministic §11.7 key: revisits resolve to the same stored object."""
    return SKETCH_STORAGE_KEY_TEMPLATE.format(artifact_id=artifact_id, image_format=image_format)


def build_public_object_url(storage_key: str) -> Optional[str]:
    """
    Stable public URL for a stored object, derived from configuration
    (`OBJECT_STORAGE_PUBLIC_URL_PREFIX`) at read time — URLs are never baked
    into stored data (DOMAIN-01 spirit). None when no prefix is configured.
    """
    if settings.is_production:
        return None  # ASSET-ACCESS-01: production always uses one-hour signed URLs.
    prefix = (settings.object_storage_public_url_prefix or "").strip().rstrip("/")
    if not prefix:
        return None
    return f"{prefix}/{storage_key.lstrip('/')}"


# Presigned read URLs are short-lived display grants, not durable storage (ASSET-01):
# the object in project-owned storage remains the source of truth.
PRESIGNED_URL_EXPIRY_SECONDS = 3600


def build_sketch_image_url(storage_key: Optional[str]) -> Optional[str]:
    """
    Resolves a display URL for a stored sketch object:
    1. stable public URL when OBJECT_STORAGE_PUBLIC_URL_PREFIX is configured;
    2. otherwise a presigned GET URL against the configured S3-compatible storage
       (works for private buckets such as Cloudflare R2 without public access);
    3. None when no storage key or no usable storage configuration exists.
    """
    if not storage_key:
        return None
    public_url = build_public_object_url(storage_key)
    if public_url:
        return public_url
    if not (settings.object_storage_bucket and settings.object_storage_access_key and settings.object_storage_secret_key):
        return None
    sink = ObjectStorageSink()
    try:
        return sink.presigned_read_url(storage_key)
    except Exception as exc:  # presigning is local; failure means misconfiguration
        logger.warning(
            "Failed to presign display URL for sketch object '%s': %s", storage_key, type(exc).__name__
        )
        return None


def _sniff_image_format(payload: bytes) -> Optional[str]:
    """Magic-byte sniffing for the formats this pipeline may produce."""
    if len(payload) >= 12 and payload[0:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"
    if len(payload) >= 8 and payload[0:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(payload) >= 3 and payload[0:3] == b"\xff\xd8\xff":
        return "jpeg"
    return None


def validate_sketch_payload(result: SketchGenerationResult) -> str:
    """
    Validates the payload and returns the CANONICAL image format for the storage
    key: the sniffed magic-byte format when it is supported, which tolerates
    OpenAI-compatible gateways that ignore the requested `output_format` and
    return PNG. Only payloads matching NO supported format are rejected — a
    mislabeled-but-valid image is reclassified, never stored under a false
    extension. Raises SketchStorageError on violation.
    """
    declared = (result.image_format or "").strip().lower()
    sniffed = _sniff_image_format(result.image_bytes)
    if sniffed is None or sniffed not in IMAGE_CONTENT_TYPES:
        raise SketchStorageError(
            f"Sketch payload does not match any supported image format "
            f"(declared={declared}, sniffed={sniffed or 'unknown'}).",
            details={"declared": declared, "sniffed": sniffed},
        )
    if declared != sniffed:
        logger.warning(
            "Provider ignored output_format: requested %s but payload is %s; "
            "storing under the sniffed format.",
            declared,
            sniffed,
        )

    size = len(result.image_bytes)
    if size < MIN_SKETCH_BYTES or size > MAX_SKETCH_BYTES:
        raise SketchStorageError(
            f"Sketch payload size {size} bytes is outside the allowed range "
            f"[{MIN_SKETCH_BYTES}, {MAX_SKETCH_BYTES}].",
            details={"size_bytes": size},
        )
    return sniffed


class ObjectStorageSink:
    """S3-compatible implementation of `SketchResultSink` (ASSET-01)."""

    provider_name = "object-storage"

    def __init__(
        self,
        bucket: Optional[str] = None,
        s3_client=None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.bucket = bucket or settings.object_storage_bucket
        self._s3_client = s3_client
        self._region = region or settings.object_storage_region
        self._endpoint_url = endpoint_url if endpoint_url is not None else settings.object_storage_endpoint
        self._access_key = access_key or settings.object_storage_access_key
        self._secret_key = secret_key or settings.object_storage_secret_key

    @property
    def is_configured(self) -> bool:
        return bool(self.bucket and self._access_key and self._secret_key)

    def _get_client(self):
        if self._s3_client is None:
            self._s3_client = boto3.client(
                "s3",
                region_name=self._region,
                endpoint_url=self._endpoint_url or None,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
            )
        return self._s3_client

    def presigned_read_url(self, storage_key: str, expires_in: int = PRESIGNED_URL_EXPIRY_SECONDS) -> str:
        """Short-lived display grant for a stored object (local computation, no network)."""
        return self._get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_key},
            ExpiresIn=expires_in,
        )

    async def persist(self, *, artifact_id: UUID, result: SketchGenerationResult) -> str:
        """Validates and uploads the payload; returns the stable §11.7 storage key."""
        image_format = validate_sketch_payload(result)
        key = sketch_storage_key(artifact_id, image_format)
        content_type = IMAGE_CONTENT_TYPES[image_format]
        client = self._get_client()

        def _upload() -> None:
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=result.image_bytes,
                ContentType=content_type,
            )

        try:
            await asyncio.to_thread(_upload)
        except SketchStorageError:
            raise
        except Exception as exc:
            # Provider/SDK exceptions are sanitized into a storage-domain error
            # (credentials/URLs never travel in messages, §19.3 spirit).
            raise SketchStorageError(
                f"Object storage upload failed for '{key}'.",
                details={"key": key, "bucket": self.bucket},
                internal_message=f"{type(exc).__name__}: {exc}",
            ) from exc

        logger.info(
            "Sketch artifact %s persisted to object storage (%s bytes, key=%s)",
            artifact_id,
            len(result.image_bytes),
            key,
        )
        return key


def build_default_sketch_sink():
    """
    Worker default sink binding: ObjectStorageSink when storage is configured
    (ASSET-01 production path), LoggingSketchResultSink otherwise (dev only —
    bytes are dropped and storage_key stays None).
    """
    if settings.object_storage_bucket and settings.object_storage_access_key and settings.object_storage_secret_key:
        return ObjectStorageSink()
    logger.warning(
        "OBJECT_STORAGE_BUCKET/keys are not configured; sketch results will not be "
        "persisted (dev fallback). Production requires durable storage per ASSET-01."
    )
    from app.soulmate.services.sketch_generation_service import LoggingSketchResultSink

    return LoggingSketchResultSink()
