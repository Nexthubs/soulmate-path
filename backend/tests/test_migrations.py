import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from app.db.session import SessionLocal
from app.db.models import (
    SoulmateQuizVersion,
    SoulmateSession,
    SoulmateAnswer,
    SoulmateProfile,
    Subscription,
    SubscriptionPayment,
    PayPalWebhookEvent,
    SoulmateArtifact,
    AIGenerationJob,
)


@pytest.fixture
def db_session():
    """Provide a transactional database session for tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_schema_tables_exist(db_session):
    """Verify all 9 tables from DEV-SPEC §14 exist in PostgreSQL."""
    inspector = inspect(db_session.bind)
    table_names = inspector.get_table_names()

    expected_tables = {
        "soulmate_quiz_versions",
        "soulmate_sessions",
        "soulmate_answers",
        "soulmate_profiles",
        "subscriptions",
        "subscription_payments",
        "paypal_webhook_events",
        "soulmate_artifacts",
        "ai_generation_jobs",
    }
    for table in expected_tables:
        assert table in table_names, f"Table {table} missing from PostgreSQL database"


def test_unique_answer_constraint(db_session):
    """High-Risk Invariant: Exactly one answer per (session_id + question_code)."""
    # Create test session
    session_obj = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status="IN_PROGRESS",
        current_step="q02",
    )
    db_session.add(session_obj)
    db_session.flush()

    # First answer
    ans1 = SoulmateAnswer(
        session_id=session_obj.id,
        question_code="q02",
        answer_json={"value": "female"},
    )
    db_session.add(ans1)
    db_session.commit()

    # Duplicate answer for same session + question must fail at DB level
    ans2 = SoulmateAnswer(
        session_id=session_obj.id,
        question_code="q02",
        answer_json={"value": "male"},
    )
    db_session.add(ans2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_one_sketch_per_email_partial_unique_index(db_session):
    """High-Risk Invariant ASSET-01: Exactly one sketch per email_normalized (DB-enforced)."""
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"

    sess1 = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        email=test_email,
        email_normalized=test_email,
        quiz_version="soulmate-quiz-v1",
        status="COMPLETED",
        current_step="result",
    )
    sess2 = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        email=test_email,
        email_normalized=test_email,
        quiz_version="soulmate-quiz-v1",
        status="COMPLETED",
        current_step="result",
    )
    db_session.add_all([sess1, sess2])
    db_session.flush()

    unlock_time = datetime.now(timezone.utc) + timedelta(hours=12)

    # First sketch artifact
    art1 = SoulmateArtifact(
        session_id=sess1.id,
        email_normalized=test_email,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=unlock_time,
        generation_status="COMPLETED",
    )
    db_session.add(art1)
    db_session.commit()

    # Second sketch artifact for same email must fail due to partial unique index
    art2 = SoulmateArtifact(
        session_id=sess2.id,
        email_normalized=test_email,
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=unlock_time,
        generation_status="PENDING",
    )
    db_session.add(art2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # But REPORT artifact for same email is allowed by the partial index
    rep1 = SoulmateArtifact(
        session_id=sess1.id,
        email_normalized=test_email,
        artifact_type="REPORT",
        artifact_version="v1",
        unlock_at=unlock_time,
        generation_status="PENDING",
    )
    db_session.add(rep1)
    db_session.commit()


def test_unique_paypal_event_id(db_session):
    """High-Risk Invariant: Webhook deduplication by paypal_event_id."""
    event_id = f"WH-{uuid.uuid4().hex}"

    evt1 = PayPalWebhookEvent(
        paypal_event_id=event_id,
        event_type="PAYMENT.SALE.COMPLETED",
        payload_json={"id": event_id},
        verified=True,
    )
    db_session.add(evt1)
    db_session.commit()

    # Duplicate webhook event ID must be rejected
    evt2 = PayPalWebhookEvent(
        paypal_event_id=event_id,
        event_type="PAYMENT.SALE.COMPLETED",
        payload_json={"id": event_id},
        verified=True,
    )
    db_session.add(evt2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_idempotency_key_ai_jobs(db_session):
    """High-Risk Invariant: AI generation job idempotency."""
    sess = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status="COMPLETED",
        current_step="result",
    )
    db_session.add(sess)
    db_session.flush()

    art = SoulmateArtifact(
        session_id=sess.id,
        email_normalized=f"idemp_{uuid.uuid4().hex[:6]}@example.com",
        artifact_type="SKETCH",
        artifact_version="v1",
        unlock_at=datetime.now(timezone.utc) + timedelta(hours=12),
        generation_status="PENDING",
    )
    db_session.add(art)
    db_session.flush()

    idemp_key = f"job_sketch_{art.id}"

    job1 = AIGenerationJob(
        artifact_id=art.id,
        job_type="SKETCH_GENERATION",
        idempotency_key=idemp_key,
        status="QUEUED",
    )
    db_session.add(job1)
    db_session.commit()

    # Duplicate idempotency_key must fail
    job2 = AIGenerationJob(
        artifact_id=art.id,
        job_type="SKETCH_GENERATION",
        idempotency_key=idemp_key,
        status="QUEUED",
    )
    db_session.add(job2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_utc_timestamptz_preservation(db_session):
    """High-Risk Invariant TIME-01: Timestamps must be timezone-aware UTC."""
    sess = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status="IN_PROGRESS",
        current_step="q02",
    )
    db_session.add(sess)
    db_session.commit()

    # Refresh and verify timezone awareness
    db_session.refresh(sess)
    assert sess.created_at.tzinfo is not None
    assert sess.updated_at.tzinfo is not None


def test_unique_provider_subscription_id(db_session):
    """High-Risk Invariant: Exactly one record per provider_subscription_id."""
    sess1 = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status="COMPLETED",
        current_step="payment",
    )
    sess2 = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status="COMPLETED",
        current_step="payment",
    )
    db_session.add_all([sess1, sess2])
    db_session.flush()

    sub_id = f"I-SUB-{uuid.uuid4().hex[:10].upper()}"

    sub1 = Subscription(
        session_id=sess1.id,
        provider="paypal",
        provider_subscription_id=sub_id,
        provider_plan_id="P-TESTPLAN1",
        provider_status="ACTIVE",
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
    )
    db_session.add(sub1)
    db_session.commit()

    # Second subscription with identical provider_subscription_id must fail at DB level
    sub2 = Subscription(
        session_id=sess2.id,
        provider="paypal",
        provider_subscription_id=sub_id,
        provider_plan_id="P-TESTPLAN2",
        provider_status="ACTIVE",
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
    )
    db_session.add(sub2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_provider_payment_id(db_session):
    """High-Risk Invariant: Exactly one record per provider_payment_id."""
    sess = SoulmateSession(
        public_id=f"sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status="COMPLETED",
        current_step="payment",
    )
    db_session.add(sess)
    db_session.flush()

    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-SUB-{uuid.uuid4().hex[:10].upper()}",
        provider_plan_id="P-TESTPLAN1",
        provider_status="ACTIVE",
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
    )
    db_session.add(sub)
    db_session.flush()

    payment_id = f"PAY-{uuid.uuid4().hex[:10].upper()}"

    pay1 = SubscriptionPayment(
        subscription_id=sub.id,
        provider_payment_id=payment_id,
        amount=Decimal("19.00"),
        currency="USD",
        status="COMPLETED",
    )
    db_session.add(pay1)
    db_session.commit()

    # Second payment with identical provider_payment_id must fail at DB level
    pay2 = SubscriptionPayment(
        subscription_id=sub.id,
        provider_payment_id=payment_id,
        amount=Decimal("29.00"),
        currency="USD",
        status="COMPLETED",
    )
    db_session.add(pay2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_and_query_indexes_exist(db_session):
    """Verify foreign key and query lookup indexes exist on PostgreSQL tables (SP-002 review fix)."""
    inspector = inspect(db_session.bind)

    # 1. soulmate_sessions: idx_soulmate_sessions_user_id and idx_soulmate_sessions_email
    sess_indexes = {idx["name"]: idx["column_names"] for idx in inspector.get_indexes("soulmate_sessions")}
    assert "idx_soulmate_sessions_user_id" in sess_indexes
    assert sess_indexes["idx_soulmate_sessions_user_id"] == ["user_id"]
    assert "idx_soulmate_sessions_email" in sess_indexes
    assert sess_indexes["idx_soulmate_sessions_email"] == ["email_normalized"]

    # 2. subscriptions: idx_subscriptions_session_id
    sub_indexes = {idx["name"]: idx["column_names"] for idx in inspector.get_indexes("subscriptions")}
    assert "idx_subscriptions_session_id" in sub_indexes
    assert sub_indexes["idx_subscriptions_session_id"] == ["session_id"]

    # 3. subscription_payments: idx_subscription_payments_subscription_id
    pay_indexes = {idx["name"]: idx["column_names"] for idx in inspector.get_indexes("subscription_payments")}
    assert "idx_subscription_payments_subscription_id" in pay_indexes
    assert pay_indexes["idx_subscription_payments_subscription_id"] == ["subscription_id"]

    # 4. ai_generation_jobs: idx_ai_generation_jobs_artifact_id
    job_indexes = {idx["name"]: idx["column_names"] for idx in inspector.get_indexes("ai_generation_jobs")}
    assert "idx_ai_generation_jobs_artifact_id" in job_indexes
    assert job_indexes["idx_ai_generation_jobs_artifact_id"] == ["artifact_id"]


def test_alembic_current_revision_is_head(db_session):
    """Verify that the database migration state is at 0002_add_indexes head."""
    result = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert result == "0002_add_indexes"


