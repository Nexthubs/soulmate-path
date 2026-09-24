"""Soulmate Subscription Offer and Checkout Domain Logic (DEV-SPEC §9.1–9.2, §15.6, §21–22)."""

from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Union


class ResubscriptionPolicy(str, Enum):
    """
    Policy governing returning subscriber promotional eligibility (Decision PAY-02).
    - BLOCKED: Returning subscribers cannot re-subscribe until product resolves the policy.
    - SINGLE_INTRO: Returning subscribers can re-subscribe but are routed to the standard monthly plan.
    - ALLOW_INTRO: Returning subscribers can purchase the introductory promotional rate again.
    """
    BLOCKED = "blocked"
    SINGLE_INTRO = "single_intro"
    ALLOW_INTRO = "allow_intro"


CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AUD": "AU$",
    "CAD": "CA$",
}


def get_currency_symbol(currency: Optional[str]) -> str:
    """Return currency display symbol, or code fallback with a space."""
    if not currency:
        return "$"
    clean = currency.upper().strip()
    return CURRENCY_SYMBOLS.get(clean, f"{clean} ")


def format_offer_price(price: Optional[Union[Decimal, float, str]], placeholder: str) -> str:
    """
    Format price decimal to 2 decimal places string (e.g. '19.00').
    If unset or None, return the designated placeholder per Decision PAY-01.
    """
    if price is None:
        return placeholder
    try:
        dec = Decimal(str(price).strip())
        return f"{dec:.2f}"
    except Exception:
        return placeholder


def evaluate_resubscription_eligibility(
    has_prior_subscription: bool,
    policy: str = "blocked",
) -> Dict[str, Any]:
    """
    Evaluates promotional price eligibility under Decision PAY-02.
    """
    policy_clean = policy.lower().strip()

    if not has_prior_subscription:
        return {
            "eligible_for_intro": True,
            "plan_class": "intro",
            "policy": policy_clean,
            "is_blocked": False,
            "reason": None,
        }

    # Returning subscriber handling per PAY-02
    if policy_clean == ResubscriptionPolicy.ALLOW_INTRO.value:
        return {
            "eligible_for_intro": True,
            "plan_class": "intro",
            "policy": policy_clean,
            "is_blocked": False,
            "reason": "Promotional intro price applied for returning subscriber.",
        }

    if policy_clean == ResubscriptionPolicy.SINGLE_INTRO.value:
        return {
            "eligible_for_intro": False,
            "plan_class": "standard",
            "policy": policy_clean,
            "is_blocked": False,
            "reason": "Returning subscriber standard pricing applied.",
        }

    # Default is BLOCKED
    return {
        "eligible_for_intro": False,
        "plan_class": "blocked",
        "policy": policy_clean,
        "is_blocked": True,
        "reason": "Returning subscriber intro pricing policy is blocked pending product resolution (PAY-02).",
    }


def build_subscription_offer(
    currency: str = "USD",
    intro_price: Optional[Union[Decimal, str]] = None,
    regular_price: Optional[Union[Decimal, str]] = None,
    intro_plan_id: Optional[str] = None,
    standard_plan_id: Optional[str] = None,
    paypal_client_id: Optional[str] = None,
    paypal_env: str = "sandbox",
    has_prior_subscription: bool = False,
    policy: str = "blocked",
) -> Dict[str, Any]:
    """
    Build display-ready offer response dict (DEV-SPEC §9.1, §15.6, §21–22, H-4 remediation).
    """
    currency_clean = (currency or "USD").upper().strip()
    symbol = get_currency_symbol(currency_clean)

    formatted_intro = format_offer_price(intro_price, "{INTRO_PRICE}")
    formatted_regular = format_offer_price(regular_price, "{REGULAR_PRICE}")

    eligibility = evaluate_resubscription_eligibility(
        has_prior_subscription=has_prior_subscription,
        policy=policy,
    )

    # Determine active plan ID and pricing disclosure based on eligibility and configuration
    if eligibility["plan_class"] == "standard":
        if standard_plan_id:
            active_plan_id = standard_plan_id
        else:
            # H-4 remediation: If standard plan is required but unconfigured, block rather than fallback
            eligibility["is_blocked"] = True
            eligibility["reason"] = (
                "Standard subscription plan is not configured. Re-subscription blocked pending configuration."
            )
            active_plan_id = None

        # H-4 remediation: Standard plan charges regular price today (not promotional intro price)
        today_text = f"Today: {symbol}{formatted_regular}"
        renewal_text = f"Then {symbol}{formatted_regular} / month"
    else:
        active_plan_id = intro_plan_id
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
