"""
Subscription Offer Domain Logic (DEV-SPEC §9.1–9.2, §15.6, §21–22, Decisions: PAY-01, PAY-02).
Pure functions for constructing the subscription offer, renewal disclosures, and eligibility evaluation.
"""

from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


class ResubscriptionPolicy(str, Enum):
    BLOCKED = "blocked"
    SINGLE_INTRO = "single_intro"
    ALLOW_INTRO = "allow_intro"


CURRENCY_SYMBOL_MAP: Dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$",
    "AUD": "AU$",
}


def get_currency_symbol(currency: str) -> str:
    """Return currency prefix symbol or fallback with a space."""
    return CURRENCY_SYMBOL_MAP.get(currency.upper().strip(), f"{currency.upper().strip()} ")


def format_offer_price(price: Optional[Decimal], placeholder: str) -> str:
    """
    Format Decimal price as string with two decimals, or return placeholder
    if price is unconfigured (per PAY-01).
    """
    if price is not None:
        return f"{price:.2f}"
    return placeholder


def evaluate_resubscription_eligibility(
    has_prior_subscription: bool,
    policy: str = ResubscriptionPolicy.BLOCKED.value,
) -> Dict[str, Any]:
    """
    Evaluate user eligibility under Decision PAY-02:
    - First-time subscriber: always eligible for intro offer.
    - Returning subscriber:
      - 'blocked' (default): blocked from re-subscribing pending product resolution.
      - 'single_intro': standard monthly price only, not eligible for intro.
      - 'allow_intro': eligible for intro price again.
    """
    clean_policy = (policy or ResubscriptionPolicy.BLOCKED.value).lower().strip()

    if not has_prior_subscription:
        return {
            "eligible_for_intro": True,
            "plan_class": "intro",
            "policy": clean_policy,
            "is_blocked": False,
            "reason": None,
        }

    # Returning subscriber handling per PAY-02
    if clean_policy == ResubscriptionPolicy.ALLOW_INTRO.value:
        return {
            "eligible_for_intro": True,
            "plan_class": "intro",
            "policy": clean_policy,
            "is_blocked": False,
            "reason": "Promotional intro price applied for returning subscriber.",
        }
    elif clean_policy == ResubscriptionPolicy.SINGLE_INTRO.value:
        return {
            "eligible_for_intro": False,
            "plan_class": "standard",
            "policy": clean_policy,
            "is_blocked": False,
            "reason": "Returning subscriber standard pricing applied.",
        }
    else:
        # Default 'blocked' per PAY-02
        return {
            "eligible_for_intro": False,
            "plan_class": "blocked",
            "policy": clean_policy,
            "is_blocked": True,
            "reason": "Returning subscriber intro pricing policy is blocked pending product resolution (PAY-02).",
        }


def build_subscription_offer(
    currency: str = "USD",
    intro_price: Optional[Decimal] = None,
    regular_price: Optional[Decimal] = None,
    intro_plan_id: Optional[str] = None,
    standard_plan_id: Optional[str] = None,
    paypal_client_id: Optional[str] = None,
    paypal_env: str = "sandbox",
    has_prior_subscription: bool = False,
    policy: str = "blocked",
) -> Dict[str, Any]:
    """
    Build display-ready offer response dict (DEV-SPEC §9.1, §15.6, §21–22).
    """
    currency_clean = (currency or "USD").upper().strip()
    symbol = get_currency_symbol(currency_clean)

    formatted_intro = format_offer_price(intro_price, "{INTRO_PRICE}")
    formatted_regular = format_offer_price(regular_price, "{REGULAR_PRICE}")

    eligibility = evaluate_resubscription_eligibility(
        has_prior_subscription=has_prior_subscription,
        policy=policy,
    )

    # Determine active plan ID based on eligibility and configuration
    if eligibility["plan_class"] == "standard" and standard_plan_id:
        active_plan_id = standard_plan_id
    else:
        active_plan_id = intro_plan_id

    # Construct renewal disclosure (DEV-SPEC §9.1 & §21)
    today_text = f"Today: {symbol}{formatted_intro}"
    renewal_text = f"Then {symbol}{formatted_regular} / month"
    terms_text = "Automatically renews monthly until canceled. Cancel anytime."

    disclosure = {
        "today_text": today_text,
        "renewal_text": renewal_text,
        "terms_text": terms_text,
        "interval": "MONTH",
        "interval_count": 1,
        "auto_renew": True,
    }

    # Safe public integration metadata (never exposes secrets or webhooks)
    paypal_config = {
        "client_id": paypal_client_id,
        "env": (paypal_env or "sandbox").lower().strip(),
        "plan_id": active_plan_id,
    }

    return {
        "currency": currency_clean,
        "intro_price": formatted_intro,
        "regular_price": formatted_regular,
        "interval": "MONTH",
        "paypal_plan_id": active_plan_id,
        "disclosure": disclosure,
        "eligibility": eligibility,
        "paypal": paypal_config,
    }
