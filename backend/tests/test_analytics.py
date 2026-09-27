"""
Central funnel analytics emitter tests (DEV-SPEC §18, SP-901).

Acceptance criteria under test:
1. The event catalog matches the §18.1 contract exactly (27 canonical events)
   and is the single server-side emission point.
2. The per-event property allowlist is enforced in code (§18.2): non-catalog
   properties are dropped; email-shaped and DOB-shaped string values are
   redacted before any emission.
3. Server-authoritative emissions fire exactly once at the right business
   moment: first completed payment (ledger) and sketch generation
   started/completed/terminal-failed (worker).
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.analytics import (
    FUNNEL_EVENT_PROPERTIES,
    sanitize_funnel_properties,
    track_funnel_event,
)
from app.soulmate.domain.sketch_models import SketchProviderError
from app.soulmate.services.ledger_service import PaymentLedgerService
from app.soulmate.services.sketch_generation_service import (
    JOB_FAILED_PERMANENT,
    SketchGenerationService,
)
from app.soulmate.domain.ledger_models import PaymentRecordCreate

pytestmark = pytest.mark.asyncio

# The §18.1 contract, pinned literally so any catalog change on either side
# (backend, frontend wrapper, DEV-SPEC) must be a conscious contract change.
SPEC_181_EVENT_NAMES = frozenset(
    {
        "soulmate_landing_view",
        "soulmate_start_click",
        "soulmate_login_click",
        "soulmate_transition_view",
        "soulmate_transition_continue",
        "soulmate_quiz_started",
        "soulmate_question_view",
        "soulmate_question_answered",
        "soulmate_quiz_back",
        "soulmate_quiz_completed",
        "soulmate_interstitial_answered",
        "soulmate_email_view",
        "soulmate_email_submitted",
        "soulmate_subscribe_view",
        "soulmate_paypal_start",
        "soulmate_paypal_approved",
        "soulmate_payment_confirmed",
        "soulmate_payment_failed",
        "soulmate_result_view",
        "soulmate_sketch_unlocked",
        "soulmate_sketch_viewed",
        "soulmate_sketch_generation_started",
        "soulmate_sketch_generation_completed",
        "soulmate_sketch_generation_failed",
        "soulmate_report_unlocked",
        "soulmate_report_viewed",
        "soulmate_subscription_cancelled",
    }
)


def funnel_records(caplog):
    """Capture structured funnel emissions as (event_type, session_id, extra_data)."""
    out = []
    for record in caplog.records:
        event_type = getattr(record, "event_type", None)
        if isinstance(event_type, str) and event_type.startswith("soulmate_"):
            out.append((event_type, getattr(record, "session_id", None), getattr(record, "extra_data", None)))
    return out


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Catalog + privacy boundary
# ---------------------------------------------------------------------------


async def test_catalog_matches_spec_181_exactly():
    assert frozenset(FUNNEL_EVENT_PROPERTIES.keys()) == SPEC_181_EVENT_NAMES


async def test_sanitize_drops_non_catalog_properties():
    sanitized = sanitize_funnel_properties(
        "soulmate_question_answered",
        {"question_code": "q05", "option_codes": ["asian"], "raw_answer": "free text!", "email": "a@b.com"},
    )
    assert sanitized == {"question_code": "q05", "option_codes": ["asian"]}


async def test_sanitize_redacts_email_and_dob_shaped_values():
    sanitized = sanitize_funnel_properties(
        "soulmate_payment_confirmed",
        {"amount": "19.00", "currency": "buyer@example.com"},
    )
    assert sanitized["amount"] == "19.00"
    assert sanitized["currency"] == "[redacted]"
    # DOB-shaped values are redacted even inside catalog properties (value-based
    # guard): a regression passing a raw date into a question property cannot leak.
    dob_guard = sanitize_funnel_properties(
        "soulmate_question_view",
        {"question_code": "1995-06-15"},
    )
    assert dob_guard == {"question_code": "[redacted]"}


async def test_sanitize_drops_none_values():
    sanitized = sanitize_funnel_properties(
        "soulmate_sketch_viewed", {"artifact_version": None, "other": "x"}
    )
    assert sanitized == {}


async def test_track_funnel_event_emits_structured_record(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    track_funnel_event(
        "soulmate_payment_confirmed",
        session_id="sess-123",
        properties={"amount": "19.00", "currency": "USD"},
    )
    events = [e for e in funnel_records(caplog) if e[0] == "soulmate_payment_confirmed"]
    assert len(events) == 1
    _, session_id, extra = events[0]
    assert session_id == "sess-123"
    assert extra == {"amount": "19.00", "currency": "USD"}


async def test_track_funnel_event_unknown_event_dropped_without_raising(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    track_funnel_event("soulmate_not_a_real_event", properties={"x": "y"})
    assert funnel_records(caplog) == []


# ---------------------------------------------------------------------------
# Server-authoritative emission: first completed payment (ledger)
# ---------------------------------------------------------------------------


async def _seed_paid_session(db, email: str):
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED",
        current_step="result",
        email=email,
        email_normalized=email.lower(),
        subscription_success_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-SP901-{uuid.uuid4().hex[:8].upper()}",
        provider_plan_id="P-SOULMATE-INTRO",
        provider_status="ACTIVE",
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sess, sub


@pytest.fixture(autouse=True)
async def purge_sp901_data():
    yield
    async with AsyncSessionLocal() as db:
        sess_ids = select(SoulmateSession.id).where(SoulmateSession.email.like("sp901_%"))
        await db.execute(
            delete(AIGenerationJob).where(
                AIGenerationJob.artifact_id.in_(
                    select(SoulmateArtifact.id).where(SoulmateArtifact.session_id.in_(sess_ids))
                )
            )
        )
        await db.execute(delete(SoulmateArtifact).where(SoulmateArtifact.session_id.in_(sess_ids)))
        await db.execute(delete(Subscription).where(Subscription.session_id.in_(sess_ids)))
        await db.execute(delete(SoulmateSession).where(SoulmateSession.email.like("sp901_%")))
        await db.commit()


async def test_first_completed_payment_emits_confirmed_once(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess, sub = await _seed_paid_session(async_db, f"sp901_{uuid.uuid4().hex[:8]}@example.com")

    await PaymentLedgerService.record_payment(
        async_db,
        PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id="PAYID-FIRST-1",
            provider_event_id="EVT-1",
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ),
    )
    confirmed = [e for e in funnel_records(caplog) if e[0] == "soulmate_payment_confirmed"]
    assert len(confirmed) == 1
    _, session_id, extra = confirmed[0]
    assert session_id == str(sess.id)
    assert extra == {"amount": "19.00", "currency": "USD"}

    # Renewal (cycle 2): no additional funnel confirmation.
    await PaymentLedgerService.record_payment(
        async_db,
        PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id="PAYID-RENEWAL-1",
            provider_event_id="EVT-2",
            amount=Decimal("29.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime.now(timezone.utc),
        ),
    )
    # Duplicate webhook replay of the first payment: idempotency keeps it at one.
    await PaymentLedgerService.record_payment(
        async_db,
        PaymentRecordCreate(
            subscription_id=sub.id,
            provider_payment_id="PAYID-FIRST-1",
            provider_event_id="EVT-1",
            amount=Decimal("19.00"),
            currency="USD",
            status="COMPLETED",
            paid_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ),
    )
    confirmed_after = [e for e in funnel_records(caplog) if e[0] == "soulmate_payment_confirmed"]
    assert len(confirmed_after) == 1


# ---------------------------------------------------------------------------
# Server-authoritative emission: sketch generation lifecycle (worker)
# ---------------------------------------------------------------------------

# Reuse the SP-603 module's seeding/fakes: identical worker inputs, different
# email prefix (purged above) so global claim scope stays isolated.
from test_sketch_generation import (  # noqa: E402
    FakeProvider,
    RecordingSink,
    seed_generation_session,
)


async def test_worker_emits_started_and_completed_events(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp901_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    assert outcome.created is True

    # job_id-scoped claim: immune to leftover QUEUED jobs from other suites
    status = await SketchGenerationService.process_next_queued_job(
        FakeProvider(), RecordingSink(), job_id=outcome.job.id
    )
    assert status == "COMPLETED"

    events = funnel_records(caplog)
    started = [e for e in events if e[0] == "soulmate_sketch_generation_started"]
    completed = [e for e in events if e[0] == "soulmate_sketch_generation_completed"]
    assert len(started) == 1 and len(completed) == 1
    assert started[0][1] == str(sess.id)
    assert started[0][2]["model"] == "gpt-image-2"
    assert started[0][2]["prompt_version"]
    assert completed[0][1] == str(sess.id)
    assert completed[0][2]["attempts"] == 1
    assert isinstance(completed[0][2]["latency_ms"], int)


async def test_worker_emits_terminal_failed_event_once(async_db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp901_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    assert outcome.created is True

    # A permanent provider error terminates on the first attempt (§11.6).
    provider = FakeProvider(error=SketchProviderError("quota exhausted", retryable=False))
    status = await SketchGenerationService.process_next_queued_job(
        provider, RecordingSink(), job_id=outcome.job.id
    )
    assert status == JOB_FAILED_PERMANENT

    failed = [e for e in funnel_records(caplog) if e[0] == "soulmate_sketch_generation_failed"]
    assert len(failed) == 1
    _, session_id, extra = failed[0]
    assert session_id == str(sess.id)
    assert extra["error_code"] == "GENERATION_FAILED"
    assert extra["attempts"] == 1


async def test_worker_retryable_requeue_emits_no_failed_event(async_db, caplog):
    """§18.1 tracks terminal failures only: a bounded retryable requeue stays off the funnel."""
    import logging

    from app.soulmate.services.sketch_generation_service import JOB_QUEUED

    caplog.set_level(logging.INFO, logger="soulmate")
    sess = await seed_generation_session(async_db, email=f"sp901_{uuid.uuid4().hex[:8]}@example.com")
    outcome = await SketchGenerationService.enqueue_sketch_generation(async_db, sess)
    retryable_provider = FakeProvider(error=SketchProviderError("timeout", retryable=True))
    status = await SketchGenerationService.process_next_queued_job(
        retryable_provider, RecordingSink(), job_id=outcome.job.id
    )
    assert status == JOB_QUEUED
    assert [e for e in funnel_records(caplog) if e[0] == "soulmate_sketch_generation_failed"] == []
