import logging
from pathlib import Path
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.quiz import SoulmateQuizVersion
from app.db.session import SessionLocal
from app.quiz.loader import invalidate_quiz_config_cache, load_quiz_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed_quiz_version(
    db: Session,
    config_path: Optional[Path] = None,
    activate: bool = True,
) -> SoulmateQuizVersion:
    """
    Validate and seed the canonical quiz version into soulmate_quiz_versions table.
    Ensures database runtime has the validated immutable JSON config and clears memory cache.
    """
    config = load_quiz_config(config_path)
    config_dict = config.model_dump(mode="json")

    stmt = select(SoulmateQuizVersion).where(SoulmateQuizVersion.version == config.version)
    record = db.execute(stmt).scalar_one_or_none()

    if record:
        if record.config_json != config_dict:
            raise ValueError(
                f"Quiz version '{config.version}' is immutable and already exists with different content. "
                "Changing questions requires publishing a new version identifier (DEV-SPEC §4.5)."
            )
        if activate and not record.is_active:
            record.is_active = True
            db.commit()
            db.refresh(record)
        logger.info(f"Verified existing immutable QuizVersion '{config.version}' (is_active={record.is_active})")
    else:
        record = SoulmateQuizVersion(
            version=config.version,
            config_json=config_dict,
            is_active=activate,
        )
        db.add(record)
        logger.info(f"Inserted new QuizVersion '{config.version}' (is_active={activate})")

    db.commit()
    db.refresh(record)
    invalidate_quiz_config_cache()
    return record


if __name__ == "__main__":
    session = SessionLocal()
    try:
        res = seed_quiz_version(session)
        print(f"Successfully seeded quiz version '{res.version}' (ID: {res.id}, Active: {res.is_active})")
    finally:
        session.close()
