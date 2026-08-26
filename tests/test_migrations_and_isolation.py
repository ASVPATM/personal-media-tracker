from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
        "external_identities",
        "integration_connections",
        "integration_cursors",
        "integration_runs",
        "integration_events",
        "integration_conflicts",
        "webhook_credentials",
        "media_lists",
        "media_list_items",
        "catalog_metadata_sources",
    } <= tables
    assert "import_context" in {
        column["name"] for column in inspector.get_columns("watch_entries")
    }
    assert "episode_progress_explicit" in {
        column["name"] for column in inspector.get_columns("watch_entries")
    }
    assert "metadata_field_sources" in {
        column["name"] for column in inspector.get_columns("catalog_items")
    }
    assert "pinned_to_navigation" in {
        column["name"] for column in inspector.get_columns("media_lists")
    }


def test_provider_source_migration_backfills_explicit_episode_progress_and_downgrades(
    tmp_path,
):
    path = tmp_path / "provider-source-upgrade.sqlite3"
    url = f"sqlite:///{path}"
    config = alembic_config(url)
    command.upgrade(config, "0010")
    engine = create_engine(url)
    now = datetime.now(UTC)
    ids = {name: str(uuid4()) for name in ("catalog", "entry", "season", "episode", "viewing")}
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO catalog_items
                    (id, canonical_title, normalized_title, media_type, provider_genres,
                     normalized_genres, inferred_subgenres, keywords, taste_evidence,
                     metadata_source, metadata_provenance, inference_version, created_at,
                     updated_at)
                VALUES (:id, 'Series', 'series', 'tv', '[]', '[]', '[]', '[]', '{}',
                        'manual', '{}', '2.0', :now, :now)
                """
            ),
            {"id": ids["catalog"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO watch_entries
                    (id, catalog_item_id, status, user_tags, view_count, genre_additions,
                     genre_removals, subgenre_additions, subgenre_removals, import_context,
                     is_favorite, created_at, updated_at)
                VALUES (:id, :catalog, 'watched', '[]', 1, '[]', '[]', '[]', '[]', '{}',
                        0, :now, :now)
                """
            ),
            {"id": ids["entry"], "catalog": ids["catalog"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO season_records
                    (id, entry_id, provider_source, provider_series_id, season_number,
                     fetched_at)
                VALUES (:id, :entry, 'tvmaze', '10', 1, :now)
                """
            ),
            {"id": ids["season"], "entry": ids["entry"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO episode_records
                    (id, season_id, provider_source, provider_episode_id, episode_number,
                     fetched_at)
                VALUES (:id, :season, 'tvmaze', '20', 1, :now)
                """
            ),
            {"id": ids["episode"], "season": ids["season"], "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO episode_viewings
                    (id, episode_id, entry_id, source, created_at)
                VALUES (:id, :episode, :entry, 'manual', :now)
                """
            ),
            {
                "id": ids["viewing"],
                "episode": ids["episode"],
                "entry": ids["entry"],
                "now": now,
            },
        )
    command.upgrade(config, "0011")
    with engine.connect() as connection:
        explicit = connection.scalar(
            text("SELECT episode_progress_explicit FROM watch_entries WHERE id = :id"),
            {"id": ids["entry"]},
        )
    assert explicit == 1
    command.downgrade(config, "0010")
    inspector = inspect(engine)
    assert "catalog_metadata_sources" not in inspector.get_table_names()
    assert "episode_progress_explicit" not in {
        column["name"] for column in inspector.get_columns("watch_entries")
    }


def test_integration_migration_backfills_compatibility_ids_and_downgrades(tmp_path):
    path = tmp_path / "integration-upgrade.sqlite3"
    url = f"sqlite:///{path}"
    config = alembic_config(url)
    command.upgrade(config, "0008")
    engine = create_engine(url)
    catalog_id = str(uuid4())
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO catalog_items
                    (id, canonical_title, normalized_title, release_year, media_type,
                     tmdb_movie_id, anilist_id, provider_genres, normalized_genres,
                     inferred_subgenres, keywords, taste_evidence, metadata_source,
                     metadata_provenance, inference_version, created_at, updated_at)
                VALUES
                    (:id, 'Migration fixture', 'migration fixture', 2026, 'anime',
                     '8100', '9100', '[]', '[]', '[]', '[]', '{}', 'manual', '{}',
                     '2.0', :created_at, :updated_at)
                """
            ),
            {"id": catalog_id, "created_at": now, "updated_at": now},
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT namespace, external_id FROM external_identities "
                "WHERE catalog_item_id = :catalog_id ORDER BY namespace"
            ),
            {"catalog_id": catalog_id},
        ).all()
    assert rows == [("anilist", "9100"), ("tmdb_movie", "8100")]
    command.downgrade(config, "0008")
    inspector = inspect(engine)
    assert "external_identities" not in inspector.get_table_names()
    assert {"tmdb_movie_id", "anilist_id"} <= {
        column["name"] for column in inspector.get_columns("catalog_items")
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
    assert 'class="insights-dashboard"' in html
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
    assert 'href="#icon-active-shows"' in html
    assert 'id="custom-list-navigation"' in html
    assert html.index('id="quick-add-shortcut"') < html.index('id="custom-list-navigation"')
    assert 'id="list-detail-view"' in html
    assert 'id="list-detail-title-search"' in html
    assert "mediaTypeLabel" not in javascript
    assert 'role="combobox"' in html
    assert '<select name="entry_id">' not in html
    assert 'id="toggle-list-navigation"' in html
    assert 'data-view="rankings"' in html
    assert 'data-settings-tab="access"' in html
    assert 'id="login-dialog"' in html
    assert 'role="tablist"' in html
    assert "librarySkeletons" in javascript
    assert "histogram-column" in javascript
    assert "watchtracker-theme" in javascript
    assert "restoreNavigationState" in javascript
    assert "persistNavigationState" in javascript
    assert "loadListDetail" in javascript
    assert "loadListNavigation" in javascript
    assert "episode-just-updated" in javascript
    assert "renderListTitleOptions" in javascript
    assert "media-list-summary" in css
    assert "episode-row-confirm" in css
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
    assert "Activity includes only stored dates" in html
    assert 'step="0.1"' in html
    assert "@media (max-width: 960px)" in css
    assert not (PROJECT_ROOT / "package.json").exists()
