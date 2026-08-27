"""Move provider episode schedules from private entries to the shared catalog.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _require_no_nulls(table: str, column: str) -> None:
    missing = op.get_bind().scalar(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
    )
    if int(missing or 0):
        raise RuntimeError(
            f"Migration refused: {missing} {table} rows have no provable {column}."
        )


def _sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    # A batch rebuild drops the old season table. With foreign keys active,
    # SQLite would cascade that temporary drop into episodes and viewings.
    driver_connection = bind.connection.driver_connection
    driver_connection.commit()
    driver_connection.execute(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def _validate_foreign_keys() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "Migration refused: schedule rebuild produced invalid foreign keys "
            f"(first violation: {violations[0]})."
        )


def upgrade() -> None:
    op.add_column("season_records", sa.Column("catalog_item_id", sa.String(36)))
    op.execute(
        """
        UPDATE season_records
        SET catalog_item_id = (
            SELECT watch_entries.catalog_item_id
            FROM watch_entries
            WHERE watch_entries.id = season_records.entry_id
        )
        """
    )
    _require_no_nulls("season_records", "catalog_item_id")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_index("ix_season_entry_number", table_name="season_records")
        op.alter_column(
            "season_records", "catalog_item_id", existing_type=sa.String(36), nullable=False
        )
        op.create_foreign_key(
            "fk_season_catalog_item",
            "season_records",
            "catalog_items",
            ["catalog_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.drop_constraint("season_records_entry_id_fkey", "season_records", type_="foreignkey")
        op.drop_column("season_records", "entry_id")
        op.create_index(
            "ix_season_catalog_number",
            "season_records",
            ["catalog_item_id", "season_number"],
        )
        return
    _sqlite_foreign_keys(False)
    op.drop_index("ix_season_entry_number", table_name="season_records")
    with op.batch_alter_table("season_records", recreate="always") as batch:
        batch.alter_column("catalog_item_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key(
            "fk_season_catalog_item",
            "catalog_items",
            ["catalog_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_column("entry_id")
    op.create_index(
        "ix_season_catalog_number",
        "season_records",
        ["catalog_item_id", "season_number"],
    )
    _validate_foreign_keys()
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    op.add_column("season_records", sa.Column("entry_id", sa.String(36)))
    op.execute(
        """
        UPDATE season_records
        SET entry_id = (
            SELECT MIN(watch_entries.id)
            FROM watch_entries
            WHERE watch_entries.catalog_item_id = season_records.catalog_item_id
        )
        """
    )
    _require_no_nulls("season_records", "entry_id")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_index("ix_season_catalog_number", table_name="season_records")
        op.alter_column(
            "season_records", "entry_id", existing_type=sa.String(36), nullable=False
        )
        op.create_foreign_key(
            "fk_season_watch_entry",
            "season_records",
            "watch_entries",
            ["entry_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.drop_constraint("fk_season_catalog_item", "season_records", type_="foreignkey")
        op.drop_column("season_records", "catalog_item_id")
        op.create_index(
            "ix_season_entry_number", "season_records", ["entry_id", "season_number"]
        )
        return
    _sqlite_foreign_keys(False)
    op.drop_index("ix_season_catalog_number", table_name="season_records")
    with op.batch_alter_table("season_records", recreate="always") as batch:
        batch.alter_column("entry_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key(
            "fk_season_watch_entry",
            "watch_entries",
            ["entry_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_column("catalog_item_id")
    op.create_index("ix_season_entry_number", "season_records", ["entry_id", "season_number"])
    _validate_foreign_keys()
    _sqlite_foreign_keys(True)
