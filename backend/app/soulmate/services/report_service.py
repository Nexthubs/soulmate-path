"""
Report persistence service (DEV-SPEC §13.2, §13.4, §14, §15.11; SP-702; Decisions: REPORT-01, REPORT-02).

Persists validated `SoulmateReportV1` content onto the session's REPORT row of
`soulmate_artifacts` (the placeholder row is created on first payment by SP-501's
ensure, which also owns `unlock_at` = first_payment_at + 24h — never re-derived here)
and serves authorized, unlocked reads for §15.11 `GET /api/soulmate/report`.

Contract points:
- content_json stores the camelCase SoulmateReportV1 payload (schemaVersion included),
  re-validated on every read so a renderer can never receive unvalidated content;
- one canonical current V1 report per entitled session: the DB unique constraint
  (session_id, artifact_type, artifact_version) admits exactly one REPORT v1 row and
  a completed report is never overwritten (idempotent no-clobber save);
- REPORT stays strictly session-scoped (Decision RECOVERY-01) — no email-scoped
  fallback like the sketch row;
- the §13.3 provider config surface (OpenAI-compatible endpoint url / api key / model,
  with shared OPENAI_* fallback) lives in settings; generation itself remains
  disabled until REPORT-01/REPORT-02 close (SP-704 will own the trigger/provider).
"""

import logging
from typing import Any, Dict, Optional, Tuple, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.base import utc_now
from app.db.models.artifact import SoulmateArtifact
from app.soulmate.domain.report import (
    REPORT_SCHEMA_VERSION,
    SoulmateReportV1,
    parse_soulmate_report_v1,
)

logger = logging.getLogger(__name__)

REPORT_ARTIFACT_TYPE = "REPORT"
# The canonical current report version (SP-702 acceptance): every read/save is pinned
# to V1 so a future V2 row can never be selected by accident (M5 review R-01).
REPORT_ARTIFACT_VERSION = "v1"


class ReportService:
    @staticmethod
    async def get_report_artifact(db: AsyncSession, session_id) -> Optional[SoulmateArtifact]:
        """
        The session's single canonical REPORT artifact row (any lifecycle state).

        Strictly session-scoped (RECOVERY-01): unlike the email-scoped sketch lookup,
        a report is never served across sessions. Pinned to artifact_version='v1'.
        """
        stmt = select(SoulmateArtifact).where(
            SoulmateArtifact.session_id == session_id,
            SoulmateArtifact.artifact_type == REPORT_ARTIFACT_TYPE,
            SoulmateArtifact.artifact_version == REPORT_ARTIFACT_VERSION,
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    async def save_completed_report(
        db: AsyncSession,
        session_id,
        report: Union[SoulmateReportV1, Dict[str, Any]],
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        provider_request_id: Optional[str] = None,
    ) -> Tuple[SoulmateArtifact, bool]:
        """
        Validate and persist a completed SoulmateReportV1 onto the session's REPORT row.

        Returns (artifact, saved). The row is locked FOR UPDATE so concurrent saves
        serialize; a row already COMPLETED with content is returned unchanged
        (saved=False) — the first completed V1 report is the canonical durable asset
        and is never overwritten, mirroring the sketch's revisit-returns-same-asset
        rule (ASSET-01) applied to report content.

        Raises NotFoundError when the placeholder row is missing (entitlement drift —
        the SP-501 self-heal owns row creation) and ReportValidationError when the
        payload violates the V1 schema/content policy (no partial write).
        """
        # Validate BEFORE taking the row lock / touching the row: an invalid payload
        # must never flip any state.
        validated = parse_soulmate_report_v1(report)

        stmt = (
            select(SoulmateArtifact)
            .where(
                SoulmateArtifact.session_id == session_id,
                SoulmateArtifact.artifact_type == REPORT_ARTIFACT_TYPE,
                SoulmateArtifact.artifact_version == REPORT_ARTIFACT_VERSION,
            )
            .with_for_update()
        )
        artifact = (await db.execute(stmt)).scalars().first()
        if artifact is None:
            raise NotFoundError(
                "Report artifact row not found for session; entitlement placeholder is missing.",
                details={"session_id": str(session_id), "artifact_type": REPORT_ARTIFACT_TYPE},
            )

        if artifact.generation_status == "COMPLETED" and artifact.content_json:
            logger.info(
                "Report save ignored: canonical V1 report already completed for session %s",
                session_id,
            )
            return artifact, False

        artifact.content_json = validated.model_dump(by_alias=True, exclude_none=True)
        artifact.generation_status = "COMPLETED"
        artifact.completed_at = utc_now()
        artifact.provider = provider
        artifact.model = model
        artifact.prompt_version = prompt_version
        artifact.provider_request_id = provider_request_id
        await db.commit()
        await db.refresh(artifact)
        logger.info(
            "Report persisted for session %s (schema_version=%s, provider=%s, model=%s, prompt_version=%s)",
            session_id,
            REPORT_SCHEMA_VERSION,
            provider,
            model,
            prompt_version,
        )
        return artifact, True

    @staticmethod
    def get_report_content(artifact: SoulmateArtifact) -> Optional[Dict[str, Any]]:
        """
        Validated camelCase report content for a COMPLETED row, or None when the row
        has not completed yet.

        The stored JSON is re-validated against SoulmateReportV1 on every read: the
        read path fails closed rather than ever returning unvalidated content to a
        renderer. Corrupt stored content raises ReportValidationError (data-integrity
        failure surfaced to the caller, never silently rewritten).
        """
        if artifact.generation_status != "COMPLETED" or not artifact.content_json:
            return None
        return parse_soulmate_report_v1(artifact.content_json).model_dump(
            by_alias=True, exclude_none=True
        )
