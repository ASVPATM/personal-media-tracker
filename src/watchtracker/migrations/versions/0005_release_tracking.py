"""Add normalized series, episode, release, and scheduler records.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "series_tracking_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_new_episode", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_new_season", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("include_specials", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("region", sa.String(10)),
        sa.Column("provider_preference", sa.String(30)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_message", sa.String(300)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_cursor", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("failure_count >= 0", name="ck_series_tracking_failure_count"),
    )
    op.create_index(
        "ix_series_tracking_due",
        "series_tracking_subscriptions",
        ["enabled", "next_check_at"],
    )

    op.create_table(
        "season_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_source", sa.String(30), nullable=False),
        sa.Column("provider_series_id", sa.String(80), nullable=False),
        sa.Column("provider_season_id", sa.String(80)),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("overview", sa.Text()),
        sa.Column("poster_url", sa.Text()),
        sa.Column("air_date", sa.Date()),
        sa.Column("episode_count", sa.Integer()),
        sa.Column("provider_status", sa.String(50)),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider_source",
            "provider_series_id",
            "season_number",
            name="uq_season_provider_number",
        ),
    )
    op.create_index("ix_season_entry_number", "season_records", ["entry_id", "season_number"])

    op.create_table(
        "episode_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "season_id",
            sa.String(36),
            sa.ForeignKey("season_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_source", sa.String(30), nullable=False),
        sa.Column("provider_episode_id", sa.String(80), nullable=False),
        sa.Column("episode_number", sa.Integer()),
        sa.Column("title", sa.String(500)),
        sa.Column("overview", sa.Text()),
        sa.Column("air_date", sa.Date()),
        sa.Column("runtime_minutes", sa.Integer()),
        sa.Column("production_code", sa.String(100)),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider_source", "provider_episode_id", name="uq_episode_provider_id"
        ),
    )
    op.create_index(
        "ix_episode_season_number", "episode_records", ["season_id", "episode_number"]
    )
    op.create_index("ix_episode_air_date", "episode_records", ["air_date", "removed_at"])

    op.create_table(
        "episode_viewings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "episode_id",
            sa.String(36),
            sa.ForeignKey("episode_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("watched_on", sa.Date()),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("source_key", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_key", name="uq_episode_viewing_source_key"),
    )
    op.create_index("ix_episode_viewing_entry", "episode_viewings", ["entry_id", "episode_id"])

    op.create_table(
        "release_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "season_id",
            sa.String(36),
            sa.ForeignKey("season_records.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "episode_id",
            sa.String(36),
            sa.ForeignKey("episode_records.id", ondelete="SET NULL"),
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("effective_date", sa.Date()),
        sa.Column("dedupe_key", sa.String(240), nullable=False, unique=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "event_type IN ('episode_announced', 'episode_released', 'season_announced', 'schedule_changed')",
            name="ck_release_event_type",
        ),
    )
    op.create_index(
        "ix_release_event_unread",
        "release_events",
        ["read_at", "dismissed_at", "first_seen_at"],
    )
    op.create_index("ix_release_event_effective", "release_events", ["effective_date"])

    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("state", sa.String(30), nullable=False, server_default="idle"),
        sa.Column("owner_id", sa.String(80)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_message", sa.String(300)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("failure_count >= 0", name="ck_sync_job_failure_count"),
    )


def downgrade() -> None:
    op.drop_table("sync_jobs")
    op.drop_index("ix_release_event_effective", table_name="release_events")
    op.drop_index("ix_release_event_unread", table_name="release_events")
    op.drop_table("release_events")
    op.drop_index("ix_episode_viewing_entry", table_name="episode_viewings")
    op.drop_table("episode_viewings")
    op.drop_index("ix_episode_air_date", table_name="episode_records")
    op.drop_index("ix_episode_season_number", table_name="episode_records")
    op.drop_table("episode_records")
    op.drop_index("ix_season_entry_number", table_name="season_records")
    op.drop_table("season_records")
    op.drop_index("ix_series_tracking_due", table_name="series_tracking_subscriptions")
    op.drop_table("series_tracking_subscriptions")
