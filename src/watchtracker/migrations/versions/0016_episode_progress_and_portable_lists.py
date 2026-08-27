"""Add compact episode progress and portable shared-list provenance.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_items", sa.Column("released_episode_count", sa.Integer()))
    op.execute(
        """
        UPDATE catalog_items
        SET released_episode_count = (
            SELECT COUNT(*)
            FROM episode_records
            JOIN season_records ON season_records.id = episode_records.season_id
            WHERE season_records.catalog_item_id = catalog_items.id
              AND season_records.removed_at IS NULL
              AND episode_records.removed_at IS NULL
              AND episode_records.air_date IS NOT NULL
              AND episode_records.air_date <= CURRENT_DATE
        )
        WHERE EXISTS (
            SELECT 1
            FROM episode_records
            JOIN season_records ON season_records.id = episode_records.season_id
            WHERE season_records.catalog_item_id = catalog_items.id
        )
        """
    )
    op.add_column("watch_entries", sa.Column("episode_progress_count", sa.Integer()))
    op.execute(
        """
        UPDATE watch_entries
        SET episode_progress_count = (
            SELECT COUNT(*)
            FROM episode_viewings
            WHERE episode_viewings.entry_id = watch_entries.id
        )
        WHERE episode_progress_explicit = TRUE
        """
    )
    op.add_column(
        "media_lists",
        sa.Column("source_kind", sa.String(20), nullable=False, server_default="owned"),
    )
    op.add_column("media_lists", sa.Column("source_label", sa.String(160)))
    op.add_column("media_lists", sa.Column("source_fingerprint", sa.String(64)))
    op.create_index("ix_media_lists_source_fingerprint", "media_lists", ["source_fingerprint"])


def downgrade() -> None:
    portable_count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM media_lists WHERE source_kind != 'owned'")
    )
    if int(portable_count or 0):
        raise RuntimeError("Remove imported portable lists before downgrading.")
    op.drop_index("ix_media_lists_source_fingerprint", table_name="media_lists")
    op.drop_column("media_lists", "source_fingerprint")
    op.drop_column("media_lists", "source_label")
    op.drop_column("media_lists", "source_kind")
    op.drop_column("watch_entries", "episode_progress_count")
    op.drop_column("catalog_items", "released_episode_count")
