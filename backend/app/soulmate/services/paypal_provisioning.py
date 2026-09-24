"""
PayPal Product & Plan Provisioning and Verification Service (DEV-SPEC §9.1–9.2, §22, §25, Decisions: PAY-01, PAY-02).
Provisions reusable PayPal products and monthly billing plans with intro promotional and standard pricing,
enforcing idempotency, monthly cadence verification, and disclosure parity.
"""

import asyncio
from decimal import Decimal
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.soulmate.domain.offer import build_subscription_offer
from app.soulmate.domain.paypal_models import (
    PayPalBillingCycle,
    PayPalFixedPrice,
    PayPalFrequency,
    PayPalPaymentPreferences,
    PayPalPlanPayload,
    PayPalPlanVerificationResult,
    PayPalPricingScheme,
    PayPalProductPayload,
    ProvisioningSummary,
)
from app.soulmate.services.paypal_client import PayPalAPIError, PayPalClient

logger = logging.getLogger(__name__)

PRODUCT_NAME_DEFAULT = "Soulmate Path Monthly Subscription"
PRODUCT_DESC_DEFAULT = "Soulmate Path membership and personalized soulmate insights"
INTRO_PLAN_NAME_DEFAULT = "Soulmate Monthly Intro"
INTRO_PLAN_DESC_DEFAULT = "Soulmate Path monthly subscription with discounted first month"
STANDARD_PLAN_NAME_DEFAULT = "Soulmate Monthly Standard"
STANDARD_PLAN_DESC_DEFAULT = "Soulmate Path standard monthly subscription"


def _generate_idempotency_key(prefix: str, *args: Any) -> str:
    """
    Generate deterministic 36-char string for PayPal-Request-Id header.
    Ensures distributed/cross-process deduplication on PayPal API.
    """
    content = ":".join(str(a) for a in args)
    return hashlib.sha256(f"{prefix}:{content}".encode()).hexdigest()[:36]


