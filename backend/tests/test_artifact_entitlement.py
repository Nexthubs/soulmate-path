"""
Artifact Entitlement Rows on First Payment (SP-501, DEV-SPEC §9.4, §10, §14; Decisions: PAY-AUTH-01, TIME-01).

Acceptance criteria under test:
1. On first successful payment, transactionally create/ensure exactly one SKETCH placeholder
   and one REPORT placeholder for the entitled session.
2. `sketch_unlock_at = first_payment_completed_at + 12h` and
   `report_unlock_at = first_payment_completed_at + 24h` (authoritative payment time, TIME-01).
3. Duplicate payment / webhook replay / concurrent first-payment delivery do NOT duplicate rows;
   unlock timestamps of existing rows are immutable.
4. Entitlement placeholders appear only after a provider-confirmed payment (PAY-AUTH-01) —
   BILLING.SUBSCRIPTION.ACTIVATED alone grants nothing.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Dict, Optional
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import SoulmateArtifact
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal
from app.soulmate.domain.webhook_models import PayPalWebhookHeaders, PayPalWebhookRawRequest
from app.soulmate.services.paypal_client import PayPalClient
from app.soulmate.services.subscription_service import SubscriptionService
from app.soulmate.services.webhook_service import PayPalWebhookService


FIRST_PAYMENT_TIME = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
FIRST_PAYMENT_TIME_STR = "2026-09-25T12:00:00Z"


@pytest.fixture
async def async_db():
    async with AsyncSessionLocal() as session:
        yield session


class MockSuccessVerifier:
    async def verify(self, raw_body: bytes, headers: PayPalWebhookHeaders, **kwargs: Any) -> bool:
        return True


class MockPayPalClient(PayPalClient):
    """Mock PayPalClient that returns configurable subscription payloads without live network calls."""

    def __init__(self, subscription_responses: Optional[Dict[str, Any]] = None):
        super().__init__(client_id="mock_id", client_secret="mock_secret")
        self.subscription_responses = subscription_responses or {}

    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        return self.subscription_responses.get(subscription_id)

    async def list_subscription_transactions(
        self,
        subscription_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        return []


SAMPLE_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-123",
    "PAYPAL-TRANSMISSION-ID": "trans_123456789",
    "PAYPAL-TRANSMISSION-SIG": "dummy_sig_base64_content",
    "PAYPAL-TRANSMISSION-TIME": "2026-09-25T12:00:00Z",
}


def make_raw_request(event_data: Dict[str, Any]) -> PayPalWebhookRawRequest:
    raw_bytes = json.dumps(event_data).encode("utf-8")

    class DummyReq:
        headers = SAMPLE_HEADERS

    return PayPalWebhookService.parse_raw_request(request=DummyReq(), raw_body=raw_bytes)


def make_payment_event(provider_sub_id: str, payment_id: str, event_id: str, create_time: str) -> Dict[str, Any]:
    return {
        "id": event_id,
        "event_version": "1.0",
        "create_time": create_time,
        "resource_type": "sale",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "summary": "Payment completed for subscription",
        "resource": {
            "id": payment_id,
            "billing_agreement_id": provider_sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "state": "completed",
            "create_time": create_time,
        },
    }


async def create_test_session_and_sub(
    db: AsyncSession,
    provider_sub_id: str,
    email: str,
    status: str = "APPROVAL_PENDING",
) -> tuple[SoulmateSession, Subscription]:
    """Seed an unpaid session + subscription in PROCESSING state (PAY-AUTH-01: not entitled yet)."""
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:10]}",
        quiz_version="soulmate-quiz-v1",
        status="email_captured",
        current_step="subscribe",
        email=email,
        email_normalized=email.lower(),
        subscription_success_at=None,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=provider_sub_id,
        provider_plan_id="P-SOULMATE-INTRO",
        provider_status=status,
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        first_payment_at=None,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sess, sub


async def deliver_payment_webhook(db: AsyncSession, event_data: Dict[str, Any]) -> None:
    await PayPalWebhookService.process_webhook(
        raw_request=make_raw_request(event_data),
        db=db,
        verifier=MockSuccessVerifier(),
    )


async def load_artifacts(db: AsyncSession, session_id) -> list[SoulmateArtifact]:
    stmt = select(SoulmateArtifact).where(SoulmateArtifact.session_id == session_id)
    return list((await db.execute(stmt)).scalars().all())


# ==============================================================================
# AC 1 & 2: First payment creates exact placeholders with exact unlock times
# ==============================================================================


@pytest.mark.asyncio
async def test_first_payment_creates_one_sketch_and_one_report_with_exact_unlocks(async_db: AsyncSession):
    provider_sub_id = f"I-SP501-{uuid.uuid4().hex[:8].upper()}"
    email = f"sp501_{uuid.uuid4().hex[:8]}@example.com"
    session, sub = await create_test_session_and_sub(async_db, provider_sub_id, email)

    # PAY-AUTH-01: no artifacts before a provider-confirmed payment
    assert await load_artifacts(async_db, session.id) == []

    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id,
            payment_id=f"SALE-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-{uuid.uuid4().hex[:8]}",
            create_time=FIRST_PAYMENT_TIME_STR,
        ),
    )
    await async_db.commit()
    await async_db.refresh(session)

    assert session.subscription_success_at == FIRST_PAYMENT_TIME
    assert session.status == "paid"
    assert session.current_step == "result"

    artifacts = await load_artifacts(async_db, session.id)
    assert len(artifacts) == 2
    types = {a.artifact_type for a in artifacts}
    assert types == {"SKETCH", "REPORT"}

    sketch = next(a for a in artifacts if a.artifact_type == "SKETCH")
    report = next(a for a in artifacts if a.artifact_type == "REPORT")

    # TIME-01: unlock timestamps derive from the authoritative first payment time
    assert sketch.unlock_at == FIRST_PAYMENT_TIME + timedelta(hours=12)
    assert report.unlock_at == FIRST_PAYMENT_TIME + timedelta(hours=24)
    for artifact in (sketch, report):
        assert artifact.artifact_version == "v1"
        assert artifact.generation_status == "NOT_STARTED"
        assert artifact.email_normalized == email.lower()
    # Placeholders only: no generated content yet
    assert sketch.storage_key is None and report.storage_key is None
    assert sketch.content_json is None and report.content_json is None


# ==============================================================================
# AC 3: Duplicates (replay, distinct event IDs, reconciliation) do not duplicate rows
# ==============================================================================


@pytest.mark.asyncio
async def test_duplicate_webhook_replay_does_not_duplicate_artifacts(async_db: AsyncSession):
    provider_sub_id = f"I-SP501D-{uuid.uuid4().hex[:8].upper()}"
    session, _ = await create_test_session_and_sub(
        async_db, provider_sub_id, f"sp501dup_{uuid.uuid4().hex[:8]}@example.com"
    )
    event = make_payment_event(
        provider_sub_id=provider_sub_id,
        payment_id=f"SALE-{uuid.uuid4().hex[:8]}",
        event_id=f"WH-{uuid.uuid4().hex[:8]}",
        create_time=FIRST_PAYMENT_TIME_STR,
    )
    await deliver_payment_webhook(async_db, event)
    await async_db.commit()

    unlocks_before = {a.artifact_type: a.unlock_at for a in await load_artifacts(async_db, session.id)}

    for _ in range(3):
        await deliver_payment_webhook(async_db, event)
        await async_db.commit()

    artifacts = await load_artifacts(async_db, session.id)
    assert len(artifacts) == 2
    assert {a.artifact_type for a in artifacts} == {"SKETCH", "REPORT"}
    for artifact in artifacts:
        assert artifact.unlock_at == unlocks_before[artifact.artifact_type]


@pytest.mark.asyncio
async def test_duplicate_payment_with_different_event_ids_does_not_duplicate_artifacts(async_db: AsyncSession):
    provider_sub_id = f"I-SP501E-{uuid.uuid4().hex[:8].upper()}"
    session, _ = await create_test_session_and_sub(
        async_db, provider_sub_id, f"sp501evt_{uuid.uuid4().hex[:8]}@example.com"
    )
    shared_payment_id = f"SALE-{uuid.uuid4().hex[:8]}"
    for i in range(3):
        await deliver_payment_webhook(
            async_db,
            make_payment_event(
                provider_sub_id=provider_sub_id,
                payment_id=shared_payment_id,
                event_id=f"WH-DIFF-{i}-{uuid.uuid4().hex[:8]}",
                create_time=FIRST_PAYMENT_TIME_STR,
            ),
        )
        await async_db.commit()

    artifacts = await load_artifacts(async_db, session.id)
    assert len(artifacts) == 2
    assert {a.artifact_type for a in artifacts} == {"SKETCH", "REPORT"}


@pytest.mark.asyncio
async def test_reconciliation_after_webhook_does_not_duplicate_or_shift_unlocks(async_db: AsyncSession):
    provider_sub_id = f"I-SP501R-{uuid.uuid4().hex[:8].upper()}"
    session, sub = await create_test_session_and_sub(
        async_db, provider_sub_id, f"sp501rec_{uuid.uuid4().hex[:8]}@example.com"
    )
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id,
            payment_id=f"SALE-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-{uuid.uuid4().hex[:8]}",
            create_time=FIRST_PAYMENT_TIME_STR,
        ),
    )
    await async_db.commit()
    before = {a.artifact_type: a.unlock_at for a in await load_artifacts(async_db, session.id)}

    # A later reconciliation (e.g. delayed webhook recovery path) must not create or shift rows
    mock_payload = {
        "id": provider_sub_id,
        "status": "ACTIVE",
        "plan_id": "P-SOULMATE-INTRO",
        "billing_info": {
            "last_payment": {"time": "2026-10-25T12:00:00Z"},
            "next_billing_time": "2026-11-25T12:00:00Z",
        },
    }
    await SubscriptionService.reconcile_subscription(
        db=async_db,
        provider_subscription_id=provider_sub_id,
        paypal_client=MockPayPalClient({provider_sub_id: mock_payload}),
    )
    await async_db.commit()

    artifacts = await load_artifacts(async_db, session.id)
    assert len(artifacts) == 2
    for artifact in artifacts:
        assert artifact.unlock_at == before[artifact.artifact_type]


# ==============================================================================
# AC 3 (concurrency): simultaneous first-payment delivery does not duplicate rows
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_ensure_artifacts_creates_single_rows(async_db: AsyncSession):
    """
    Webhook and reconcile paths can process the first payment at the same moment.
    Two concurrent create/ensure executions against the same session must commit cleanly
    (savepoint race tolerance) and leave exactly one SKETCH and one REPORT row.
    """
    provider_sub_id = f"I-SP501C-{uuid.uuid4().hex[:8].upper()}"
    email = f"sp501conc_{uuid.uuid4().hex[:8]}@example.com"
    session, _ = await create_test_session_and_sub(async_db, provider_sub_id, email)
    session_id = session.id

    async def ensure_in_own_session() -> None:
        async with AsyncSessionLocal() as db:
            stmt = select(SoulmateSession).where(SoulmateSession.id == session_id)
            sess = (await db.execute(stmt)).scalars().first()
            await SubscriptionService._ensure_artifacts_initialized(
                session=sess,
                paid_at=FIRST_PAYMENT_TIME,
                db=db,
            )
            await db.commit()

    await asyncio.gather(ensure_in_own_session(), ensure_in_own_session())

    artifacts = await load_artifacts(async_db, session_id)
    assert len(artifacts) == 2
    assert {a.artifact_type for a in artifacts} == {"SKETCH", "REPORT"}
    for artifact in artifacts:
        expected = FIRST_PAYMENT_TIME + timedelta(hours=12 if artifact.artifact_type == "SKETCH" else 24)
        assert artifact.unlock_at == expected


@pytest.mark.asyncio
async def test_ensure_artifacts_tolerates_lost_insert_race_deterministically(async_db: AsyncSession):
    """
    Deterministic reproduction of the concurrent first-payment race: an uncommitted competing
    transaction inserts the SKETCH row first, so the ensure SELECT misses it and the INSERT
    blocks on the unique index until the competitor commits. The savepoint rollback must
    swallow the resulting IntegrityError and the ensure must complete with exactly one
    SKETCH (the competitor's) and one REPORT row — no failed webhook transaction.
    """
    provider_sub_id = f"I-SP501L-{uuid.uuid4().hex[:8].upper()}"
    email = f"sp501race_{uuid.uuid4().hex[:8]}@example.com"
    session, _ = await create_test_session_and_sub(async_db, provider_sub_id, email)
    session_id = session.id

    # Competing delivery (e.g. reconcile) inserts the sketch row first, uncommitted
    blocker = AsyncSessionLocal()
    try:
        stmt = select(SoulmateSession).where(SoulmateSession.id == session_id)
        sess_b = (await blocker.execute(stmt)).scalars().first()
        blocker.add(
            SoulmateArtifact(
                session_id=session_id,
                email_normalized=email.lower(),
                artifact_type="SKETCH",
                artifact_version="v1",
                unlock_at=FIRST_PAYMENT_TIME + timedelta(hours=12),
                generation_status="NOT_STARTED",
            )
        )
        await blocker.flush()

        # Concurrent webhook-side ensure in its own transaction: its SELECT cannot see the
        # uncommitted row above, so its INSERT blocks on the unique index.
        ensure_task = asyncio.create_task(
            SubscriptionService._ensure_artifacts_initialized(
                session=session,
                paid_at=FIRST_PAYMENT_TIME,
                db=async_db,
            )
        )
        # Deterministically wait until the ensure INSERT is observed blocked on the
        # competing transaction (proves the lost-insert race is actually exercised).
        # Polled from the blocker's own idle-in-transaction connection: an AsyncSession
        # must never be driven by two coroutines at once.
        race_exercised = False
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            blocked = (
                await blocker.execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted"))
            ).scalar()
            if blocked > 0:
                race_exercised = True
                break
            await asyncio.sleep(0.05)

        await blocker.commit()
        await asyncio.wait_for(ensure_task, timeout=10)
        await async_db.commit()
    finally:
        await blocker.close()

    assert race_exercised, "ensure INSERT was never observed blocking on the competing transaction"

    artifacts = await load_artifacts(async_db, session_id)
    assert len(artifacts) == 2
    assert {a.artifact_type for a in artifacts} == {"SKETCH", "REPORT"}
    for artifact in artifacts:
        expected = FIRST_PAYMENT_TIME + timedelta(hours=12 if artifact.artifact_type == "SKETCH" else 24)
        assert artifact.unlock_at == expected


# ==============================================================================
# AC 4 (PAY-AUTH-01): activation without payment grants no artifacts
# ==============================================================================


@pytest.mark.asyncio
async def test_subscription_activated_event_alone_does_not_create_artifacts(async_db: AsyncSession):
    provider_sub_id = f"I-SP501A-{uuid.uuid4().hex[:8].upper()}"
    session, _ = await create_test_session_and_sub(async_db, provider_sub_id, f"sp501act_{uuid.uuid4().hex[:8]}@example.com")

    event = {
        "id": f"WH-ACT-{uuid.uuid4().hex[:8]}",
        "create_time": FIRST_PAYMENT_TIME_STR,
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {"id": provider_sub_id, "status": "ACTIVE"},
    }
    await deliver_payment_webhook(async_db, event)
    await async_db.commit()
    await async_db.refresh(session)

    assert session.subscription_success_at is None
    assert await load_artifacts(async_db, session.id) == []


# ==============================================================================
# AC 5 (TIME-01): renewals never shift unlock timestamps
# ==============================================================================


@pytest.mark.asyncio
async def test_renewal_payment_does_not_shift_unlock_times(async_db: AsyncSession):
    provider_sub_id = f"I-SP501N-{uuid.uuid4().hex[:8].upper()}"
    session, _ = await create_test_session_and_sub(async_db, provider_sub_id, f"sp501ren_{uuid.uuid4().hex[:8]}@example.com")
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id,
            payment_id=f"SALE-FIRST-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-FIRST-{uuid.uuid4().hex[:8]}",
            create_time=FIRST_PAYMENT_TIME_STR,
        ),
    )
    await async_db.commit()
    await async_db.refresh(session)
    success_at_before = session.subscription_success_at
    unlocks_before = {a.artifact_type: a.unlock_at for a in await load_artifacts(async_db, session.id)}

    renewal_time_str = "2026-10-25T12:00:00Z"
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id,
            payment_id=f"SALE-RENEW-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-RENEW-{uuid.uuid4().hex[:8]}",
            create_time=renewal_time_str,
        ),
    )
    await async_db.commit()
    await async_db.refresh(session)

    assert session.subscription_success_at == success_at_before
    artifacts = await load_artifacts(async_db, session.id)
    assert len(artifacts) == 2
    for artifact in artifacts:
        assert artifact.unlock_at == unlocks_before[artifact.artifact_type]


@pytest.mark.asyncio
async def test_missing_artifacts_self_heal_from_authoritative_first_payment(async_db: AsyncSession):
    """
    If an entitled session is missing artifact rows (e.g. drift from a partial historical
    activation), the next confirmed payment recreates them based on the authoritative
    FIRST payment time — not the renewal time that triggered the heal.
    """
    provider_sub_id = f"I-SP501H-{uuid.uuid4().hex[:8].upper()}"
    session, sub = await create_test_session_and_sub(async_db, provider_sub_id, f"sp501heal_{uuid.uuid4().hex[:8]}@example.com")
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id,
            payment_id=f"SALE-FIRST-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-FIRST-{uuid.uuid4().hex[:8]}",
            create_time=FIRST_PAYMENT_TIME_STR,
        ),
    )
    await async_db.commit()

    # Simulate row drift by deleting the placeholders
    for artifact in await load_artifacts(async_db, session.id):
        await async_db.delete(artifact)
    await async_db.commit()
    assert await load_artifacts(async_db, session.id) == []

    renewal_time_str = "2026-10-25T12:00:00Z"
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id,
            payment_id=f"SALE-RENEW-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-RENEW-{uuid.uuid4().hex[:8]}",
            create_time=renewal_time_str,
        ),
    )
    await async_db.commit()

    artifacts = await load_artifacts(async_db, session.id)
    assert len(artifacts) == 2
    for artifact in artifacts:
        expected = FIRST_PAYMENT_TIME + timedelta(hours=12 if artifact.artifact_type == "SKETCH" else 24)
        assert artifact.unlock_at == expected


# ==============================================================================
# ASSET-01 boundary: one sketch per email across sessions
# ==============================================================================


@pytest.mark.asyncio
async def test_second_session_same_email_does_not_duplicate_sketch(async_db: AsyncSession):
    email = f"sp501one_{uuid.uuid4().hex[:8]}@example.com"
    provider_sub_id_a = f"I-SP501SA-{uuid.uuid4().hex[:8].upper()}"
    session_a, _ = await create_test_session_and_sub(async_db, provider_sub_id_a, email)
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id_a,
            payment_id=f"SALE-A-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-A-{uuid.uuid4().hex[:8]}",
            create_time=FIRST_PAYMENT_TIME_STR,
        ),
    )
    await async_db.commit()

    second_payment_time = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    second_payment_time_str = "2026-10-25T12:00:00Z"
    provider_sub_id_b = f"I-SP501SB-{uuid.uuid4().hex[:8].upper()}"
    session_b, _ = await create_test_session_and_sub(async_db, provider_sub_id_b, email)
    await deliver_payment_webhook(
        async_db,
        make_payment_event(
            provider_sub_id=provider_sub_id_b,
            payment_id=f"SALE-B-{uuid.uuid4().hex[:8]}",
            event_id=f"WH-B-{uuid.uuid4().hex[:8]}",
            create_time=second_payment_time_str,
        ),
    )
    await async_db.commit()

    # Sketch remains unique per email (ASSET-01); session B still gets its own report placeholder
    stmt = select(SoulmateArtifact).where(
        SoulmateArtifact.email_normalized == email,
        SoulmateArtifact.artifact_type == "SKETCH",
    )
    sketches = list((await async_db.execute(stmt)).scalars().all())
    assert len(sketches) == 1
    assert sketches[0].session_id == session_a.id
    assert sketches[0].unlock_at == FIRST_PAYMENT_TIME + timedelta(hours=12)

    report_b = (
        await async_db.execute(
            select(SoulmateArtifact).where(
                SoulmateArtifact.session_id == session_b.id,
                SoulmateArtifact.artifact_type == "REPORT",
            )
        )
    ).scalars().first()
    assert report_b is not None
    assert report_b.unlock_at == second_payment_time + timedelta(hours=24)
