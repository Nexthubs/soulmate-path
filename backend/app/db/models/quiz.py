import uuid
from datetime import datetime
from typing import Any, Dict
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, utc_now


class SoulmateQuizVersion(Base):
    __tablename__ = "soulmate_quiz_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    version: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    config_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
