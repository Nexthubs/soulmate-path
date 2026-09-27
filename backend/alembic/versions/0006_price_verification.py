"""Add provider price verification provenance to subscriptions (SP-803/804 RV remediation).

Revision ID: 0006_price_verification
Revises: 0005_legacy_session_status
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_price_verification"
down_revision = "0005_legacy_session_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # High-risk audit remediation (Wave 8): displayed/quoted renewal prices must
    # be traceable to a verified PayPal plan snapshot, not just local config.
    op.add_column(
        "subscriptions",
        sa.Column("price_verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "price_verified_at")
