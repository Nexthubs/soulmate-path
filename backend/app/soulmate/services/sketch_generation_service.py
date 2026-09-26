"""
Sketch generation queue / worker (DEV-SPEC §11.3–11.7; Decisions: ASSET-01, SP-603).

DB-backed durable queue on `ai_generation_jobs` (SP-501 schema, §11.6 states) —
the repo has no external broker (docker-compose: postgres only), so the smallest
repo-consistent mechanism is a PostgreSQL job table claimed with
`FOR UPDATE SKIP LOCKED`.

Enqueue (`enqueue_sketch_generation`):
- gates: PAY-AUTH-01 entitlement, TIME-01 server-side unlock (on_demand §11.4);
- idempotent per identity: unique `idempotency_key` = `sketch:<email_hash>:<artifact_version>`
  (§11.6) plus a transaction-scoped advisory lock, so concurrent enqueue attempts
  converge on one logical generation;
- never re-enqueues a COMPLETED artifact (no regeneration on revisit/refresh).

Worker (`process_next_queued_job`):
- claims one QUEUED job (SKIP LOCKED) and runs prompt build (SP-601) → provider
  (SP-602 interface) → §11.3 metadata persistence inside the claim transaction,
  so a crashed worker releases the claim automatically (job returns to QUEUED);
- provider failures map to job state FAILED_RETRYABLE / FAILED_PERMANENT via
  `SketchProviderError.retryable`; artifact records last_error_* and attempt_count.

Storage seam (`SketchResultSink`): the worker yields provider bytes to an
app-owned sink; SP-605 provides the durable object-storage implementation. The
shipped default logs and drops bytes (dev only) — production persistence is
incomplete until SP-605 lands.

Retry/backoff scheduling and stale-claim reclamation belong to SP-604; this
module records attempt/run_after state durably for it.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ForbiddenOwnershipError,
    InternalServerError,
    LockedAssetError,
    ValidationError,
)
from app.db.base import utc_now
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.session import SoulmateProfile, SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.domain.artifact_status import normalize_generation
from app.soulmate.domain.profile import ProfileValidationError, SoulmateProfileV1
from app.soulmate.domain.sketch_models import SketchGenerationResult, SketchProviderError
from app.soulmate.domain.sketch_prompt import build_rendered_sketch_prompt
from app.soulmate.services.payment_consistency import payment_lock
from app.soulmate.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

JOB_TYPE_SKETCH = "SOULMATE_SKETCH"

# §11.6 job states
JOB_QUEUED = "QUEUED"
JOB_PROCESSING = "PROCESSING"
JOB_COMPLETED = "COMPLETED"
JOB_FAILED_RETRYABLE = "FAILED_RETRYABLE"
JOB_FAILED_PERMANENT = "FAILED_PERMANENT"

ACTIVE_JOB_STATUSES = (JOB_QUEUED, JOB_PROCESSING)


def sketch_idempotency_key(email_normalized: str, artifact_version: str) -> str:
    """`sketch:<email_hash>:<artifact_version>` per DEV-SPEC §11.6."""
    email_hash = hashlib.sha256(email_normalized.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"sketch:{email_hash}:{artifact_version}"


class SketchResultSink(Protocol):
    """
    App-owned seam between the worker and durable storage (ASSET-01, §11.7).

    Implementations (SP-605) persist `result.image_bytes` to project-owned object
    storage and return the stable storage key. Provider temporary URLs must never
    become the durable source of truth.
    """

    async def persist(self, *, artifact_id: UUID, result: SketchGenerationResult) -> Optional[str]: ...


class LoggingSketchResultSink:
    """
    Dev/default sink: records the generation and drops the bytes.

    Artifact rows completed through this sink carry generation metadata but no
    storage_key; SP-605 replaces this sink with durable object storage.
    """

    async def persist(self, *, artifact_id: UUID, result: SketchGenerationResult) -> Optional[str]:
        logger.warning(
            "Sketch result for artifact %s generated (model=%s, bytes=%s) but durable object "
            "storage is not configured yet (SP-605); bytes are not persisted.",
            artifact_id,
            result.model,
            len(result.image_bytes),
        )
        return None


@dataclass
class SketchEnqueueOutcome:
    artifact: SoulmateArtifact
    job: Optional[AIGenerationJob]
    created: bool


class SketchGenerationService:
    """Idempotent enqueue + transactional claim/process for sketch generation."""

    # ------------------------------------------------------------------
    # Enqueue (API-triggered, §11.4 on_demand)
    # ------------------------------------------------------------------

    @classmethod
    async def enqueue_sketch_generation(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        now: Optional[datetime] = None,
    ) -> SketchEnqueueOutcome:
        """
        Enqueue one logical sketch generation for an entitled, unlocked session.

        Concurrent calls converge on a single job row (unique idempotency key +
        advisory lock). A COMPLETED artifact short-circuits without a new job.
        """
        effective_now = now or utc_now()

        # PAY-AUTH-01: server-confirmed entitlement only.
        if session.subscription_success_at is None:
            raise ForbiddenOwnershipError(
                "Sketch generation is available only after a confirmed first payment (PAY-AUTH-01)."
            )

        email = (session.email_normalized or session.email or "").strip().lower()
        if not email:
            raise ValidationError(
                "Session has no bound email; sketch generation identity cannot be established."
            )

        # SP-501 self-heal (idempotent; acquires the session advisory lock itself).
        await SubscriptionService.ensure_artifacts_for_session(
            session=session,
            paid_at=session.subscription_success_at,
            db=db,
        )

        # Serialize concurrent enqueues for the same identity (§11.5/§11.6).
        await payment_lock(db, "sketch-generate", email)

        artifact = await cls._get_sketch_artifact(db, session.id)
        if artifact is None:
            raise InternalServerError("Sketch artifact row is missing after self-heal.")

        # TIME-01: on_demand trigger only after the persisted unlock time.
        if artifact.unlock_at is None or effective_now < artifact.unlock_at:
            raise LockedAssetError(
                "Sketch is still locked; generation unlocks at the persisted server time (TIME-01)."
            )

        generation = normalize_generation(artifact.generation_status)
        if generation.value == "COMPLETED":
            # §11.4: an existing completed result is returned directly — never regenerated.
            return SketchEnqueueOutcome(artifact=artifact, job=None, created=False)

        key = sketch_idempotency_key(email, artifact.artifact_version)

        if generation.value in ("QUEUED", "PROCESSING"):
            existing = await cls._get_job_by_key(db, key)
            if existing is not None and existing.status in ACTIVE_JOB_STATUSES:
                return SketchEnqueueOutcome(artifact=artifact, job=existing, created=False)
            # Artifact stuck mid-generation without an active job (e.g. pre-SP-604
            # crash recovery): fall through and converge on the idempotency key.

        created = False
        job = AIGenerationJob(
            artifact_id=artifact.id,
            job_type=JOB_TYPE_SKETCH,
            idempotency_key=key,
            status=JOB_QUEUED,
        )
        try:
            async with db.begin_nested():
                db.add(job)
                if generation.value == "NOT_STARTED":
                    artifact.generation_status = "QUEUED"
                await db.flush()
            created = True
        except IntegrityError:
            # A concurrent enqueue inserted the job first — converge on it.
            await db.flush()
            job = await cls._get_job_by_key(db, key)
            if job is None:
                raise

        await db.commit()
        await db.refresh(artifact)
        return SketchEnqueueOutcome(artifact=artifact, job=job, created=created)

    # ------------------------------------------------------------------
    # Worker (§11.6)
    # ------------------------------------------------------------------

    @classmethod
    async def process_next_queued_job(
        cls,
        provider,
        sink: SketchResultSink,
        now: Optional[datetime] = None,
        job_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """
        Claim and process one QUEUED sketch job; returns the final job status.

        The claim (`FOR UPDATE SKIP LOCKED`) and all writes live in one
        transaction: a crash rolls the claim back and the job returns to QUEUED.
        The provider call is therefore at-least-once; SP-604 owns duplicate-spend
        hardening. The DB session/transaction is owned and closed by this method
        so the work survives the triggering request lifecycle.

        `job_id` (optional) scopes the claim to one specific job — used by tests
        and by SP-604-style targeted reprocessing; production workers omit it.
        """
        effective_now = now or utc_now()
        async with AsyncSessionLocal() as db:
            try:
                job = await cls._claim_next_queued(db, effective_now, job_id)
                if job is None:
                    return None
                return await cls._process_claimed_job(db, job, provider, sink)
            except Exception:
                await db.rollback()
                raise

    @classmethod
    async def _claim_next_queued(
        cls,
        db: AsyncSession,
        now: datetime,
        job_id: Optional[UUID] = None,
    ) -> Optional[AIGenerationJob]:
        conditions = [
            AIGenerationJob.job_type == JOB_TYPE_SKETCH,
            AIGenerationJob.status == JOB_QUEUED,
            or_(
                AIGenerationJob.run_after.is_(None),
                AIGenerationJob.run_after <= now,
            ),
        ]
        if job_id is not None:
            conditions.append(AIGenerationJob.id == job_id)
        stmt = (
            select(AIGenerationJob)
            .where(*conditions)
            .order_by(AIGenerationJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = (await db.execute(stmt)).scalars().first()
        if job is None:
            return None
        job.status = JOB_PROCESSING
        job.locked_at = utc_now()
        await db.flush()
        return job

    @classmethod
    async def _process_claimed_job(
        cls,
        db: AsyncSession,
        job: AIGenerationJob,
        provider,
        sink: SketchResultSink,
    ) -> str:
        artifact = await db.get(SoulmateArtifact, job.artifact_id)
        if artifact is None:
            return await cls._fail_job(
                db, job, None,
                retryable=False,
                message="Sketch artifact row for job is missing.",
                error_code="ARTIFACT_MISSING",
            )

        started_at = utc_now()
        if artifact.generation_status in ("NOT_STARTED", "QUEUED"):
            artifact.generation_status = "PROCESSING"
        if artifact.generation_started_at is None:
            artifact.generation_started_at = started_at

        try:
            profile_row = (
                await db.execute(
                    select(SoulmateProfile).where(SoulmateProfile.session_id == artifact.session_id)
                )
            ).scalar_one_or_none()
            if profile_row is None:
                raise ProfileValidationError(
                    "Normalized profile is missing for the sketch session; "
                    "generation inputs cannot be established.",
                )
            profile = SoulmateProfileV1.model_validate(profile_row)
            rendered = build_rendered_sketch_prompt(profile)
            result = await provider.generate_image(rendered.rendered_text)
            storage_key = await sink.persist(artifact_id=artifact.id, result=result)
        except SketchProviderError as exc:
            return await cls._fail_job(
                db, job, artifact,
                retryable=exc.retryable,
                message=exc.message,
                error_code=exc.error_code.value,
                provider_code=exc.provider_code,
                provider_request_id=exc.provider_request_id,
                details=exc.details,
            )
        except ProfileValidationError as exc:
            # Invalid/missing generation inputs never resolve by retrying (§11.6).
            return await cls._fail_job(
                db, job, artifact,
                retryable=False,
                message=exc.message,
                error_code=exc.error_code.value,
                details=exc.details,
            )

        # §11.3: persist provider/model/prompt_version/inputs/request id/time with the asset.
        artifact.provider = result.provider
        artifact.model = result.model
        artifact.prompt_version = rendered.prompt_version
        artifact.input_json = rendered.inputs.model_dump()
        artifact.provider_request_id = result.provider_request_id
        artifact.storage_key = storage_key
        artifact.attempt_count = (artifact.attempt_count or 0) + 1
        artifact.generation_status = "COMPLETED"
        artifact.completed_at = utc_now()

        job.attempt = (job.attempt or 0) + 1
        job.status = JOB_COMPLETED
        job.locked_at = None
        await db.commit()
        logger.info(
            "Sketch generation completed for artifact %s (job %s, model=%s, request_id=%s)",
            artifact.id,
            job.id,
            result.model,
            result.provider_request_id,
        )
        return JOB_COMPLETED

    @classmethod
    async def _fail_job(
        cls,
        db: AsyncSession,
        job: AIGenerationJob,
        artifact: Optional[SoulmateArtifact],
        *,
        retryable: bool,
        message: str,
        error_code: str,
        provider_code: Optional[str] = None,
        provider_request_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> str:
        status = JOB_FAILED_RETRYABLE if retryable else JOB_FAILED_PERMANENT
        job.attempt = (job.attempt or 0) + 1
        job.status = status
        job.locked_at = None
        job.error_json = {
            "message": message,
            "error_code": error_code,
            "retryable": retryable,
            "provider_code": provider_code,
            "provider_request_id": provider_request_id,
            **({"details": details} if details else {}),
        }
        if artifact is not None:
            artifact.attempt_count = (artifact.attempt_count or 0) + 1
            artifact.generation_status = "FAILED"
            artifact.last_error_code = error_code
            artifact.last_error_message = message
        await db.commit()
        logger.warning(
            "Sketch generation job %s ended %s (error_code=%s, provider_code=%s)",
            job.id,
            status,
            error_code,
            provider_code,
        )
        return status

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    @classmethod
    async def _get_sketch_artifact(cls, db: AsyncSession, session_id) -> Optional[SoulmateArtifact]:
        stmt = select(SoulmateArtifact).where(
            SoulmateArtifact.session_id == session_id,
            SoulmateArtifact.artifact_type == "SKETCH",
        )
        return (await db.execute(stmt)).scalars().first()

    @classmethod
    async def _get_job_by_key(cls, db: AsyncSession, key: str) -> Optional[AIGenerationJob]:
        stmt = select(AIGenerationJob).where(AIGenerationJob.idempotency_key == key)
        return (await db.execute(stmt)).scalars().first()


class SketchGenerationWorker:
    """In-process asyncio worker polling the DB-backed sketch job queue (§11.6)."""

    def __init__(
        self,
        provider=None,
        sink: Optional[SketchResultSink] = None,
        poll_seconds: Optional[float] = None,
    ):
        # Lazy import avoids a circular import at module load (services package).
        from app.soulmate.services.openai_image_provider import OpenAIImageProvider

        self.provider = provider or OpenAIImageProvider()
        self.sink = sink or LoggingSketchResultSink()
        self.poll_seconds = (
            poll_seconds if poll_seconds is not None else settings.job_worker_poll_seconds
        )

    async def run_loop(self) -> None:
        # Initial delay keeps short-lived lifespans (tests, quick restarts) harmless.
        await asyncio.sleep(self.poll_seconds)
        while True:
            try:
                processed = await SketchGenerationService.process_next_queued_job(
                    provider=self.provider,
                    sink=self.sink,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sketch generation worker iteration failed.")
                processed = False
            await asyncio.sleep(0 if processed else self.poll_seconds)


def start_sketch_workers() -> list:
    """Starts the configured number of in-process workers (no-op when disabled)."""
    if not settings.job_worker_enabled:
        return []
    return [
        asyncio.create_task(
            SketchGenerationWorker().run_loop(),
            name=f"sketch-generation-worker-{index + 1}",
        )
        for index in range(max(1, settings.job_worker_concurrency))
    ]


async def stop_sketch_workers(tasks: list) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
