"""
SP-1005 — Security / IDOR test pass (DEV-SPEC §20, §23; Decisions: PAY-AUTH-01, TIME-01).

Attacker-perspective pass over every user-facing API surface with independent
live sessions: a paid VICTIM and an unpaid ATTACKER, each with its own signed
soulmate_sid cookie. Covers the TASK-BREAKDOWN SP-1005 cases:

1. access another session by ID             -> cross-session matrix on all scoped endpoints;
2. access another sketch/report             -> artifact reads/generates stay session-scoped;
3. spoof paid/unlocked fields from browser  -> forged fields rejected, tokens cannot be
                                               tampered or minted (§20 client-immutable
                                               columns), provider confirm cannot grant or
                                               hijack entitlement (PAY-AUTH-01);
4. call generate before unlock              -> 423 against the persisted unlock_at, no job
                                               row (TIME-01);
5. invalid webhook/signature                -> rejected with zero business effect (§9.6);
6. manipulate route only without entitlement -> guard denies paid routes for unpaid
                                               sessions; data APIs deny independently.

Acceptance (TASK-BREAKDOWN SP-1005): every unauthorized path is denied without
leaking target existence (the ownership guard answers 403 before any existence
lookup, so real and fabricated target IDs are indistinguishable) or content
(no victim email/storage-key/report content in any denial body).

Run via backend/scripts/test_isolated.py on a disposable PostgreSQL database.
"""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.artifact import AIGenerationJob, SoulmateArtifact
from app.db.models.billing import PayPalWebhookEvent, Subscription, SubscriptionPayment
from app.db.models.session import SoulmateAnswer, SoulmateSession
from app.db.session import AsyncSessionLocal
from app.main import app
from app.soulmate.security import generate_session_token
from app.soulmate.services import subscription_service
from app.soulmate.services.report_fixture import MOCK_REPORT_JSON
from app.soulmate.services.webhook_verifier import PayPalWebhookVerifier, get_webhook_verifier
from test_subscription_confirm import MockPayPalClient


API = "/api/soulmate"
VICTIM_STORAGE_KEY = "qa/security/victim-sketch.png"


# ==============================================================================
# Fixtures & seeding
# ==============================================================================


async def seed_session(
    db: AsyncSession,
    *,
    paid: bool = False,
    recently_paid: bool = False,
    sketch_completed: bool = False,
    report_completed: bool = False,
) -> SoulmateSession:
    """Seed one session. Paid sessions get a confirmed subscription + artifact rows
    whose unlock times follow TIME-01 arithmetic from first_payment_at."""
    now = datetime.now(timezone.utc)
    paid_at = now - (timedelta(hours=1) if recently_paid else timedelta(hours=25))
    email = f"sec_{uuid.uuid4().hex[:10]}@example.com"

    sess = SoulmateSession(
        public_id=f"ses_{uuid.uuid4().hex}",
        quiz_version="soulmate-quiz-v1",
        status="SUBSCRIBED" if paid else "EMAIL_CAPTURED",
        current_step="result" if paid else "subscribe",
        email=email,
        email_normalized=email,
        subscription_success_at=paid_at if paid else None,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    if paid:
        db.add(
            Subscription(
                session_id=sess.id,
                provider="paypal",
                provider_subscription_id=f"I-SEC-{uuid.uuid4().hex[:10].upper()}",
                provider_plan_id="P-SECURITY-INTRO",
                provider_status="ACTIVE",
                currency="USD",
                intro_price=Decimal("19.00"),
                regular_price=Decimal("29.00"),
                first_payment_at=paid_at,
                next_billing_at=paid_at + timedelta(days=30),
            )
        )
        db.add(
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="SKETCH",
                artifact_version="v1",
                unlock_at=paid_at + timedelta(hours=12),
                generation_status="COMPLETED" if sketch_completed else "NOT_STARTED",
                storage_key=VICTIM_STORAGE_KEY if sketch_completed else None,
            )
        )
        db.add(
            SoulmateArtifact(
                session_id=sess.id,
                email_normalized=email,
                artifact_type="REPORT",
                artifact_version="v1",
                unlock_at=paid_at + timedelta(hours=24),
                generation_status="COMPLETED" if report_completed else "NOT_STARTED",
                content_json=MOCK_REPORT_JSON if report_completed else None,
            )
        )
        await db.commit()
    return sess


@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def victim(db):
    """Paid 25h ago: sketch unlocked+COMPLETED, report unlocked+COMPLETED."""
    return await seed_session(db, paid=True, sketch_completed=True, report_completed=True)


