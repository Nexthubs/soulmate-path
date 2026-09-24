"""
Subscription Offer Service (DEV-SPEC §9.1–9.2, §15.6, §21–22, Decisions: PAY-01, PAY-02).
Retrieves current offer, checks historical subscriptions, and applies eligibility policy.
"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings, settings
from app.db.models.billing import Subscription
from app.db.models.session import SoulmateSession
from app.soulmate.domain.offer import build_subscription_offer
from app.soulmate.schema import SubscriptionOfferResponse


class OfferService:
    """Service for calculating and delivering subscription checkout offers and eligibility."""

    @staticmethod
    async def check_prior_subscription(db: AsyncSession, session: Optional[SoulmateSession]) -> bool:
        """
        Check if the session, user, or associated email has a recorded prior subscription.
        Used to determine eligibility under Decision PAY-02.
        """
        if not session:
            return False

        # 1. Direct subscription on this specific session
        sub_by_session_res = await db.execute(
            select(Subscription).where(Subscription.session_id == session.id)
        )
        if sub_by_session_res.scalars().first():
            return True

        # 2. Direct subscription tied to the session's user_id
        if session.user_id:
            sub_by_user_res = await db.execute(
                select(Subscription).where(Subscription.user_id == session.user_id)
            )
            if sub_by_user_res.scalars().first():
                return True

        # 3. Direct subscription tied to the session's email
        target_email = session.email_normalized or session.email
        if target_email:
            prior_session_sub_res = await db.execute(
                select(Subscription)
                .join(SoulmateSession, Subscription.session_id == SoulmateSession.id)
                .where(
                    (SoulmateSession.email == target_email)
                    | (SoulmateSession.email_normalized == target_email)
                )
            )
            if prior_session_sub_res.scalars().first():
                return True

        return False

    @classmethod
    async def get_subscription_offer(
        cls,
        db: AsyncSession,
        session: Optional[SoulmateSession] = None,
        custom_settings: Optional[Settings] = None,
    ) -> SubscriptionOfferResponse:
        """
        Build dynamic SubscriptionOfferResponse respecting PAY-01 pricing placeholders
        and PAY-02 re-subscription policy.
        """
        active_settings = custom_settings or settings
        has_prior = await cls.check_prior_subscription(db, session)

        offer_dict = build_subscription_offer(
            currency=active_settings.soulmate_currency,
            intro_price=active_settings.soulmate_intro_price,
            regular_price=active_settings.soulmate_regular_price,
            intro_plan_id=active_settings.paypal_soulmate_intro_plan_id,
            standard_plan_id=active_settings.paypal_soulmate_standard_plan_id,
            paypal_client_id=active_settings.paypal_client_id,
            paypal_env=active_settings.paypal_env,
            has_prior_subscription=has_prior,
            policy=active_settings.soulmate_resubscription_policy,
        )

        return SubscriptionOfferResponse(**offer_dict)
