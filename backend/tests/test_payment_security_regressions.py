"""RV-01/RV-02 Critical/High regression evidence on real PostgreSQL.

Provider responses are mocked; transaction/locking/constraints and HTTP ownership
are real. Run using backend/scripts/test_isolated.py, never the shared app DB.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import select, func

from app.core.config import settings
from app.core.errors import ProviderUnavailableError, ValidationError
from app.db.models.billing import Subscription, SubscriptionPayment, PayPalWebhookEvent
from app.db.models.session import SoulmateSession
from app.db.models.artifact import SoulmateArtifact
from app.db.session import AsyncSessionLocal
from app.soulmate.services.subscription_service import SubscriptionService as SubService
from app.soulmate.services.webhook_service import PayPalWebhookService as Webhooks
from test_webhook_idempotency_ordering import make_raw_request, MockSuccessVerifier

T0 = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=31)


@pytest.fixture(autouse=True)
def configured_policy(monkeypatch):
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", "P-RV-INTRO")
    monkeypatch.setattr(settings, "paypal_soulmate_standard_plan_id", "P-RV-STANDARD")
    monkeypatch.setattr(settings, "soulmate_resubscription_policy", "blocked")


async def seed(*, with_sub=True, email=None):
    async with AsyncSessionLocal() as db:
        sid = uuid.uuid4().hex
        session = SoulmateSession(public_id=f"rv_{sid}", quiz_version="soulmate-quiz-v1",
            status="EMAIL_CAPTURED", current_step="subscribe",
            email=email or f"{sid}@example.com", email_normalized=email or f"{sid}@example.com")
        db.add(session)
        await db.flush()
        sub = None
        if with_sub:
            sub = Subscription(session_id=session.id, provider_subscription_id=f"I-{sid[:12].upper()}",
                provider_plan_id="P-RV-INTRO", provider_status="APPROVAL_PENDING", currency="USD",
                intro_price=Decimal("19"), regular_price=Decimal("29"), created_at=T0-timedelta(days=1))
            db.add(sub)
        await db.commit()
        return session, sub


def event(kind, sub_id, at=T0, **resource):
    return {"id": f"WH-{uuid.uuid4().hex}", "event_type": kind, "create_time": at.isoformat(),
            "resource": {"id": sub_id, **resource}}


def sale(sub_id, at=T0, payment_id=None):
    return event("PAYMENT.SALE.COMPLETED", sub_id, at,
        id=payment_id or f"SALE-{uuid.uuid4().hex}", billing_agreement_id=sub_id,
        amount={"total": "19.00", "currency": "USD"}, create_time=at.isoformat())


async def deliver(payload, client=None):
    async with AsyncSessionLocal() as db:
        return await Webhooks.process_webhook(make_raw_request(payload), db,
            verifier=MockSuccessVerifier(), client=client)


def provider(session, sub_id, *, last=T1, transactions=None):
    remote = {"id": sub_id, "custom_id": session.public_id, "plan_id": "P-RV-INTRO",
        "status": "ACTIVE", "create_time": (T0-timedelta(days=2)).isoformat(),
        "status_update_time": T0.isoformat(), "billing_info": {
            "last_payment": {"time": last.isoformat(), "amount": {"value": "29", "currency_code": "USD"}}}}
    if transactions is None:
        transactions = [transaction(T0), transaction(T1)]
    return AsyncMock(get_subscription=AsyncMock(return_value=remote),
                     list_subscription_transactions=AsyncMock(return_value=transactions))


def transaction(at):
    return {"id": f"TX-{at.timestamp()}", "status": "COMPLETED", "time": at.isoformat(),
            "amount_with_breakdown": {"gross_amount": {"value": "19", "currency_code": "USD"}}}


async def assert_entitlement(session_id, sub_id, base, payments=None):
    async with AsyncSessionLocal() as db:
        session = await db.get(SoulmateSession, session_id)
        sub = await db.get(Subscription, sub_id)
        assert session.subscription_success_at == sub.first_payment_at == base
        artifacts = (await db.execute(select(SoulmateArtifact).where(SoulmateArtifact.session_id == session_id))).scalars().all()
        assert len(artifacts) == 2
        assert {a.artifact_type: a.unlock_at for a in artifacts} == {
            "SKETCH": base+timedelta(hours=12), "REPORT": base+timedelta(hours=24)}
        if payments is not None:
            count = (await db.execute(select(func.count()).select_from(SubscriptionPayment).where(
                SubscriptionPayment.subscription_id == sub_id))).scalar()
            assert count == payments


@pytest.mark.asyncio
async def test_reconciliation_uses_earliest_transaction_not_last_payment():
    session, sub = await seed()
    client = provider(session, sub.provider_subscription_id)
    # IDs must be unique across independent test subscriptions.
    for tx in client.list_subscription_transactions.return_value:
        tx["id"] += uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        await SubService.reconcile_subscription(db, sub.provider_subscription_id, client)
        await db.commit()
    await assert_entitlement(session.id, sub.id, T0, payments=2)
    assert client.list_subscription_transactions.call_args.kwargs["start_time"] < T0.isoformat()


@pytest.mark.asyncio
async def test_last_payment_summary_without_transactions_never_grants_entitlement():
    session, sub = await seed()
    async with AsyncSessionLocal() as db:
        await SubService.reconcile_subscription(db, sub.provider_subscription_id,
            provider(session, sub.provider_subscription_id, transactions=[]))
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Subscription, sub.id)).first_payment_at is None
        assert (await db.get(SoulmateSession, session.id)).subscription_success_at is None


@pytest.mark.asyncio
async def test_unbound_sale_provider_outage_is_retryable_then_recovers():
    session, _ = await seed(with_sub=False)
    sub_id = f"I-{uuid.uuid4().hex[:12].upper()}"
    payload = sale(sub_id)
    client = provider(session, sub_id, transactions=[])
    client.get_subscription.side_effect = TimeoutError("temporary outage")
    with pytest.raises(ProviderUnavailableError):
        await deliver(payload, client)
    async with AsyncSessionLocal() as db:
        receipt = (await db.execute(select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == payload["id"]))).scalar_one()
        assert receipt.processed_at is None and receipt.processing_error
        assert (await db.execute(select(Subscription).where(Subscription.provider_subscription_id == sub_id))).scalar_one_or_none() is None
    client.get_subscription.side_effect = None
    response = await deliver(payload, client)
    assert response.status == "success"
    async with AsyncSessionLocal() as db:
        sub = (await db.execute(select(Subscription).where(Subscription.provider_subscription_id == sub_id))).scalar_one()
    await assert_entitlement(session.id, sub.id, T0, payments=1)
    assert (await deliver(payload, client)).duplicate


@pytest.mark.asyncio
async def test_missing_binding_sale_stays_pending_even_with_unique_payer_email():
    session, _ = await seed(with_sub=False)
    sub_id = f"I-{uuid.uuid4().hex[:12].upper()}"
    client = provider(session, sub_id)
    remote = client.get_subscription.return_value
    del remote["custom_id"]
    remote["subscriber"] = {"email_address": session.email_normalized}
    payload = sale(sub_id)
    for _ in range(2):
        with pytest.raises(ProviderUnavailableError):
            await deliver(payload, client)
    async with AsyncSessionLocal() as db:
        assert (await db.get(SoulmateSession, session.id)).subscription_success_at is None
        receipt = (await db.execute(select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == payload["id"]))).scalar_one()
        assert receipt.processed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["PAYMENT.SALE.REFUNDED", "PAYMENT.SALE.REVERSED"])
async def test_refund_reversal_before_sale_retries_and_uses_sale_identity(kind):
    session, sub = await seed()
    completed = sale(sub.provider_subscription_id)
    pay_id = completed["resource"]["id"]
    resource = {"parent_payment": "PAY-NOT-A-SALE", "create_time": T1.isoformat()}
    if kind.endswith("REFUNDED"):
        resource["sale_id"] = pay_id
    payload = event(kind, pay_id if kind.endswith("REVERSED") else "REFUND-ID", T1, **resource)
    with pytest.raises(ProviderUnavailableError):
        await deliver(payload)
    await deliver(completed)
    assert (await deliver(payload)).status == "success"
    assert (await deliver(payload)).duplicate
    # A second sale event must not undo the refund.
    completed["id"] = f"WH-{uuid.uuid4().hex}"
    await deliver(completed)
    async with AsyncSessionLocal() as db:
        payment = (await db.execute(select(SubscriptionPayment).where(SubscriptionPayment.provider_payment_id == pay_id))).scalar_one()
        assert payment.status == kind.split(".")[-1]
        assert payment.refunded_at == T1


@pytest.mark.asyncio
@pytest.mark.parametrize("new_status,old_status", [("CANCELLED", "SUSPENDED"), ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")])
async def test_stale_updated_event_cannot_regress_state_or_billing(new_status, old_status):
    _, sub = await seed()
    await deliver(event("BILLING.SUBSCRIPTION.UPDATED", sub.provider_subscription_id, T1,
        status=new_status, billing_info={"failed_payments_count": 2}))
    await deliver(event("BILLING.SUBSCRIPTION.UPDATED", sub.provider_subscription_id, T0,
        status=old_status, billing_info={"failed_payments_count": 0}))
    async with AsyncSessionLocal() as db:
        row = await db.get(Subscription, sub.id)
        assert row.provider_status == new_status
        assert row.provider_status_updated_at == T1
        assert row.failed_payments_count == 2


@pytest.mark.asyncio
async def test_activation_is_not_payment_and_old_sale_does_not_clear_new_failure():
    session, sub = await seed()
    await deliver(event("BILLING.SUBSCRIPTION.PAYMENT.FAILED", sub.provider_subscription_id, T1,
                        status="SUSPENDED", billing_info={"failed_payments_count": 2}))
    await deliver(sale(sub.provider_subscription_id, T0))
    async with AsyncSessionLocal() as db:
        row = await db.get(Subscription, sub.id)
        assert row.provider_status == "SUSPENDED" and row.failed_payments_count == 2
    await deliver(event("BILLING.SUBSCRIPTION.ACTIVATED", sub.provider_subscription_id, T1+timedelta(hours=1)))
    async with AsyncSessionLocal() as db:
        row = await db.get(Subscription, sub.id)
        assert row.provider_status == "ACTIVE" and row.failed_payments_count == 2
    await deliver(sale(sub.provider_subscription_id, T1+timedelta(hours=2)))
    async with AsyncSessionLocal() as db:
        assert (await db.get(Subscription, sub.id)).failed_payments_count == 0
    await assert_entitlement(session.id, sub.id, T0)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy,plan,accepted", [("blocked","P-RV-INTRO",False), ("single_intro","P-RV-INTRO",False), ("single_intro","P-RV-STANDARD",True), ("allow_intro","P-RV-INTRO",True)])
@pytest.mark.parametrize("path", ["confirm", "reconcile"])
async def test_server_enforces_plan_policy_on_both_binding_paths(monkeypatch, policy, plan, accepted, path):
    session, _ = await seed()
    monkeypatch.setattr(settings, "soulmate_resubscription_policy", policy)
    new_id = f"I-{uuid.uuid4().hex[:12].upper()}"
    client = provider(session, new_id, transactions=[])
    client.get_subscription.return_value["plan_id"] = plan
    async with AsyncSessionLocal() as db:
        if path == "confirm":
            if accepted:
                await SubService.confirm_paypal_subscription(db, session, new_id, client)
            else:
                with pytest.raises(ValidationError):
                    await SubService.confirm_paypal_subscription(db, session, new_id, client)
        else:
            result = await SubService.reconcile_subscription(db, new_id, client)
            assert (result is not None) == accepted
            await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_event", [True, False])
async def test_concurrent_webhooks_have_one_payment_and_one_entitlement(same_event):
    session, sub = await seed()
    payload = sale(sub.provider_subscription_id)
    events = [dict(payload, id=payload["id"] if same_event else f"WH-{uuid.uuid4().hex}") for _ in range(6)]
    await asyncio.wait_for(asyncio.gather(*(deliver(e) for e in events)), 15)
    await assert_entitlement(session.id, sub.id, T0, payments=1)


@pytest.mark.asyncio
async def test_webhook_reconcile_concurrency_keeps_earliest_base_consistent():
    session, sub = await seed()
    client = provider(session, sub.provider_subscription_id)
    for tx in client.list_subscription_transactions.return_value:
        tx["id"] += uuid.uuid4().hex
    async def reconcile():
        async with AsyncSessionLocal() as db:
            await SubService.reconcile_subscription(db, sub.provider_subscription_id, client)
            await db.commit()
    await asyncio.wait_for(asyncio.gather(deliver(sale(sub.provider_subscription_id, T1)), reconcile()), 15)
    await assert_entitlement(session.id, sub.id, T0, payments=3)


@pytest.mark.asyncio
async def test_delayed_earlier_sale_corrects_times_without_replacing_completed_asset():
    session, sub = await seed()
    await deliver(sale(sub.provider_subscription_id, T1))
    async with AsyncSessionLocal() as db:
        artifact = (await db.execute(select(SoulmateArtifact).where(SoulmateArtifact.session_id==session.id,
                                    SoulmateArtifact.artifact_type=="SKETCH"))).scalar_one()
        artifact.generation_status="COMPLETED"
        artifact.storage_key="durable/original.png"
        original_id=artifact.id
        await db.commit()
    await deliver(sale(sub.provider_subscription_id, T0))
    await assert_entitlement(session.id, sub.id, T0, payments=2)
    async with AsyncSessionLocal() as db:
        artifact=await db.get(SoulmateArtifact, original_id)
        assert artifact.generation_status=="COMPLETED" and artifact.storage_key=="durable/original.png"


@pytest.mark.asyncio
async def test_business_failure_rolls_back_payment_and_entitlement_but_keeps_retry_receipt(monkeypatch):
    session, sub = await seed()
    payload = sale(sub.provider_subscription_id)
    original = SubService._ensure_artifacts_initialized
    monkeypatch.setattr(SubService,"_ensure_artifacts_initialized",AsyncMock(side_effect=RuntimeError("after ledger")))
    with pytest.raises(RuntimeError):
        await deliver(payload)
    async with AsyncSessionLocal() as db:
        assert (await db.get(Subscription,sub.id)).first_payment_at is None
        assert (await db.get(SoulmateSession,session.id)).subscription_success_at is None
        assert (await db.execute(select(func.count()).select_from(SubscriptionPayment).where(SubscriptionPayment.subscription_id==sub.id))).scalar()==0
    monkeypatch.setattr(SubService,"_ensure_artifacts_initialized",original)
    await deliver(payload)
    await assert_entitlement(session.id,sub.id,T0,payments=1)
