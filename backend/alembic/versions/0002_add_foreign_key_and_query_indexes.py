"""Add foreign key and query lookup indexes (SP-002 review fix)

Revision ID: 0002_add_indexes
Revises: 0001_initial
Create Date: 2026-09-23 16:05:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002_add_indexes"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. soulmate_sessions: index on user_id for user account lookups
    op.create_index(
        "idx_soulmate_sessions_user_id",
        "soulmate_sessions",
        ["user_id"],
        unique=False,
    )

    # 2. subscriptions: index on session_id for session entitlement lookups
    op.create_index(
        "idx_subscriptions_session_id",
        "subscriptions",
        ["session_id"],
        unique=False,
    )

    # 3. subscription_payments: index on subscription_id for billing history queries
    op.create_index(
        "idx_subscription_payments_subscription_id",
        "subscription_payments",
        ["subscription_id"],
        unique=False,
    )

    # 4. ai_generation_jobs: index on artifact_id for job polling and dispatch
    op.create_index(
        "idx_ai_generation_jobs_artifact_id",
        "ai_generation_jobs",
        ["artifact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ai_generation_jobs_artifact_id", table_name="ai_generation_jobs")
    op.drop_index("idx_subscription_payments_subscription_id", table_name="subscription_payments")
    op.drop_index("idx_subscriptions_session_id", table_name="subscriptions")
    op.drop_index("idx_soulmate_sessions_user_id", table_name="soulmate_sessions")