class PayPalProvisioningService:
    """
    Orchestrates creation, detection, and verification of reusable PayPal billing infrastructure.
    Enforces that plans are reusable templates, not created per-user (Spec §9.2).
    Thread/async safe: Uses in-process async lock and PayPal-Request-Id deduplication headers.
    """

    def __init__(self, client: PayPalClient):
        self.client = client
        self._lock = asyncio.Lock()

    # --------------------------------------------------------------------------
    # Payload Builders (DEV-SPEC §9.1.1 & §9.2)
    # --------------------------------------------------------------------------

    @staticmethod
    def build_intro_plan_payload(
        product_id: str,
        intro_price: Decimal,
        regular_price: Decimal,
        currency: str = "USD",
        name: str = INTRO_PLAN_NAME_DEFAULT,
        description: Optional[str] = INTRO_PLAN_DESC_DEFAULT,
    ) -> Dict[str, Any]:
        """
        Build canonical 2-cycle monthly intro subscription plan payload (DEV-SPEC §9.1.1):
        - Cycle 1: MONTH x 1, TRIAL tenure, sequence 1, total_cycles 1, intro discounted price.
        - Cycle 2: MONTH x 1, REGULAR tenure, sequence 2, total_cycles 0 (infinite), regular price.
        """
        if intro_price <= 0:
            raise ValueError(f"Intro price must be positive, got {intro_price}")
        if regular_price <= 0:
            raise ValueError(f"Regular price must be positive, got {regular_price}")

        curr = currency.upper().strip()
        intro_val = f"{Decimal(str(intro_price)):.2f}"
        reg_val = f"{Decimal(str(regular_price)):.2f}"

        cycle_1 = PayPalBillingCycle(
            frequency=PayPalFrequency(interval_unit="MONTH", interval_count=1),
            tenure_type="TRIAL",
            sequence=1,
            total_cycles=1,
            pricing_scheme=PayPalPricingScheme(
                fixed_price=PayPalFixedPrice(value=intro_val, currency_code=curr)
            ),
        )

        cycle_2 = PayPalBillingCycle(
            frequency=PayPalFrequency(interval_unit="MONTH", interval_count=1),
            tenure_type="REGULAR",
            sequence=2,
            total_cycles=0,
            pricing_scheme=PayPalPricingScheme(
                fixed_price=PayPalFixedPrice(value=reg_val, currency_code=curr)
            ),
        )

        payload = PayPalPlanPayload(
            product_id=product_id,
            name=name,
            description=description,
            status="ACTIVE",
            billing_cycles=[cycle_1, cycle_2],
            payment_preferences=PayPalPaymentPreferences(
                auto_bill_outstanding=True,
                payment_failure_threshold=1,
            ),
        )
        return payload.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def build_standard_plan_payload(
        product_id: str,
        regular_price: Decimal,
        currency: str = "USD",
        name: str = STANDARD_PLAN_NAME_DEFAULT,
        description: Optional[str] = STANDARD_PLAN_DESC_DEFAULT,
    ) -> Dict[str, Any]:
        """
        Build standard 1-cycle monthly recurring subscription plan payload (DEV-SPEC §9.2):
        - Cycle 1: MONTH x 1, REGULAR tenure, sequence 1, total_cycles 0 (infinite), regular price.
        """
        if regular_price <= 0:
            raise ValueError(f"Regular price must be positive, got {regular_price}")

        curr = currency.upper().strip()
        reg_val = f"{Decimal(str(regular_price)):.2f}"

        cycle_1 = PayPalBillingCycle(
            frequency=PayPalFrequency(interval_unit="MONTH", interval_count=1),
            tenure_type="REGULAR",
            sequence=1,
            total_cycles=0,
            pricing_scheme=PayPalPricingScheme(
                fixed_price=PayPalFixedPrice(value=reg_val, currency_code=curr)
            ),
        )

        payload = PayPalPlanPayload(
            product_id=product_id,
            name=name,
            description=description,
            status="ACTIVE",
            billing_cycles=[cycle_1],
            payment_preferences=PayPalPaymentPreferences(
                auto_bill_outstanding=True,
                payment_failure_threshold=1,
            ),
        )
        return payload.model_dump(mode="json", exclude_none=True)

    # --------------------------------------------------------------------------
    # Plan Verification (Acceptance: Cadence, Disclosure, Cycle Parity)
    # --------------------------------------------------------------------------

    @classmethod
    def verify_plan(
        cls,
        plan_data: Dict[str, Any],
        expected_type: str,
        expected_regular_price: Decimal,
        expected_intro_price: Optional[Decimal] = None,
        expected_currency: str = "USD",
        expected_product_id: Optional[str] = None,
    ) -> PayPalPlanVerificationResult:
        """
        Verify a provisioned PayPal billing plan matches the product specification:
        - Status must be ACTIVE.
        - Product ID matches if specified.
        - Cadence must be strictly monthly (interval_unit == 'MONTH', interval_count == 1).
        - Correct cycle sequences, tenure types, and pricing amounts.
        """
        plan_id = plan_data.get("id", "UNKNOWN")
        plan_name = plan_data.get("name", "Unknown Plan")
        status = plan_data.get("status", "UNKNOWN").upper()
        prod_id = plan_data.get("product_id")
        cycles = plan_data.get("billing_cycles", [])
        curr_expected = expected_currency.upper().strip()
        expected_reg_str = f"{Decimal(str(expected_regular_price)):.2f}"
        expected_intro_str = f"{Decimal(str(expected_intro_price)):.2f}" if expected_intro_price is not None else None

        discrepancies: List[str] = []

        # 1. Status check
        if status != "ACTIVE":
            discrepancies.append(f"Plan status is '{status}', expected 'ACTIVE'.")

        # 2. Product ID check
        if expected_product_id and prod_id != expected_product_id:
            discrepancies.append(f"Product ID mismatch: plan has '{prod_id}', expected '{expected_product_id}'.")

        # 3. Billing cycles count
        detected_intro_price: Optional[str] = None
        detected_reg_price: Optional[str] = None
        detected_interval = "MONTH"
        detected_count = 1

        if expected_type == "intro":
            if len(cycles) != 2:
                discrepancies.append(f"Intro plan must have exactly 2 billing cycles, found {len(cycles)}.")
            else:
                c1, c2 = cycles[0], cycles[1]
                # Cycle 1: Trial intro
                c1_freq = c1.get("frequency", {})
                detected_interval = c1_freq.get("interval_unit", "")
                detected_count = c1_freq.get("interval_count", 0)
                if detected_interval != "MONTH" or detected_count != 1:
                    discrepancies.append(f"Cycle 1 cadence is {detected_interval} x {detected_count}, expected MONTH x 1.")
                if c1.get("tenure_type") != "TRIAL":
                    discrepancies.append(f"Cycle 1 tenure_type is '{c1.get('tenure_type')}', expected 'TRIAL'.")
                if c1.get("sequence") != 1:
                    discrepancies.append(f"Cycle 1 sequence is {c1.get('sequence')}, expected 1.")
                if c1.get("total_cycles") != 1:
                    discrepancies.append(f"Cycle 1 total_cycles is {c1.get('total_cycles')}, expected 1.")

                p1_fixed = c1.get("pricing_scheme", {}).get("fixed_price", {})
                detected_intro_price = p1_fixed.get("value")
                c1_curr = p1_fixed.get("currency_code", "").upper()
                if c1_curr != curr_expected:
                    discrepancies.append(f"Cycle 1 currency is '{c1_curr}', expected '{curr_expected}'.")
                if expected_intro_str and detected_intro_price != expected_intro_str:
                    discrepancies.append(
                        f"Cycle 1 price is '{detected_intro_price}', expected intro price '{expected_intro_str}'."
                    )

                # Cycle 2: Regular renewal
                c2_freq = c2.get("frequency", {})
                if c2_freq.get("interval_unit") != "MONTH" or c2_freq.get("interval_count") != 1:
                    discrepancies.append(
                        f"Cycle 2 cadence is {c2_freq.get('interval_unit')} x {c2_freq.get('interval_count')}, expected MONTH x 1."
                    )
                if c2.get("tenure_type") != "REGULAR":
                    discrepancies.append(f"Cycle 2 tenure_type is '{c2.get('tenure_type')}', expected 'REGULAR'.")
                if c2.get("sequence") != 2:
                    discrepancies.append(f"Cycle 2 sequence is {c2.get('sequence')}, expected 2.")
                if c2.get("total_cycles") != 0:
                    discrepancies.append(f"Cycle 2 total_cycles is {c2.get('total_cycles')}, expected 0 (infinite).")

                p2_fixed = c2.get("pricing_scheme", {}).get("fixed_price", {})
                detected_reg_price = p2_fixed.get("value")
                c2_curr = p2_fixed.get("currency_code", "").upper()
                if c2_curr != curr_expected:
                    discrepancies.append(f"Cycle 2 currency is '{c2_curr}', expected '{curr_expected}'.")
                if detected_reg_price != expected_reg_str:
                    discrepancies.append(
                        f"Cycle 2 price is '{detected_reg_price}', expected regular price '{expected_reg_str}'."
                    )

        elif expected_type == "standard":
            if len(cycles) != 1:
                discrepancies.append(f"Standard plan must have exactly 1 billing cycle, found {len(cycles)}.")
            else:
                c1 = cycles[0]
                c1_freq = c1.get("frequency", {})
                detected_interval = c1_freq.get("interval_unit", "")
                detected_count = c1_freq.get("interval_count", 0)
                if detected_interval != "MONTH" or detected_count != 1:
                    discrepancies.append(f"Cadence is {detected_interval} x {detected_count}, expected MONTH x 1.")
                if c1.get("tenure_type") != "REGULAR":
                    discrepancies.append(f"Tenure_type is '{c1.get('tenure_type')}', expected 'REGULAR'.")
                if c1.get("sequence") != 1:
                    discrepancies.append(f"Sequence is {c1.get('sequence')}, expected 1.")
                if c1.get("total_cycles") != 0:
                    discrepancies.append(f"Total_cycles is {c1.get('total_cycles')}, expected 0 (infinite).")

                p1_fixed = c1.get("pricing_scheme", {}).get("fixed_price", {})
                detected_reg_price = p1_fixed.get("value")
                c1_curr = p1_fixed.get("currency_code", "").upper()
                if c1_curr != curr_expected:
                    discrepancies.append(f"Currency is '{c1_curr}', expected '{curr_expected}'.")
                if detected_reg_price != expected_reg_str:
                    discrepancies.append(
                        f"Price is '{detected_reg_price}', expected regular price '{expected_reg_str}'."
                    )
        else:
            discrepancies.append(f"Unknown plan verification type '{expected_type}'.")

        # 4. Payment preferences check
        prefs = plan_data.get("payment_preferences", {})
        if prefs.get("auto_bill_outstanding") is not True:
            discrepancies.append("Payment preferences auto_bill_outstanding must be true.")

        return PayPalPlanVerificationResult(
            plan_id=plan_id,
            plan_name=plan_name,
            status=status,
            product_id=prod_id,
            matches=len(discrepancies) == 0,
            plan_type=expected_type if expected_type in ("intro", "standard") else "unknown",
            currency=curr_expected,
            intro_price=detected_intro_price,
            regular_price=detected_reg_price,
            interval=detected_interval,
            interval_count=detected_count,
            total_billing_cycles=len(cycles),
            discrepancies=discrepancies,
        )

    @classmethod
    def verify_disclosures_match_plan(
        cls,
        intro_price: Decimal,
        regular_price: Decimal,
        currency: str,
        intro_plan_id: str,
        standard_plan_id: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Verify that server subscription offer disclosures match the planned amounts.
        Validates DEV-SPEC §9.1 and Acceptance: 'renewal disclosure values match plan'.
        """
        discrepancies: List[str] = []
        offer = build_subscription_offer(
            currency=currency,
            intro_price=intro_price,
            regular_price=regular_price,
            intro_plan_id=intro_plan_id,
            standard_plan_id=standard_plan_id,
            has_prior_subscription=False,
        )

        disclosure = offer.get("disclosure", {})
        today_text = disclosure.get("today_text", "")
        renewal_text = disclosure.get("renewal_text", "")

        intro_str = f"{Decimal(str(intro_price)):.2f}"
        reg_str = f"{Decimal(str(regular_price)):.2f}"

        if intro_str not in today_text:
            discrepancies.append(f"Today disclosure '{today_text}' does not contain intro price '{intro_str}'.")
        if reg_str not in renewal_text:
            discrepancies.append(f"Renewal disclosure '{renewal_text}' does not contain regular price '{reg_str}'.")
        if disclosure.get("interval") != "MONTH" or disclosure.get("interval_count") != 1:
            discrepancies.append(
                f"Disclosure cadence is {disclosure.get('interval')} x {disclosure.get('interval_count')}, expected MONTH x 1."
            )
        if not disclosure.get("auto_renew"):
            discrepancies.append("Disclosure auto_renew must be true.")

        return len(discrepancies) == 0, discrepancies

    # --------------------------------------------------------------------------
    # Repeatable / Idempotent Provisioning Workflow (Concurrency Safe)
    # --------------------------------------------------------------------------

    async def get_or_create_product(
        self,
        existing_product_id: Optional[str] = None,
        name: str = PRODUCT_NAME_DEFAULT,
        description: str = PRODUCT_DESC_DEFAULT,
    ) -> Dict[str, Any]:
        """Thread/coroutine safe product retrieval or creation."""
        async with self._lock:
            return await self._get_or_create_product_unlocked(
                existing_product_id=existing_product_id,
                name=name,
                description=description,
            )

    async def _get_or_create_product_unlocked(
        self,
        existing_product_id: Optional[str] = None,
        name: str = PRODUCT_NAME_DEFAULT,
        description: str = PRODUCT_DESC_DEFAULT,
    ) -> Dict[str, Any]:
        """
        Locate existing PayPal catalog product or create a new one.
        Ensures idempotent re-runs without creating redundant products.
        """
        # 1. If explicit ID provided, verify it on PayPal
        if existing_product_id:
            logger.info("Checking specified PayPal product ID: %s", existing_product_id)
            prod = await self.client.get_product(existing_product_id)
            if prod:
                logger.info("Found existing PayPal product: %s (%s)", existing_product_id, prod.get("name"))
                return prod
            logger.warning("Product ID %s not found on PayPal, checking existing products by name...", existing_product_id)

        # 2. Check catalog products for matching name
        products = await self.client.list_products(page=1, page_size=20)
        for p in products:
            if p.get("name") in (name, "Soulmate Path", PRODUCT_NAME_DEFAULT):
                logger.info("Reusing existing PayPal product: %s (%s)", p.get("id"), p.get("name"))
                return p

        # 3. Create new product with deterministic request_id for distributed idempotency
        logger.info("Creating new PayPal product: %s", name)
        request_id = _generate_idempotency_key("product", name)
        new_prod = await self.client.create_product(
            name=name,
            description=description,
            product_type="SERVICE",
            category="ONLINE_SERVICES",
            request_id=request_id,
        )
        logger.info("Successfully created PayPal product: %s", new_prod.get("id"))
        return new_prod

    async def get_or_create_intro_plan(
        self,
        product_id: str,
        intro_price: Decimal,
        regular_price: Decimal,
        currency: str = "USD",
        existing_plan_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], PayPalPlanVerificationResult]:
        """Thread/coroutine safe intro plan retrieval or creation."""
        async with self._lock:
            return await self._get_or_create_intro_plan_unlocked(
                product_id=product_id,
                intro_price=intro_price,
                regular_price=regular_price,
                currency=currency,
                existing_plan_id=existing_plan_id,
            )

    async def _get_or_create_intro_plan_unlocked(
        self,
        product_id: str,
        intro_price: Decimal,
        regular_price: Decimal,
        currency: str = "USD",
        existing_plan_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], PayPalPlanVerificationResult]:
        """
        Locate existing matching intro plan or create a new one.
        Ensures idempotent re-runs and validates plan parameters.
        """
        # 1. If existing ID provided, verify and reuse if matching
        if existing_plan_id:
            logger.info("Checking specified PayPal intro plan ID: %s", existing_plan_id)
            plan = await self.client.get_plan(existing_plan_id)
            if plan:
                v_res = self.verify_plan(
                    plan_data=plan,
                    expected_type="intro",
                    expected_intro_price=intro_price,
                    expected_regular_price=regular_price,
                    expected_currency=currency,
                    expected_product_id=product_id,
                )
                if v_res.matches:
                    logger.info("Existing intro plan %s matches specifications. Reusing.", existing_plan_id)
                    return plan, v_res
                logger.warning(
                    "Specified intro plan %s does not match specifications: %s",
                    existing_plan_id,
                    v_res.discrepancies,
                )

        # 2. Inspect existing plans for this product on PayPal
        plans = await self.client.list_plans(product_id=product_id, page=1, page_size=20)
        for p_summary in plans:
            p_id = p_summary.get("id")
            if not p_id:
                continue
            plan_detail = await self.client.get_plan(p_id)
            if not plan_detail:
                continue
            v_res = self.verify_plan(
                plan_data=plan_detail,
                expected_type="intro",
                expected_intro_price=intro_price,
                expected_regular_price=regular_price,
                expected_currency=currency,
                expected_product_id=product_id,
            )
            if v_res.matches:
                logger.info("Found existing matching intro plan: %s. Reusing.", p_id)
                return plan_detail, v_res

        # 3. Create new intro plan with deterministic request_id for distributed idempotency
        logger.info("Creating new PayPal intro plan on product %s...", product_id)
        payload = self.build_intro_plan_payload(
            product_id=product_id,
            intro_price=intro_price,
            regular_price=regular_price,
            currency=currency,
        )
        request_id = _generate_idempotency_key("intro-plan", product_id, intro_price, regular_price, currency)
        created_plan = await self.client.create_plan(payload, request_id=request_id, auto_activate=True)
        v_res = self.verify_plan(
            plan_data=created_plan,
            expected_type="intro",
            expected_intro_price=intro_price,
            expected_regular_price=regular_price,
            expected_currency=currency,
            expected_product_id=product_id,
        )
        logger.info("Successfully created intro plan: %s (matches=%s)", created_plan.get("id"), v_res.matches)
        return created_plan, v_res

    async def get_or_create_standard_plan(
        self,
        product_id: str,
        regular_price: Decimal,
        currency: str = "USD",
        existing_plan_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], PayPalPlanVerificationResult]:
        """Thread/coroutine safe standard plan retrieval or creation."""
        async with self._lock:
            return await self._get_or_create_standard_plan_unlocked(
                product_id=product_id,
                regular_price=regular_price,
                currency=currency,
                existing_plan_id=existing_plan_id,
            )

    async def _get_or_create_standard_plan_unlocked(
        self,
        product_id: str,
        regular_price: Decimal,
        currency: str = "USD",
        existing_plan_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], PayPalPlanVerificationResult]:
        """
        Locate existing matching standard plan or create a new one.
        Ensures idempotent re-runs for PAY-02 standard monthly plan.
        """
        # 1. If existing ID provided, verify and reuse if matching
        if existing_plan_id:
            logger.info("Checking specified PayPal standard plan ID: %s", existing_plan_id)
            plan = await self.client.get_plan(existing_plan_id)
            if plan:
                v_res = self.verify_plan(
                    plan_data=plan,
                    expected_type="standard",
                    expected_regular_price=regular_price,
                    expected_currency=currency,
                    expected_product_id=product_id,
                )
                if v_res.matches:
                    logger.info("Existing standard plan %s matches specifications. Reusing.", existing_plan_id)
                    return plan, v_res
                logger.warning(
                    "Specified standard plan %s does not match specifications: %s",
                    existing_plan_id,
                    v_res.discrepancies,
                )

        # 2. Inspect existing plans for this product on PayPal
        plans = await self.client.list_plans(product_id=product_id, page=1, page_size=20)
        for p_summary in plans:
            p_id = p_summary.get("id")
            if not p_id:
                continue
            plan_detail = await self.client.get_plan(p_id)
            if not plan_detail:
                continue
            v_res = self.verify_plan(
                plan_data=plan_detail,
                expected_type="standard",
                expected_regular_price=regular_price,
                expected_currency=currency,
                expected_product_id=product_id,
            )
            if v_res.matches:
                logger.info("Found existing matching standard plan: %s. Reusing.", p_id)
                return plan_detail, v_res

        # 3. Create new standard plan with deterministic request_id for distributed idempotency
        logger.info("Creating new PayPal standard plan on product %s...", product_id)
        payload = self.build_standard_plan_payload(
            product_id=product_id,
            regular_price=regular_price,
            currency=currency,
        )
        request_id = _generate_idempotency_key("standard-plan", product_id, regular_price, currency)
        created_plan = await self.client.create_plan(payload, request_id=request_id, auto_activate=True)
        v_res = self.verify_plan(
            plan_data=created_plan,
            expected_type="standard",
            expected_regular_price=regular_price,
            expected_currency=currency,
            expected_product_id=product_id,
        )
        logger.info("Successfully created standard plan: %s (matches=%s)", created_plan.get("id"), v_res.matches)
        return created_plan, v_res

    async def provision(
        self,
        intro_price: Decimal,
        regular_price: Decimal,
        currency: str = "USD",
        existing_product_id: Optional[str] = None,
        existing_intro_plan_id: Optional[str] = None,
        existing_standard_plan_id: Optional[str] = None,
        provision_standard_plan: bool = True,
    ) -> ProvisioningSummary:
        """
        Execute full idempotent provisioning workflow for PayPal subscription infrastructure.
        Protected by asyncio.Lock and deterministic request_ids to ensure concurrency safety.
        """
        async with self._lock:
            return await self._provision_unlocked(
                intro_price=intro_price,
                regular_price=regular_price,
                currency=currency,
                existing_product_id=existing_product_id,
                existing_intro_plan_id=existing_intro_plan_id,
                existing_standard_plan_id=existing_standard_plan_id,
                provision_standard_plan=provision_standard_plan,
            )

    async def _provision_unlocked(
        self,
        intro_price: Decimal,
        regular_price: Decimal,
        currency: str = "USD",
        existing_product_id: Optional[str] = None,
        existing_intro_plan_id: Optional[str] = None,
        existing_standard_plan_id: Optional[str] = None,
        provision_standard_plan: bool = True,
    ) -> ProvisioningSummary:
        curr = currency.upper().strip()

        # Step 1: Product
        product = await self._get_or_create_product_unlocked(existing_product_id=existing_product_id)
        prod_id = product["id"]
        prod_name = product.get("name", PRODUCT_NAME_DEFAULT)

        # Step 2: Intro Plan
        intro_plan, intro_v = await self._get_or_create_intro_plan_unlocked(
            product_id=prod_id,
            intro_price=intro_price,
            regular_price=regular_price,
            currency=curr,
            existing_plan_id=existing_intro_plan_id,
        )
        intro_plan_id = intro_plan["id"]

        # Step 3: Standard Plan (optional per PAY-02)
        standard_plan_id: Optional[str] = None
        standard_v: Optional[PayPalPlanVerificationResult] = None
        if provision_standard_plan:
            standard_plan, standard_v = await self._get_or_create_standard_plan_unlocked(
                product_id=prod_id,
                regular_price=regular_price,
                currency=curr,
                existing_plan_id=existing_standard_plan_id,
            )
            standard_plan_id = standard_plan["id"]

        # Step 4: Disclosures parity check
        disc_ok, disc_discrepancies = self.verify_disclosures_match_plan(
            intro_price=intro_price,
            regular_price=regular_price,
            currency=curr,
            intro_plan_id=intro_plan_id,
            standard_plan_id=standard_plan_id,
        )
        if not disc_ok:
            logger.warning("Disclosure parity warning: %s", disc_discrepancies)

        # Step 5: Format .env configuration
        env_lines = [
            f"PAYPAL_PRODUCT_ID={prod_id}",
            f"PAYPAL_SOULMATE_INTRO_PLAN_ID={intro_plan_id}",
        ]
        if standard_plan_id:
            env_lines.append(f"PAYPAL_SOULMATE_STANDARD_PLAN_ID={standard_plan_id}")
        env_lines.extend([
            f"SOULMATE_CURRENCY={curr}",
            f"SOULMATE_INTRO_PRICE={Decimal(str(intro_price)):.2f}",
            f"SOULMATE_REGULAR_PRICE={Decimal(str(regular_price)):.2f}",
        ])
        env_output = "\n".join(env_lines)

        return ProvisioningSummary(
            environment=self.client.environment,
            product_id=prod_id,
            product_name=prod_name,
            intro_plan_id=intro_plan_id,
            standard_plan_id=standard_plan_id,
            intro_plan_verification=intro_v,
            standard_plan_verification=standard_v,
            env_output=env_output,
            disclosures_verified=disc_ok,
        )
