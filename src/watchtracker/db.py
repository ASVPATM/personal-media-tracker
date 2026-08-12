from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from watchtracker.config import MIGRATIONS_DIR, PROJECT_ROOT, Settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    connect_args = (
        {"check_same_thread": False, "timeout": 15} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def _alembic_config(settings: Settings, database_url: str) -> Config:
    ini_path = PROJECT_ROOT / "alembic.ini"
    config = Config(str(ini_path)) if ini_path.exists() else Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def sqlite_integrity_check(path: Path) -> None:
    if not path.exists() or path.stat().st_size < 100:
        raise RuntimeError("The selected database is missing or empty.")
    try:
        with sqlite3.connect(path) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
    except sqlite3.DatabaseError as exc:
        raise RuntimeError("The database could not be opened as SQLite.") from exc
    if not result or result[0] != "ok":
        raise RuntimeError("The database failed its SQLite integrity check.")
    required = {"catalog_items", "watch_entries", "viewing_events"}
    if not required <= tables:
        raise RuntimeError("The file is not a Personal Media Tracker database.")


def sqlite_online_backup(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(temporary) as destination_connection,
        ):
            source_connection.backup(destination_connection)
        sqlite_integrity_check(temporary)
        temporary.replace(destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def database_revision(database_url: str) -> str | None:
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def migration_head(settings: Settings, database_url: str | None = None) -> str:
    config = _alembic_config(settings, database_url or settings.database_url)
    return ScriptDirectory.from_config(config).get_current_head()


@dataclass(frozen=True)
class MigrationResult:
    changed: bool
    previous_revision: str | None
    current_revision: str
    backup_path: Path | None = None


def upgrade_database(settings: Settings, database_url: str | None = None) -> MigrationResult:
    url = database_url or settings.database_url
    settings.ensure_runtime_directories()
    database_path: Path | None = None
    if url.startswith("sqlite:///") and ":memory:" not in url:
        database_path = Path(url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    config = _alembic_config(settings, url)
    head = ScriptDirectory.from_config(config).get_current_head()
    previous = database_revision(url) if database_path and database_path.exists() else None
    changed = previous != head
    backup_path = None
    if changed and database_path and database_path.exists() and database_path.stat().st_size:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = settings.resolved_backups_dir / f"pre-migration-{stamp}.sqlite3"
        try:
            sqlite_online_backup(database_path, backup_path)
        except RuntimeError:
            # A pre-Alembic/empty legacy SQLite file can still be backed up byte-for-byte.
            shutil.copy2(database_path, backup_path)
    if changed:
        command.upgrade(config, "head")
    if database_path:
        sqlite_integrity_check(database_path)
    return MigrationResult(
        changed=changed,
        previous_revision=previous,
        current_revision=head,
        backup_path=backup_path,
    )


def session_dependency(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
