"""Persist provider state/billing ordering checkpoints (RV-01/RV-02).

Revision ID: 0004_payment_event_order
Revises: 0003_add_failed_payments
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_payment_event_order"
down_revision = "0003_add_failed_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("provider_status_updated_at", sa.DateTime(timezone=True)))
    op.add_column("subscriptions", sa.Column("billing_updated_at", sa.DateTime(timezone=True)))
    # Only reuse actual persisted event times; never invent an ordering timestamp.
    op.execute("""UPDATE subscriptions SET provider_status_updated_at =
        greatest(cancelled_at, expired_at, suspended_at),
        billing_updated_at = billing_issue_detected_at""")


def downgrade() -> None:
    op.drop_column("subscriptions", "billing_updated_at")
    op.drop_column("subscriptions", "provider_status_updated_at")
