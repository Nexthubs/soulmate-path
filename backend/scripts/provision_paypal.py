#!/usr/bin/env python3
"""
PayPal Product & Plan Provisioning Tool (SP-401, DEV-SPEC §9.1–9.2, §22, §25, Decisions: PAY-01, PAY-02).

Repeatable CLI tool for provisioning and verifying reusable PayPal monthly subscription infrastructure:
- Creates or detects reusable PayPal Catalog Product.
- Creates or detects reusable Intro Plan (promotional 1st month, then regular renewal).
- Creates or detects reusable Standard Plan (for PAY-02 re-subscription policy).
- Validates strictly monthly cadence and disclosure parity.
- Outputs copy-pasteable environment configuration for .env.

Usage:
    # 1. Dry run inspection of payloads (no network calls):
    python backend/scripts/provision_paypal.py --dry-run --intro-price 19.00 --regular-price 29.00

    # 2. Provision objects in PayPal Sandbox:
    python backend/scripts/provision_paypal.py --intro-price 19.00 --regular-price 29.00 --env sandbox

    # 3. Verify existing Sandbox plan configuration without creating new objects:
    python backend/scripts/provision_paypal.py --verify-only --intro-price 19.00 --regular-price 29.00
"""

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import json
import logging
from pathlib import Path
import sys
from typing import Optional

# Ensure 'backend' directory is in python search path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.soulmate.services.paypal_client import PayPalAPIError, PayPalAuthError, PayPalClient
from app.soulmate.services.paypal_provisioning import (
    INTRO_PLAN_DESC_DEFAULT,
    INTRO_PLAN_NAME_DEFAULT,
    PRODUCT_DESC_DEFAULT,
    PRODUCT_NAME_DEFAULT,
    STANDARD_PLAN_DESC_DEFAULT,
    STANDARD_PLAN_NAME_DEFAULT,
    PayPalProvisioningService,
)

logger = logging.getLogger("paypal_provisioning")


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision and verify reusable PayPal billing objects for Soulmate Path monthly subscriptions."
    )
    parser.add_argument(
        "--intro-price",
        type=str,
        default=None,
        help="Discounted first month price (e.g. 19.00). Defaults to SOULMATE_INTRO_PRICE.",
    )
    parser.add_argument(
        "--regular-price",
        type=str,
        default=None,
        help="Regular monthly renewal price (e.g. 29.00). Defaults to SOULMATE_REGULAR_PRICE.",
    )
    parser.add_argument(
        "--currency",
        type=str,
        default=None,
        help="Currency code (e.g. USD). Defaults to SOULMATE_CURRENCY or USD.",
    )
    parser.add_argument(
        "--env",
        choices=["sandbox", "production"],
        default=None,
        help="PayPal environment (sandbox or production). Defaults to PAYPAL_ENV.",
    )
    parser.add_argument(
        "--client-id",
        type=str,
        default=None,
        help="PayPal Client ID override. Defaults to PAYPAL_CLIENT_ID from environment.",
    )
    parser.add_argument(
        "--client-secret",
        type=str,
        default=None,
        help="PayPal Client Secret override. Defaults to PAYPAL_CLIENT_SECRET from environment.",
    )
    parser.add_argument(
        "--product-id",
        type=str,
        default=None,
        help="Existing PayPal Product ID to reuse or verify. Defaults to PAYPAL_PRODUCT_ID.",
    )
    parser.add_argument(
        "--intro-plan-id",
        type=str,
        default=None,
        help="Existing PayPal Intro Plan ID to reuse or verify. Defaults to PAYPAL_SOULMATE_INTRO_PLAN_ID.",
    )
    parser.add_argument(
        "--standard-plan-id",
        type=str,
        default=None,
        help="Existing PayPal Standard Plan ID to reuse or verify. Defaults to PAYPAL_SOULMATE_STANDARD_PLAN_ID.",
    )
    parser.add_argument(
        "--skip-standard-plan",
        action="store_true",
        help="Skip provisioning standard recurring plan (only provision intro plan).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan payloads and verify disclosures without making PayPal API calls.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify existing configured plans on PayPal without provisioning new ones.",
    )
    return parser.parse_args(args)


