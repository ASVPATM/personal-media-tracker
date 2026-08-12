from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from watchtracker import models  # noqa: F401
from watchtracker.config import Settings
from watchtracker.db import Base

config = context.config
target_metadata = Base.metadata

# Programmatic upgrades inject their target URL directly. For the standalone Alembic
# command, honor the same documented environment overrides as the application so CI and
# developers never migrate the repository-local default by accident.
if any(name in os.environ for name in ("WATCHTRACKER_DATABASE_PATH", "WATCHTRACKER_DATA_DIR")):
    runtime_settings = Settings()
    config.set_main_option("sqlalchemy.url", runtime_settings.database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # An outer transaction ensures Alembic's version-row DML is committed on SQLite,
    # whose DDL itself is treated as non-transactional.
    with connectable.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
