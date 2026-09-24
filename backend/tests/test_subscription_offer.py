"""
Automated unit and integration tests for Subscription Offer API (SP-303, DEV-SPEC §9.1–9.2, §15.6, §21–22, Decisions: PAY-01, PAY-02).
"""

from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.db.session import AsyncSessionLocal, SessionLocal
from app.main import app
from app.soulmate.domain.offer import (
    ResubscriptionPolicy,
    build_subscription_offer,
    evaluate_resubscription_eligibility,
    format_offer_price,
    get_currency_symbol,
)
from app.soulmate.domain.session_state import SessionStatus
from app.soulmate.security import generate_session_token
from app.soulmate.services.offer_service import OfferService


@pytest.fixture
def db_session():
    """Provides a synchronous transactional DB session for asserting DB state."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def async_db():
    """Provides an asynchronous DB session for service layer calls."""
    async with AsyncSessionLocal() as session:
        yield session


# ==============================================================================
# 1. Pure Domain Logic Tests
# ==============================================================================


def test_currency_symbol_mapping():
    assert get_currency_symbol("USD") == "$"
    assert get_currency_symbol("usd") == "$"
    assert get_currency_symbol("EUR") == "€"
    assert get_currency_symbol("GBP") == "£"
    assert get_currency_symbol("cad") == "CA$"
    assert get_currency_symbol("JPY") == "JPY "


def test_format_offer_price_pay_01():
    """PAY-01: format Decimal price or return placeholder when None."""
    assert format_offer_price(Decimal("19.00"), "{INTRO_PRICE}") == "19.00"
    assert format_offer_price(Decimal("14.99"), "{INTRO_PRICE}") == "14.99"
    assert format_offer_price(None, "{INTRO_PRICE}") == "{INTRO_PRICE}"
    assert format_offer_price(None, "{REGULAR_PRICE}") == "{REGULAR_PRICE}"


def test_evaluate_resubscription_eligibility_pay_02():
    """PAY-02: evaluate eligibility for new vs returning subscribers under configurable policies."""
    # First time user
    res_new = evaluate_resubscription_eligibility(has_prior_subscription=False, policy="blocked")
    assert res_new["eligible_for_intro"] is True
    assert res_new["plan_class"] == "intro"
    assert res_new["is_blocked"] is False
    assert res_new["reason"] is None

    # Returning user under 'blocked' policy (default PAY-02)
    res_blocked = evaluate_resubscription_eligibility(has_prior_subscription=True, policy="blocked")
    assert res_blocked["eligible_for_intro"] is False
    assert res_blocked["plan_class"] == "blocked"
    assert res_blocked["is_blocked"] is True
    assert "blocked pending product resolution" in res_blocked["reason"]

    # Returning user under 'single_intro' policy
    res_single = evaluate_resubscription_eligibility(has_prior_subscription=True, policy="single_intro")
    assert res_single["eligible_for_intro"] is False
    assert res_single["plan_class"] == "standard"
    assert res_single["is_blocked"] is False
    assert "standard pricing applied" in res_single["reason"]

    # Returning user under 'allow_intro' policy
    res_allow = evaluate_resubscription_eligibility(has_prior_subscription=True, policy="allow_intro")
    assert res_allow["eligible_for_intro"] is True
    assert res_allow["plan_class"] == "intro"
    assert res_allow["is_blocked"] is False
    assert "Promotional intro price applied" in res_allow["reason"]


def test_build_subscription_offer_structure_and_safe_client_metadata():
    """Verify offer dictionary matches contract and never leaks sensitive credentials."""
    offer = build_subscription_offer(
        currency="USD",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        intro_plan_id="P-INTRO-123",
        standard_plan_id="P-STANDARD-456",
        paypal_client_id="client_pub_abc",
        paypal_env="sandbox",
        has_prior_subscription=False,
        policy="blocked",
    )

    assert offer["currency"] == "USD"
    assert offer["intro_price"] == "19.00"
    assert offer["regular_price"] == "29.00"
    assert offer["interval"] == "MONTH"
    assert offer["paypal_plan_id"] == "P-INTRO-123"

    # Disclosures per DEV-SPEC §9.1 & §21
    assert offer["disclosure"]["today_text"] == "Today: $19.00"
    assert offer["disclosure"]["renewal_text"] == "Then $29.00 / month"
    assert "Automatically renews" in offer["disclosure"]["terms_text"]
    assert offer["disclosure"]["auto_renew"] is True

    # Safe PayPal client configuration
    assert offer["paypal"]["client_id"] == "client_pub_abc"
    assert offer["paypal"]["env"] == "sandbox"
    assert offer["paypal"]["plan_id"] == "P-INTRO-123"
    # Invariant: No secrets or webhooks in client metadata
    assert "client_secret" not in offer["paypal"]
    assert "webhook_id" not in offer["paypal"]


def test_build_subscription_offer_unconfigured_placeholders():
    """PAY-01: When prices are unconfigured, placeholder strings are safely used."""
    offer = build_subscription_offer(
        currency="USD",
        intro_price=None,
        regular_price=None,
    )
    assert offer["intro_price"] == "{INTRO_PRICE}"
    assert offer["regular_price"] == "{REGULAR_PRICE}"
    assert offer["disclosure"]["today_text"] == "Today: ${INTRO_PRICE}"
    assert offer["disclosure"]["renewal_text"] == "Then ${REGULAR_PRICE} / month"


# ==============================================================================
# 2. Service Layer Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_offer_service_without_session(async_db):
    """Anonymous visitors receive the standard first-time offer."""
    offer = await OfferService.get_subscription_offer(db=async_db, session=None)
    assert offer.currency == "USD"
    assert offer.eligibility.eligible_for_intro is True
    assert offer.eligibility.is_blocked is False


@pytest.mark.asyncio
async def test_offer_service_with_new_session(async_db, db_session: Session):
    """New session with no subscriptions receives promotional intro offer."""
    sess = SoulmateSession(
        public_id=f"test_sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.QUIZ_IN_PROGRESS.value,
        current_step="q01",
    )
    db_session.add(sess)
    db_session.commit()

    offer = await OfferService.get_subscription_offer(db=async_db, session=sess)
    assert offer.eligibility.eligible_for_intro is True
    assert offer.eligibility.is_blocked is False


@pytest.mark.asyncio
async def test_offer_service_detects_prior_subscription_and_blocks_by_default(async_db, db_session: Session):
    """PAY-02 Acceptance: Returning subscribers are blocked by default rather than guessing."""
    sess = SoulmateSession(
        public_id=f"test_sub_sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.QUIZ_IN_PROGRESS.value,
        current_step="q01",
    )
    db_session.add(sess)
    db_session.commit()

    # Create prior subscription
    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-TEST-{uuid.uuid4().hex[:8]}",
        provider_plan_id="P-TEST-INTRO",
        provider_status="ACTIVE",
        currency="USD",
        regular_price=Decimal("29.00"),
    )
    db_session.add(sub)
    db_session.commit()

    # With default policy='blocked'
    offer = await OfferService.get_subscription_offer(db=async_db, session=sess)
    assert offer.eligibility.eligible_for_intro is False
    assert offer.eligibility.plan_class == "blocked"
    assert offer.eligibility.is_blocked is True
    assert "blocked pending product resolution" in (offer.eligibility.reason or "")


@pytest.mark.asyncio
async def test_offer_service_configurable_via_settings_pay_01_pay_02(async_db, db_session: Session):
    """
    Acceptance:
    - PAY-01 can be configured without source changes.
    - PAY-02 remains configurable rather than guessed.
    """
    sess = SoulmateSession(
        public_id=f"test_cfg_sess_{uuid.uuid4().hex[:12]}",
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.QUIZ_IN_PROGRESS.value,
        current_step="q01",
    )
    db_session.add(sess)
    db_session.commit()

    sub = Subscription(
        session_id=sess.id,
        provider="paypal",
        provider_subscription_id=f"I-TEST-CFG-{uuid.uuid4().hex[:8]}",
        provider_plan_id="P-TEST-INTRO",
        provider_status="EXPIRED",
        currency="USD",
        regular_price=Decimal("29.00"),
    )
    db_session.add(sub)
    db_session.commit()

    # Custom settings injecting specific prices (PAY-01) and 'single_intro' policy (PAY-02)
    custom_settings = Settings(
        soulmate_intro_price=Decimal("12.50"),
        soulmate_regular_price=Decimal("35.00"),
        paypal_soulmate_intro_plan_id="P-INTRO-999",
        paypal_soulmate_standard_plan_id="P-STD-888",
        soulmate_resubscription_policy="single_intro",
    )

    offer = await OfferService.get_subscription_offer(
        db=async_db,
        session=sess,
        custom_settings=custom_settings,
    )

    # PAY-01 verification: dynamic configured prices applied
    assert offer.intro_price == "12.50"
    assert offer.regular_price == "35.00"
    assert offer.disclosure.today_text == "Today: $12.50"
    assert offer.disclosure.renewal_text == "Then $35.00 / month"

    # PAY-02 verification: routed to standard plan instead of blocked or guessed intro
    assert offer.eligibility.eligible_for_intro is False
    assert offer.eligibility.plan_class == "standard"
    assert offer.eligibility.is_blocked is False
    assert offer.paypal_plan_id == "P-STD-888"


# ==============================================================================
# 3. HTTP API Endpoint Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_api_get_subscription_offer_anonymous():
    """Anonymous call to GET /api/soulmate/subscription/offer returns 200 with offer schema."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/soulmate/subscription/offer")
        assert resp.status_code == 200
        data = resp.json()
        assert "currency" in data
        assert "intro_price" in data
        assert "regular_price" in data
        assert "disclosure" in data
        assert "eligibility" in data
        assert "paypal" in data
        assert data["disclosure"]["interval"] == "MONTH"
        assert data["eligibility"]["eligible_for_intro"] is True


