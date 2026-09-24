"""
Automated tests for PayPal Product and Plan Provisioning (SP-401, DEV-SPEC §9.1–9.2, §22, §25, Decisions: PAY-01, PAY-02).
"""

import asyncio
from decimal import Decimal
import json
from typing import Any, Dict
import pytest
import httpx

from app.soulmate.domain.paypal_models import (
    PayPalBillingCycle,
    PayPalFixedPrice,
    PayPalFrequency,
    PayPalPaymentPreferences,
    PayPalPlanPayload,
    PayPalPricingScheme,
    PayPalProductPayload,
)
from app.soulmate.services.paypal_client import (
    PAYPAL_BASE_URLS,
    PayPalAPIError,
    PayPalAuthError,
    PayPalClient,
)
from app.soulmate.services.paypal_provisioning import (
    INTRO_PLAN_NAME_DEFAULT,
    PRODUCT_NAME_DEFAULT,
    STANDARD_PLAN_NAME_DEFAULT,
    PayPalProvisioningService,
)
from scripts.provision_paypal import main_async, parse_args


@pytest.fixture
def mock_paypal_credentials() -> Dict[str, str]:
    """Provides non-sensitive mock PayPal credentials for isolated test suites (M-1)."""
    return {
        "client_id": "mock_paypal_client_id_fixture",
        "client_secret": "mock_paypal_client_secret_fixture",
    }


# ==============================================================================
# 1. Domain Payload Builders & Price Validation (DEV-SPEC §9.1.1 & §9.2)
# ==============================================================================


def test_build_intro_plan_payload_exact_dev_spec_structure():
    """Verify intro plan payload matches DEV-SPEC §9.1.1 exactly."""
    payload = PayPalProvisioningService.build_intro_plan_payload(
        product_id="PROD-TEST-123",
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        currency="USD",
    )

    assert payload["product_id"] == "PROD-TEST-123"
    assert payload["name"] == INTRO_PLAN_NAME_DEFAULT
    assert payload["status"] == "ACTIVE"

    cycles = payload["billing_cycles"]
    assert len(cycles) == 2

    # Cycle 1: Promotional trial
    c1 = cycles[0]
    assert c1["frequency"]["interval_unit"] == "MONTH"
    assert c1["frequency"]["interval_count"] == 1
    assert c1["tenure_type"] == "TRIAL"
    assert c1["sequence"] == 1
    assert c1["total_cycles"] == 1
    assert c1["pricing_scheme"]["fixed_price"]["value"] == "19.00"
    assert c1["pricing_scheme"]["fixed_price"]["currency_code"] == "USD"

    # Cycle 2: Regular recurring
    c2 = cycles[1]
    assert c2["frequency"]["interval_unit"] == "MONTH"
    assert c2["frequency"]["interval_count"] == 1
    assert c2["tenure_type"] == "REGULAR"
    assert c2["sequence"] == 2
    assert c2["total_cycles"] == 0  # Infinite recurrence
    assert c2["pricing_scheme"]["fixed_price"]["value"] == "29.00"
    assert c2["pricing_scheme"]["fixed_price"]["currency_code"] == "USD"

    # Payment preferences (DEV-SPEC §9.1.1 lines 1126-1129)
    prefs = payload["payment_preferences"]
    assert prefs["auto_bill_outstanding"] is True
    assert prefs["payment_failure_threshold"] == 1
    assert "setup_fee_failure_action" not in prefs  # M-2: No setup fee in Soulmate V1


def test_build_standard_plan_payload_exact_dev_spec_structure():
    """Verify standard plan payload matches DEV-SPEC §9.2 exactly."""
    payload = PayPalProvisioningService.build_standard_plan_payload(
        product_id="PROD-TEST-123",
        regular_price=Decimal("29.00"),
        currency="USD",
    )

    assert payload["product_id"] == "PROD-TEST-123"
    assert payload["name"] == STANDARD_PLAN_NAME_DEFAULT
    assert payload["status"] == "ACTIVE"

    cycles = payload["billing_cycles"]
    assert len(cycles) == 1

    c1 = cycles[0]
    assert c1["frequency"]["interval_unit"] == "MONTH"
    assert c1["frequency"]["interval_count"] == 1
    assert c1["tenure_type"] == "REGULAR"
    assert c1["sequence"] == 1
    assert c1["total_cycles"] == 0
    assert c1["pricing_scheme"]["fixed_price"]["value"] == "29.00"
    assert c1["pricing_scheme"]["fixed_price"]["currency_code"] == "USD"

    # Payment preferences (DEV-SPEC §9.2)
    prefs = payload["payment_preferences"]
    assert prefs["auto_bill_outstanding"] is True
    assert prefs["payment_failure_threshold"] == 1
    assert "setup_fee_failure_action" not in prefs  # M-2: No setup fee in Soulmate V1


