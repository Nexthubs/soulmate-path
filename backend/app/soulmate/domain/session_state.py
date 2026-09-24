"""Soulmate Session Domain States and Constants (DEV-SPEC §6.2)."""

from enum import Enum


class SessionStatus(str, Enum):
    """Canonical session statuses per DEV-SPEC §6.2."""
    CREATED = "CREATED"
    QUIZ_IN_PROGRESS = "QUIZ_IN_PROGRESS"
    QUIZ_COMPLETED = "QUIZ_COMPLETED"
    EMAIL_CAPTURED = "EMAIL_CAPTURED"
    CHECKOUT_PENDING = "CHECKOUT_PENDING"
    SUBSCRIBED = "SUBSCRIBED"
    ABANDONED = "ABANDONED"


INITIAL_SESSION_STATUS: SessionStatus = SessionStatus.CREATED
INITIAL_STEP_CODE: str = "transition_0"
