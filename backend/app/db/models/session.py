import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin, utc_now


class SoulmateSession(Base, TimestampMixin):
    __tablename__ = "soulmate_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    public_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(320),
        nullable=True,
    )
    email_normalized: Mapped[Optional[str]] = mapped_column(
        String(320),
        nullable=True,
        index=True,
    )
    quiz_version: Mapped[str] = mapped_column(
        String(64),
        default="soulmate-quiz-v1",
        nullable=False,
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("quiz_version", "soulmate-quiz-v1")
        super().__init__(**kwargs)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    current_step: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    utm_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    quiz_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    email_captured_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    subscription_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    answers: Mapped[List["SoulmateAnswer"]] = relationship(
        "SoulmateAnswer",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    profile: Mapped[Optional["SoulmateProfile"]] = relationship(
        "SoulmateProfile",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_soulmate_sessions_email", "email_normalized"),
    )


class SoulmateAnswer(Base):
    __tablename__ = "soulmate_answers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soulmate_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_code: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    answer_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    first_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    session: Mapped["SoulmateSession"] = relationship(
        "SoulmateSession",
        back_populates="answers",
    )

    __table_args__ = (
        UniqueConstraint("session_id", "question_code", name="uq_soulmate_answers_session_question"),
    )


class SoulmateProfile(Base):
    __tablename__ = "soulmate_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soulmate_sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    profile_version: Mapped[str] = mapped_column(
        String(32),
        default="v1",
        nullable=False,
    )
    user_gender: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    preferred_partner_gender: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    love_life_status: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    preferred_partner_age_range: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    preferred_partner_ethnicity: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    key_soulmate_quality: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    birth_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    zodiac_sign: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    element: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    decision_style: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    personal_challenge: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    red_flag: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    similarity_preference: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    relationship_dynamic: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    love_language: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    connection_style: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    relationship_fear: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    life_goals: Mapped[List[Any]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    spiritual_person: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
    )
    familiar_psychic_artistry: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
    )
    warning_response: Mapped[Optional[str]] = mapped_column(
        String(8),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    session: Mapped["SoulmateSession"] = relationship(
        "SoulmateSession",
        back_populates="profile",
    )
