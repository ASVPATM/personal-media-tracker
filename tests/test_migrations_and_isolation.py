from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from watchtracker import __version__
from watchtracker.config import PROJECT_ROOT, Settings
from watchtracker.db import database_revision, migration_head, upgrade_database


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "src/watchtracker/migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migrations_work_from_empty_and_previous_revision(tmp_path):
    path = tmp_path / "migrations.sqlite3"
    url = f"sqlite:///{path}"
    config = alembic_config(url)
    command.upgrade(config, "0001")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"catalog_items", "watch_entries", "viewing_events", "audit_events"} <= tables
    assert "import_previews" not in tables
    command.upgrade(config, "head")
    inspector = inspect(create_engine(url))
    tables = set(inspector.get_table_names())
    assert {
        "import_previews",
        "import_history",
        "rating_assessments",
        "rating_comparisons",
        "series_tracking_subscriptions",
        "season_records",
        "episode_records",
        "episode_viewings",
        "release_events",
        "sync_jobs",
        "owner_accounts",
        "owner_sessions",
        "login_throttles",
        "calendar_feed_tokens",
    } <= tables
    assert "import_context" in {
        column["name"] for column in inspector.get_columns("watch_entries")
    }


def test_automatic_migration_creates_recoverable_backup(tmp_path):
    path = tmp_path / "automatic.sqlite3"
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), "0001")
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        log_dir=tmp_path / "logs",
        backups_dir=tmp_path / "backups",
        cache_dir=tmp_path / "cache",
        database_path=path,
        env_path=tmp_path / ".env",
    )
    result = upgrade_database(settings)
    assert result.changed is True
    assert result.previous_revision == "0001"
    assert result.current_revision == migration_head(settings)
    assert database_revision(url) == result.current_revision
    assert result.backup_path is not None and result.backup_path.exists()


def test_migration_failure_keeps_pre_migration_backup(tmp_path, monkeypatch):
    path = tmp_path / "failure.sqlite3"
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), "0001")
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        log_dir=tmp_path / "logs",
        backups_dir=tmp_path / "backups",
        cache_dir=tmp_path / "cache",
        database_path=path,
        env_path=tmp_path / ".env",
    )

    monkeypatch.setattr(
        "watchtracker.db.command.upgrade",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        upgrade_database(settings)
    backups = list(settings.resolved_backups_dir.glob("pre-migration-*.sqlite3"))
    assert len(backups) == 1
    assert database_revision(url) == "0001"


def test_source_has_no_recommendation_system_dependency():
    forbidden = ("from recsys", "import recsys", "recommendationsys/")
    checked = [
        *PROJECT_ROOT.glob("src/**/*.py"),
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "alembic.ini",
    ]
    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden), path


def test_project_can_import_from_isolated_copy(tmp_path):
    destination = tmp_path / "standalone"
    shutil.copytree(
        PROJECT_ROOT,
        destination,
        ignore=shutil.ignore_patterns(".venv", "data/*.sqlite3", "cache/*.json", "__pycache__"),
    )
    environment = {"PYTHONPATH": str(destination / "src"), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, "-c", "import watchtracker; print(watchtracker.__version__)"],
        cwd=destination,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == __version__


def test_ui_assets_are_build_free_and_accessible_smoke(client):
    html = client.get("/").text
    css = client.get("/static/styles.css").text
    javascript = client.get("/static/app.js").text
    assert '<main id="main">' in html
    assert 'aria-live="polite"' in html
    assert "prefers-reduced-motion" in css
    assert "runSearch" in javascript
    assert 'id="start-enrichment"' in html
    assert 'id="enrich-after-import"' in html
    assert 'class="insights-grid"' in html
    assert "findEntryMetadata" in javascript
    assert 'id="quick-add-shortcut"' in html
    assert 'id="quick-add-details-dialog"' in html
    assert 'id="back-to-quick-add"' in html
    assert 'id="quick-confirm-refine"' in html
    assert 'id="entry-dialog-art"' in html
    assert 'id="release-check-mode" type="checkbox" role="switch"' in html
    assert 'id="release-check-dialog"' not in html
    assert 'aria-label="List layout"' not in html
    assert 'id="previous-assessment-question"' in html
    assert 'id="skip-assessment-title"' in html
    assert 'id="comparison-back"' in html
    assert 'id="theme-toggle"' not in html
    assert 'id="theme-preference"' in html
    assert 'class="app-sidebar"' in html
    assert 'data-view="currently_watching"' in html
    assert 'data-view="rankings"' in html
    assert 'data-settings-tab="access"' in html
    assert 'id="login-dialog"' in html
    assert 'role="tablist"' in html
    assert "librarySkeletons" in javascript
    assert "histogram-column" in javascript
    assert "watchtracker-theme" in javascript
    assert "restoreNavigationState" in javascript
    assert "persistNavigationState" in javascript
    assert 'id="review-missing-metadata"' in html
    assert 'id="entry-metadata-query"' in html
    assert 'id="review-ratings"' in html
    assert 'id="save-next-rating"' in html
    assert "insight-disclosure" in javascript
    assert "What shapes your taste?" in javascript
    assert "Data quality & confidence" in javascript
    assert "weighted share" in javascript.lower()
    assert "Dated events" not in javascript
    assert "Activity & personal ratings" not in javascript
    assert "Activity charts use stored viewing dates" in html
    assert 'step="0.1"' in html
    assert "@media (max-width: 960px)" in css
    assert not (PROJECT_ROOT / "package.json").exists()
