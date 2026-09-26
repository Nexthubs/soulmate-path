"""
Artifact status derivation for the Result / Countdown state machine
(DEV-SPEC §10, Decision: TIME-01, SP-502).

Derivation is a pure function of persisted timestamps (soulmate_artifacts.unlock_at,
generation_status) and the server clock (`now`). Client time is never an input:
the frontend calibrates its countdown from `server_time` and cannot grant access
by changing its local clock (TIME-01).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


class ArtifactAvailability(str, Enum):
    """Availability per DEV-SPEC §10.1."""
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


class ArtifactGeneration(str, Enum):
    """Generation lifecycle per DEV-SPEC §10.2."""
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ArtifactStatus(str, Enum):
    """Combined frontend state per DEV-SPEC §10.3 (SP-502 acceptance)."""
    LOCKED = "LOCKED"
    READY = "READY"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC (naive values are assumed UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def derive_availability(unlock_at: datetime, now: datetime) -> ArtifactAvailability:
    """Availability per DEV-SPEC §10.1: LOCKED while now < unlock_at, else UNLOCKED."""
    return ArtifactAvailability.LOCKED if ensure_utc(now) < ensure_utc(unlock_at) else ArtifactAvailability.UNLOCKED


def normalize_generation(generation_status: Union[str, ArtifactGeneration]) -> ArtifactGeneration:
    """
    Map a persisted generation_status to the canonical §10.2 enum.
    Unknown/corrupt values fail closed to FAILED (Retry/Support) — never READY.
    """
    if isinstance(generation_status, ArtifactGeneration):
        return generation_status
    try:
        return ArtifactGeneration(str(generation_status).upper())
    except ValueError:
        return ArtifactGeneration.FAILED


def derive_artifact_status(
    unlock_at: datetime,
    generation_status: Union[str, ArtifactGeneration],
    now: datetime,
) -> ArtifactStatus:
    """
    Combined state per DEV-SPEC §10.3:
      LOCKED      now < unlock_at (any generation state — countdown wins)
      READY       unlocked, NOT_STARTED
      GENERATING  unlocked, QUEUED/PROCESSING
      COMPLETED   unlocked, COMPLETED
      FAILED      unlocked, FAILED (or unknown generation value)
    """
    if derive_availability(unlock_at, now) == ArtifactAvailability.LOCKED:
        return ArtifactStatus.LOCKED

    generation = normalize_generation(generation_status)
    if generation in (ArtifactGeneration.QUEUED, ArtifactGeneration.PROCESSING):
        return ArtifactStatus.GENERATING
    if generation == ArtifactGeneration.COMPLETED:
        return ArtifactStatus.COMPLETED
    if generation == ArtifactGeneration.FAILED:
        return ArtifactStatus.FAILED
    return ArtifactStatus.READY


class ArtifactStatusView(BaseModel):
    """Per-artifact status view (DEV-SPEC §10.4 response shape plus combined `status`)."""
    unlock_at: Optional[datetime] = Field(default=None, description="Persisted unlock timestamp (UTC)")
    availability: ArtifactAvailability
    generation: ArtifactGeneration
    status: ArtifactStatus


class SessionArtifactStatuses(BaseModel):
    """Sketch/Report statuses for one entitled session, derived at a single server instant."""
    server_time: datetime = Field(description="Server clock instant used for this derivation")
    sketch: ArtifactStatusView
    report: ArtifactStatusView


def derive_artifact_status_view(
    unlock_at: Optional[datetime],
    generation_status: Union[str, ArtifactGeneration],
    now: datetime,
) -> ArtifactStatusView:
    """
    Build the per-artifact view. A missing artifact row (unlock_at=None) fails closed:
    LOCKED with no unlock timestamp; callers (SP-503) can trigger the SP-501 self-heal.
    """
    if unlock_at is None:
        return ArtifactStatusView(
            unlock_at=None,
            availability=ArtifactAvailability.LOCKED,
            generation=ArtifactGeneration.NOT_STARTED,
            status=ArtifactStatus.LOCKED,
        )
    return ArtifactStatusView(
        unlock_at=ensure_utc(unlock_at),
        availability=derive_availability(unlock_at, now),
        generation=normalize_generation(generation_status),
        status=derive_artifact_status(unlock_at, generation_status, now),
    )
