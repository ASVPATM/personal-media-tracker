"""Add user ownership and deterministically backfill the legacy library.

Revision ID: 0013
Revises: 0012
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
OWNED_TABLES = (
    "watch_entries",
    "viewing_events",
    "audit_events",
    "import_previews",
    "import_history",
    "rating_comparisons",
    "rating_refinement_runs",
    "episode_viewings",
    "release_events",
    "integration_connections",
    "calendar_feed_tokens",
    "media_lists",
)


def _legacy_user() -> str:
    bind = op.get_bind()
    owners = (
        bind.execute(
            sa.text(
                "SELECT id, username, password_hash, password_changed_at, created_at "
                "FROM owner_accounts ORDER BY created_at, id"
            )
        )
        .mappings()
        .all()
    )
    private_count = sum(
        int(bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")) or 0)
        for table in OWNED_TABLES
    )
    if len(owners) > 1 and private_count:
        raise RuntimeError(
            "Migration refused: the legacy database has multiple owner accounts, so "
            "private record ownership cannot be proven."
        )
    now = datetime.now(UTC)
    if owners:
        owner = owners[0]
        user_id = str(owner["id"])
        username = str(owner["username"])
        password_hash = owner["password_hash"]
        password_changed_at = owner["password_changed_at"]
        created_at = owner["created_at"]
    else:
        user_id = LOCAL_USER_ID
        username = "local"
        password_hash = None
        password_changed_at = None
        created_at = now
    bind.execute(
        sa.text(
            """
            INSERT INTO user_accounts
                (id, username, normalized_username, display_name, password_hash, role,
                 state, locale, timezone, password_changed_at, created_at, updated_at)
            VALUES
                (:id, :username, :normalized_username, :display_name, :password_hash,
                 'admin', 'active', 'en', 'UTC', :password_changed_at, :created_at, :now)
            """
        ),
        {
            "id": user_id,
            "username": username,
            "normalized_username": username.strip().casefold(),
            "display_name": "Owner" if owners else "Local profile",
            "password_hash": password_hash,
            "password_changed_at": password_changed_at,
            "created_at": created_at,
            "now": now,
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO user_preferences (user_id, preferences, updated_at) "
            "VALUES (:user_id, '{}', :now)"
        ),
        {"user_id": user_id, "now": now},
    )
    return user_id


def _add_owner(table: str, user_id: str) -> None:
    op.add_column(table, sa.Column("user_id", sa.String(36), nullable=True))
    op.execute(
        sa.text(f"UPDATE {table} SET user_id = :user_id WHERE user_id IS NULL").bindparams(
            user_id=user_id
        )
    )
    missing = op.get_bind().scalar(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
    )
    if int(missing or 0):
        raise RuntimeError(f"Migration refused: {table} contains unowned rows.")


def _sqlite_foreign_keys(enabled: bool) -> None:
    """Prevent SQLite batch table rebuilds from cascading into child tables.

    Alembic recreates tables to change nullability and uniqueness on SQLite. Dropping
    the old parent table while foreign keys are active is observed as a real delete and
    would erase histories, assessments, list items, and integration children. The pragma
    is connection-local; validation runs before it is restored.
    """
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    # SQLite ignores PRAGMA foreign_keys inside an open transaction.
    # Alembic wraps the connection in a context manager even though SQLite DDL is
    # non-transactional, so use the underlying DB-API connection without closing
    # SQLAlchemy's transaction context.
    driver_connection = bind.connection.driver_connection
    driver_connection.commit()
    driver_connection.execute(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def _validate_foreign_keys() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        first = violations[0]
        raise RuntimeError(
            "Migration refused: ownership rebuild produced invalid foreign keys "
            f"(first violation: {first})."
        )


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("normalized_username", sa.String(80), nullable=False, unique=True),
        sa.Column("email", sa.String(320), unique=True),
        sa.Column("normalized_email", sa.String(320), unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_user_account_role"),
        sa.CheckConstraint(
            "state IN ('invited', 'active', 'disabled')", name="ck_user_account_state"
        ),
    )
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    user_id = _legacy_user()
    for table in OWNED_TABLES:
        _add_owner(table, user_id)
    op.add_column("watch_entries", sa.Column("poster_override_url", sa.Text()))
    op.execute(
        """
        UPDATE watch_entries
        SET poster_override_url = (
            SELECT catalog_items.poster_override_url
            FROM catalog_items
            WHERE catalog_items.id = watch_entries.catalog_item_id
        )
        """
    )

    # Replace legacy global uniqueness with tenant-scoped uniqueness while each
    # table is already being rebuilt to make user_id non-null on SQLite.
    replacements = {
        "watch_entries": (
            "uq_watch_entries_catalog_item_id",
            "uq_watch_entry_user_catalog",
            ["user_id", "catalog_item_id"],
        ),
        "viewing_events": (
            "uq_viewing_source_key",
            "uq_viewing_user_source_key",
            ["user_id", "source", "source_key"],
        ),
        "import_history": (
            "uq_import_history_hash",
            "uq_import_history_user_hash",
            ["user_id", "source_hash"],
        ),
        "rating_comparisons": (
            "uq_rating_comparison_pair",
            "uq_rating_user_pair",
            ["user_id", "entry_low_id", "entry_high_id"],
        ),
        "episode_viewings": (
            "uq_episode_viewing_source_key",
            "uq_episode_viewing_user_source_key",
            ["user_id", "source", "source_key"],
        ),
        "release_events": (
            "uq_release_events_dedupe_key",
            "uq_release_event_user_dedupe",
            ["user_id", "dedupe_key"],
        ),
        "media_lists": (
            "uq_media_lists_name",
            "uq_media_list_user_name",
            ["user_id", "name"],
        ),
    }
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_foreign_keys(False)
        for table in OWNED_TABLES:
            with op.batch_alter_table(
                table, recreate="always", naming_convention=NAMING_CONVENTION
            ) as batch:
                batch.alter_column("user_id", existing_type=sa.String(36), nullable=False)
                batch.create_foreign_key(
                    f"fk_{table}_user",
                    "user_accounts",
                    ["user_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
                if table in replacements:
                    old_name, new_name, columns = replacements[table]
                    batch.drop_constraint(old_name, type_="unique")
                    batch.create_unique_constraint(new_name, columns)
    else:
        postgres_legacy_names = {
            "watch_entries": "watch_entries_catalog_item_id_key",
            "release_events": "release_events_dedupe_key_key",
            "media_lists": "media_lists_name_key",
        }
        for table in OWNED_TABLES:
            op.alter_column(table, "user_id", existing_type=sa.String(36), nullable=False)
            op.create_foreign_key(
                f"fk_{table}_user",
                table,
                "user_accounts",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )
            if table in replacements:
                old_name, new_name, columns = replacements[table]
                op.drop_constraint(
                    postgres_legacy_names.get(table, old_name), table, type_="unique"
                )
                op.create_unique_constraint(new_name, table, columns)

    for table in OWNED_TABLES:
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    op.create_index("ix_watch_entry_user_deleted", "watch_entries", ["user_id", "deleted_at"])
    op.create_index("ix_media_list_user_updated", "media_lists", ["user_id", "updated_at"])
    op.create_index(
        "ix_integration_connection_user",
        "integration_connections",
        ["user_id", "provider_slug"],
    )
    op.drop_column("catalog_items", "poster_override_url")
    _validate_foreign_keys()
    _sqlite_foreign_keys(True)


def _ensure_single_owner() -> None:
    bind = op.get_bind()
    for table in OWNED_TABLES:
        owners = int(bind.scalar(sa.text(f"SELECT COUNT(DISTINCT user_id) FROM {table}")) or 0)
        if owners > 1:
            raise RuntimeError(
                "Downgrade refused: multiple users own private records. Export or remove "
                "additional users before returning to the single-owner schema."
            )


def downgrade() -> None:
    _ensure_single_owner()
    op.add_column("catalog_items", sa.Column("poster_override_url", sa.Text()))
    op.execute(
        """
        UPDATE catalog_items
        SET poster_override_url = (
            SELECT watch_entries.poster_override_url
            FROM watch_entries
            WHERE watch_entries.catalog_item_id = catalog_items.id
            ORDER BY watch_entries.created_at, watch_entries.id
            LIMIT 1
        )
        """
    )
    for index_name, table in (
        ("ix_integration_connection_user", "integration_connections"),
        ("ix_media_list_user_updated", "media_lists"),
        ("ix_watch_entry_user_deleted", "watch_entries"),
    ):
        op.drop_index(index_name, table_name=table)
    for table in OWNED_TABLES:
        op.drop_index(f"ix_{table}_user_id", table_name=table)

    replacements = {
        "watch_entries": (
            "uq_watch_entry_user_catalog",
            "uq_watch_entries_catalog_item_id",
            ["catalog_item_id"],
        ),
        "viewing_events": (
            "uq_viewing_user_source_key",
            "uq_viewing_source_key",
            ["source", "source_key"],
        ),
        "import_history": (
            "uq_import_history_user_hash",
            "uq_import_history_hash",
            ["source_hash"],
        ),
        "rating_comparisons": (
            "uq_rating_user_pair",
            "uq_rating_comparison_pair",
            ["entry_low_id", "entry_high_id"],
        ),
        "episode_viewings": (
            "uq_episode_viewing_user_source_key",
            "uq_episode_viewing_source_key",
            ["source", "source_key"],
        ),
        "release_events": (
            "uq_release_event_user_dedupe",
            "uq_release_events_dedupe_key",
            ["dedupe_key"],
        ),
        "media_lists": (
            "uq_media_list_user_name",
            "uq_media_lists_name",
            ["name"],
        ),
    }
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_foreign_keys(False)
        for table in reversed(OWNED_TABLES):
            with op.batch_alter_table(
                table, recreate="always", naming_convention=NAMING_CONVENTION
            ) as batch:
                if table in replacements:
                    old_name, new_name, columns = replacements[table]
                    batch.drop_constraint(old_name, type_="unique")
                    batch.create_unique_constraint(new_name, columns)
                batch.drop_column("user_id")
    else:
        postgres_legacy_names = {
            "watch_entries": "watch_entries_catalog_item_id_key",
            "release_events": "release_events_dedupe_key_key",
            "media_lists": "media_lists_name_key",
        }
        for table in reversed(OWNED_TABLES):
            if table in replacements:
                old_name, new_name, columns = replacements[table]
                op.drop_constraint(old_name, table, type_="unique")
                op.create_unique_constraint(
                    postgres_legacy_names.get(table, new_name), table, columns
                )
            op.drop_constraint(f"fk_{table}_user", table, type_="foreignkey")
            op.drop_column(table, "user_id")
    op.drop_column("watch_entries", "poster_override_url")
    op.drop_table("user_preferences")
    op.drop_table("user_accounts")
    _validate_foreign_keys()
    _sqlite_foreign_keys(True)
