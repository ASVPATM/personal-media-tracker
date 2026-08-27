from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from watchtracker.app import create_app
from watchtracker.config import MIGRATIONS_DIR, PROJECT_ROOT, Settings
from watchtracker.db import make_engine, make_session_factory
from watchtracker.services.backups import BackupService

POSTGRES_URL = os.environ.get("PMT_TEST_POSTGRES_URL")
RESTORE_URL = os.environ.get("PMT_TEST_POSTGRES_RESTORE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL or not RESTORE_URL,
    reason="PostgreSQL integration URLs are not configured",
)


def _admin_url(value: str) -> str:
    parsed = urlsplit(value)
    return parsed._replace(path="/postgres").geturl()


def _database_name(value: str) -> str:
    return urlsplit(value).path.lstrip("/")


def _recreate_database(value: str) -> None:
    engine = create_engine(_admin_url(value), isolation_level="AUTOCOMMIT")
    name = _database_name(value)
    assert name.replace("_", "").isalnum()
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        engine.dispose()


def _alembic(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_postgres_full_migration_runtime_and_disaster_restore(tmp_path: Path):
    assert POSTGRES_URL and RESTORE_URL
    _recreate_database(POSTGRES_URL)
    config = _alembic(POSTGRES_URL)
    command.upgrade(config, "head")
    assert {
        "user_accounts",
        "watch_entries",
        "media_list_memberships",
        "scheduled_jobs",
    } <= set(inspect(create_engine(POSTGRES_URL)).get_table_names())

    # Empty-schema downgrade rehearsal catches dialect-specific constraint names.
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        backups_dir=tmp_path / "backups",
        database_url_override=POSTGRES_URL,
        access_mode="local",
        host="127.0.0.1",
        release_scheduler_enabled=False,
    )
    with TestClient(create_app(settings, migrate=False)) as client:
        response = client.post(
            "/api/entries/manual",
            json={
                "canonical_title": "PostgreSQL verification title",
                "release_year": 2026,
                "media_type": "movie",
                "status": "plan_to_watch",
            },
        )
        assert response.status_code == 201
        assert client.get("/health").json()["database"] == "ready"

    engine = make_engine(POSTGRES_URL)
    backups = BackupService(settings, engine, make_session_factory(engine))
    snapshot = backups.create_server_snapshot()
    assert snapshot.path.suffix == ".dump"
    assert backups.verify_recovery_archive(snapshot.path)["status"] == "verified"
    _recreate_database(RESTORE_URL)
    restored = backups.restore_postgres_snapshot(snapshot.path, RESTORE_URL)
    assert restored["status"] == "restored_and_verified"
    assert restored["titles"] == 1
    engine.dispose()