@pytest.fixture
async def fresh_victim(db):
    """Paid 1h ago: both artifacts still LOCKED (TIME-01 +12h/+24h)."""
    return await seed_session(db, paid=True, recently_paid=True)


@pytest.fixture
async def attacker(db):
    """Unpaid session: no subscription, no artifacts, no entitlement."""
    return await seed_session(db, paid=False)


def auth_client(token: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.cookies.set(settings.session_cookie_name, token)
    return client


def assert_no_victim_leak(response, victim: SoulmateSession) -> None:
    """Denial bodies must carry only generic guidance: no victim identity, no
    victim storage key, no report content markers."""
    body = response.text
    assert victim.email not in body, "victim email leaked in denial body"
    assert VICTIM_STORAGE_KEY not in body, "victim storage key leaked in denial body"
    assert MOCK_REPORT_JSON["title"] not in body, "victim report content leaked"


def scoped_targets(victim: SoulmateSession):
    """Every endpoint that scopes by session ID, with schema-valid bodies."""
    return [
        ("GET", f"{API}/sessions/{victim.public_id}", None),
        ("PUT", f"{API}/sessions/{victim.public_id}/answers/q02", {"value": "option_a"}),
        ("PUT", f"{API}/sessions/{victim.public_id}/interstitials/spiritual_person", {"value": True}),
        ("GET", f"{API}/sessions/{victim.public_id}/flow/state", None),
        ("POST", f"{API}/sessions/{victim.public_id}/transitions/transition_1/continue", None),
        ("POST", f"{API}/sessions/{victim.public_id}/step/back", None),
        ("GET", f"{API}/sessions/{victim.public_id}/profile", None),
        ("POST", f"{API}/sessions/{victim.public_id}/email", {"email": "attacker-owner@example.com"}),
        ("GET", f"{API}/sessions/{victim.public_id}/email-summary", None),
        ("GET", f"{API}/result?session_id={victim.public_id}", None),
        ("GET", f"{API}/subscription/status?session_id={victim.public_id}", None),
        ("GET", f"{API}/artifacts/sketch?session_id={victim.public_id}", None),
        ("GET", f"{API}/artifacts/report?session_id={victim.public_id}", None),
        ("POST", f"{API}/artifacts/sketch/generate?session_id={victim.public_id}", None),
        ("POST", f"{API}/artifacts/report/generate?session_id={victim.public_id}", None),
        ("GET", f"{API}/guard/check?target_route=/soulmate/result&session_id={victim.public_id}", None),
    ]


# ==============================================================================
# Case 1 — access another session by ID (DEV-SPEC §20 IDOR guard)
# ==============================================================================


@pytest.mark.asyncio
async def test_cross_session_access_denied_on_every_scoped_endpoint(victim, attacker):
    """Cases 1+2: the attacker's own valid credentials must never reach another
    session's data on any scoped endpoint — the ownership guard fires before any
    target lookup."""
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        for method, path, body in scoped_targets(victim):
            response = await client.request(method, path, json=body)
            assert response.status_code == 403, (
                f"{method} {path}: expected 403, got {response.status_code} {response.text}"
            )
            assert response.json()["error_code"] == "FORBIDDEN_OWNERSHIP"
            assert_no_victim_leak(response, victim)


@pytest.mark.asyncio
async def test_cross_session_write_attempts_change_nothing(victim, attacker):
    """Case 1: even ignoring the status code, a cross-session PUT must not mutate
    the victim's answers or identity."""
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        await client.put(
            f"{API}/sessions/{victim.public_id}/answers/q02", json={"value": "option_a"}
        )
        await client.post(
            f"{API}/sessions/{victim.public_id}/email", json={"email": "hijack@example.com"}
        )

    async with AsyncSessionLocal() as db:
        fresh = await db.get(SoulmateSession, victim.id)
        assert fresh.email == victim.email, "victim email mutated via IDOR attempt"
        answers = (
            await db.execute(
                select(SoulmateAnswer).where(SoulmateAnswer.session_id == victim.id)
            )
        ).scalars().all()
        assert answers == [], "victim answer row created via IDOR attempt"


@pytest.mark.asyncio
async def test_confirm_endpoint_rejects_victim_session_binding(
    victim, attacker, monkeypatch
):
    """Case 1: confirm with the victim's session_id is an ownership denial, and the
    victim's entitlement row is untouched. The provider client is mocked; the
    mocked subscription is bound (custom_id) to the VICTIM."""
    sub_id = f"I-HIJACK-{uuid.uuid4().hex[:8].upper()}"
    mock_client = MockPayPalClient(
        {sub_id: {"id": sub_id, "status": "APPROVED", "plan_id": "P-SECURITY-INTRO",
                  "custom_id": victim.public_id}}
    )
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", "P-SECURITY-INTRO")
    monkeypatch.setattr(subscription_service, "PayPalClient", lambda: mock_client)

    async with auth_client(generate_session_token(attacker.public_id)) as client:
        response = await client.post(
            f"{API}/subscription/paypal/confirm",
            json={"session_id": victim.public_id, "paypal_subscription_id": sub_id},
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN_OWNERSHIP"
    assert_no_victim_leak(response, victim)

    async with AsyncSessionLocal() as db:
        fresh = await db.get(SoulmateSession, victim.id)
        assert fresh.subscription_success_at == victim.subscription_success_at


# ==============================================================================
# Acceptance — no existence oracle (denial must not disclose the target exists)
# ==============================================================================


@pytest.mark.asyncio
async def test_nonexistent_target_indistinguishable_from_existing_target(victim, attacker):
    """Acceptance: the ownership guard answers 403 BEFORE the existence lookup, so a
    fabricated session ID gets the same denial as a real victim session — the
    attacker cannot probe which session IDs exist."""
    fake_id = f"ses_{uuid.uuid4().hex}"
    probes = [
        ("GET", f"{API}/sessions/{{target}}", None),
        ("GET", f"{API}/result?session_id={{target}}", None),
        ("GET", f"{API}/artifacts/sketch?session_id={{target}}", None),
        ("GET", f"{API}/artifacts/report?session_id={{target}}", None),
        ("GET", f"{API}/guard/check?target_route=/soulmate/result&session_id={{target}}", None),
    ]
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        for method, template, body in probes:
            existing = await client.request(
                method, template.format(target=victim.public_id), json=body
            )
            fabricated = await client.request(
                method, template.format(target=fake_id), json=body
            )

            assert existing.status_code == 403, f"{method} {template}: real-target denial missing"
            assert fabricated.status_code == 403, (
                f"{method} {template}: fabricated target returned "
                f"{fabricated.status_code} — existence oracle"
            )
            assert (
                fabricated.json()["error_code"]
                == existing.json()["error_code"]
                == "FORBIDDEN_OWNERSHIP"
            )
            assert_no_victim_leak(fabricated, victim)


@pytest.mark.asyncio
async def test_unauthenticated_requests_denied_without_target_data(victim):
    """No credentials at all: every scoped surface answers the generic ownership
    error and never echoes victim data."""
    probes = [
        ("GET", f"{API}/sessions/current", None),
        ("GET", f"{API}/sessions/{victim.public_id}", None),
        ("GET", f"{API}/result", None),
        ("GET", f"{API}/artifacts/sketch", None),
        ("GET", f"{API}/artifacts/report", None),
        ("POST", f"{API}/artifacts/sketch/generate", None),
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path, body in probes:
            response = await client.request(method, path, json=body)
            assert response.status_code == 403, f"{method} {path}: {response.status_code}"
            assert response.json()["error_code"] == "FORBIDDEN_OWNERSHIP"
            assert_no_victim_leak(response, victim)


@pytest.mark.asyncio
async def test_no_artifact_id_read_surface(victim):
    """DEV-SPEC §20: guessing artifact IDs must not be a read path at all — the API
    exposes only session-scoped /artifacts/sketch and /artifacts/report routes."""
    fake_artifact_id = uuid.uuid4()
    async with auth_client(generate_session_token(victim.public_id)) as client:
        for path in (
            f"{API}/artifacts/{fake_artifact_id}",
            f"{API}/artifacts/{fake_artifact_id}/image",
            f"{API}/artifacts/sketch/{fake_artifact_id}",
        ):
            response = await client.get(path)
            assert response.status_code == 404, f"{path}: {response.status_code}"
            assert VICTIM_STORAGE_KEY not in response.text


# ==============================================================================
# Case 2 — access another sketch/report (session-scoped reads, RECOVERY-01)
# ==============================================================================


@pytest.mark.asyncio
async def test_completed_sketch_and_report_reads_are_session_scoped(victim, attacker):
    """Case 2: token-only artifact reads resolve the CALLER's own session. The
    attacker (unpaid, nothing generated) sees an empty own state — never the
    victim's image URL, storage key, or report content. The victim's own read
    serves their data, proving the denial is the ownership guard, not breakage."""
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        sketch = await client.get(f"{API}/artifacts/sketch")
        report = await client.get(f"{API}/artifacts/report")

    assert sketch.status_code == 200
    assert sketch.json()["session_id"] == attacker.public_id
    assert sketch.json()["image_url"] is None
    assert sketch.json()["storage_key"] is None
    assert VICTIM_STORAGE_KEY not in sketch.text

    assert report.status_code == 200
    assert report.json()["session_id"] == attacker.public_id
    assert report.json()["content"] is None
    assert MOCK_REPORT_JSON["title"] not in report.text

    async with auth_client(generate_session_token(victim.public_id)) as client:
        victim_sketch = await client.get(f"{API}/artifacts/sketch")
        victim_report = await client.get(f"{API}/artifacts/report")

    assert victim_sketch.status_code == 200
    assert victim_sketch.json()["session_id"] == victim.public_id
    assert victim_sketch.json()["storage_key"] == VICTIM_STORAGE_KEY

    assert victim_report.status_code == 200
    assert victim_report.json()["content"] is not None
    assert victim_report.json()["content"]["title"] == MOCK_REPORT_JSON["title"]


# ==============================================================================
# Case 3 — spoof paid/unlocked fields from browser (PAY-AUTH-01, §20 immutability)
# ==============================================================================


@pytest.mark.asyncio
async def test_forged_entitlement_fields_are_rejected_not_applied(victim, attacker):
    """Case 3: §20 client-immutable fields (subscription_success_at, unlock_at,
    provider_status, generation_status, storage_key) have no write path. The
    strict request schemas reject them outright, and nothing in the DB changes."""
    forged = {
        "subscription_success_at": "2020-01-01T00:00:00Z",
        "unlock_at": "2020-01-01T00:00:00Z",
        "provider_status": "ACTIVE",
        "generation_status": "COMPLETED",
        "storage_key": "forged/forged.png",
    }
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        email_attempt = await client.post(
            f"{API}/sessions/{attacker.public_id}/email",
            json={"email": "attacker-owner@example.com", **forged},
        )
        answer_attempt = await client.put(
            f"{API}/sessions/{attacker.public_id}/answers/q02",
            json={"value": "option_a", **forged},
        )

    assert email_attempt.status_code == 422, "forged fields must not be accepted"
    assert answer_attempt.status_code == 422, "forged fields must not be accepted"

    async with AsyncSessionLocal() as db:
        fresh_attacker = await db.get(SoulmateSession, attacker.id)
        assert fresh_attacker.subscription_success_at is None
        victim_sketch = (
            await db.execute(
                select(SoulmateArtifact).where(
                    SoulmateArtifact.session_id == victim.id,
                    SoulmateArtifact.artifact_type == "SKETCH",
                )
            )
        ).scalar_one()
        assert victim_sketch.storage_key == VICTIM_STORAGE_KEY
        assert victim_sketch.generation_status == "COMPLETED"

    # The unpaid attacker still cannot read the Result aggregate.
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        assert (await client.get(f"{API}/result")).status_code == 403


@pytest.mark.asyncio
async def test_session_tokens_cannot_be_tampered_or_minted(victim):
    """Case 3: the soulmate_sid token is the only browser-held authority. A flipped
    signature, a foreign-key signature, or an expired timestamp all fail closed —
    an attacker without SESSION_SECRET_KEY cannot mint a victim token."""
    real_token = generate_session_token(victim.public_id)
    public_id, timestamp, signature = real_token.split(".")

    flipped = f"{public_id}.{timestamp}.{'0' * len(signature)}"
    foreign_key_sig = hmac.new(
        b"attacker-controlled-key", f"{public_id}:{timestamp}".encode(), hashlib.sha256
    ).hexdigest()
    expired = generate_session_token(victim.public_id, timestamp=0)

    forged_tokens = {
        "flipped-signature": flipped,
        "foreign-key": f"{public_id}.{timestamp}.{foreign_key_sig}",
        "expired": expired,
    }
    for label, token in forged_tokens.items():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set(settings.session_cookie_name, token)
            response = await client.get(f"{API}/sessions/current")
        assert response.status_code == 403, f"{label}: {response.status_code}"
        assert response.json()["error_code"] == "FORBIDDEN_OWNERSHIP"


@pytest.mark.asyncio
async def test_confirm_cannot_grant_entitlement_without_payment(attacker, monkeypatch):
    """Case 3 (PAY-AUTH-01): even a provider-APPROVED subscription bound to the
    caller is not entitlement — and a fabricated subscription grants nothing."""
    own_sub_id = f"I-OWN-{uuid.uuid4().hex[:8].upper()}"
    mock_client = MockPayPalClient(
        {own_sub_id: {"id": own_sub_id, "status": "APPROVED", "plan_id": "P-SECURITY-INTRO",
                      "custom_id": attacker.public_id}}
    )
    monkeypatch.setattr(settings, "paypal_soulmate_intro_plan_id", "P-SECURITY-INTRO")
    monkeypatch.setattr(subscription_service, "PayPalClient", lambda: mock_client)

    async with auth_client(generate_session_token(attacker.public_id)) as client:
        fabricated = await client.post(
            f"{API}/subscription/paypal/confirm",
            json={"paypal_subscription_id": f"I-FABRICATED-{uuid.uuid4().hex[:8].upper()}"},
        )
        approved = await client.post(
            f"{API}/subscription/paypal/confirm",
            json={"paypal_subscription_id": own_sub_id},
        )
        # After a successful confirmation, the Result aggregate must still deny.
        result_after_confirm = await client.get(f"{API}/result")

    assert fabricated.status_code == 404, "fabricated subscription must not confirm"

    assert approved.status_code == 200
    assert approved.json()["is_paid"] is False, "client approval must not grant entitlement"
    assert approved.json()["status"] == "PROCESSING"
    assert result_after_confirm.status_code == 403, "unpaid session must not read Result"

    async with AsyncSessionLocal() as db:
        fresh = await db.get(SoulmateSession, attacker.id)
        assert fresh.subscription_success_at is None


# ==============================================================================
# Case 4 — call generate before unlock (TIME-01, §23.1 Artifacts)
# ==============================================================================


@pytest.mark.asyncio
async def test_generate_before_unlock_denied_and_creates_no_job(fresh_victim):
    """Case 4: generation is gated on the artifact's persisted unlock_at with the
    server clock. Both pipelines deny with LOCKED_ASSET and enqueue nothing; stray
    client-supplied 'unlock' query parameters are ignored."""
    async with auth_client(generate_session_token(fresh_victim.public_id)) as client:
        sketch = await client.post(
            f"{API}/artifacts/sketch/generate?unlock_at=1970-01-01T00:00:00Z"
        )
        report = await client.post(f"{API}/artifacts/report/generate")

    assert sketch.status_code == 423
    assert sketch.json()["error_code"] == "LOCKED_ASSET"
    assert report.status_code == 423
    assert report.json()["error_code"] == "LOCKED_ASSET"

    async with AsyncSessionLocal() as db:
        artifacts = (
            await db.execute(
                select(SoulmateArtifact).where(SoulmateArtifact.session_id == fresh_victim.id)
            )
        ).scalars().all()
        assert {a.artifact_type for a in artifacts} == {"SKETCH", "REPORT"}
        jobs = (
            await db.execute(
                select(AIGenerationJob).where(
                    AIGenerationJob.artifact_id.in_([a.id for a in artifacts])
                )
            )
        ).scalars().all()
        assert jobs == [], "locked session must not enqueue generation jobs"


@pytest.mark.asyncio
async def test_generate_without_payment_denied_and_creates_no_job(attacker):
    """Case 4 (PAY-AUTH-01): an unentitled session cannot trigger either pipeline
    and no job can ever reference its (nonexistent) artifacts."""
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        sketch = await client.post(f"{API}/artifacts/sketch/generate")
        report = await client.post(f"{API}/artifacts/report/generate")

    assert sketch.status_code == 403
    assert sketch.json()["error_code"] == "FORBIDDEN_OWNERSHIP"
    assert report.status_code == 403

    async with AsyncSessionLocal() as db:
        attacker_artifacts = (
            await db.execute(
                select(SoulmateArtifact).where(SoulmateArtifact.session_id == attacker.id)
            )
        ).scalars().all()
        assert attacker_artifacts == [], "unpaid session must not gain artifact rows"
        jobs = (
            await db.execute(
                select(AIGenerationJob).where(
                    AIGenerationJob.artifact_id.in_(
                        select(SoulmateArtifact.id).where(
                            SoulmateArtifact.session_id == attacker.id
                        )
                    )
                )
            )
        ).scalars().all()
        assert jobs == [], "unpaid session must not enqueue generation jobs"


# ==============================================================================
# Case 5 — invalid webhook/signature (§9.6, §23.1 Payment)
# ==============================================================================


class RejectingVerifier(PayPalWebhookVerifier):
    """Mimics PayPal rejecting the transmission signature (tampered body, wrong
    webhook id, or replayed capture)."""

    def __init__(self):
        super().__init__()

    async def verify(self, *args, **kwargs) -> bool:
        return False


def forged_sale_payload() -> dict:
    """A structurally valid PAYMENT.SALE.COMPLETED claiming a first payment for an
    attacker-chosen, unbound subscription — exactly what a forged webhook would
    carry. Only a valid PayPal transmission signature could make it count."""
    sub_id = f"I-FORGED-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"WH-FORGED-{uuid.uuid4().hex[:12]}",
        "event_version": "1.0",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "create_time": now,
        "resource_type": "sale",
        "resource": {
            "id": f"SALE-FORGED-{uuid.uuid4().hex[:8].upper()}",
            "billing_agreement_id": sub_id,
            "amount": {"total": "19.00", "currency": "USD"},
            "create_time": now,
        },
    }


async def assert_forged_webhook_has_zero_business_effect() -> None:
    async with AsyncSessionLocal() as db:
        events = (
            await db.execute(
                select(PayPalWebhookEvent).where(
                    PayPalWebhookEvent.paypal_event_id.like("WH-FORGED-%")
                )
            )
        ).scalars().all()
        assert all(e.processed_at is None for e in events), "forged event was processed"
        payments = (
            await db.execute(
                select(SubscriptionPayment).where(
                    SubscriptionPayment.provider_payment_id.like("SALE-FORGED-%")
                )
            )
        ).scalars().all()
        assert payments == [], "forged webhook created ledger rows"
        subs = (
            await db.execute(
                select(Subscription).where(
                    Subscription.provider_subscription_id.like("I-FORGED-%")
                )
            )
        ).scalars().all()
        assert subs == [], "forged webhook created subscription rows"


@pytest.mark.asyncio
async def test_webhook_without_transmission_headers_rejected(attacker):
    """Case 5a: missing PayPal transmission headers fail closed before any
    processing — zero business effect, no entitlement for the forged sale."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/webhooks/paypal", json=forged_sale_payload())

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["message"]

    async with AsyncSessionLocal() as db:
        fresh = await db.get(SoulmateSession, attacker.id)
        assert fresh.subscription_success_at is None, "forged webhook granted entitlement"
    await assert_forged_webhook_has_zero_business_effect()


@pytest.mark.asyncio
async def test_webhook_with_invalid_signature_rejected(attacker):
    """Case 5b: a present-but-invalid signature (tampered body / wrong webhook id)
    is rejected — zero business effect, event never processed."""
    app.dependency_overrides[get_webhook_verifier] = lambda: RejectingVerifier()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/webhooks/paypal", json=forged_sale_payload())
    finally:
        app.dependency_overrides.pop(get_webhook_verifier, None)

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"

    async with AsyncSessionLocal() as db:
        fresh = await db.get(SoulmateSession, attacker.id)
        assert fresh.subscription_success_at is None, "forged webhook granted entitlement"
    await assert_forged_webhook_has_zero_business_effect()


# ==============================================================================
# Case 6 — manipulate route only without entitlement (DEV-SPEC §3)
# ==============================================================================


@pytest.mark.asyncio
async def test_route_guard_denies_paid_routes_without_entitlement(victim, attacker):
    """Case 6: deep-linking to paid routes with an unpaid session yields a
    server-side redirect, never access. (Even a bypassed guard would not leak data:
    the data APIs deny independently — Cases 1–4 prove that.)"""
    async with auth_client(generate_session_token(attacker.public_id)) as client:
        for route in ("/soulmate/result", "/soulmate/sketch", "/soulmate/report"):
            response = await client.get(
                f"{API}/guard/check", params={"target_route": route}
            )
            assert response.status_code == 200
            verdict = response.json()
            assert verdict["allowed"] is False, f"{route}: unpaid session allowed"
            assert verdict["redirect_to"], f"{route}: no redirect for unpaid session"
            assert_no_victim_leak(response, victim)

    # Control: the entitled victim is allowed through on the same verdict API.
    async with auth_client(generate_session_token(victim.public_id)) as client:
        response = await client.get(
            f"{API}/guard/check", params={"target_route": "/soulmate/result"}
        )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
