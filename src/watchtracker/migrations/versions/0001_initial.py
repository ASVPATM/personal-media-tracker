"""Initial catalog, entries, viewings, and audit tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_title", sa.String(500), nullable=False),
        sa.Column("original_title", sa.String(500)),
        sa.Column("normalized_title", sa.String(500), nullable=False),
        sa.Column("release_year", sa.Integer),
        sa.Column("release_date", sa.Date),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("provider_format", sa.String(50)),
        sa.Column("provider_source", sa.String(30)),
        sa.Column("provider_id", sa.String(80)),
        sa.Column("tmdb_movie_id", sa.String(80), unique=True),
        sa.Column("tmdb_tv_id", sa.String(80), unique=True),
        sa.Column("anilist_id", sa.String(80), unique=True),
        sa.Column("mal_id", sa.String(80), unique=True),
        sa.Column("poster_url", sa.Text),
        sa.Column("overview", sa.Text),
        sa.Column("provider_genres", sa.JSON, nullable=False),
        sa.Column("normalized_genres", sa.JSON, nullable=False),
        sa.Column("inferred_subgenres", sa.JSON, nullable=False),
        sa.Column("keywords", sa.JSON, nullable=False),
        sa.Column("country", sa.String(100)),
        sa.Column("language", sa.String(30)),
        sa.Column("runtime_minutes", sa.Integer),
        sa.Column("episode_count", sa.Integer),
        sa.Column("public_score", sa.Float),
        sa.Column("taste_evidence", sa.JSON, nullable=False),
        sa.Column("metadata_source", sa.String(50), nullable=False),
        sa.Column("metadata_provenance", sa.JSON, nullable=False),
        sa.Column("inference_version", sa.String(20), nullable=False),
        sa.Column("metadata_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("raw_provider_payload", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_source", "provider_id", name="uq_catalog_provider_id"),
    )
    op.create_index("ix_catalog_items_normalized_title", "catalog_items", ["normalized_title"])
    op.create_index(
        "ix_catalog_fallback",
        "catalog_items",
        ["normalized_title", "release_year", "media_type"],
    )
    op.create_index("ix_catalog_items_media_type", "catalog_items", ["media_type"])
    op.create_table(
        "watch_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_item_id",
            sa.String(36),
            sa.ForeignKey("catalog_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("personal_rating", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column("user_tags", sa.JSON, nullable=False),
        sa.Column("started_date", sa.Date),
        sa.Column("finished_date", sa.Date),
        sa.Column("watched_date", sa.Date),
        sa.Column("view_count", sa.Integer, nullable=False),
        sa.Column("genre_additions", sa.JSON, nullable=False),
        sa.Column("genre_removals", sa.JSON, nullable=False),
        sa.Column("subgenre_additions", sa.JSON, nullable=False),
        sa.Column("subgenre_removals", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("view_count >= 0", name="ck_entry_view_count"),
        sa.CheckConstraint(
            "personal_rating IS NULL OR (personal_rating >= 1 AND personal_rating <= 10)",
            name="ck_entry_rating_range",
        ),
    )
    op.create_index("ix_watch_entries_status", "watch_entries", ["status"])
    op.create_index("ix_watch_entries_created_at", "watch_entries", ["created_at"])
    op.create_index("ix_watch_entries_deleted_at", "watch_entries", ["deleted_at"])
    op.create_index("ix_entry_status_deleted", "watch_entries", ["status", "deleted_at"])
    op.create_table(
        "viewing_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("viewed_on", sa.Date),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_key", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_key", name="uq_viewing_source_key"),
    )
    op.create_index("ix_viewing_entry_date", "viewing_events", ["entry_id", "viewed_on"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("before_data", sa.JSON),
        sa.Column("after_data", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_entity_time", "audit_events", ["entity_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("viewing_events")
    op.drop_table("watch_entries")
    op.drop_table("catalog_items")
