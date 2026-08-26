"""Add provider snapshots, explicit episode progress, and list pinning.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column("metadata_field_sources", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "watch_entries",
        sa.Column(
            "episode_progress_explicit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        """
        UPDATE watch_entries
        SET episode_progress_explicit = 1
        WHERE id IN (SELECT DISTINCT entry_id FROM episode_viewings)
        """
    )
    op.add_column(
        "media_lists",
        sa.Column(
            "pinned_to_navigation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "catalog_metadata_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_item_id",
            sa.String(36),
            sa.ForeignKey("catalog_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_id", sa.String(200), nullable=False),
        sa.Column("normalized_data", sa.JSON(), nullable=False),
        sa.Column("external_ids", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "catalog_item_id", "provider", "provider_id", name="uq_catalog_metadata_source"
        ),
    )
    op.create_index(
        "ix_catalog_metadata_source_catalog",
        "catalog_metadata_sources",
        ["catalog_item_id", "provider"],
    )


def downgrade() -> None:
    op.drop_table("catalog_metadata_sources")
    op.drop_column("media_lists", "pinned_to_navigation")
    op.drop_column("watch_entries", "episode_progress_explicit")
    op.drop_column("catalog_items", "metadata_field_sources")
