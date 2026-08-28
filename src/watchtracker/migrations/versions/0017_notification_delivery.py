"""Add notification rules, protected endpoints, and a delivery outbox.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_notifications", sa.Column("source_kind", sa.String(30)))
    op.add_column("user_notifications", sa.Column("source_key", sa.String(160)))
    op.create_index(
        "uq_user_notification_source",
        "user_notifications",
        ["user_id", "source_kind", "source_key"],
        unique=True,
    )
    op.create_table(
        "notification_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("adapter", sa.String(30), nullable=False),
        sa.Column("secret_reference", sa.String(160), nullable=False, unique=True),
        sa.Column("redacted_hint", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_test_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_code", sa.String(80)),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "adapter IN ('apprise', 'apprise_api')",
            name="ck_notification_endpoint_adapter",
        ),
        sa.CheckConstraint("version >= 1", name="ck_notification_endpoint_version"),
    )
    op.create_index(
        "ix_notification_endpoint_user", "notification_endpoints", ["user_id", "enabled"]
    )

    op.create_table(
        "notification_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_pattern", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("lead_time_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quiet_start", sa.String(5)),
        sa.Column("quiet_end", sa.String(5)),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column(
            "endpoint_id",
            sa.String(36),
            sa.ForeignKey("notification_endpoints.id", ondelete="CASCADE"),
        ),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("external_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lead_time_hours >= 0", name="ck_notification_rule_lead_time"),
        sa.CheckConstraint("version >= 1", name="ck_notification_rule_version"),
        sa.UniqueConstraint(
            "user_id",
            "event_pattern",
            "endpoint_id",
            "lead_time_hours",
            name="uq_notification_rule_route",
        ),
    )
    op.create_index("ix_notification_rule_user", "notification_rules", ["user_id", "enabled"])

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            sa.String(36),
            sa.ForeignKey("notification_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("safe_message", sa.String(500), nullable=False),
        sa.Column("resource_type", sa.String(40)),
        sa.Column("resource_id", sa.String(80)),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'leased', 'retry', 'delivered', 'failed', 'cancelled')",
            name="ck_notification_outbox_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_notification_outbox_attempts"),
    )
    op.create_index("ix_notification_outbox_due", "notification_outbox", ["state", "due_at"])
    op.create_index(
        "ix_notification_outbox_user", "notification_outbox", ["user_id", "created_at"]
    )

    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "outbox_id",
            sa.String(36),
            sa.ForeignKey("notification_outbox.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("result_category", sa.String(30), nullable=False),
        sa.Column("receipt_hash", sa.String(64)),
        sa.Column("safe_error_code", sa.String(80)),
        sa.Column("safe_error_message", sa.String(300)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_number >= 1", name="ck_notification_attempt_number"),
        sa.UniqueConstraint("outbox_id", "attempt_number", name="uq_notification_attempt"),
    )
    op.create_index(
        "ix_notification_attempt_outbox",
        "notification_delivery_attempts",
        ["outbox_id", "started_at"],
    )


def downgrade() -> None:
    leased = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM notification_outbox WHERE state = 'leased'")
    )
    if int(leased or 0):
        raise RuntimeError("Wait for active notification deliveries before downgrading.")
    op.drop_index("ix_notification_attempt_outbox", table_name="notification_delivery_attempts")
    op.drop_table("notification_delivery_attempts")
    op.drop_index("ix_notification_outbox_user", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_notification_rule_user", table_name="notification_rules")
    op.drop_table("notification_rules")
    op.drop_index("ix_notification_endpoint_user", table_name="notification_endpoints")
    op.drop_table("notification_endpoints")
    op.drop_index("uq_user_notification_source", table_name="user_notifications")
    op.drop_column("user_notifications", "source_key")
    op.drop_column("user_notifications", "source_kind")
