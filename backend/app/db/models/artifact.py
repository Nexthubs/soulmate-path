import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin, utc_now


class SoulmateArtifact(Base, TimestampMixin):
    __tablename__ = "soulmate_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soulmate_sessions.id"),
        nullable=False,
    )
    email_normalized: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    artifact_version: Mapped[str] = mapped_column(
        String(32),
        default="v1",
        nullable=False,
    )
    unlock_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    generation_status: Mapped[str] = mapped_column(
        String(32),
        default="NOT_STARTED",
        nullable=False,
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    model: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    prompt_version: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    input_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    content_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    storage_key: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    provider_request_id: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_error_code: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    last_error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    generation_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    jobs: Mapped[List["AIGenerationJob"]] = relationship(
        "AIGenerationJob",
        back_populates="artifact",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "artifact_type",
            "artifact_version",
            name="uq_soulmate_artifacts_session_type_version",
        ),
        Index(
            "uq_soulmate_one_sketch_per_email",
            "email_normalized",
            unique=True,
            postgresql_where=text("artifact_type = 'SKETCH'"),
        ),
    )


class AIGenerationJob(Base, TimestampMixin):
    __tablename__ = "ai_generation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soulmate_artifacts.id"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(256),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    run_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )

    artifact: Mapped["SoulmateArtifact"] = relationship(
        "SoulmateArtifact",
        back_populates="jobs",
    )

    __table_args__ = (
        Index("idx_ai_generation_jobs_artifact_id", "artifact_id"),
    )

