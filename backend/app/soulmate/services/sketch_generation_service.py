"""
Sketch generation queue / worker (DEV-SPEC §11.3–11.7, §19; Decisions: ASSET-01, SP-603/604/606).

DB-backed durable queue on `ai_generation_jobs` (SP-501 schema, §11.6 states) —
the repo has no external broker (docker-compose: postgres only), so the smallest
repo-consistent mechanism is a PostgreSQL job table claimed with
`FOR UPDATE SKIP LOCKED`.

Enqueue (`enqueue_sketch_generation`):
- gates: PAY-AUTH-01 entitlement, TIME-01 server-side unlock gated on the ASSET's
  persisted `unlock_at` (on_demand §11.4), triggerable by any entitled session of
  the identity (write path is identity-level, SP-606);
- idempotent per identity: unique `idempotency_key` = `sketch:<email_hash>:<artifact_version>`
  (§11.6) plus a transaction-scoped advisory lock, so concurrent enqueue attempts
  converge on one logical generation;
- never re-enqueues a COMPLETED artifact (no regeneration on revisit/refresh);
- §10.3 bounded user retry: a FAILED artifact whose terminal job is
  FAILED_RETRYABLE and whose consumed attempts are under the hard cap
  (2 × JOB_RETRY_MAX_ATTEMPTS) is requeued in place by an explicit user retry;
  FAILED_PERMANENT jobs never requeue here (support path).

Worker (`process_next_queued_job`, two-phase):
- phase A (txn): claim one QUEUED job (SKIP LOCKED) -> PROCESSING, consuming one
  attempt (`job.attempt` is the CLAIM FENCE TOKEN); completion guard (a COMPLETED
  artifact short-circuits without a provider call); prompt build (SP-601) and
  profile validation (invalid/missing inputs fail permanently);
- phase B (no txn held): provider call only (SP-602 interface);
- phase C (txn, fenced): finalizes only when the job is STILL PROCESSING and
  `job.attempt` equals the claim token — a stale worker whose claim was reclaimed
  (or superseded by a later claim) can never commit. The durable upload runs
  INSIDE this fenced section, so only the surviving attempt ever writes the
  §11.7 key and the object can never be overwritten by a discarded late worker.
  A non-empty storage key is mandatory: without one the job fails
  (STORAGE_NOT_CONFIGURED, permanent) instead of completing — ASSET-01 §11.7.
- retry policy (§11.6): retryable failures requeue with exponential backoff until
  the attempt budget is exhausted, then terminate as FAILED_RETRYABLE; permanent
  failures (invalid input, policy rejection, storage unavailable) terminate
  immediately as FAILED_PERMANENT and are never requeued;
- stale-claim reclamation (`reclaim_stale_processing_jobs`): PROCESSING jobs
  whose `locked_at` outlived the claim threshold (worker death mid-call) are
  requeued with the same attempt accounting — crash loops are bounded.

Structured logging follows §19.1 (job_id, artifact_id, provider_request_id);
provider raw errors never reach API responses (§19.3).

The provider call is at-least-once (OpenAI image generation has no provider-side
idempotency key): worker death after a provider success but before phase C can
re-run the provider on retry. The OWNED asset can never duplicate or mismatch
(fence + single-fenced-upload above); provider spend duplication is the residual
risk this design accepts and alerts on.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError as PydanticValidationError

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
from app.soulmate.analytics import track_funnel_event
from app.soulmate.metrics import record_generation_metric
from app.soulmate.domain.artifact_status import normalize_generation
from app.soulmate.domain.profile import ProfileValidationError, SoulmateProfileV1
from app.soulmate.domain.sketch_models import SketchGenerationResult, SketchProviderError
from app.soulmate.domain.sketch_prompt import (
    RenderedSketchPrompt,
    SketchPromptInputError,
    SketchPromptTemplateError,
    build_rendered_sketch_prompt,
)
from app.soulmate.services.object_storage_sink import (
    SketchStorageError,
    SketchStorageUnavailableError,
)
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

RECLAIM_ERROR_CODE = "CLAIM_STALE"
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
STORAGE_NOT_CONFIGURED_CODE = "STORAGE_NOT_CONFIGURED"
BUDGET_EXHAUSTED_CODE = "ATTEMPT_BUDGET_EXHAUSTED"

def sketch_idempotency_key(email_normalized: str, artifact_version: str) -> str:
    """`sketch:<email_hash>:<artifact_version>` per DEV-SPEC §11.6."""
    email_hash = hashlib.sha256(email_normalized.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"sketch:{email_hash}:{artifact_version}"


def retry_backoff_seconds(attempt: int) -> float:
    """Exponential backoff per §11.6: base * 2^(attempt-1), minimum one attempt."""
    base = settings.job_retry_base_backoff_seconds
    return base * (2 ** max(0, attempt - 1))


def hard_attempt_cap() -> int:
    """
    Total consumed attempts (auto + user retries) after which a FAILED_RETRYABLE
    job can no longer be requeued by user action (§10.3 bounded retry policy).
    """
    return 2 * max(1, settings.job_retry_max_attempts)


def _record_job_event(job: AIGenerationJob, entry: Dict[str, Any]) -> None:
    """
    Appends one entry to the job's attempt history (M-02, §11.3/§19).
    A worker that dies before persisting a provider response cannot record that
    response's request id; its claim remains visible as an unknown outcome.
    """
    entry = {"at": utc_now().isoformat(), **entry}
    existing = job.error_json if isinstance(job.error_json, dict) else {}
    history = list(existing.get("attempts") or [])
    history.append(entry)
    job.error_json = {**existing, "attempts": history}


@runtime_checkable
class SketchResultSink(Protocol):
    """
    App-owned seam between the worker and durable storage (ASSET-01, §11.7).

    Implementations persist `result.image_bytes` to project-owned object storage
    and return the stable storage key. Provider temporary URLs must never become
    the durable source of truth. A generation may only complete when this returns
    a non-empty key; a sink without durable storage must raise.
    """

    async def persist(self, *, artifact_id: UUID, result: SketchGenerationResult) -> str: ...


class LoggingSketchResultSink:
    """
    Dev sink for deployments without OBJECT_STORAGE_* configuration.

    ASSET-01 forbids completing a generation without durable persistence, so this
    sink does NOT drop bytes and fake success — it fails the attempt permanently
    with STORAGE_NOT_CONFIGURED (visible in the job/artifact error fields and
    §19.2 alerts) instead of producing a COMPLETED artifact with no image.
    """

    async def persist(self, *, artifact_id: UUID, result: SketchGenerationResult) -> str:
        logger.error(
            "OBJECT_STORAGE_* is not configured; refusing to complete sketch generation "
            "for artifact %s without durable persistence (ASSET-01, §11.7).",
            artifact_id,
        )
        raise SketchStorageUnavailableError(
            "Object storage is not configured; the sketch cannot be durably persisted."
        )


@dataclass
class SketchEnqueueOutcome:
    artifact: SoulmateArtifact
    job: Optional[AIGenerationJob]
    created: bool
    # True when the resolved identity-owned sketch artifact belongs to a DIFFERENT
    # session of the same normalized email. Reads stay session-scoped (RECOVERY-01):
    # the caller must not expose the owning session's job/artifact state to this
    # session (the endpoint therefore reports job_status=None for cross-session
    # outcomes). Write-side convergence (one logical generation per identity, §11.5)
    # is unaffected.
    cross_session: bool = False


@dataclass
class _ClaimedWork:
    """Phase-A output carried across the provider call (no DB objects held)."""
    job_id: UUID
    artifact_id: UUID
    rendered: RenderedSketchPrompt
    # Fencing token: the attempt count consumed by THIS claim (§11.6). Phase C
    # finalizes only when the job's attempt still equals this value.
    claim_attempt: int


class SketchGenerationService:
    """Idempotent enqueue + two-phase fenced claim/process for sketch generation."""

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
        Enqueue the ONE logical sketch generation owned by the session's normalized
        email identity (§11.5, SP-606).

        Identity-level rules (canonical DB key: `email_normalized`, enforced by
        `uq_soulmate_one_sketch_per_email`; `user_id` is deterministically derived
        from the email in SP-301 but never set on anonymous sessions):
        - identity asset COMPLETED → returned as-is, never regenerated;
        - any existing job for the identity → converged on, never a second job;
          a FAILED_RETRYABLE terminal job under the hard attempt cap is requeued
          in place by an explicit user retry (§10.3 bounded retry);
        - no job yet → exactly one is created, TIME-01-gated by the ASSET's
          persisted `unlock_at`.

        Cross-session reads stay session-scoped (Decision RECOVERY-01): outcomes
        resolved against another session's artifact carry `cross_session=True` and
        `job=None` so callers never expose the owning session's state.
        """
        effective_now = now or utc_now()

        # PAY-AUTH-01: server-confirmed entitlement only.
        if session.subscription_success_at is None:
            raise ForbiddenOwnershipError(
                "Sketch generation is available only after a confirmed first payment."
            )

        # PAID-THROUGH-01: a known-and-passed paid window cannot start new
        # generations (uniform API-layer enforcement).
        await SubscriptionService.assert_paid_access_window(db, session, effective_now)

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

        artifact = await cls._resolve_identity_sketch_artifact(db, session, email)
        if artifact is None:
            raise InternalServerError("Sketch artifact row is missing after self-heal.")

        own = artifact.session_id == session.id
        generation = normalize_generation(artifact.generation_status)
        key = sketch_idempotency_key(email, artifact.artifact_version)

        # §11.5: an identity-owned COMPLETED asset is never regenerated.
        if generation.value == "COMPLETED":
            return SketchEnqueueOutcome(
                artifact=artifact, job=None, created=False, cross_session=not own
            )

        # §11.5: at most one job per identity — converge on the existing record.
        existing_job = await cls._get_job_by_key(db, key)
        if existing_job is not None:
            # §10.3 bounded user retry: only a transient-exhausted terminal job
            # (FAILED_RETRYABLE) under the hard attempt cap may be requeued in
            # place. FAILED_PERMANENT and over-cap jobs stay terminal (support).
            if (
                existing_job.status == JOB_FAILED_RETRYABLE
                and generation.value == "FAILED"
                and (existing_job.attempt or 0) < hard_attempt_cap()
            ):
                existing_job.status = JOB_QUEUED
                existing_job.run_after = None
                existing_job.locked_at = None
                existing_job.error_json = {
                    **(existing_job.error_json or {}),
                    "user_retry": True,
                    "user_retry_grant_pending": True,
                    "requeued_at": utc_now().isoformat(),
                }
                _record_job_event(
                    existing_job,
                    {
                        "event": "user_retry",
                        "attempt": existing_job.attempt or 0,
                        "message": "Explicit user retry requeued the terminal FAILED_RETRYABLE job in place.",
                    },
                )
                artifact.generation_status = "QUEUED"
                await db.commit()
                await db.refresh(artifact)
                logger.info(
                    "User retry requeued sketch job %s (attempt %s/%s)",
                    existing_job.id,
                    existing_job.attempt,
                    hard_attempt_cap(),
                )
                # §19/SP-902: user-triggered requeues count toward retry volume.
                record_generation_metric(
                    "generation_user_retry",
                    job_id=existing_job.id,
                    artifact_id=artifact.id,
                    session_id=str(artifact.session_id),
                    fields={"job_type": JOB_TYPE_SKETCH, "attempt": existing_job.attempt or 0},
                )
                return SketchEnqueueOutcome(
                    artifact=artifact,
                    job=existing_job if own else None,  # job state is only for the owning session
                    created=False,
                    cross_session=not own,
                )
            # §19/SP-902: idempotency conflicts (re-enqueue converging on the
            # existing job) are only observable through this metric stream —
            # they leave no durable DB trace.
            record_generation_metric(
                "enqueue_duplicate",
                job_id=existing_job.id,
                artifact_id=artifact.id,
                session_id=str(artifact.session_id),
                fields={"job_type": JOB_TYPE_SKETCH},
            )
            return SketchEnqueueOutcome(
                artifact=artifact,
                job=existing_job if own else None,  # job state is only for the owning session
                created=False,
                cross_session=not own,
            )

        # No job exists yet. TIME-01 gates on the asset's persisted unlock time —
        # the same server-side rule regardless of which entitled session triggers.
        if artifact.unlock_at is None or effective_now < artifact.unlock_at:
            raise LockedAssetError(
                "Sketch is still locked; generation unlocks at the persisted server time."
            )

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
        if created:
            # §19/SP-902: one metric per logically created generation job.
            record_generation_metric(
                "enqueue_created",
                job_id=job.id,
                artifact_id=artifact.id,
                session_id=str(artifact.session_id),
                fields={"job_type": JOB_TYPE_SKETCH},
            )
        return SketchEnqueueOutcome(
            artifact=artifact,
            job=job if own else None,  # same isolation rule as convergence above
            created=created,
            cross_session=not own,
        )

    # ------------------------------------------------------------------
    # Worker (§11.6, SP-604 retry/idempotency, fenced per review R1)
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

        Two-phase with a claim fence: phase A claims and prepares inside one
        transaction (the consumed `job.attempt` is the fence token), the provider
        call runs WITHOUT holding a transaction, and phase C finalizes only when
        the fence still matches — a stale worker whose claim was reclaimed or
        superseded can never commit, and only the surviving attempt performs the
        durable upload (inside phase C), so the §11.7 object can never be
        overwritten by a discarded late worker.

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

        # Phase B: provider call only — no storage writes before the fence.
        try:
            result = await provider.generate_image(work.rendered.rendered_text)
        except SketchProviderError as exc:
            return await cls._finalize_failure(
                job_id=work.job_id,
                artifact_id=work.artifact_id,
                claim_attempt=work.claim_attempt,
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
                claim_attempt=work.claim_attempt,
                retryable=True,
                message=str(exc)[:300] or type(exc).__name__,
                error_code=INTERNAL_ERROR_CODE,
            )

        return await cls._finalize_success(
            job_id=work.job_id,
            artifact_id=work.artifact_id,
            claim_attempt=work.claim_attempt,
            rendered=work.rendered,
            result=result,
            sink=sink,
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
        or the prepared work (with the claim fence token) for the provider call.
        """
        async with db_session_factory() as db:
            try:
                job, budget_exhausted = await cls._claim_next_queued(db, now, job_id)
                if job is None:
                    return None
                if budget_exhausted:
                    # Crash-loop terminal (M-01): the budget was consumed by real
                    # claims; terminate without another provider opportunity.
                    artifact = await cls._lock_artifact(db, job.artifact_id)
                    if artifact is not None:
                        artifact.generation_status = "FAILED"
                        artifact.last_error_code = BUDGET_EXHAUSTED_CODE
                        artifact.last_error_message = (
                            "Generation attempt budget exhausted after repeated worker loss."
                        )
                    await db.commit()
                    logger.warning(
                        "Sketch job %s terminated %s at claim time (crash-loop budget exhausted)",
                        job.id, JOB_FAILED_RETRYABLE,
                    )
                    # §19/SP-902: crash-loop terminal counts as a final failure.
                    record_generation_metric(
                        "generation_final_failure",
                        job_id=job.id,
                        artifact_id=job.artifact_id,
                        session_id=str(artifact.session_id) if artifact is not None else None,
                        fields={
                            "job_type": JOB_TYPE_SKETCH,
                            "error_code": BUDGET_EXHAUSTED_CODE,
                            "attempts": job.attempt or 0,
                        },
                    )
                    track_funnel_event(
                        "soulmate_sketch_generation_failed",
                        session_id=str(artifact.session_id) if artifact is not None else None,
                        properties={"error_code": BUDGET_EXHAUSTED_CODE, "attempts": job.attempt or 0},
                    )
                    return JOB_FAILED_RETRYABLE
                claim_attempt = job.attempt or 0

                artifact = await cls._lock_artifact(db, job.artifact_id)
                if artifact is None:
                    return await cls._fail_job(
                        db, job, None,
                        retryable=False,
                        message="Sketch artifact row for job is missing.",
                        error_code="ARTIFACT_MISSING",
                    )

                # Completion guard: never call the provider for an owned, completed
                # sketch (duplicate-job / requeue-after-success protection). The
                # claim already consumed the attempt — no further increment.
                if normalize_generation(artifact.generation_status).value == "COMPLETED":
                    job.status = JOB_COMPLETED
                    job.locked_at = None
                    _record_job_event(
                        job,
                        {
                            "event": "completed",
                            "attempt": job.attempt or 0,
                            "message": "Artifact already completed; provider call skipped.",
                        },
                    )
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

                # The DB read stays outside the classification boundary: a
                # transient database error must keep its rollback-and-retry
                # semantics. Everything from profile materialization to the
                # rendered prompt is deterministic, in-process work (H-01): any
                # failure there is an invalid-input/template failure (§11.6,
                # §12) and MUST terminate the job permanently instead of
                # rolling the claim back into a poison-poll loop.
                profile_row = (
                    await db.execute(
                        select(SoulmateProfile).where(SoulmateProfile.session_id == artifact.session_id)
                    )
                ).scalar_one_or_none()

                try:
                    if profile_row is None:
                        raise ProfileValidationError(
                            "Normalized profile is missing for the sketch session; "
                            "generation inputs cannot be established.",
                        )
                    profile = SoulmateProfileV1.model_validate(profile_row)
                    rendered = build_rendered_sketch_prompt(profile)
                except ProfileValidationError as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=exc.message,
                        error_code=exc.error_code.value,
                        details=exc.details,
                    )
                except SketchPromptTemplateError as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=exc.message,
                        error_code="PROMPT_TEMPLATE_INVALID",
                        details=getattr(exc, "details", {}) or None,
                    )
                except SketchPromptInputError as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=exc.message,
                        error_code="PROMPT_INPUT_INVALID",
                        details=getattr(exc, "details", {}) or None,
                    )
                except PydanticValidationError as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=f"Persisted profile failed validation: {str(exc)[:300]}",
                        error_code="PROFILE_INVALID",
                    )
                except Exception as exc:
                    # Deterministic non-I/O failure while materializing the
                    # prompt (e.g. an unmapped encoding edge) — treated as an
                    # invalid-input terminal state per §11.6, never a
                    # rollback-requeue loop.
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=f"Prompt materialization failed: {type(exc).__name__}: {str(exc)[:200]}",
                        error_code="PROMPT_BUILD_FAILED",
                    )

                await db.commit()
                # §19/SP-902: queue latency = enqueue → this claim.
                queue_latency_ms = None
                if job.created_at is not None:
                    queue_latency_ms = max(0, int((started_at - job.created_at).total_seconds() * 1000))
                record_generation_metric(
                    "queue_latency_ms",
                    job_id=job.id,
                    artifact_id=artifact.id,
                    session_id=str(artifact.session_id),
                    fields={
                        "job_type": JOB_TYPE_SKETCH,
                        "latency_ms": queue_latency_ms,
                        "attempt": claim_attempt,
                    },
                )
                # §18.1: the provider call for this claim has started.
                track_funnel_event(
                    "soulmate_sketch_generation_started",
                    session_id=str(artifact.session_id),
                    properties={
                        "model": settings.soulmate_image_model,
                        "prompt_version": rendered.prompt_version,
                    },
                )
                return _ClaimedWork(
                    job_id=job.id,
                    artifact_id=artifact.id,
                    rendered=rendered,
                    claim_attempt=claim_attempt,
                )
            except Exception:
                await db.rollback()
                raise

    @classmethod
    async def _finalize_success(
        cls,
        *,
        job_id: UUID,
        artifact_id: UUID,
        claim_attempt: int,
        rendered: RenderedSketchPrompt,
        result: SketchGenerationResult,
        sink: SketchResultSink,
    ) -> str:
        """
        Phase C success path (fenced): persist the durable asset INSIDE the fence,
        then commit §11.3 metadata + COMPLETED. A generation without a non-empty
        storage key can never complete (ASSET-01, §11.7).
        """
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await cls._lock_job(db, job_id)
                artifact = await cls._lock_artifact(db, artifact_id)
                if job is None or artifact is None:
                    logger.error("Sketch finalization lost its job/artifact rows (%s/%s)", job_id, artifact_id)
                    return JOB_FAILED_PERMANENT

                # Fence: a reclaimed/superseded claim may not commit anything —
                # and since the upload happens below, it can never overwrite the
                # surviving attempt's object either.
                if job.status != JOB_PROCESSING or (job.attempt or 0) != claim_attempt:
                    logger.warning(
                        "Sketch job %s fence mismatch (status=%s attempt=%s claim=%s); "
                        "discarding provider result",
                        job_id, job.status, job.attempt, claim_attempt,
                    )
                    _record_job_event(
                        job,
                        {
                            "event": "fence_discarded",
                            "attempt": claim_attempt,
                            "provider_request_id": result.provider_request_id,
                            "job_status": job.status,
                            "message": "Stale worker result discarded at the fence; no state or storage write.",
                        },
                    )
                    return job.status

                # Second completion guard under the row lock.
                if normalize_generation(artifact.generation_status).value == "COMPLETED":
                    job.status = JOB_COMPLETED
                    job.locked_at = None
                    return JOB_COMPLETED

                # Durable persistence happens here — after the fence, before any
                # success state is written. Failures fall through to the same-txn
                # failure path; a COMPLETED artifact without a storage key is
                # structurally impossible.
                try:
                    storage_key = await sink.persist(artifact_id=artifact.id, result=result)
                    if not storage_key or not str(storage_key).strip():
                        raise SketchStorageUnavailableError(
                            "Sink returned an empty storage key; refusing to complete."
                        )
                except SketchStorageUnavailableError as exc:
                    logger.error("Sketch job %s: %s", job_id, exc)
                    return await cls._write_failure_locked(
                        db, job, artifact,
                        claim_attempt=claim_attempt,
                        retryable=False,
                        message=exc.message,
                        error_code=STORAGE_NOT_CONFIGURED_CODE,
                        provider_request_id=result.provider_request_id,
                    )
                except SketchStorageError as exc:
                    # Upload/validation failure: same bounded budget as provider
                    # errors (fresh object write overwrites nothing referenced).
                    logger.warning("Sketch job %s storage error: %s", job_id, exc.message)
                    return await cls._write_failure_locked(
                        db, job, artifact,
                        claim_attempt=claim_attempt,
                        retryable=True,
                        message=exc.message,
                        error_code="STORAGE_ERROR",
                        provider_request_id=result.provider_request_id,
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

                job.status = JOB_COMPLETED
                # Captured BEFORE the claim fence is released: winning-claim →
                # completion is the §19/SP-902 generation latency.
                winning_claim_at = job.locked_at
                job.locked_at = None
                # M-02: keep the append-only attempt history on success — the
                # artifact carries the WINNING request id, the job history carries
                # every earlier (failed/discarded/reclaimed) call's id too.
                _record_job_event(
                    job,
                    {
                        "event": "completed",
                        "attempt": claim_attempt,
                        "provider_request_id": result.provider_request_id,
                        "model": result.model,
                        "storage_key": storage_key,
                    },
                )
                # Captured inside the fenced txn for the post-commit §18.1 event.
                gen_started_at = artifact.generation_started_at
                gen_completed_at = artifact.completed_at
                gen_session_id = artifact.session_id

            logger.info(
                "Sketch generation completed for artifact %s (job %s, model=%s, request_id=%s, key=%s)",
                artifact_id,
                job_id,
                result.model,
                result.provider_request_id,
                storage_key,
            )
            latency_ms = None
            if gen_started_at is not None and gen_completed_at is not None:
                latency_ms = int((gen_completed_at - gen_started_at).total_seconds() * 1000)
            # §19/SP-902: winning-claim → durable completion on the metrics stream.
            generation_latency_ms = None
            if winning_claim_at is not None and gen_completed_at is not None:
                generation_latency_ms = max(0, int((gen_completed_at - winning_claim_at).total_seconds() * 1000))
            record_generation_metric(
                "generation_success",
                job_id=job_id,
                artifact_id=artifact_id,
                session_id=str(gen_session_id) if gen_session_id else None,
                fields={
                    "job_type": JOB_TYPE_SKETCH,
                    "latency_ms": generation_latency_ms,
                    "attempts": claim_attempt,
                },
            )
            track_funnel_event(
                "soulmate_sketch_generation_completed",
                session_id=str(gen_session_id) if gen_session_id else None,
                properties={"latency_ms": latency_ms, "attempts": claim_attempt},
            )
            return JOB_COMPLETED

    @classmethod
    async def _finalize_failure(
        cls,
        *,
        job_id: UUID,
        artifact_id: Optional[UUID],
        claim_attempt: int,
        retryable: bool,
        message: str,
        error_code: str,
        provider_code: Optional[str] = None,
        provider_request_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> str:
        """Phase C failure path (fenced): bounded requeue with backoff, or terminal."""
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await cls._lock_job(db, job_id)
                if job is None:
                    logger.error("Sketch failure handling lost job %s", job_id)
                    return JOB_FAILED_PERMANENT
                artifact = await cls._lock_artifact(db, artifact_id) if artifact_id else None

                # Fence: only the attempt that owns the current claim may report.
                if job.status != JOB_PROCESSING or (job.attempt or 0) != claim_attempt:
                    logger.warning(
                        "Sketch job %s fence mismatch on failure report (status=%s attempt=%s claim=%s); "
                        "failure result discarded",
                        job_id, job.status, job.attempt, claim_attempt,
                    )
                    _record_job_event(
                        job,
                        {
                            "event": "fence_discarded",
                            "attempt": claim_attempt,
                            "error_code": error_code,
                            "provider_request_id": provider_request_id,
                            "job_status": job.status,
                            "message": "Stale worker failure report discarded at the fence.",
                        },
                    )
                    return job.status

                return await cls._write_failure_locked(
                    db, job, artifact,
                    claim_attempt=claim_attempt,
                    retryable=retryable,
                    message=message,
                    error_code=error_code,
                    provider_code=provider_code,
                    provider_request_id=provider_request_id,
                    details=details,
                )

    @classmethod
    async def _write_failure_locked(
        cls,
        db: AsyncSession,
        job: AIGenerationJob,
        artifact: Optional[SoulmateArtifact],
        *,
        claim_attempt: int,
        retryable: bool,
        message: str,
        error_code: str,
        provider_code: Optional[str] = None,
        provider_request_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> str:
        """
        Failure decision written inside the caller's already-locked transaction:
        bounded requeue with exponential backoff while the attempt budget lasts,
        terminal (FAILED_RETRYABLE / FAILED_PERMANENT) once exhausted. The caller's
        `db.begin()` commits. The outcome (including its provider request id) is
        appended to the job's attempt history (M-02).
        """
        job.locked_at = None
        # Carry the existing attempt history forward before overwriting the
        # top-level "latest outcome" fields (the claim event lives here too).
        prior_attempts = list((job.error_json or {}).get("attempts") or []) if isinstance(job.error_json, dict) else []
        job.error_json = {
            "message": message,
            "error_code": error_code,
            "retryable": retryable,
            "provider_code": provider_code,
            "provider_request_id": provider_request_id,
            "attempt": claim_attempt,
            "attempts": prior_attempts,
            **({"details": details} if details else {}),
        }
        # Append AFTER the top-level "latest outcome" fields are set, so the
        # helper preserves them and grows the attempts timeline (M-02).
        _record_job_event(
            job,
            {
                "event": "failed",
                "attempt": claim_attempt,
                "error_code": error_code,
                "retryable": retryable,
                "provider_code": provider_code,
                "provider_request_id": provider_request_id,
                "message": message[:300],
            },
        )

        max_attempts = max(1, settings.job_retry_max_attempts)
        if retryable and claim_attempt < max_attempts:
            # Bounded transient retry: back to QUEUED with exponential backoff;
            # the artifact stays PROCESSING (§10.3 GENERATING).
            job.status = JOB_QUEUED
            backoff = retry_backoff_seconds(claim_attempt)
            job.run_after = utc_now() + timedelta(seconds=backoff)
            if artifact is not None:
                artifact.attempt_count = (artifact.attempt_count or 0) + 1
            logger.warning(
                "Sketch job %s attempt %s/%s failed retryably (error_code=%s); "
                "requeued with backoff until %s",
                job.id, claim_attempt, max_attempts, error_code, job.run_after,
            )
            # §19/SP-902: retryable requeues count toward retry volume.
            record_generation_metric(
                "generation_retry",
                job_id=job.id,
                artifact_id=artifact.id if artifact is not None else None,
                session_id=str(artifact.session_id) if artifact is not None else None,
                fields={
                    "job_type": JOB_TYPE_SKETCH,
                    "error_code": error_code,
                    "attempt": claim_attempt,
                    "backoff_seconds": backoff,
                },
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
            job.id, status, claim_attempt, error_code, provider_code,
        )
        # §18.1 terminal failure only — bounded retries stay off the funnel.
        track_funnel_event(
            "soulmate_sketch_generation_failed",
            session_id=str(artifact.session_id) if artifact is not None else None,
            properties={"error_code": error_code, "attempts": claim_attempt},
        )
        # §19/SP-902: the same terminal outcome on the metrics stream.
        record_generation_metric(
            "generation_final_failure",
            job_id=job.id,
            artifact_id=artifact.id if artifact is not None else None,
            session_id=str(artifact.session_id) if artifact is not None else None,
            fields={
                "job_type": JOB_TYPE_SKETCH,
                "error_code": error_code,
                "attempts": claim_attempt,
            },
        )
        return status

    @classmethod
    async def reclaim_stale_processing_jobs(cls, now: Optional[datetime] = None) -> int:
        """
        Requeue PROCESSING jobs whose claim outlived the staleness threshold
        (worker death mid-call).

        M-01: reclamation does NOT charge the attempt budget — the stale claim
        was already charged when it was claimed, and charging again at reclaim
        made one crashed logical attempt consume two budget slots. The budget is
        instead enforced at claim time (see `_claim_next_queued`), so a crash
        loop is bounded by the number of actual claims. The fence token stays
        intact: the next claim bumps `attempt`, discarding any late worker from
        the stale claim.
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
                    attempt = job.attempt or 0
                    job.locked_at = None
                    job.status = JOB_QUEUED
                    job.run_after = effective_now + timedelta(seconds=retry_backoff_seconds(max(1, attempt)))
                    _record_job_event(
                        job,
                        {
                            "event": "reclaimed",
                            "attempt": attempt,
                            "error_code": RECLAIM_ERROR_CODE,
                            "retryable": True,
                            "message": "Claim went stale (worker loss mid-generation); requeued without charging.",
                        },
                    )
                    reclaimed += 1
                    logger.warning(
                        "Reclaimed stale sketch job %s (attempt %s unchanged; budget enforced at claim)",
                        job.id, attempt,
                    )
        if reclaimed:
            # §19/SP-902: stale-claim reclamation count (worker-loss signal).
            record_generation_metric(
                "generation_stale_reclaimed",
                fields={"job_type": JOB_TYPE_SKETCH, "count": reclaimed},
            )
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
    ) -> "tuple[Optional[AIGenerationJob], bool]":
        """
        Claims one QUEUED job under row lock.

        Returns `(job, budget_exhausted)`. `budget_exhausted=True` means the job
        was terminated inside this transaction instead of being claimed: every
        budget slot had been consumed by REAL claims. An explicit user retry
        grants exactly one additional claim, represented by a persistent flag
        consumed at claim time. History events never act as authorization.
        """
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
            return None, False

        max_attempts = max(1, settings.job_retry_max_attempts)
        metadata = job.error_json if isinstance(job.error_json, dict) else {}
        user_retry_grant = metadata.get("user_retry_grant_pending") is True
        if (job.attempt or 0) >= hard_attempt_cap() or (
            (job.attempt or 0) >= max_attempts and not user_retry_grant
        ):
            job.status = JOB_FAILED_RETRYABLE
            job.locked_at = None
            job.error_json = {
                **metadata,
                "error_code": BUDGET_EXHAUSTED_CODE,
                "retryable": False,
                "attempt": job.attempt or 0,
                "user_retry_grant_pending": False,
            }
            _record_job_event(
                job,
                {
                    "event": "budget_exhausted",
                    "attempt": job.attempt or 0,
                    "error_code": BUDGET_EXHAUSTED_CODE,
                    "retryable": False,
                    "message": "Retry budget consumed by prior claims (crash loop); terminated at claim time.",
                },
            )
            await db.flush()
            return job, True

        # Consuming the attempt at claim time doubles as the phase-C fence token:
        # any reclaim or later claim changes it, invalidating stale workers.
        job.attempt = (job.attempt or 0) + 1
        job.status = JOB_PROCESSING
        job.locked_at = utc_now()
        if user_retry_grant:
            job.error_json = {**metadata, "user_retry_grant_pending": False}
        _record_job_event(job, {"event": "claimed", "attempt": job.attempt or 0})
        await db.flush()
        return job, False

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
        job.status = JOB_FAILED_RETRYABLE if retryable else JOB_FAILED_PERMANENT
        job.locked_at = None
        prior_attempts = list((job.error_json or {}).get("attempts") or []) if isinstance(job.error_json, dict) else []
        job.error_json = {
            "message": message,
            "error_code": error_code,
            "retryable": retryable,
            "provider_code": provider_code,
            "provider_request_id": provider_request_id,
            "attempt": job.attempt or 0,
            "attempts": prior_attempts,
            **({"details": details} if details else {}),
        }
        _record_job_event(
            job,
            {
                "event": "failed",
                "attempt": job.attempt or 0,
                "error_code": error_code,
                "retryable": retryable,
                "provider_code": provider_code,
                "provider_request_id": provider_request_id,
                "message": message[:300],
            },
        )
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
    async def _resolve_identity_sketch_artifact(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        email: str,
    ) -> Optional[SoulmateArtifact]:
        """
        Resolves the ONE sketch artifact owned by the normalized-email identity
        (§11.5): the session's own row, or the row held by another session of the
        same identity. `uq_soulmate_one_sketch_per_email` guarantees at most one
        SKETCH row per email, so the resolution is unambiguous. The canonical DB
        identity key is email_normalized (user_id is deterministically derived
        from it in SP-301 but is never set on anonymous sessions).
        """
        stmt = select(SoulmateArtifact).where(
            SoulmateArtifact.artifact_type == "SKETCH",
            or_(
                SoulmateArtifact.session_id == session.id,
                SoulmateArtifact.email_normalized == email,
            ),
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