@pytest.mark.asyncio
async def test_api_get_checkout_config_alias():
    """Verify /api/soulmate/checkout/config alias matches DEV-SPEC §15.6 router table."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/soulmate/checkout/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval"] == "MONTH"
        assert "disclosure" in data
        assert "today_text" in data["disclosure"]


@pytest.mark.asyncio
async def test_api_get_subscription_offer_with_cookie(db_session: Session):
    """Request with valid session cookie evaluates the active session."""
    public_id = f"test_api_{uuid.uuid4().hex[:12]}"
    sess = SoulmateSession(
        public_id=public_id,
        quiz_version="soulmate-quiz-v1",
        status=SessionStatus.QUIZ_IN_PROGRESS.value,
        current_step="q01",
    )
    db_session.add(sess)
    db_session.commit()

    token = generate_session_token(public_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("soulmate_sid", token)
        resp = await client.get("/api/soulmate/subscription/offer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["eligibility"]["eligible_for_intro"] is True
        assert data["eligibility"]["is_blocked"] is False


@pytest.mark.asyncio
async def test_api_get_subscription_offer_with_session_id_query_and_idor_guard(db_session: Session):
    """
    Verify ownership check on session_id query param:
    - Authorized caller succeeds.
    - Foreign token caller is rejected with 403 (IDOR guard).
    """
    public_id_a = f"test_api_a_{uuid.uuid4().hex[:12]}"
    public_id_b = f"test_api_b_{uuid.uuid4().hex[:12]}"
    sess_a = SoulmateSession(public_id=public_id_a, quiz_version="soulmate-quiz-v1", status=SessionStatus.QUIZ_IN_PROGRESS.value, current_step="q01")
    sess_b = SoulmateSession(public_id=public_id_b, quiz_version="soulmate-quiz-v1", status=SessionStatus.QUIZ_IN_PROGRESS.value, current_step="q01")
    db_session.add_all([sess_a, sess_b])
    db_session.commit()

    token_a = generate_session_token(public_id_a)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Matching token for session_a -> 200 OK
        client.cookies.set("soulmate_sid", token_a)
        resp = await client.get(f"/api/soulmate/subscription/offer?session_id={public_id_a}")
        assert resp.status_code == 200

        # 2. Token A attempting to inspect session_b -> 403 Forbidden
        resp_idor = await client.get(f"/api/soulmate/subscription/offer?session_id={public_id_b}")
        assert resp_idor.status_code == 403
        assert resp_idor.json()["error_code"] == "FORBIDDEN_OWNERSHIP"
