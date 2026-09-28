"""
Report generation queue / worker (DEV-SPEC §13.3–13.4, §15.11; Decisions: REPORT-01, REPORT-02; SP-706).

on_demand report generation over the same DB-backed durable queue as the sketch
(`ai_generation_jobs`, §11.6 states, `FOR UPDATE SKIP LOCKED`), mirroring the
reviewed SP-603/604 machinery with the report's own semantics:

- **Session-scoped** (Decision RECOVERY-01): the report artifact is strictly the
  session's own V1 row — no email-identity resolution. Idempotency key is
  `report:<session_id>:<artifact_version>` and concurrent enqueues serialize on a
  per-session advisory lock.
- **Provider boundary** (SP-704): the worker calls the configured
  `SoulmateReportGenerator` via `build_report_provider()`; generation is refused
  outright while the production switch is off (`REPORT_GENERATION_DISABLED`).
  The provider renders the versioned prompt template and validates its own output
  against the ReportV1 contract.
- **Content persistence replaces the storage sink** (§13.2): the fenced phase-C
  success path writes the validated camelCase content onto the artifact row
  (content_json + §13.3 metadata) — the report has no object-storage asset, so
  ASSET-01's sink seam does not apply. The write replicates
  `ReportService.save_completed_report` semantics inside the fence (validate-then-
  write, no-clobber); that service remains the canonical direct-persistence API.
- **Retry policy** (§11.6): retryable provider failures requeue with exponential
  backoff until the attempt budget is exhausted (FAILED_RETRYABLE, user-retryable
  under the hard cap); permanent failures (invalid profile, template missing/
  invalid, contract-violating provider output) terminate immediately.
- **Two-phase fence**: phase A claims (attempt = fence token) and materializes the
  normalized profile; phase B runs the provider without holding a transaction;
  phase C finalizes only when the fence still matches, so a stale worker can never
  commit content over a surviving attempt.

Structured logging follows §19.1; provider raw errors never reach API responses.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union
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
)
from app.db.base import utc_now
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.session import SoulmateProfile, SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.domain.artifact_status import normalize_generation
from app.soulmate.domain.profile import ProfileValidationError, SoulmateProfileV1
from app.soulmate.domain.report import parse_soulmate_report_v1
from app.soulmate.domain.report_models import (
    ReportGenerationDisabledError,
    ReportGenerationInput,
    ReportProviderError,
)
from app.soulmate.metrics import record_generation_metric
from app.soulmate.services.payment_consistency import payment_lock
from app.soulmate.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

JOB_TYPE_REPORT = "SOULMATE_REPORT"

# §11.6 job states (shared with the sketch queue).
from app.soulmate.services.sketch_generation_service import (  # noqa: E402
    BUDGET_EXHAUSTED_CODE,
    INTERNAL_ERROR_CODE,
    JOB_COMPLETED,
    JOB_FAILED_PERMANENT,
    JOB_FAILED_RETRYABLE,
    JOB_PROCESSING,
    JOB_QUEUED,
    RECLAIM_ERROR_CODE,
    hard_attempt_cap,
    retry_backoff_seconds,
)

PROMPT_TEMPLATE_UNAVAILABLE_CODE = "PROMPT_TEMPLATE_UNAVAILABLE"


def report_idempotency_key(session_id: UUID, artifact_version: str) -> str:
    """`report:<session_id>:<artifact_version>` — one logical generation per session V1 report."""
    return f"report:{session_id}:{artifact_version}"


def _record_job_event(job: AIGenerationJob, entry: Dict[str, Any]) -> None:
    """Appends one entry to the job's append-only attempt history (§11.3/§19)."""
    entry = {"at": utc_now().isoformat(), **entry}
    existing = job.error_json if isinstance(job.error_json, dict) else {}
    history = list(existing.get("attempts") or [])
    history.append(entry)
    job.error_json = {**existing, "attempts": history}


@dataclass
class ReportEnqueueOutcome:
    artifact: SoulmateArtifact
    job: Optional[AIGenerationJob]
    created: bool


@dataclass
class _ClaimedWork:
    """Phase-A output carried across the provider call (no DB objects held)."""
    job_id: UUID
    artifact_id: UUID
    generation_input: ReportGenerationInput
    # Fence token: the attempt count consumed by THIS claim (§11.6).
    claim_attempt: int


