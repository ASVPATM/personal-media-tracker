"""Add multi-user sessions, invitations, server identity, and sync versions.

Revision ID: 0014
Revises: 0013
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("owner_sessions", "legacy_owner_sessions")
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_kind", sa.String(20), nullable=False),
        sa.Column("device_id", sa.String(80)),
        sa.Column("device_label", sa.String(120)),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64)),
        sa.Column("refresh_token_hash", sa.String(64), unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "session_kind IN ('browser', 'native')", name="ck_user_session_kind"
        ),
    )
    op.create_index("ix_user_session_expiry", "user_sessions", ["expires_at"])
    op.create_index("ix_user_session_user", "user_sessions", ["user_id", "created_at"])
    op.execute(
        """
        INSERT INTO user_sessions
            (id, user_id, session_kind, token_hash, csrf_hash, scopes, created_at,
             last_seen_at, expires_at, revoked_at)
        SELECT id, owner_id, 'browser', token_hash, csrf_hash, '[]', created_at,
               last_seen_at, expires_at, revoked_at
        FROM legacy_owner_sessions
        """
    )
    op.drop_table("legacy_owner_sessions")

    op.create_table(
        "account_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recovery_for_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(320)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('signup', 'recovery')", name="ck_invitation_kind"),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_invitation_role"),
    )
    op.create_index(
        "ix_invitation_expiry",
        "account_invitations",
        ["expires_at", "consumed_at", "revoked_at"],
    )

    op.create_table(
        "server_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40)),
        sa.Column("target_id", sa.String(80)),
        sa.Column("safe_summary", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_server_audit_created", "server_audit_events", ["created_at"])

    op.create_table(
        "server_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False, unique=True),
        sa.Column("api_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO server_state (id, instance_id, api_version, created_at) "
            "VALUES (1, :instance_id, '1', CURRENT_TIMESTAMP)"
        ).bindparams(instance_id=str(uuid4()))
    )

    op.create_table(
        "sync_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(80), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "request_id", name="uq_sync_request_user_request"),
    )
    op.create_index("ix_sync_request_user_created", "sync_requests", ["user_id", "created_at"])

    op.add_column(
        "watch_entries",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "media_lists",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("media_lists", "version")
    op.drop_column("watch_entries", "version")
    op.drop_index("ix_sync_request_user_created", table_name="sync_requests")
    op.drop_table("sync_requests")
    op.drop_table("server_state")
    op.drop_index("ix_server_audit_created", table_name="server_audit_events")
    op.drop_table("server_audit_events")
    op.drop_index("ix_invitation_expiry", table_name="account_invitations")
    op.drop_table("account_invitations")

    op.create_table(
        "owner_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(36),
            sa.ForeignKey("owner_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_owner_session_expiry", "owner_sessions", ["expires_at"])
    op.create_index("ix_owner_session_owner", "owner_sessions", ["owner_id", "created_at"])
    op.execute(
        """
        INSERT INTO owner_sessions
            (id, owner_id, token_hash, csrf_hash, created_at, last_seen_at,
             expires_at, revoked_at)
        SELECT s.id, s.user_id, s.token_hash, s.csrf_hash, s.created_at,
               s.last_seen_at, s.expires_at, s.revoked_at
        FROM user_sessions AS s
        JOIN owner_accounts AS o ON o.id = s.user_id
        WHERE s.session_kind = 'browser' AND s.csrf_hash IS NOT NULL
        """
    )
    op.drop_index("ix_user_session_user", table_name="user_sessions")
    op.drop_index("ix_user_session_expiry", table_name="user_sessions")
    op.drop_table("user_sessions")
