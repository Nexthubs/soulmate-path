"""Add failed_payments_count and billing_issue_detected_at to subscriptions (H-5)

Revision ID: 0003_add_failed_payments
Revises: 0002_add_indexes
Create Date: 2026-09-25 22:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_add_failed_payments"
down_revision: Union[str, None] = "0002_add_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "failed_payments_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "billing_issue_detected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "billing_issue_detected_at")
    op.drop_column("subscriptions", "failed_payments_count")
