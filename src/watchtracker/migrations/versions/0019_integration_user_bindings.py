"""Add explicit remote-media-server to PMT user bindings.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_user_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("remote_user_id", sa.String(200), nullable=False),
        sa.Column("remote_user_label", sa.String(120)),
        sa.Column(
            "pmt_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "remote_user_id", name="uq_binding_remote_user"),
        sa.UniqueConstraint("connection_id", "pmt_user_id", name="uq_binding_pmt_user"),
    )
    op.create_index(
        "ix_integration_binding_user",
        "integration_user_bindings",
        ["pmt_user_id", "connection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_integration_binding_user", table_name="integration_user_bindings")
    op.drop_table("integration_user_bindings")