def test_payload_builder_price_validation():
    """Prices must come from approved inputs and be strictly positive."""
    with pytest.raises(ValueError, match="Intro price must be positive"):
        PayPalProvisioningService.build_intro_plan_payload(
            product_id="PROD-1",
            intro_price=Decimal("0.00"),
            regular_price=Decimal("29.00"),
        )

    with pytest.raises(ValueError, match="Regular price must be positive"):
        PayPalProvisioningService.build_intro_plan_payload(
            product_id="PROD-1",
            intro_price=Decimal("19.00"),
            regular_price=Decimal("-10.00"),
        )

    with pytest.raises(ValueError, match="Regular price must be positive"):
        PayPalProvisioningService.build_standard_plan_payload(
            product_id="PROD-1",
            regular_price=Decimal("0.00"),
        )


# ==============================================================================
# 2. Plan Verification Logic (Acceptance: Cadence, Cycles, Discrepancies)
# ==============================================================================


def test_verify_plan_valid_intro_plan():
    """A correctly formed intro plan passes verification with 0 discrepancies."""
    plan_data = {
        "id": "P-VALID-INTRO",
        "name": "Soulmate Monthly Intro",
        "status": "ACTIVE",
        "product_id": "PROD-123",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {"fixed_price": {"value": "19.00", "currency_code": "USD"}},
            },
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": "29.00", "currency_code": "USD"}},
            },
        ],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1},
    }

    res = PayPalProvisioningService.verify_plan(
        plan_data=plan_data,
        expected_type="intro",
        expected_intro_price=Decimal("19.00"),
        expected_regular_price=Decimal("29.00"),
        expected_currency="USD",
        expected_product_id="PROD-123",
    )

    assert res.matches is True
    assert res.discrepancies == []
    assert res.plan_type == "intro"
    assert res.intro_price == "19.00"
    assert res.regular_price == "29.00"
    assert res.interval == "MONTH"
    assert res.interval_count == 1


def test_verify_plan_valid_standard_plan():
    """A correctly formed standard plan passes verification with 0 discrepancies."""
    plan_data = {
        "id": "P-VALID-STD",
        "name": "Soulmate Monthly Standard",
        "status": "ACTIVE",
        "product_id": "PROD-123",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": "29.00", "currency_code": "USD"}},
            }
        ],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1},
    }

    res = PayPalProvisioningService.verify_plan(
        plan_data=plan_data,
        expected_type="standard",
        expected_regular_price=Decimal("29.00"),
        expected_currency="USD",
        expected_product_id="PROD-123",
    )

    assert res.matches is True
    assert res.discrepancies == []
    assert res.plan_type == "standard"
    assert res.regular_price == "29.00"


def test_verify_plan_detects_cadence_and_status_discrepancies():
    """Verify that yearly cadence, inactive status, and wrong prices are caught."""
    bad_plan = {
        "id": "P-BAD-CADENCE",
        "name": "Bad Cadence Plan",
        "status": "INACTIVE",
        "product_id": "PROD-999",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "YEAR", "interval_count": 1},  # Non-monthly!
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {"fixed_price": {"value": "99.00", "currency_code": "USD"}},
            },
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 3},  # 3 months, not 1!
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": "29.00", "currency_code": "EUR"}},  # EUR, not USD!
            },
        ],
        "payment_preferences": {"auto_bill_outstanding": False},
    }

    res = PayPalProvisioningService.verify_plan(
        plan_data=bad_plan,
        expected_type="intro",
        expected_intro_price=Decimal("19.00"),
        expected_regular_price=Decimal("29.00"),
        expected_currency="USD",
        expected_product_id="PROD-123",
    )

    assert res.matches is False
    assert any("Plan status is 'INACTIVE'" in d for d in res.discrepancies)
    assert any("Product ID mismatch" in d for d in res.discrepancies)
    assert any("Cycle 1 cadence is YEAR x 1" in d for d in res.discrepancies)
    assert any("Cycle 2 cadence is MONTH x 3" in d for d in res.discrepancies)
    assert any("Cycle 1 price is '99.00'" in d for d in res.discrepancies)
    assert any("Cycle 2 currency is 'EUR'" in d for d in res.discrepancies)
    assert any("auto_bill_outstanding must be true" in d for d in res.discrepancies)


