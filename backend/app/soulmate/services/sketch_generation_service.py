"""
Sketch generation queue / worker (DEV-SPEC §11.3–11.7, §19; Decisions: ASSET-01, SP-603/SP-604).

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

Worker (`process_next_queued_job`, two-phase for SP-604 retry/idempotency):
- phase A (txn): claim one QUEUED job (SKIP LOCKED) -> PROCESSING + locked_at,
  load the artifact (FOR UPDATE) and short-circuit COMPLETED artifacts without a
  provider call, build the rendered prompt (SP-601) and validate profile inputs
  (invalid/missing inputs fail permanently here, §11.6);
- phase B (no txn held): provider call (SP-602 interface) + result sink;
- phase C (txn): guarded finalization — the job row must still be PROCESSING and
  the artifact must not have completed via another path (a retry never creates a
  second owned sketch after a success); §11.3 metadata persisted on success.
- retry policy (§11.6, max attempts 3): retryable failures requeue with
  exponential backoff (`run_after`) until the attempt budget is exhausted, then
  terminate as FAILED_RETRYABLE; permanent/safety/input failures terminate
  immediately as FAILED_PERMANENT and are never requeued;
- stale-claim reclamation (`reclaim_stale_processing_jobs`): PROCESSING jobs
  whose `locked_at` outlived the claim threshold (worker death mid-call) are
  requeued with the same attempt accounting and budget — crash loops are bounded.

Structured logging follows §19.1 (job_id, artifact_id, provider_request_id);
provider raw errors never reach API responses (§19.3) — clients see only the
derived §10.3 status.

Storage seam (`SketchResultSink`): the worker yields provider bytes to an
app-owned sink; SP-605 provides the durable object-storage implementation. The
shipped default logs and drops bytes (dev only) — production persistence is
incomplete until SP-605 lands.

The provider call is at-least-once (OpenAI image generation has no provider-side
idempotency key): worker death after a provider success but before phase C can
re-run the provider on retry. The OWNED asset can never duplicate (SP-501 DB
uniqueness + phase A/C guards above); provider spend duplication is the residual
risk this design accepts and alerts on.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol, Union, runtime_checkable
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
from app.soulmate.domain.sketch_prompt import RenderedSketchPrompt, build_rendered_sketch_prompt
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

RECLAIM_ERROR_CODE = "CLAIM_STALE"
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


def sketch_idempotency_key(email_normalized: str, artifact_version: str) -> str:
    """`sketch:<email_hash>:<artifact_version>` per DEV-SPEC §11.6."""
    email_hash = hashlib.sha256(email_normalized.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"sketch:{email_hash}:{artifact_version}"


def retry_backoff_seconds(attempt: int) -> float:
    """Exponential backoff per §11.6: base * 2^(attempt-1), minimum one attempt."""
    base = settings.job_retry_base_backoff_seconds
    return base * (2 ** max(0, attempt - 1))


@runtime_checkable
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


@dataclass
class _ClaimedWork:
    """Phase-A output carried across the provider call (no DB objects held)."""
    job_id: UUID
    artifact_id: UUID
    rendered: RenderedSketchPrompt


class SketchGenerationService:
    """Idempotent enqueue + two-phase claim/process for sketch generation."""

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
            # Artifact stuck mid-generation without an active job (e.g. a terminal
            # job after the artifact was reset by support): fall through and
            # converge on the idempotency key.

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
    # Worker (§11.6, SP-604 retry/idempotency)
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

        Two-phase (SP-04 hardening): phase A claims and prepares inside one
        transaction (crash-safe — an uncommitted claim rolls back to QUEUED),
        the provider call runs WITHOUT holding a transaction, and phase C
        finalizes under fresh row locks with completion guards so a retry can
        never produce a second owned sketch after a success.

        `job_id` (optional) scopes the claim to one specific job — used by tests
        and targeted reprocessing; production workers omit it.
        """
        effective_now = now or utc_now()

        prepared = await cls._claim_and_prepare(db_session_factory=AsyncSessionLocal, now=effective_now, job_id=job_id)
        if prepared is None:
            return None
        if isinstance(prepared, str):
            # Terminal state reached during phase A (input failure, short-circuit).
            return prepared
        work = prepared

        # Phase B: provider call + sink, intentionally outside any DB transaction.
        try:
            result = await provider.generate_image(work.rendered.rendered_text)
            storage_key = await sink.persist(artifact_id=work.artifact_id, result=result)
        except SketchProviderError as exc:
            return await cls._finalize_failure(
                job_id=work.job_id,
                artifact_id=work.artifact_id,
                retryable=exc.retryable,
                message=exc.message,
                error_code=exc.error_code.value,
                provider_code=exc.provider_code,
                provider_request_id=exc.provider_request_id,
                details=exc.details,
            )
        except Exception as exc:
            # Infrastructure/unknown failures are treated as transient; the retry
            # budget bounds any persistent bug (§11.6).
            return await cls._finalize_failure(
                job_id=work.job_id,
                artifact_id=work.artifact_id,
                retryable=True,
                message=str(exc)[:300] or type(exc).__name__,
                error_code=INTERNAL_ERROR_CODE,
            )

        return await cls._finalize_success(
            job_id=work.job_id,
            artifact_id=work.artifact_id,
            rendered=work.rendered,
            result=result,
            storage_key=storage_key,
        )

    @classmethod
    async def _claim_and_prepare(
        cls,
        db_session_factory,
        now: datetime,
        job_id: Optional[UUID] = None,
    ) -> Optional[Union[_ClaimedWork, str]]:
        """
        Phase A: claim + input preparation + terminal short-circuits (one txn).

        Returns None when nothing was claimable, a terminal status string when the
        job finalized inside this transaction (completion guard, input failure),
        or the prepared work for the provider call.
        """
        async with db_session_factory() as db:
            try:
                job = await cls._claim_next_queued(db, now, job_id)
                if job is None:
                    return None

                artifact = await cls._lock_artifact(db, job.artifact_id)
                if artifact is None:
                    return await cls._fail_job(
                        db, job, None,
                        retryable=False,
                        message="Sketch artifact row for job is missing.",
                        error_code="ARTIFACT_MISSING",
                    )

                # Completion guard: never call the provider for an owned, completed
                # sketch (duplicate-job / requeue-after-success protection).
                if normalize_generation(artifact.generation_status).value == "COMPLETED":
                    job.attempt = (job.attempt or 0) + 1
                    job.status = JOB_COMPLETED
                    job.locked_at = None
                    job.error_json = {"message": "Artifact already completed; provider call skipped."}
                    await db.commit()
                    logger.info(
                        "Sketch job %s short-circuited: artifact %s already completed",
                        job.id, artifact.id,
                    )
                    return JOB_COMPLETED

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
                except ProfileValidationError as exc:
                    # Invalid/missing generation inputs never resolve by retrying (§11.6).
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=exc.message,
                        error_code=exc.error_code.value,
                        details=exc.details,
                    )

                await db.commit()
                return _ClaimedWork(job_id=job.id, artifact_id=artifact.id, rendered=rendered)
            except Exception:
                await db.rollback()
                raise

    @classmethod
    async def _finalize_success(
        cls,
        *,
        job_id: UUID,
        artifact_id: UUID,
        rendered: RenderedSketchPrompt,
        result: SketchGenerationResult,
        storage_key: Optional[str],
    ) -> str:
        """Phase C success path: guarded §11.3 persistence under fresh row locks."""
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await cls._lock_job(db, job_id)
                artifact = await cls._lock_artifact(db, artifact_id)
                if job is None or artifact is None:
                    logger.error("Sketch finalization lost its job/artifact rows (%s/%s)", job_id, artifact_id)
                    return JOB_FAILED_PERMANENT
                if job.status != JOB_PROCESSING:
                    # The claim was reclaimed or resolved elsewhere while the
                    # provider call ran; discard this result (at-least-once).
                    logger.warning(
                        "Sketch job %s no longer PROCESSING (%s); discarding provider result",
                        job_id, job.status,
                    )
                    return job.status

                # Second completion guard under the row lock.
                if normalize_generation(artifact.generation_status).value == "COMPLETED":
                    job.attempt = (job.attempt or 0) + 1
                    job.status = JOB_COMPLETED
                    job.locked_at = None
                    return JOB_COMPLETED

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
                job.error_json = None

            logger.info(
                "Sketch generation completed for artifact %s (job %s, model=%s, request_id=%s)",
                artifact_id,
                job_id,
                result.model,
                result.provider_request_id,
            )
            return JOB_COMPLETED

    @classmethod
    async def _finalize_failure(
        cls,
        *,
        job_id: UUID,
        artifact_id: Optional[UUID],
        retryable: bool,
        message: str,
        error_code: str,
        provider_code: Optional[str] = None,
        provider_request_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> str:
        """Phase C failure path: bounded requeue with backoff, or terminal failure."""
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await cls._lock_job(db, job_id)
                if job is None:
                    logger.error("Sketch failure handling lost job %s", job_id)
                    return JOB_FAILED_PERMANENT
                artifact = await cls._lock_artifact(db, artifact_id) if artifact_id else None

                if job.status != JOB_PROCESSING:
                    logger.warning(
                        "Sketch job %s no longer PROCESSING (%s); failure result discarded",
                        job_id, job.status,
                    )
                    return job.status

                attempt = (job.attempt or 0) + 1
                job.attempt = attempt
                job.locked_at = None
                job.error_json = {
                    "message": message,
                    "error_code": error_code,
                    "retryable": retryable,
                    "provider_code": provider_code,
                    "provider_request_id": provider_request_id,
                    "attempt": attempt,
                    **({"details": details} if details else {}),
                }

                max_attempts = max(1, settings.job_retry_max_attempts)
                if retryable and attempt < max_attempts:
                    # Bounded transient retry: back to QUEUED with exponential
                    # backoff; the artifact stays PROCESSING (§10.3 GENERATING).
                    job.status = JOB_QUEUED
                    job.run_after = utc_now() + timedelta(seconds=retry_backoff_seconds(attempt))
                    if artifact is not None:
                        artifact.attempt_count = (artifact.attempt_count or 0) + 1
                    logger.warning(
                        "Sketch job %s attempt %s/%s failed retryably (error_code=%s); "
                        "requeued with backoff until %s",
                        job_id, attempt, max_attempts, error_code, job.run_after,
                    )
                    return JOB_QUEUED

                status = JOB_FAILED_RETRYABLE if retryable else JOB_FAILED_PERMANENT
                job.status = status
                if artifact is not None:
                    artifact.attempt_count = (artifact.attempt_count or 0) + 1
                    artifact.generation_status = "FAILED"
                    artifact.last_error_code = error_code
                    artifact.last_error_message = message
                logger.warning(
                    "Sketch job %s reached terminal %s after %s attempt(s) (error_code=%s, provider_code=%s)",
                    job_id, status, attempt, error_code, provider_code,
                )
                return status

    @classmethod
    async def reclaim_stale_processing_jobs(cls, now: Optional[datetime] = None) -> int:
        """
        Requeue PROCESSING jobs whose claim outlived the staleness threshold
        (worker death mid-call). Attempts are consumed the same way as ordinary
        failures so crash loops respect the §11.6 budget.
        """
        effective_now = now or utc_now()
        stale_before = effective_now - timedelta(seconds=settings.job_claim_stale_seconds)
        reclaimed = 0
        async with AsyncSessionLocal() as db:
            async with db.begin():
                stmt = (
                    select(AIGenerationJob)
                    .where(
                        AIGenerationJob.job_type == JOB_TYPE_SKETCH,
                        AIGenerationJob.status == JOB_PROCESSING,
                        AIGenerationJob.locked_at.is_not(None),
                        AIGenerationJob.locked_at < stale_before,
                    )
                    .with_for_update(skip_locked=True)
                )
                jobs = (await db.execute(stmt)).scalars().all()
                for job in jobs:
                    attempt = (job.attempt or 0) + 1
                    job.attempt = attempt
                    job.locked_at = None
                    max_attempts = max(1, settings.job_retry_max_attempts)
                    artifact = await cls._lock_artifact(db, job.artifact_id)
                    if attempt >= max_attempts:
                        job.status = JOB_FAILED_RETRYABLE
                        job.error_json = {
                            "message": "Claim went stale and the retry budget is exhausted.",
                            "error_code": RECLAIM_ERROR_CODE,
                            "retryable": False,
                            "attempt": attempt,
                        }
                        if artifact is not None:
                            artifact.attempt_count = (artifact.attempt_count or 0) + 1
                            artifact.generation_status = "FAILED"
                            artifact.last_error_code = RECLAIM_ERROR_CODE
                            artifact.last_error_message = "Generation claim expired after repeated worker loss."
                    else:
                        job.status = JOB_QUEUED
                        job.run_after = effective_now + timedelta(seconds=retry_backoff_seconds(attempt))
                        job.error_json = {
                            "message": "Claim went stale (worker loss mid-generation); requeued.",
                            "error_code": RECLAIM_ERROR_CODE,
                            "retryable": True,
                            "attempt": attempt,
                        }
                        if artifact is not None:
                            artifact.attempt_count = (artifact.attempt_count or 0) + 1
                    reclaimed += 1
                    logger.warning("Reclaimed stale sketch job %s (attempt %s)", job.id, attempt)
        return reclaimed

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

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
    async def _lock_job(cls, db: AsyncSession, job_id: UUID) -> Optional[AIGenerationJob]:
        stmt = select(AIGenerationJob).where(AIGenerationJob.id == job_id).with_for_update()
        return (await db.execute(stmt)).scalars().first()

    @classmethod
    async def _lock_artifact(cls, db: AsyncSession, artifact_id: UUID) -> Optional[SoulmateArtifact]:
        stmt = select(SoulmateArtifact).where(SoulmateArtifact.id == artifact_id).with_for_update()
        return (await db.execute(stmt)).scalars().first()

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
        """Terminal failure inside the phase-A transaction (input/row problems)."""
        job.attempt = (job.attempt or 0) + 1
        job.status = JOB_FAILED_RETRYABLE if retryable else JOB_FAILED_PERMANENT
        job.locked_at = None
        job.error_json = {
            "message": message,
            "error_code": error_code,
            "retryable": retryable,
            "provider_code": provider_code,
            "provider_request_id": provider_request_id,
            "attempt": job.attempt,
            **({"details": details} if details else {}),
        }
        if artifact is not None:
            artifact.attempt_count = (artifact.attempt_count or 0) + 1
            artifact.generation_status = "FAILED"
            artifact.last_error_code = error_code
            artifact.last_error_message = message
        await db.commit()
        logger.warning(
            "Sketch job %s terminated %s (error_code=%s)",
            job.id, job.status, error_code,
        )
        return job.status

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
        # Lazy imports avoid circular imports at module load (services package).
        from app.soulmate.services.object_storage_sink import build_default_sketch_sink
        from app.soulmate.services.openai_image_provider import OpenAIImageProvider

        self.provider = provider or OpenAIImageProvider()
        self.sink = sink or build_default_sketch_sink()
        self.poll_seconds = (
            poll_seconds if poll_seconds is not None else settings.job_worker_poll_seconds
        )

    async def run_loop(self) -> None:
        # Initial delay keeps short-lived lifespans (tests, quick restarts) harmless.
        await asyncio.sleep(self.poll_seconds)
        while True:
            try:
                reclaimed = await SketchGenerationService.reclaim_stale_processing_jobs()
                processed = await SketchGenerationService.process_next_queued_job(
                    provider=self.provider,
                    sink=self.sink,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sketch generation worker iteration failed.")
                reclaimed, processed = 0, None
            active = bool(processed) or reclaimed > 0
            await asyncio.sleep(0 if active else self.poll_seconds)


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
