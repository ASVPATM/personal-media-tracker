"""Add reusable provider-account OAuth lifecycle records.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_slug", sa.String(60), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("verifier_reference", sa.String(160), nullable=False, unique=True),
        sa.Column("redirect_uri", sa.String(800), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_integration_oauth_state_expiry",
        "integration_oauth_states",
        ["expires_at", "used_at"],
    )
    op.create_table(
        "integration_oauth_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("token_type", sa.String(30), nullable=False, server_default="Bearer"),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remote_subject", sa.String(200)),
        sa.Column("reconnect_reason", sa.String(160)),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("integration_oauth_grants")
    op.drop_index("ix_integration_oauth_state_expiry", table_name="integration_oauth_states")
    op.drop_table("integration_oauth_states")
