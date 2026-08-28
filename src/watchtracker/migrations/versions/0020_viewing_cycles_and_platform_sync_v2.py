"""Add authoritative viewing cycles and platform-sync v2 import ledger.

Revision ID: 0020
Revises: 0019b

The migration is deliberately additive. Existing scalar projections and legacy event
rows remain intact, so downgrade removes only the compatibility layer and never has to
guess at a user's old counters.
"""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019b"
branch_labels = None
depends_on = None


def _stable_id(material: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"pmt:viewing-migration:{material}"))


def upgrade() -> None:
    op.create_table(
        "viewing_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("scope", sa.String(30), nullable=False, server_default="title"),
        sa.Column("scope_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "target_episode_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("initiated_by", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("origin_device_id", sa.String(100)),
        sa.Column("origin_event_id", sa.String(200)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.CheckConstraint("kind IN ('initial', 'rewatch')", name="ck_viewing_cycle_kind"),
        sa.CheckConstraint(
            "scope IN ('title', 'season', 'episode_range')", name="ck_viewing_cycle_scope"
        ),
        sa.CheckConstraint(
            "state IN ('active', 'closed', 'completed', 'abandoned')",
            name="ck_viewing_cycle_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["watch_entries.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_viewing_cycle_entry_state",
        "viewing_cycles",
        ["entry_id", "state", "deleted_at"],
    )
    op.create_index(
        "ix_viewing_cycle_user_modified", "viewing_cycles", ["user_id", "updated_at"]
    )
    op.create_index("ix_viewing_cycles_deleted_at", "viewing_cycles", ["deleted_at"])
    op.create_index("ix_viewing_cycles_user_id", "viewing_cycles", ["user_id"])

    _add_occurrence_columns("viewing_events")
    _add_occurrence_columns("episode_viewings")
    op.add_column("media_lists", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("media_lists", sa.Column("origin_device_id", sa.String(100)))
    op.add_column("media_lists", sa.Column("origin_event_id", sa.String(200)))
    op.add_column(
        "media_lists",
        sa.Column("field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_media_lists_deleted_at", "media_lists", ["deleted_at"])
    op.add_column(
        "media_list_items",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column("media_list_items", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("media_list_items", sa.Column("origin_device_id", sa.String(100)))
    op.add_column("media_list_items", sa.Column("origin_event_id", sa.String(200)))
    op.add_column(
        "media_list_items",
        sa.Column("field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_media_list_items_deleted_at", "media_list_items", ["deleted_at"])
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE media_list_items SET updated_at = added_at"))
    # SQLite cannot add a column with CURRENT_TIMESTAMP as a non-constant
    # default. Add it nullable, backfill from the row's original timestamp,
    # then rebuild only to enforce the invariant. Alembic's batch copy keeps
    # every legacy list item and avoids synthesizing a misleading timestamp.
    with op.batch_alter_table("media_list_items") as batch:
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    op.create_table(
        "playback_bookmarks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("episode_id", sa.String(36)),
        sa.Column("position_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("origin_device_id", sa.String(100)),
        sa.Column("origin_event_id", sa.String(200)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["watch_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_id"], ["episode_records.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "source", "source_key", name="uq_bookmark_source_key"),
    )
    op.create_index(
        "ix_bookmark_entry_modified", "playback_bookmarks", ["entry_id", "updated_at"]
    )
    op.create_index("ix_playback_bookmarks_deleted_at", "playback_bookmarks", ["deleted_at"])
    op.create_index("ix_playback_bookmarks_user_id", "playback_bookmarks", ["user_id"])

    op.create_table(
        "provider_progress_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("claim", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("accepted_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("origin_device_id", sa.String(100)),
        sa.Column("origin_event_id", sa.String(200)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["watch_entries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "provider", "source_key", name="uq_progress_claim_key"),
    )
    op.create_index(
        "ix_progress_claim_entry_observed",
        "provider_progress_claims",
        ["entry_id", "observed_at"],
    )
    op.create_index(
        "ix_provider_progress_claims_deleted_at", "provider_progress_claims", ["deleted_at"]
    )
    op.create_index(
        "ix_provider_progress_claims_user_id", "provider_progress_claims", ["user_id"]
    )

    op.create_table(
        "viewing_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(36)),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("before_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reason", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("origin_device_id", sa.String(100)),
        sa.Column("origin_event_id", sa.String(200)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["watch_entries.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_viewing_correction_entry", "viewing_corrections", ["entry_id", "created_at"]
    )
    op.create_index("ix_viewing_corrections_deleted_at", "viewing_corrections", ["deleted_at"])
    op.create_index("ix_viewing_corrections_user_id", "viewing_corrections", ["user_id"])

    op.create_table(
        "platform_sync_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("source_product", sa.String(80), nullable=False),
        sa.Column("source_version", sa.String(40)),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "snapshot_hash", name="uq_platform_import_snapshot"),
    )
    op.create_index(
        "ix_platform_import_user_created",
        "platform_sync_import_batches",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_platform_sync_import_batches_user_id",
        "platform_sync_import_batches",
        ["user_id"],
    )

    op.create_table(
        "platform_sync_import_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("record_type", sa.String(60), nullable=False),
        sa.Column("record_id", sa.String(200), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("origin_device_id", sa.String(100)),
        sa.Column("origin_event_id", sa.String(200)),
        sa.Column("safe_message", sa.String(300)),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["platform_sync_import_batches.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "batch_id", "record_type", "record_id", name="uq_platform_import_record"
        ),
    )
    op.create_index(
        "ix_platform_import_record_origin",
        "platform_sync_import_records",
        ["origin_device_id", "origin_event_id"],
    )

    _backfill_legacy_history()


def _add_occurrence_columns(table: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column("cycle_id", sa.String(36)))
        batch.add_column(
            sa.Column(
                "occurrence_kind", sa.String(20), nullable=False, server_default="completion"
            )
        )
        batch.add_column(
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "source_event_keys", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            )
        )
        batch.add_column(sa.Column("origin_device_id", sa.String(100)))
        batch.add_column(sa.Column("origin_event_id", sa.String(200)))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column(
                "field_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            )
        )
        batch.create_index(f"ix_{table}_cycle_id", ["cycle_id"])
        batch.create_index(f"ix_{table}_deleted_at", ["deleted_at"])
        batch.create_foreign_key(
            f"fk_{table}_cycle_id",
            "viewing_cycles",
            ["cycle_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _backfill_legacy_history() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    entries = sa.Table("watch_entries", metadata, autoload_with=bind)
    title_events = sa.Table("viewing_events", metadata, autoload_with=bind)
    episode_events = sa.Table("episode_viewings", metadata, autoload_with=bind)
    cycles = sa.Table("viewing_cycles", metadata, autoload_with=bind)
    claims = sa.Table("provider_progress_claims", metadata, autoload_with=bind)

    now = datetime.now(UTC)
    entry_rows = bind.execute(
        sa.select(
            entries.c.id,
            entries.c.user_id,
            entries.c.status,
            entries.c.view_count,
            entries.c.created_at,
            entries.c.updated_at,
        ).order_by(entries.c.id)
    ).mappings()
    for entry in entry_rows:
        title_rows = list(
            bind.execute(
                sa.select(title_events)
                .where(title_events.c.entry_id == entry["id"])
                .order_by(title_events.c.created_at, title_events.c.id)
            ).mappings()
        )
        episode_rows = list(
            bind.execute(
                sa.select(episode_events)
                .where(episode_events.c.entry_id == entry["id"])
                .order_by(episode_events.c.created_at, episode_events.c.id)
            ).mappings()
        )
        desired_count = max(int(entry["view_count"] or 0), len(title_rows))
        if desired_count > len(title_rows):
            claim_time = entry["updated_at"] or now
            bind.execute(
                claims.insert().values(
                    id=_stable_id(f"{entry['id']}:legacy-view-count-claim"),
                    user_id=entry["user_id"],
                    entry_id=entry["id"],
                    provider="legacy_migration",
                    source_key=f"legacy-view-count:{entry['id']}",
                    claim={"view_count": desired_count},
                    accepted_values={"view_count": desired_count},
                    observed_at=claim_time,
                    created_at=claim_time,
                    updated_at=claim_time,
                    version=1,
                    field_versions={},
                )
            )
        if not title_rows and not episode_rows:
            continue
        initial_id = _stable_id(f"{entry['id']}:initial")
        started = entry["created_at"] or now
        last_title_time = title_rows[-1]["created_at"] if title_rows else None
        target_episode_ids = sorted({row["episode_id"] for row in episode_rows})
        bind.execute(
            cycles.insert().values(
                id=initial_id,
                user_id=entry["user_id"],
                entry_id=entry["id"],
                kind="initial",
                scope="title",
                scope_data={"migration": "legacy"},
                target_episode_ids=target_episode_ids,
                state="completed" if title_rows else "active",
                initiated_by="legacy_migration",
                started_at=started,
                ended_at=last_title_time,
                created_at=started,
                updated_at=entry["updated_at"] or now,
                version=1,
                field_versions={},
            )
        )
        if episode_rows:
            bind.execute(
                episode_events.update()
                .where(episode_events.c.entry_id == entry["id"])
                .values(cycle_id=initial_id, updated_at=episode_events.c.created_at)
            )
        for index, existing in enumerate(title_rows):
            if index == 0:
                cycle_id = initial_id
            else:
                event_material = existing["id"]
                cycle_id = _stable_id(f"{entry['id']}:rewatch:{event_material}")
                event_time = existing["created_at"]
                bind.execute(
                    cycles.insert().values(
                        id=cycle_id,
                        user_id=entry["user_id"],
                        entry_id=entry["id"],
                        kind="rewatch",
                        scope="title",
                        scope_data={"migration": "legacy"},
                        target_episode_ids=[],
                        state="completed",
                        initiated_by="legacy_migration",
                        started_at=event_time,
                        ended_at=event_time,
                        created_at=event_time,
                        updated_at=event_time,
                        version=1,
                        field_versions={},
                    )
                )
            bind.execute(
                title_events.update()
                .where(title_events.c.id == existing["id"])
                .values(
                    cycle_id=cycle_id,
                    occurrence_kind="completion",
                    updated_at=existing["created_at"],
                )
            )
        if int(entry["view_count"] or 0) != desired_count:
            bind.execute(
                entries.update()
                .where(entries.c.id == entry["id"])
                .values(view_count=desired_count)
            )


def downgrade() -> None:
    op.drop_index("ix_platform_import_record_origin", table_name="platform_sync_import_records")
    op.drop_table("platform_sync_import_records")
    op.drop_index(
        "ix_platform_sync_import_batches_user_id", table_name="platform_sync_import_batches"
    )
    op.drop_index("ix_platform_import_user_created", table_name="platform_sync_import_batches")
    op.drop_table("platform_sync_import_batches")
    op.drop_index("ix_viewing_corrections_user_id", table_name="viewing_corrections")
    op.drop_index("ix_viewing_corrections_deleted_at", table_name="viewing_corrections")
    op.drop_index("ix_viewing_correction_entry", table_name="viewing_corrections")
    op.drop_table("viewing_corrections")
    op.drop_index("ix_provider_progress_claims_user_id", table_name="provider_progress_claims")
    op.drop_index(
        "ix_provider_progress_claims_deleted_at", table_name="provider_progress_claims"
    )
    op.drop_index("ix_progress_claim_entry_observed", table_name="provider_progress_claims")
    op.drop_table("provider_progress_claims")
    op.drop_index("ix_playback_bookmarks_user_id", table_name="playback_bookmarks")
    op.drop_index("ix_playback_bookmarks_deleted_at", table_name="playback_bookmarks")
    op.drop_index("ix_bookmark_entry_modified", table_name="playback_bookmarks")
    op.drop_table("playback_bookmarks")
    with op.batch_alter_table("media_list_items") as batch:
        batch.drop_index("ix_media_list_items_deleted_at")
        for column in (
            "field_versions",
            "origin_event_id",
            "origin_device_id",
            "deleted_at",
            "updated_at",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("media_lists") as batch:
        batch.drop_index("ix_media_lists_deleted_at")
        for column in (
            "field_versions",
            "origin_event_id",
            "origin_device_id",
            "deleted_at",
        ):
            batch.drop_column(column)
    _drop_occurrence_columns("episode_viewings")
    _drop_occurrence_columns("viewing_events")
    op.drop_index("ix_viewing_cycles_user_id", table_name="viewing_cycles")
    op.drop_index("ix_viewing_cycles_deleted_at", table_name="viewing_cycles")
    op.drop_index("ix_viewing_cycle_user_modified", table_name="viewing_cycles")
    op.drop_index("ix_viewing_cycle_entry_state", table_name="viewing_cycles")
    op.drop_table("viewing_cycles")


def _drop_occurrence_columns(table: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(f"fk_{table}_cycle_id", type_="foreignkey")
        batch.drop_index(f"ix_{table}_deleted_at")
        batch.drop_index(f"ix_{table}_cycle_id")
        for column in (
            "field_versions",
            "deleted_at",
            "updated_at",
            "origin_event_id",
            "origin_device_id",
            "source_event_keys",
            "confidence",
            "occurrence_kind",
            "cycle_id",
        ):
            batch.drop_column(column)