class ReportGenerationService:
    """Idempotent enqueue + two-phase fenced claim/process for report generation."""

    # ------------------------------------------------------------------
    # Enqueue (API-triggered, §13.4 on_demand, §15.11)
    # ------------------------------------------------------------------

    @classmethod
    async def enqueue_report_generation(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        now: Optional[datetime] = None,
    ) -> ReportEnqueueOutcome:
        """
        Enqueue the ONE logical V1 report generation for the authenticated session.

        Gates, in order: PAY-AUTH-01 entitlement; the production switch
        (REPORT-01/02 — raises `ReportGenerationDisabledError` while off); SP-501
        self-heal; per-session advisory lock; the session's V1 REPORT row
        (v1-pinned); never re-enqueue a COMPLETED report; converge on any existing
        job (an explicit user retry requeues a FAILED_RETRYABLE terminal job under
        the hard attempt cap); TIME-01 unlock gate on the persisted `unlock_at`.
        """
        effective_now = now or utc_now()

        if session.subscription_success_at is None:
            raise ForbiddenOwnershipError(
                "Report generation is available only after a confirmed first payment."
            )

        # PAID-THROUGH-01: a known-and-passed paid window cannot start new
        # generations (uniform API-layer enforcement).
        await SubscriptionService.assert_paid_access_window(db, session, effective_now)

        if not settings.is_report_generation_enabled:
            raise ReportGenerationDisabledError(
                "Report generation is not enabled on this deployment."
            )

        # SP-501 self-heal (idempotent; acquires the session advisory lock itself).
        await SubscriptionService.ensure_artifacts_for_session(
            session=session,
            paid_at=session.subscription_success_at,
            db=db,
        )

        # Serialize concurrent enqueues for the same session (report is session-scoped).
        await payment_lock(db, "report-generate", str(session.id))

        artifact = await cls._resolve_report_artifact(db, session.id)
        if artifact is None:
            raise InternalServerError("Report artifact row is missing after self-heal.")

        generation = normalize_generation(artifact.generation_status)
        key = report_idempotency_key(session.id, artifact.artifact_version)

        # An already-completed report is never regenerated (durable asset rule).
        if generation.value == "COMPLETED":
            return ReportEnqueueOutcome(artifact=artifact, job=None, created=False)

        existing_job = await cls._get_job_by_key(db, key)
        if existing_job is not None:
            # §10.3 bounded user retry: only a transient-exhausted terminal job
            # (FAILED_RETRYABLE) under the hard attempt cap may be requeued in place.
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
                record_generation_metric(
                    "generation_user_retry",
                    job_id=existing_job.id,
                    artifact_id=artifact.id,
                    session_id=str(artifact.session_id),
                    fields={"job_type": JOB_TYPE_REPORT, "attempt": existing_job.attempt or 0},
                )
                logger.info(
                    "User retry requeued report job %s (attempt %s/%s)",
                    existing_job.id,
                    existing_job.attempt,
                    hard_attempt_cap(),
                )
                return ReportEnqueueOutcome(artifact=artifact, job=existing_job, created=False)
            record_generation_metric(
                "enqueue_duplicate",
                job_id=existing_job.id,
                artifact_id=artifact.id,
                session_id=str(artifact.session_id),
                fields={"job_type": JOB_TYPE_REPORT},
            )
            return ReportEnqueueOutcome(artifact=artifact, job=existing_job, created=False)

        # TIME-01: the persisted unlock time gates generation server-side.
        if artifact.unlock_at is None or effective_now < artifact.unlock_at:
            raise LockedAssetError(
                "Report is still locked; generation unlocks at the persisted server time."
            )

        created = False
        job = AIGenerationJob(
            artifact_id=artifact.id,
            job_type=JOB_TYPE_REPORT,
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
            record_generation_metric(
                "enqueue_created",
                job_id=job.id,
                artifact_id=artifact.id,
                session_id=str(artifact.session_id),
                fields={"job_type": JOB_TYPE_REPORT},
            )
        return ReportEnqueueOutcome(artifact=artifact, job=job, created=created)

    # ------------------------------------------------------------------
    # Worker (two-phase fenced, mirroring §11.6/SP-604)
    # ------------------------------------------------------------------

    @classmethod
    async def process_next_queued_job(
        cls,
        provider=None,
        now: Optional[datetime] = None,
        job_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """
        Claim and process one QUEUED report job; returns the final job status.

        `provider` defaults to the configured `build_report_provider()`; tests and
        targeted reprocessing may inject a specific generator or scope the claim
        with `job_id`.
        """
        effective_now = now or utc_now()

        prepared = await cls._claim_and_prepare(
            db_session_factory=AsyncSessionLocal, now=effective_now, job_id=job_id
        )
        if prepared is None:
            return None
        if isinstance(prepared, str):
            return prepared
        work = prepared

        if provider is None:
            from app.soulmate.services.report_providers import build_report_provider

            provider = build_report_provider()

        # Phase B: provider call only — no writes before the fence.
        try:
            result = await provider.generate(work.generation_input)
        except ReportProviderError as exc:
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
            result=result,
        )

    @classmethod
    async def _claim_and_prepare(
        cls,
        db_session_factory,
        now: datetime,
        job_id: Optional[UUID] = None,
    ) -> Optional[Union[_ClaimedWork, str]]:
        """
        Phase A: claim + normalized-profile materialization + terminal short-circuits
        (one txn). Returns None when nothing was claimable, a terminal status string
        when the job finalized inside this transaction, or the prepared work.
        """
        async with db_session_factory() as db:
            try:
                job, budget_exhausted = await cls._claim_next_queued(db, now, job_id)
                if job is None:
                    return None
                if budget_exhausted:
                    artifact = await cls._lock_artifact(db, job.artifact_id)
                    if artifact is not None:
                        artifact.generation_status = "FAILED"
                        artifact.last_error_code = BUDGET_EXHAUSTED_CODE
                        artifact.last_error_message = (
                            "Generation attempt budget exhausted after repeated worker loss."
                        )
                    await db.commit()
                    logger.warning(
                        "Report job %s terminated %s at claim time (crash-loop budget exhausted)",
                        job.id, JOB_FAILED_RETRYABLE,
                    )
                    record_generation_metric(
                        "generation_final_failure",
                        job_id=job.id,
                        artifact_id=job.artifact_id,
                        session_id=str(artifact.session_id) if artifact is not None else None,
                        fields={
                            "job_type": JOB_TYPE_REPORT,
                            "error_code": BUDGET_EXHAUSTED_CODE,
                            "attempts": job.attempt or 0,
                        },
                    )
                    return JOB_FAILED_RETRYABLE
                claim_attempt = job.attempt or 0

                artifact = await cls._lock_artifact(db, job.artifact_id)
                if artifact is None:
                    return await cls._fail_job(
                        db, job, None,
                        retryable=False,
                        message="Report artifact row for job is missing.",
                        error_code="ARTIFACT_MISSING",
                    )

                # Completion guard: never call the provider for a completed report.
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
                        "Report job %s short-circuited: artifact %s already completed",
                        job.id, artifact.id,
                    )
                    return JOB_COMPLETED

                started_at = utc_now()
                if artifact.generation_status in ("NOT_STARTED", "QUEUED"):
                    artifact.generation_status = "PROCESSING"
                if artifact.generation_started_at is None:
                    artifact.generation_started_at = started_at

                # Normalized-profile materialization is deterministic in-process
                # work: failures here are permanent invalid-input terminals, never
                # rollback-requeue loops (§11.6; the provider-side prompt/template
                # failures are classified permanent by the SP-704 error taxonomy).
                profile_row = (
                    await db.execute(
                        select(SoulmateProfile).where(SoulmateProfile.session_id == artifact.session_id)
                    )
                ).scalar_one_or_none()

                try:
                    if profile_row is None:
                        raise ProfileValidationError(
                            "Normalized profile is missing for the report session; "
                            "generation inputs cannot be established.",
                        )
                    profile = SoulmateProfileV1.model_validate(profile_row)
                except ProfileValidationError as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=exc.message,
                        error_code=exc.error_code.value,
                        details=exc.details,
                    )
                except PydanticValidationError as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=f"Persisted profile failed validation: {str(exc)[:300]}",
                        error_code="PROFILE_INVALID",
                    )
                except Exception as exc:
                    return await cls._fail_job(
                        db, job, artifact,
                        retryable=False,
                        message=f"Generation input materialization failed: {type(exc).__name__}: {str(exc)[:200]}",
                        error_code="INPUT_BUILD_FAILED",
                    )

                generation_input = ReportGenerationInput(
                    profile=profile,
                    prompt_version=settings.soulmate_report_prompt_version or "v1",
                )

                await db.commit()
                queue_latency_ms = None
                if job.created_at is not None:
                    queue_latency_ms = max(0, int((started_at - job.created_at).total_seconds() * 1000))
                record_generation_metric(
                    "queue_latency_ms",
                    job_id=job.id,
                    artifact_id=artifact.id,
                    session_id=str(artifact.session_id),
                    fields={
                        "job_type": JOB_TYPE_REPORT,
                        "latency_ms": queue_latency_ms,
                        "attempt": claim_attempt,
                    },
                )
                return _ClaimedWork(
                    job_id=job.id,
                    artifact_id=artifact.id,
                    generation_input=generation_input,
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
        result,
    ) -> str:
        """
        Phase C success path (fenced): write the validated report content INSIDE the
        fence, then commit COMPLETED. Re-validates the provider output at the
        persistence boundary (M-01) and never overwrites an existing completed
        report (no-clobber, SP-702 semantics inside the fence).
        """
        async with AsyncSessionLocal() as db:
            async with db.begin():
                job = await cls._lock_job(db, job_id)
                artifact = await cls._lock_artifact(db, artifact_id)
                if job is None or artifact is None:
                    logger.error("Report finalization lost its job/artifact rows (%s/%s)", job_id, artifact_id)
                    return JOB_FAILED_PERMANENT

                # Fence: a reclaimed/superseded claim may not commit anything.
                if job.status != JOB_PROCESSING or (job.attempt or 0) != claim_attempt:
                    logger.warning(
                        "Report job %s fence mismatch (status=%s attempt=%s claim=%s); "
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
                            "message": "Stale worker result discarded at the fence; no state write.",
                        },
                    )
                    return job.status

                # Second completion guard under the row lock (no-clobber).
                if normalize_generation(artifact.generation_status).value == "COMPLETED":
                    job.status = JOB_COMPLETED
                    job.locked_at = None
                    return JOB_COMPLETED

                # Persistence-boundary revalidation: the stored form can only ever
                # be a contract-valid SoulmateReportV1 (M5 review M-01).
                try:
                    report = parse_soulmate_report_v1(result.report)
                except Exception as exc:
                    return await cls._write_failure_locked(
                        db, job, artifact,
                        claim_attempt=claim_attempt,
                        retryable=False,
                        message="Provider output does not conform to the ReportV1 contract.",
                        error_code="REPORT_CONTRACT_INVALID",
                        provider_request_id=result.provider_request_id,
                        details={"error": str(exc)[:500]},
                    )

                artifact.content_json = report.model_dump(by_alias=True, exclude_none=True)
                artifact.provider = result.provider
                artifact.model = result.model
                artifact.prompt_version = result.prompt_version
                artifact.provider_request_id = result.provider_request_id
                artifact.attempt_count = (artifact.attempt_count or 0) + 1
                artifact.generation_status = "COMPLETED"
                artifact.completed_at = utc_now()

                job.status = JOB_COMPLETED
                winning_claim_at = job.locked_at
                job.locked_at = None
                _record_job_event(
                    job,
                    {
                        "event": "completed",
                        "attempt": claim_attempt,
                        "provider_request_id": result.provider_request_id,
                        "model": result.model,
                        "prompt_version": result.prompt_version,
                    },
                )

            logger.info(
                "Report generation completed for artifact %s (job %s, model=%s, request_id=%s)",
                artifact_id,
                job_id,
                result.model,
                result.provider_request_id,
            )
            generation_latency_ms = None
            if winning_claim_at is not None and artifact.completed_at is not None:
                generation_latency_ms = max(
                    0, int((artifact.completed_at - winning_claim_at).total_seconds() * 1000)
                )
            record_generation_metric(
                "generation_success",
                job_id=job_id,
                artifact_id=artifact_id,
                session_id=str(artifact.session_id),
                fields={
                    "job_type": JOB_TYPE_REPORT,
                    "latency_ms": generation_latency_ms,
                    "attempts": claim_attempt,
                },
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
                    logger.error("Report failure handling lost job %s", job_id)
                    return JOB_FAILED_PERMANENT
                artifact = await cls._lock_artifact(db, artifact_id) if artifact_id else None

                # Fence: only the attempt that owns the current claim may report.
                if job.status != JOB_PROCESSING or (job.attempt or 0) != claim_attempt:
                    logger.warning(
                        "Report job %s fence mismatch on failure report (status=%s attempt=%s claim=%s); "
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
        `db.begin()` commits; the outcome is appended to the attempt history.
        """
        job.locked_at = None
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
            job.status = JOB_QUEUED
            backoff = retry_backoff_seconds(claim_attempt)
            job.run_after = utc_now() + timedelta(seconds=backoff)
            if artifact is not None:
                artifact.attempt_count = (artifact.attempt_count or 0) + 1
            logger.warning(
                "Report job %s attempt %s/%s failed retryably (error_code=%s); "
                "requeued with backoff until %s",
                job.id, claim_attempt, max_attempts, error_code, job.run_after,
            )
            record_generation_metric(
                "generation_retry",
                job_id=job.id,
                artifact_id=artifact.id if artifact is not None else None,
                session_id=str(artifact.session_id) if artifact is not None else None,
                fields={
                    "job_type": JOB_TYPE_REPORT,
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
            "Report job %s reached terminal %s after %s attempt(s) (error_code=%s, provider_code=%s)",
            job.id, status, claim_attempt, error_code, provider_code,
        )
        record_generation_metric(
            "generation_final_failure",
            job_id=job.id,
            artifact_id=artifact.id if artifact is not None else None,
            session_id=str(artifact.session_id) if artifact is not None else None,
            fields={
                "job_type": JOB_TYPE_REPORT,
                "error_code": error_code,
                "attempts": claim_attempt,
            },
        )
        return status

    @classmethod
    async def reclaim_stale_processing_jobs(cls, now: Optional[datetime] = None) -> int:
        """
        Requeue PROCESSING report jobs whose claim outlived the staleness threshold
        (worker death mid-call) without charging the attempt budget — the budget is
        enforced at claim time (SP-604 M-01 semantics).
        """
        effective_now = now or utc_now()
        stale_before = effective_now - timedelta(seconds=settings.job_claim_stale_seconds)
        reclaimed = 0
        async with AsyncSessionLocal() as db:
            async with db.begin():
                stmt = (
                    select(AIGenerationJob)
                    .where(
                        AIGenerationJob.job_type == JOB_TYPE_REPORT,
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
                        "Reclaimed stale report job %s (attempt %s unchanged; budget enforced at claim)",
                        job.id, attempt,
                    )
        if reclaimed:
            record_generation_metric(
                "generation_stale_reclaimed",
                fields={"job_type": JOB_TYPE_REPORT, "count": reclaimed},
            )
        return reclaimed

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _resolve_report_artifact(
        cls,
        db: AsyncSession,
        session_id,
    ) -> Optional[SoulmateArtifact]:
        """The session's own V1 REPORT row (v1-pinned, session-scoped — RECOVERY-01)."""
        stmt = select(SoulmateArtifact).where(
            SoulmateArtifact.session_id == session_id,
            SoulmateArtifact.artifact_type == "REPORT",
            SoulmateArtifact.artifact_version == "v1",
        )
        return (await db.execute(stmt)).scalars().first()

    @classmethod
    async def _get_job_by_key(cls, db: AsyncSession, key: str) -> Optional[AIGenerationJob]:
        stmt = select(AIGenerationJob).where(AIGenerationJob.idempotency_key == key)
        return (await db.execute(stmt)).scalars().first()

    @classmethod
    async def _claim_next_queued(
        cls,
        db: AsyncSession,
        now: datetime,
        job_id: Optional[UUID] = None,
    ) -> "tuple[Optional[AIGenerationJob], bool]":
        """
        Claims one QUEUED report job under row lock; the consumed attempt doubles as
        the phase-C fence token. Budget-exhausted jobs terminate at claim time.
        """
        conditions = [
            AIGenerationJob.job_type == JOB_TYPE_REPORT,
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
            "Report job %s terminated %s (error_code=%s)",
            job.id, job.status, error_code,
        )
        return job.status


class ReportGenerationWorker:
    """In-process asyncio worker polling the DB-backed report job queue (§11.6)."""

    def __init__(self, provider=None, poll_seconds: Optional[float] = None):
        self.provider = provider
        self.poll_seconds = (
            poll_seconds if poll_seconds is not None else settings.job_worker_poll_seconds
        )

    async def run_loop(self) -> None:
        # Initial delay keeps short-lived lifespans (tests, quick restarts) harmless.
        await asyncio.sleep(self.poll_seconds)
        while True:
            try:
                reclaimed = await ReportGenerationService.reclaim_stale_processing_jobs()
                processed = await ReportGenerationService.process_next_queued_job(
                    provider=self.provider,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Report generation worker iteration failed.")
                reclaimed, processed = 0, None
            active = bool(processed) or reclaimed > 0
            await asyncio.sleep(0 if active else self.poll_seconds)


def start_report_workers() -> list:
    """Starts the configured number of in-process report workers (no-op when disabled)."""
    if not settings.job_worker_enabled:
        return []
    return [
        asyncio.create_task(
            ReportGenerationWorker().run_loop(),
            name=f"report-generation-worker-{index + 1}",
        )
        for index in range(max(1, settings.job_worker_concurrency))
    ]


async def stop_report_workers(tasks: list) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
