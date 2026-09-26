"""Normalize legacy post-payment session status to the canonical enum (RV-01/RV-02 M7).

Revision ID: 0005_legacy_session_status
Revises: 0004_payment_event_order
"""
from alembic import op


revision = "0005_legacy_session_status"
down_revision = "0004_payment_event_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DEV-SPEC §6.2: post-payment state is SUBSCRIBED. Rows written by the
    # pre-M7 writer used the ad-hoc lowercase value "paid".
    op.execute("""UPDATE soulmate_sessions SET status = 'SUBSCRIBED'
        WHERE status = 'paid'""")


def downgrade() -> None:
    # Restore the legacy value only for rows the canonical enum would not accept;
    # the canonical value itself is kept because writers now emit it.
    op.execute("""UPDATE soulmate_sessions SET status = 'paid'
        WHERE status = 'SUBSCRIBED'""")