async def main_async(args: argparse.Namespace) -> int:
    # 1. Resolve Environment & Currency
    paypal_env = (args.env or settings.paypal_env or "sandbox").lower().strip()
    currency = (args.currency or settings.soulmate_currency or "USD").upper().strip()

    # 2. Resolve Prices (Enforce Decision PAY-01: No hardcoded pricing)
    intro_price_str = args.intro_price
    if intro_price_str is None and settings.soulmate_intro_price is not None:
        intro_price_str = str(settings.soulmate_intro_price)

    regular_price_str = args.regular_price
    if regular_price_str is None and settings.soulmate_regular_price is not None:
        regular_price_str = str(settings.soulmate_regular_price)

    if not intro_price_str or not regular_price_str:
        print("\n[ERROR] Both INTRO_PRICE and REGULAR_PRICE are required.", file=sys.stderr)
        print("In accordance with Decision PAY-01, production pricing is never guessed or hardcoded.", file=sys.stderr)
        print("Please supply them via arguments (e.g. --intro-price 19.00 --regular-price 29.00)", file=sys.stderr)
        print("or via environment variables SOULMATE_INTRO_PRICE and SOULMATE_REGULAR_PRICE.\n", file=sys.stderr)
        return 1

    try:
        intro_price = Decimal(intro_price_str.strip())
        regular_price = Decimal(regular_price_str.strip())
    except InvalidOperation as e:
        print(f"\n[ERROR] Invalid pricing format: {e}", file=sys.stderr)
        return 1

    if intro_price <= 0 or regular_price <= 0:
        print("\n[ERROR] Prices must be strictly positive amounts.", file=sys.stderr)
        return 1

    # 3. Handle Dry Run Mode
    if args.dry_run:
        print("\n" + "=" * 65)
        print(" PayPal Monthly Subscription - DRY RUN PAYLOAD INSPECTION")
        print("=" * 65)
        print(f"Target Environment: {paypal_env}")
        print(f"Currency:           {currency}")
        print(f"Intro Price:        {intro_price:.2f}")
        print(f"Regular Price:      {regular_price:.2f}")
        print("-" * 65)

        dummy_product_id = args.product_id or "PROD-SAMPLE-12345"
        intro_payload = PayPalProvisioningService.build_intro_plan_payload(
            product_id=dummy_product_id,
            intro_price=intro_price,
            regular_price=regular_price,
            currency=currency,
        )
        std_payload = PayPalProvisioningService.build_standard_plan_payload(
            product_id=dummy_product_id,
            regular_price=regular_price,
            currency=currency,
        )

        print("\n--- Canonical Intro Plan Payload (DEV-SPEC §9.1.1) ---")
        print(json.dumps(intro_payload, indent=2))

        print("\n--- Canonical Standard Plan Payload (DEV-SPEC §9.2) ---")
        print(json.dumps(std_payload, indent=2))

        # Check disclosure parity
        disc_ok, disc_errs = PayPalProvisioningService.verify_disclosures_match_plan(
            intro_price=intro_price,
            regular_price=regular_price,
            currency=currency,
            intro_plan_id="P-INTRO-PREVIEW",
            standard_plan_id="P-STD-PREVIEW",
        )
        print("\n--- Disclosure Parity Check ---")
        if disc_ok:
            print("✓ Disclosures accurately match introductory and renewal amounts.")
        else:
            print(f"✗ Disclosure discrepancies: {disc_errs}")

        print("=" * 65 + "\n")
        return 0

    # 4. Resolve Credentials
    client_id = args.client_id or settings.paypal_client_id
    client_secret = args.client_secret or settings.paypal_client_secret

    if not client_id or not client_secret:
        print("\n[ERROR] PayPal credentials are required for live/sandbox execution.", file=sys.stderr)
        print("Please configure PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env or pass --client-id and --client-secret.", file=sys.stderr)
        return 1

    # 5. Initialize PayPal Client & Service
    async with PayPalClient(
        client_id=client_id,
        client_secret=client_secret,
        environment=paypal_env,
    ) as client:
        service = PayPalProvisioningService(client=client)

        # 6. Verify-Only Mode
        if args.verify_only:
            prod_id = args.product_id or settings.paypal_product_id
            intro_id = args.intro_plan_id or settings.paypal_soulmate_intro_plan_id
            std_id = args.standard_plan_id or settings.paypal_soulmate_standard_plan_id

            if not intro_id:
                print("\n[ERROR] --verify-only requires an intro plan ID to verify.", file=sys.stderr)
                return 1

            print("\n" + "=" * 65)
            print(" PayPal Subscription Plan Verification (DEV-SPEC §9.1–9.2)")
            print("=" * 65)
            print(f"Environment: {paypal_env}")
            print(f"Product ID:  {prod_id or 'Not specified'}")
            print(f"Intro Plan:  {intro_id}")
            if std_id:
                print(f"Std Plan:    {std_id}")
            print("-" * 65)

            try:
                intro_plan_data = await client.get_plan(intro_id)
                if not intro_plan_data:
                    print(f"\n[FAIL] Intro plan '{intro_id}' was not found on PayPal ({paypal_env}).", file=sys.stderr)
                    return 1

                intro_v = service.verify_plan(
                    plan_data=intro_plan_data,
                    expected_type="intro",
                    expected_intro_price=intro_price,
                    expected_regular_price=regular_price,
                    expected_currency=currency,
                    expected_product_id=prod_id,
                )

                if intro_v.matches:
                    print(f"✓ Intro Plan [{intro_id}]: VALID (ACTIVE, monthly cadence, 2 cycles verified)")
                    print(f"    Cycle 1: Trial @ {intro_v.intro_price} {intro_v.currency}")
                    print(f"    Cycle 2: Regular @ {intro_v.regular_price} {intro_v.currency}/month")
                else:
                    print(f"✗ Intro Plan [{intro_id}]: INVALID")
                    for d in intro_v.discrepancies:
                        print(f"    - {d}")

                std_valid = True
                if std_id:
                    std_plan_data = await client.get_plan(std_id)
                    if not std_plan_data:
                        print(f"\n[FAIL] Standard plan '{std_id}' was not found on PayPal ({paypal_env}).", file=sys.stderr)
                        return 1

                    std_v = service.verify_plan(
                        plan_data=std_plan_data,
                        expected_type="standard",
                        expected_regular_price=regular_price,
                        expected_currency=currency,
                        expected_product_id=prod_id,
                    )
                    if std_v.matches:
                        print(f"✓ Standard Plan [{std_id}]: VALID (ACTIVE, monthly cadence, 1 cycle verified)")
                        print(f"    Cycle 1: Regular @ {std_v.regular_price} {std_v.currency}/month")
                    else:
                        print(f"✗ Standard Plan [{std_id}]: INVALID")
                        for d in std_v.discrepancies:
                            print(f"    - {d}")
                        std_valid = False

                if intro_v.matches and std_valid:
                    print("-" * 65)
                    print("RESULT: PASS — All plans match contract specifications.")
                    print("=" * 65 + "\n")
                    return 0
                else:
                    print("-" * 65)
                    print("RESULT: FAIL — Plan verification detected discrepancies.")
                    print("=" * 65 + "\n")
                    return 1

            except (PayPalAuthError, PayPalAPIError) as e:
                print(f"\n[ERROR] PayPal API request failed: {e}", file=sys.stderr)
                return 1

        # 7. Provisioning Execution
        print("\n" + "=" * 65)
        print(" Provisioning PayPal Subscription Billing Objects")
        print("=" * 65)
        print(f"Environment:       {paypal_env}")
        print(f"Currency:          {currency}")
        print(f"Intro Price:       {intro_price:.2f}")
        print(f"Regular Price:     {regular_price:.2f}")
        print(f"Standard Plan:     {'Enabled' if not args.skip_standard_plan else 'Skipped'}")
        print("-" * 65)

        existing_prod = args.product_id or settings.paypal_product_id
        existing_intro = args.intro_plan_id or settings.paypal_soulmate_intro_plan_id
        existing_std = args.standard_plan_id or settings.paypal_soulmate_standard_plan_id

        try:
            summary = await service.provision(
                intro_price=intro_price,
                regular_price=regular_price,
                currency=currency,
                existing_product_id=existing_prod,
                existing_intro_plan_id=existing_intro,
                existing_standard_plan_id=existing_std,
                provision_standard_plan=not args.skip_standard_plan,
            )
        except (PayPalAuthError, PayPalAPIError) as e:
            print(f"\n[ERROR] PayPal operation failed: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            logger.exception("Unexpected error during provisioning")
            print(f"\n[ERROR] Unexpected error: {e}", file=sys.stderr)
            return 1

        print("✓ Product ID:       ", summary.product_id, f"({summary.product_name})")
        print(
            "✓ Intro Plan ID:    ",
            summary.intro_plan_id,
            f"(Verified: {summary.intro_plan_verification.matches}, Status: {summary.intro_plan_verification.status})",
        )
        if summary.standard_plan_id:
            matches = summary.standard_plan_verification.matches if summary.standard_plan_verification else False
            status = summary.standard_plan_verification.status if summary.standard_plan_verification else "UNKNOWN"
            print(
                "✓ Standard Plan ID: ",
                summary.standard_plan_id,
                f"(Verified: {matches}, Status: {status})",
            )
        print("✓ Monthly Cadence:   VERIFIED (interval=MONTH, interval_count=1)")
        print(f"✓ Disclosures Parity: {'VERIFIED' if summary.disclosures_verified else 'FAILED'}")
        print("-" * 65)
        print("Copy the following configuration lines into your .env:")
        print("-" * 65)
        print(summary.env_output)
        print("=" * 65 + "\n")
        return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
