"""Add provider-neutral integration identity, connection, and audit records.

Revision ID: 0009
Revises: 0008
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _backfill_external_identities(namespace: str, external_id_column: str) -> None:
    """Copy legacy provider IDs without relying on database-specific UUID SQL."""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"""
            SELECT id AS catalog_item_id,
                   {external_id_column} AS external_id,
                   metadata_fetched_at AS verified_at,
                   created_at,
                   updated_at
            FROM catalog_items
            WHERE {external_id_column} IS NOT NULL
            """
        )
    ).mappings()
    values = [
        {
            "id": str(uuid4()),
            "catalog_item_id": row["catalog_item_id"],
            "namespace": namespace,
            "external_id": row["external_id"],
            "verified_at": row["verified_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    if not values:
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO external_identities
                (id, catalog_item_id, namespace, external_id, provenance, confidence,
                 verified_at, created_at, updated_at)
            VALUES
                (:id, :catalog_item_id, :namespace, :external_id,
                 'compatibility_backfill', 1.0, :verified_at, :created_at, :updated_at)
            """
        ),
        values,
    )


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_item_id",
            sa.String(36),
            sa.ForeignKey("catalog_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("provenance", sa.String(80), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("namespace", "external_id", name="uq_external_identity_value"),
        sa.UniqueConstraint(
            "catalog_item_id", "namespace", name="uq_catalog_external_identity_namespace"
        ),
    )
    op.create_index(
        "ix_external_identity_catalog",
        "external_identities",
        ["catalog_item_id", "namespace"],
    )
    _backfill_external_identities("tmdb_movie", "tmdb_movie_id")
    _backfill_external_identities("tmdb_tv", "tmdb_tv_id")
    _backfill_external_identities("anilist", "anilist_id")
    _backfill_external_identities("mal", "mal_id")

    op.create_table(
        "integration_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_slug", sa.String(60), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("configuration", sa.JSON, nullable=False),
        sa.Column("remote_profile", sa.JSON, nullable=False),
        sa.Column("capabilities", sa.JSON, nullable=False),
        sa.Column("schedule", sa.JSON, nullable=False),
        sa.Column("secret_reference", sa.String(160), unique=True),
        sa.Column("failure_count", sa.Integer, nullable=False),
        sa.Column("paused_reason", sa.String(300)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("failure_count >= 0", name="ck_integration_failure_count"),
    )
    op.create_index(
        "ix_integration_connection_provider",
        "integration_connections",
        ["provider_slug", "enabled"],
    )
    op.create_table(
        "integration_cursors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(60), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("checkpoint", sa.JSON, nullable=False),
        sa.Column("provider_version", sa.String(60)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "connection_id", "capability", "direction", name="uq_integration_cursor"
        ),
    )
    op.create_table(
        "integration_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("capability", sa.String(60), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("dry_run", sa.Boolean, nullable=False),
        sa.Column("counts", sa.JSON, nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(300)),
        sa.Column("retry_after_seconds", sa.Integer),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_integration_run_connection_time",
        "integration_runs",
        ["connection_id", "started_at"],
    )
    op.create_index("ix_integration_run_state", "integration_runs", ["state", "started_at"])
    op.create_table(
        "integration_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("integration_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_event_id", sa.String(200)),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("canonical_target", sa.String(200)),
        sa.Column("event_kind", sa.String(60), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("safe_summary", sa.String(300), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "connection_id", "idempotency_key", name="uq_integration_event_delivery"
        ),
    )
    op.create_index("ix_integration_event_run", "integration_events", ["run_id", "created_at"])
    op.create_index(
        "ix_integration_event_target",
        "integration_events",
        ["canonical_target", "created_at"],
    )
    op.create_table(
        "integration_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("integration_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "catalog_item_id",
            sa.String(36),
            sa.ForeignKey("catalog_items.id", ondelete="SET NULL"),
        ),
        sa.Column("conflict_kind", sa.String(60), nullable=False),
        sa.Column("local_value", sa.JSON, nullable=False),
        sa.Column("remote_value", sa.JSON, nullable=False),
        sa.Column("safe_summary", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", sa.String(30)),
    )
    op.create_index(
        "ix_integration_conflict_open",
        "integration_conflicts",
        ["connection_id", "resolved_at", "created_at"],
    )
    op.create_table(
        "webhook_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_id", sa.String(24), unique=True, nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_webhook_credential_public",
        "webhook_credentials",
        ["public_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_table("webhook_credentials")
    op.drop_table("integration_conflicts")
    op.drop_table("integration_events")
    op.drop_table("integration_runs")
    op.drop_table("integration_cursors")
    op.drop_table("integration_connections")
    op.drop_table("external_identities")
