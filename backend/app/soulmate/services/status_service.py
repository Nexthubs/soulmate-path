"""
Artifact Status Service (DEV-SPEC §10, Decision: TIME-01, SP-502).

Loads persisted artifact placeholders for an entitled session and derives the
Result/Countdown statuses from the server clock. The clock is injectable
(`now` parameter) so unit tests can simulate 12h/24h progression deterministically.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.artifact import SoulmateArtifact
from app.soulmate.domain.artifact_status import (
    SessionArtifactStatuses,
    derive_artifact_status_view,
)

logger = logging.getLogger(__name__)


class ArtifactStatusService:
    @classmethod
    async def get_artifact_statuses(
        cls,
        db: AsyncSession,
        session_id,
        now: Optional[datetime] = None,
        email_normalized: Optional[str] = None,
    ) -> SessionArtifactStatuses:
        """
        Derive SKETCH and REPORT statuses for a session from persisted rows.

        `now` defaults to the server clock (utc_now). A missing artifact row
        (entitlement not yet initialized / drift) fails closed to LOCKED; the
        SP-501 create/ensure self-heal runs on the next confirmed payment or
        reconciliation and restores the rows.

        Email uniqueness prevents duplicate generation; it is not authorization.
        Both artifacts remain session-scoped until a verified recovery flow exists.
        The legacy email argument is intentionally ignored for compatibility.
        """
        effective_now = now or utc_now()

        stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == session_id)
        artifacts = (await db.execute(stmt)).scalars().all()
        by_type = {a.artifact_type: a for a in artifacts}

        sketch = by_type.get("SKETCH")
        report = by_type.get("REPORT")

        if sketch is None or report is None:
            logger.warning(
                "Artifact rows missing for session %s (sketch=%s report=%s); failing closed to LOCKED",
                session_id,
                sketch is not None,
                report is not None,
            )

        return SessionArtifactStatuses(
            server_time=effective_now,
            sketch=derive_artifact_status_view(
                unlock_at=sketch.unlock_at if sketch else None,
                generation_status=sketch.generation_status if sketch else "NOT_STARTED",
                now=effective_now,
            ),
            report=derive_artifact_status_view(
                unlock_at=report.unlock_at if report else None,
                generation_status=report.generation_status if report else "NOT_STARTED",
                now=effective_now,
            ),
        )
