"""Add catalog-based shared lists, collaboration inbox, and durable jobs.

Revision ID: 0015
Revises: 0014
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_lists",
        sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
    )

    op.rename_table("media_list_items", "legacy_media_list_items")
    op.create_table(
        "media_list_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "list_id",
            sa.String(36),
            sa.ForeignKey("media_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "catalog_item_id",
            sa.String(36),
            sa.ForeignKey("catalog_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_by_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shared_note", sa.String(500)),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("list_id", "catalog_item_id", name="uq_media_list_catalog"),
    )
    op.execute(
        """
        INSERT INTO media_list_items
            (id, list_id, catalog_item_id, added_by_user_id, position, shared_note, added_at)
        SELECT old.id, old.list_id, entry.catalog_item_id, lists.user_id, 0, NULL, old.added_at
        FROM legacy_media_list_items AS old
        JOIN watch_entries AS entry ON entry.id = old.entry_id
        JOIN media_lists AS lists ON lists.id = old.list_id
        """
    )
    op.drop_table("legacy_media_list_items")
    op.create_index(
        "ix_media_list_item_list",
        "media_list_items",
        ["list_id", "position", "added_at"],
    )

    op.create_table(
        "media_list_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "list_id",
            sa.String(36),
            sa.ForeignKey("media_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "invited_by_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_list_member_role"),
        sa.UniqueConstraint("list_id", "user_id", name="uq_list_membership_user"),
    )
    op.create_index(
        "ix_list_membership_user", "media_list_memberships", ["user_id", "accepted_at"]
    )

    connection = op.get_bind()
    lists = connection.execute(
        sa.text("SELECT id, user_id, created_at FROM media_lists")
    ).mappings()
    membership_table = sa.table(
        "media_list_memberships",
        sa.column("id"),
        sa.column("list_id"),
        sa.column("user_id"),
        sa.column("role"),
        sa.column("invited_by_user_id"),
        sa.column("accepted_at"),
        sa.column("created_at"),
    )
    rows = [
        {
            "id": str(uuid4()),
            "list_id": row["id"],
            "user_id": row["user_id"],
            "role": "owner",
            "invited_by_user_id": row["user_id"],
            "accepted_at": row["created_at"],
            "created_at": row["created_at"],
        }
        for row in lists
    ]
    if rows:
        op.bulk_insert(membership_table, rows)

    op.create_table(
        "media_list_activity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "list_id",
            sa.String(36),
            sa.ForeignKey("media_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("safe_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_list_activity_list_created", "media_list_activity", ["list_id", "created_at"]
    )

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("safe_message", sa.String(300), nullable=False),
        sa.Column("resource_type", sa.String(40)),
        sa.Column("resource_id", sa.String(80)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_notification_inbox",
        "user_notifications",
        ["user_id", "read_at", "created_at"],
    )

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
        ),
        sa.Column("scope_type", sa.String(40)),
        sa.Column("scope_id", sa.String(80)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_message", sa.String(300)),
        sa.Column("paused_notified_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('scheduled', 'running', 'retry', 'paused', 'completed', 'cancelled')",
            name="ck_scheduled_job_state",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_scheduled_job_attempts"),
        sa.UniqueConstraint("idempotency_key", name="uq_scheduled_job_idempotency"),
    )
    op.create_index("ix_scheduled_job_due", "scheduled_jobs", ["state", "due_at"])
    op.create_index("ix_scheduled_job_owner", "scheduled_jobs", ["user_id", "created_at"])


def downgrade() -> None:
    connection = op.get_bind()
    shared_members = connection.scalar(
        sa.text("SELECT COUNT(*) FROM media_list_memberships WHERE role != 'owner'")
    )
    unowned_items = connection.scalar(
        sa.text(
            """
            SELECT COUNT(*) FROM media_list_items AS item
            JOIN media_lists AS lists ON lists.id = item.list_id
            LEFT JOIN watch_entries AS entry
              ON entry.user_id = lists.user_id
             AND entry.catalog_item_id = item.catalog_item_id
            WHERE entry.id IS NULL
            """
        )
    )
    if shared_members or unowned_items:
        raise RuntimeError(
            "Remove shared-list memberships and owner-untracked items before downgrading."
        )

    op.drop_index("ix_scheduled_job_owner", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_job_due", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
    op.drop_index("ix_user_notification_inbox", table_name="user_notifications")
    op.drop_table("user_notifications")
    op.drop_index("ix_list_activity_list_created", table_name="media_list_activity")
    op.drop_table("media_list_activity")
    op.drop_index("ix_list_membership_user", table_name="media_list_memberships")
    op.drop_table("media_list_memberships")

    op.rename_table("media_list_items", "shared_media_list_items")
    op.create_table(
        "media_list_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "list_id",
            sa.String(36),
            sa.ForeignKey("media_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("list_id", "entry_id", name="uq_media_list_entry"),
    )
    op.execute(
        """
        INSERT INTO media_list_items (id, list_id, entry_id, added_at)
        SELECT item.id, item.list_id, entry.id, item.added_at
        FROM shared_media_list_items AS item
        JOIN media_lists AS lists ON lists.id = item.list_id
        JOIN watch_entries AS entry
          ON entry.user_id = lists.user_id
         AND entry.catalog_item_id = item.catalog_item_id
        """
    )
    op.drop_table("shared_media_list_items")
    op.create_index("ix_media_list_item_list", "media_list_items", ["list_id", "added_at"])
    op.drop_column("media_lists", "visibility")
