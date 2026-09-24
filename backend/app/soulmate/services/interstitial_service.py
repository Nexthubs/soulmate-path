"""Interstitial Answer Submission and Domain Service (DEV-SPEC §5.7, §15.4, SP-206)."""

import logging
from typing import Any, Set, Union
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.db.base import utc_now
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.soulmate.domain.step_resolver import (
    INTERSTITIAL_CODES,
    INTERSTITIAL_CODES_SET,
    resolve_next_step_for_interstitial,
    validate_can_submit_interstitial,
)
from app.soulmate.schema import InterstitialSubmitRequest, InterstitialSubmitResponse
from app.soulmate.services.flow_service import FlowService
from app.soulmate.services.profile_service import ProfileService

logger = logging.getLogger(__name__)


class InterstitialService:
    """Service governing post-quiz interstitial modal answer validation, atomic upsert, and flow progression."""

    @classmethod
    def normalize_interstitial_value(
        cls,
        interstitial_code: str,
        val: Any,
    ) -> Union[bool, str]:
        """
        Normalizes and strictly validates user input for interstitial popups.
        - spiritual_person: bool or 'yes'/'no' -> bool
        - familiar_psychic_artistry: bool or 'yes'/'no' -> bool
        - warning_response: 'yes'|'no' (or bool) -> 'yes'|'no'
        """
        if interstitial_code in ("spiritual_person", "familiar_psychic_artistry"):
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                lowered = val.strip().lower()
                if lowered in ("true", "yes", "1"):
                    return True
                if lowered in ("false", "no", "0"):
                    return False
            raise ValidationError(
                f"Invalid answer for '{interstitial_code}': expected boolean or 'yes'/'no', got '{val}'."
            )

        if interstitial_code == "warning_response":
            if isinstance(val, bool):
                return "yes" if val else "no"
            if isinstance(val, str):
                lowered = val.strip().lower()
                if lowered in ("yes", "no"):
                    return lowered
                if lowered in ("true", "1"):
                    return "yes"
                if lowered in ("false", "0"):
                    return "no"
            raise ValidationError(
                f"Invalid answer for 'warning_response': expected 'yes' or 'no', got '{val}'."
            )

        raise ValidationError(
            f"Invalid interstitial code '{interstitial_code}'. Valid codes: {sorted(INTERSTITIAL_CODES)}."
        )

    @classmethod
    async def submit_interstitial(
        cls,
        db: AsyncSession,
        session: SoulmateSession,
        interstitial_code: str,
        req: InterstitialSubmitRequest,
    ) -> InterstitialSubmitResponse:
        """
        Validates, normalizes, and atomically persists an interstitial modal answer into soulmate_answers,
        advances session flow step, updates normalized SoulmateProfile, and emits non-PII analytics logging.
        """
        # 1. Validate interstitial code namespace (strictly separate from q02..q18)
        if interstitial_code not in INTERSTITIAL_CODES_SET:
            raise ValidationError(
                f"Invalid interstitial code '{interstitial_code}'. Valid codes: {sorted(INTERSTITIAL_CODES)}."
            )

        # 2. Normalize and validate payload value
        norm_val = cls.normalize_interstitial_value(interstitial_code, req.value)

        # 3. Skip and transition prevention guard (DEV-SPEC §5.7, §15.4, SP-206)
        ans_stmt = select(SoulmateAnswer.question_code).where(SoulmateAnswer.session_id == session.id)
        ans_res = await db.execute(ans_stmt)
        answered_codes: Set[str] = set(ans_res.scalars().all())
        validate_can_submit_interstitial(interstitial_code, session.current_step, answered_codes)

        # 4. Atomic PostgreSQL upsert (idempotent across network retries)
        now = utc_now()
        stmt = pg_insert(SoulmateAnswer).values(
            session_id=session.id,
            question_code=interstitial_code,
            answer_json={"value": norm_val},
            duration_ms=req.duration_ms,
            answered_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_soulmate_answers_session_question",
            set_={
                "answer_json": stmt.excluded.answer_json,
                "duration_ms": stmt.excluded.duration_ms,
                "updated_at": now,
            },
        )
        await db.execute(stmt)

        # 5. Advance session state and step
        next_step = resolve_next_step_for_interstitial(interstitial_code)
        session.current_step = next_step
        session.updated_at = now

        # 6. Synchronize normalized SoulmateProfile (DEV-SPEC §7)
        await ProfileService.sync_profile_for_session(db, session, commit=False)

        await db.commit()
        await db.refresh(session)

        # 7. Non-PII structured analytics event (DEV-SPEC §5.7, AGENTS.md §6)
        logger.info(
            "Interstitial answered: %s",
            interstitial_code,
            extra={
                "event_type": "interstitial_answered",
                "session_id": str(session.id),
                "interstitial_code": interstitial_code,
                "answer_value": norm_val,
            },
        )

        # 8. Compile updated flow state for client convenience
        flow_state = await FlowService.get_flow_state(db, session)

        return InterstitialSubmitResponse(
            saved=True,
            interstitial_code=interstitial_code,
            value=norm_val,
            next_step=next_step,
            flow_state=flow_state,
        )
