"""Initial Soulmate Schema (DEV-SPEC §14)

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-23 11:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. soulmate_quiz_versions
    op.create_table(
        "soulmate_quiz_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(64), unique=True, nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # 2. soulmate_sessions
    op.create_table(
        "soulmate_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_id", sa.String(64), unique=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("email_normalized", sa.String(320), nullable=True),
        sa.Column("quiz_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_step", sa.String(64), nullable=False),
        sa.Column("utm_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("quiz_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_soulmate_sessions_email",
        "soulmate_sessions",
        ["email_normalized"],
        unique=False,
    )
    op.create_index(
        "idx_soulmate_sessions_user_id",
        "soulmate_sessions",
        ["user_id"],
        unique=False,
    )

    # 3. soulmate_answers
    op.create_table(
        "soulmate_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soulmate_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_code", sa.String(32), nullable=False),
        sa.Column("answer_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("session_id", "question_code", name="uq_soulmate_answers_session_question"),
    )

    # 4. soulmate_profiles
    op.create_table(
        "soulmate_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soulmate_sessions.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("profile_version", sa.String(32), server_default="v1", nullable=False),
        sa.Column("user_gender", sa.String(32), nullable=True),
        sa.Column("preferred_partner_gender", sa.String(32), nullable=True),
        sa.Column("love_life_status", sa.String(64), nullable=True),
        sa.Column("preferred_partner_age_range", sa.String(64), nullable=True),
        sa.Column("preferred_partner_ethnicity", sa.String(128), nullable=True),
        sa.Column("key_soulmate_quality", sa.String(64), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("zodiac_sign", sa.String(32), nullable=True),
        sa.Column("element", sa.String(32), nullable=True),
        sa.Column("decision_style", sa.String(32), nullable=True),
        sa.Column("personal_challenge", sa.String(64), nullable=True),
        sa.Column("red_flag", sa.String(64), nullable=True),
        sa.Column("similarity_preference", sa.String(64), nullable=True),
        sa.Column("relationship_dynamic", sa.String(64), nullable=True),
        sa.Column("love_language", sa.String(64), nullable=True),
        sa.Column("connection_style", sa.String(64), nullable=True),
        sa.Column("relationship_fear", sa.String(64), nullable=True),
        sa.Column("life_goals", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("spiritual_person", sa.Boolean(), nullable=True),
        sa.Column("familiar_psychic_artistry", sa.Boolean(), nullable=True),
        sa.Column("warning_response", sa.String(8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # 5. subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soulmate_sessions.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(32), server_default="paypal", nullable=False),
        sa.Column("provider_subscription_id", sa.String(128), unique=True, nullable=False),
        sa.Column("provider_plan_id", sa.String(128), nullable=False),
        sa.Column("provider_status", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("intro_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("regular_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("first_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_billing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_through_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "idx_subscriptions_session_id",
        "subscriptions",
        ["session_id"],
        unique=False,
    )

    # 6. subscription_payments
    op.create_table(
        "subscription_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("provider_payment_id", sa.String(128), unique=True, nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=True),
        sa.Column("cycle_no", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "idx_subscription_payments_subscription_id",
        "subscription_payments",
        ["subscription_id"],
        unique=False,
    )

    # 7. paypal_webhook_events
    op.create_table(
        "paypal_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("paypal_event_id", sa.String(128), unique=True, nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # 8. soulmate_artifacts
    op.create_table(
        "soulmate_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soulmate_sessions.id"), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("artifact_version", sa.String(32), server_default="v1", nullable=False),
        sa.Column("unlock_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_status", sa.String(32), server_default="NOT_STARTED", nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("provider_request_id", sa.String(256), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(128), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("session_id", "artifact_type", "artifact_version", name="uq_soulmate_artifacts_session_type_version"),
    )
    # High-Risk Invariant ASSET-01: Exactly one sketch per normalized email
    op.create_index(
        "uq_soulmate_one_sketch_per_email",
        "soulmate_artifacts",
        ["email_normalized"],
        unique=True,
        postgresql_where=sa.text("artifact_type = 'SKETCH'"),
    )

    # 9. ai_generation_jobs
    op.create_table(
        "ai_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soulmate_artifacts.id"), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(256), unique=True, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "idx_ai_generation_jobs_artifact_id",
        "ai_generation_jobs",
        ["artifact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ai_generation_jobs_artifact_id", table_name="ai_generation_jobs", if_exists=True)
    op.drop_table("ai_generation_jobs")
    op.drop_index("uq_soulmate_one_sketch_per_email", table_name="soulmate_artifacts", if_exists=True)
    op.drop_table("soulmate_artifacts")
    op.drop_table("paypal_webhook_events")
    op.drop_index("idx_subscription_payments_subscription_id", table_name="subscription_payments", if_exists=True)
    op.drop_table("subscription_payments")
    op.drop_index("idx_subscriptions_session_id", table_name="subscriptions", if_exists=True)
    op.drop_table("subscriptions")
    op.drop_table("soulmate_profiles")
    op.drop_table("soulmate_answers")
    op.drop_index("idx_soulmate_sessions_user_id", table_name="soulmate_sessions", if_exists=True)
    op.drop_index("idx_soulmate_sessions_email", table_name="soulmate_sessions", if_exists=True)
    op.drop_table("soulmate_sessions")
    op.drop_table("soulmate_quiz_versions")
