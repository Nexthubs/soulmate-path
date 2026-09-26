"""
DB-level constraint enforcement tests for soulmate_artifacts (Wave 5 audit M1/M2;
DEV-SPEC §14, AGENTS.md §6, Decision: ASSET-01).

M1 guard: the suite deliberately runs against real PostgreSQL (DATABASE_URL in .env).
There is no conftest.py SQLite override anywhere; the tests depend on Postgres-only
semantics (JSONB columns, partial unique indexes, and the pg_locks-based deterministic
race test in test_artifact_entitlement.py). These tests fail fast if the engine ever
drifts to SQLite or another backend that cannot enforce the same constraints.

M2: explicitly trigger the artifact uniqueness constraints at the DB level and assert
IntegrityError — proving enforcement lives in the database, not just application logic.
Note: uq_soulmate_one_sketch_per_email is already explicitly exercised in
test_migrations.py::test_one_sketch_per_email_partial_unique_index (SP-002);
uq_soulmate_artifacts_session_type_version was the missing one and is covered here.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.models.artifact import SoulmateArtifact
from app.db.models.session import SoulmateSession
from app.db.session import SessionLocal


@pytest.fixture
def db_session():
    """Sync transactional DB session mirroring test_migrations.py."""
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def test_tests_run_on_postgresql(db_session):
    """
    Audit M1 guard: the constraint/integration suites require PostgreSQL semantics.
    Fails loudly if the configured database ever drifts to SQLite (partial indexes,
    JSONB, pg_locks and the concurrency tests would silently lose meaning).
    """
    url = settings.database_url
    assert url.startswith("postgresql://"), (
        "Backend tests must run against PostgreSQL (DEV-SPEC §14 DB-level uniqueness, "
        f"JSONB, partial unique indexes); got: {url.split('@')[-1]}"
    )
    # The live engine must really be Postgres, not just the configured URL string.
    dialect = db_session.get_bind().dialect.name
    assert dialect == "postgresql", f"Unexpected test engine dialect: {dialect}"


def _make_session(db_session, email: str) -> SoulmateSession:
    sess = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        email=email,
        email_normalized=email,
        quiz_version="soulmate-quiz-v1",
        status="paid",
        current_step="result",
    )
    db_session.add(sess)
    db_session.commit()
    return sess


def test_uq_artifacts_session_type_version_enforced_at_db_level(db_session):
    """
    Audit M2: duplicate (session_id, artifact_type, artifact_version) must be rejected
    by the DATABASE constraint uq_soulmate_artifacts_session_type_version with
    IntegrityError — not merely by application-level existence checks.
    """
    email = f"m2_{uuid.uuid4().hex[:8]}@example.com"
    sess = _make_session(db_session, email)
    unlock = datetime.now(timezone.utc) + timedelta(hours=12)

    first = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=email,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=unlock,
        generation_status="NOT_STARTED",
    )
    db_session.add(first)
    db_session.commit()

    duplicate = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=email,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=unlock + timedelta(hours=1),
        generation_status="NOT_STARTED",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Exactly one row survived
    rows = (
        db_session.execute(
            select(SoulmateArtifact).where(
                SoulmateArtifact.session_id == sess.id,
                SoulmateArtifact.artifact_type == "SKETCH",
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


def test_uq_artifacts_session_type_version_allows_distinct_type_or_version(db_session):
    """Same session may hold one SKETCH and one REPORT, and future artifact versions."""
    email = f"m2b_{uuid.uuid4().hex[:8]}@example.com"
    sess = _make_session(db_session, email)
    unlock = datetime.now(timezone.utc)

    db_session.add_all(
        [
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="SKETCH",
                artifact_version="v1",
                unlock_at=unlock,
            ),
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="REPORT",
                artifact_version="v1",
                unlock_at=unlock,
            ),
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="REPORT",
                artifact_version="v2",
                unlock_at=unlock,
            ),
        ]
    )
    db_session.commit()  # must not raise

    rows = (
        db_session.execute(select(SoulmateArtifact).where(SoulmateArtifact.session_id == sess.id))
        .scalars()
        .all()
    )
    assert len(rows) == 3