def test_verify_disclosures_match_plan():
    """Verify disclosure parity against planned intro and regular amounts."""
    ok, errors = PayPalProvisioningService.verify_disclosures_match_plan(
        intro_price=Decimal("19.00"),
        regular_price=Decimal("29.00"),
        currency="USD",
        intro_plan_id="P-INTRO-1",
        standard_plan_id="P-STD-1",
    )
    assert ok is True
    assert errors == []


# ==============================================================================
# 3. PayPalClient HTTP Communication & Authentication
# ==============================================================================


@pytest.mark.asyncio
async def test_paypal_client_oauth_token_caching_and_basic_auth(mock_paypal_credentials):
    """PayPalClient requests and caches OAuth2 token using HTTP Basic auth."""
    calls = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/oauth2/token":
            # Verify HTTP Basic Auth header is present
            assert "Authorization" in request.headers
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(
                200,
                json={"access_token": "mock_token_xyz_123", "token_type": "Bearer", "expires_in": 3600},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PayPalClient(
            client_id=mock_paypal_credentials["client_id"],
            client_secret=mock_paypal_credentials["client_secret"],
            environment="sandbox",
            http_client=http_client,
        )

        token1 = await client.get_access_token()
        assert token1 == "mock_token_xyz_123"

        # Subsequent call uses cache
        token2 = await client.get_access_token()
        assert token2 == "mock_token_xyz_123"
        assert len(calls) == 1  # Only 1 request made due to caching


@pytest.mark.asyncio
async def test_paypal_client_auth_failure():
    """Invalid credentials raise PayPalAuthError without exposing secrets."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client", "error_description": "Client Authentication failed"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PayPalClient(
            client_id="mock_invalid_user_id",
            client_secret="mock_invalid_user_secret",
            environment="sandbox",
            http_client=http_client,
        )
        with pytest.raises(PayPalAuthError) as exc_info:
            await client.get_access_token()
        assert exc_info.value.status_code == 401
        assert "Client Authentication failed" in str(exc_info.value)
        # Ensure secret is not in exception message
        assert "mock_invalid_user_secret" not in str(exc_info.value)


# ==============================================================================
# 4. Service Provisioning Workflow & Idempotency / Re-run Safety
# ==============================================================================


@pytest.mark.asyncio
async def test_provisioning_service_creates_new_infrastructure_when_none_exists(mock_paypal_credentials):
    """When no matching objects exist, creates Product, Intro Plan, and Standard Plan."""
    created_objects = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok_123", "expires_in": 3600})

        if path == "/v1/catalogs/products":
            if request.method == "GET":
                return httpx.Response(200, json={"products": []})
            if request.method == "POST":
                data = json.loads(request.content.decode())
                created_objects.append(("product", data))
                return httpx.Response(201, json={"id": "PROD-NEW-999", "name": data["name"]})

        if path == "/v1/billing/plans":
            if request.method == "GET":
                return httpx.Response(200, json={"plans": []})
            if request.method == "POST":
                data = json.loads(request.content.decode())
                plan_id = f"P-{data['name'].replace(' ', '-').upper()}-123"
                created_objects.append(("plan", data))
                # Return created plan echoing back cycles and ACTIVE status
                return httpx.Response(201, json={**data, "id": plan_id, "status": "ACTIVE"})

        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PayPalClient(
            client_id=mock_paypal_credentials["client_id"],
            client_secret=mock_paypal_credentials["client_secret"],
            environment="sandbox",
            http_client=http_client,
        )
        service = PayPalProvisioningService(client=client)

        summary = await service.provision(
            intro_price=Decimal("19.00"),
            regular_price=Decimal("29.00"),
            currency="USD",
        )

        assert summary.product_id == "PROD-NEW-999"
        assert summary.intro_plan_id == "P-SOULMATE-MONTHLY-INTRO-123"
        assert summary.standard_plan_id == "P-SOULMATE-MONTHLY-STANDARD-123"
        assert summary.intro_plan_verification.matches is True
        assert summary.standard_plan_verification.matches is True
        assert summary.disclosures_verified is True

        # Check config output contains all required keys
        assert "PAYPAL_PRODUCT_ID=PROD-NEW-999" in summary.env_output
        assert "PAYPAL_SOULMATE_INTRO_PLAN_ID=P-SOULMATE-MONTHLY-INTRO-123" in summary.env_output
        assert "PAYPAL_SOULMATE_STANDARD_PLAN_ID=P-SOULMATE-MONTHLY-STANDARD-123" in summary.env_output
        assert "SOULMATE_CURRENCY=USD" in summary.env_output
        assert "SOULMATE_INTRO_PRICE=19.00" in summary.env_output
        assert "SOULMATE_REGULAR_PRICE=29.00" in summary.env_output


@pytest.mark.asyncio
async def test_provisioning_service_idempotent_reuses_existing_matching_objects(mock_paypal_credentials):
    """Acceptance: Safe to re-run; reuses existing provisioned product and plans without duplicating."""
    existing_intro_plan = {
        "id": "P-EXISTING-INTRO",
        "name": "Soulmate Monthly Intro",
        "status": "ACTIVE",
        "product_id": "PROD-EXISTING-1",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {"fixed_price": {"value": "19.00", "currency_code": "USD"}},
            },
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": "29.00", "currency_code": "USD"}},
            },
        ],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1},
    }

    existing_std_plan = {
        "id": "P-EXISTING-STD",
        "name": "Soulmate Monthly Standard",
        "status": "ACTIVE",
        "product_id": "PROD-EXISTING-1",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": "29.00", "currency_code": "USD"}},
            }
        ],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1},
    }

    post_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok_123", "expires_in": 3600})

        if request.method == "POST":
            post_count += 1

        if path == "/v1/catalogs/products/PROD-EXISTING-1":
            return httpx.Response(200, json={"id": "PROD-EXISTING-1", "name": "Soulmate Path Monthly Subscription"})

        if path == "/v1/billing/plans/P-EXISTING-INTRO":
            return httpx.Response(200, json=existing_intro_plan)

        if path == "/v1/billing/plans/P-EXISTING-STD":
            return httpx.Response(200, json=existing_std_plan)

        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PayPalClient(
            client_id=mock_paypal_credentials["client_id"],
            client_secret=mock_paypal_credentials["client_secret"],
            environment="sandbox",
            http_client=http_client,
        )
        service = PayPalProvisioningService(client=client)

        summary = await service.provision(
            intro_price=Decimal("19.00"),
            regular_price=Decimal("29.00"),
            currency="USD",
            existing_product_id="PROD-EXISTING-1",
            existing_intro_plan_id="P-EXISTING-INTRO",
            existing_standard_plan_id="P-EXISTING-STD",
        )

        assert summary.product_id == "PROD-EXISTING-1"
        assert summary.intro_plan_id == "P-EXISTING-INTRO"
        assert summary.standard_plan_id == "P-EXISTING-STD"
        assert summary.intro_plan_verification.matches is True
        assert summary.standard_plan_verification.matches is True

        # Invariant: Zero POST requests were made because all objects were existing and valid
        assert post_count == 0


@pytest.mark.asyncio
async def test_provisioning_service_concurrency_safety(mock_paypal_credentials):
    """
    M-3 / AGENTS.md §6: Verify concurrency safety of provisioning workflow.
    Multiple concurrent calls to service.provision() must serialize and create exactly
    one product and one intro plan, utilizing async lock and deterministic request_ids.
    """
    created_products = []
    created_plans = []
    product_store = {}
    plan_store = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok_123", "expires_in": 3600})

        if path == "/v1/catalogs/products":
            if request.method == "GET":
                return httpx.Response(200, json={"products": list(product_store.values())})
            if request.method == "POST":
                data = json.loads(request.content.decode())
                prod_id = "PROD-CONCURRENT-1"
                created_products.append(data)
                prod_obj = {"id": prod_id, "name": data["name"]}
                product_store[prod_id] = prod_obj
                return httpx.Response(201, json=prod_obj)

        if path == "/v1/billing/plans":
            if request.method == "GET":
                return httpx.Response(200, json={"plans": list(plan_store.values())})
            if request.method == "POST":
                data = json.loads(request.content.decode())
                plan_id = f"P-{data['name'].replace(' ', '-').upper()}-CONCURRENT"
                created_plans.append(data)
                plan_obj = {**data, "id": plan_id, "status": "ACTIVE"}
                plan_store[plan_id] = plan_obj
                return httpx.Response(201, json=plan_obj)

        if path.startswith("/v1/billing/plans/"):
            p_id = path.split("/")[-1]
            if p_id in plan_store:
                return httpx.Response(200, json=plan_store[p_id])

        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PayPalClient(
            client_id=mock_paypal_credentials["client_id"],
            client_secret=mock_paypal_credentials["client_secret"],
            environment="sandbox",
            http_client=http_client,
        )
        service = PayPalProvisioningService(client=client)

        # Launch 5 concurrent provisioning calls simultaneously
        tasks = [
            service.provision(
                intro_price=Decimal("19.00"),
                regular_price=Decimal("29.00"),
                currency="USD",
                provision_standard_plan=False,
            )
            for _ in range(5)
        ]
        summaries = await asyncio.gather(*tasks)

        # Invariant: All 5 coroutines succeed and return the exact same product and plan IDs
        for s in summaries:
            assert s.product_id == "PROD-CONCURRENT-1"
            assert s.intro_plan_id == "P-SOULMATE-MONTHLY-INTRO-CONCURRENT"

        # Invariant: Only 1 product creation and 1 plan creation request occurred
        assert len(created_products) == 1
        assert len(created_plans) == 1


# ==============================================================================
# 5. CLI Tool Execution & Modes
# ==============================================================================


@pytest.mark.asyncio
async def test_cli_dry_run_mode():
    """CLI --dry-run prints payloads and exits cleanly with 0."""
    args = parse_args(["--dry-run", "--intro-price", "19.00", "--regular-price", "29.00"])
    code = await main_async(args)
    assert code == 0


@pytest.mark.asyncio
async def test_cli_rejects_missing_prices():
    """CLI fails fast when prices are missing (Decision PAY-01)."""
    args = parse_args(["--dry-run"])
    code = await main_async(args)
    assert code == 1


@pytest.mark.asyncio
async def test_cli_verify_only_mode_success(mock_paypal_credentials, monkeypatch):
    """CLI --verify-only inspects and confirms existing plan without mutations."""
    plan_mock = {
        "id": "P-TEST-INTRO-100",
        "name": "Soulmate Monthly Intro",
        "status": "ACTIVE",
        "product_id": "PROD-100",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {"fixed_price": {"value": "19.00", "currency_code": "USD"}},
            },
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": "29.00", "currency_code": "USD"}},
            },
        ],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1},
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok_123", "expires_in": 3600})
        if request.url.path == "/v1/billing/plans/P-TEST-INTRO-100":
            return httpx.Response(200, json=plan_mock)
        return httpx.Response(404)

    # Patch AsyncClient in PayPalClient
    orig_init = PayPalClient.__init__

    def patched_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        self._http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        self._owns_http_client = True

    monkeypatch.setattr(PayPalClient, "__init__", patched_init)

    args = parse_args([
        "--verify-only",
        "--intro-price", "19.00",
        "--regular-price", "29.00",
        "--intro-plan-id", "P-TEST-INTRO-100",
        "--product-id", "PROD-100",
        "--client-id", mock_paypal_credentials["client_id"],
        "--client-secret", mock_paypal_credentials["client_secret"],
    ])
    code = await main_async(args)
    assert code == 0
