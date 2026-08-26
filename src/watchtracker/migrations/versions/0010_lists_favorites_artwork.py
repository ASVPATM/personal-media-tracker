"""Add simple lists, favorites, and persistent poster overrides.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_items", sa.Column("poster_override_url", sa.Text(), nullable=True))
    op.add_column(
        "watch_entries",
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "media_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
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
    op.create_index("ix_media_list_item_list", "media_list_items", ["list_id", "added_at"])


def downgrade() -> None:
    op.drop_table("media_list_items")
    op.drop_table("media_lists")
    op.drop_column("watch_entries", "is_favorite")
    op.drop_column("catalog_items", "poster_override_url")
