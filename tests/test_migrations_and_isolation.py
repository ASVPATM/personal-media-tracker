from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from watchtracker import __version__
from watchtracker.authorization import LOCAL_USER_ID
from watchtracker.config import PROJECT_ROOT, Settings
from watchtracker.db import database_revision, migration_head, upgrade_database
from watchtracker.models import CatalogItem, UserAccount, WatchEntry


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
        "user_sessions",
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
        "user_accounts",
        "user_preferences",
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
    assert "catalog_item_id" in {
        column["name"] for column in inspector.get_columns("season_records")
    }
    assert "entry_id" not in {
        column["name"] for column in inspector.get_columns("season_records")
    }
    for table in (
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
    ):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert columns["user_id"]["nullable"] is False, table


def test_rich_legacy_fixture_preserves_records_ownership_and_rollback(tmp_path):
    fixture = json.loads(
        (PROJECT_ROOT / "tests/fixtures/legacy_library_v0011.json").read_text(encoding="utf-8")
    )
    path = tmp_path / "legacy-v0011.sqlite3"
    url = f"sqlite:///{path}"
    config = alembic_config(url)
    command.upgrade(config, "0011")
    engine = create_engine(url)
    owner = fixture["owner_id"]
    catalog_a, catalog_b = fixture["catalog_ids"]
    entry_a, entry_b = fixture["entry_ids"]
    values = fixture["sentinels"]
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    expires = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO owner_accounts "
                "(id, username, password_hash, password_changed_at, "
                "bootstrap_completed_at, created_at) "
                "VALUES (:id, 'legacy-owner', 'synthetic-password-hash', :now, :now, :now)"
            ),
            {"id": owner, "now": now},
        )
        for catalog_id, title, normalized, media_type, override in (
            (
                catalog_a,
                values["title"],
                "synthetic legacy series",
                "tv",
                values["poster_override_url"],
            ),
            (catalog_b, "Synthetic legacy film", "synthetic legacy film", "movie", None),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO catalog_items
                        (id, canonical_title, normalized_title, release_year, media_type,
                         provider_genres, normalized_genres, inferred_subgenres, keywords,
                         taste_evidence, metadata_source, metadata_provenance,
                         metadata_field_sources, inference_version, created_at, updated_at,
                         poster_override_url)
                    VALUES
                        (:id, :title, :normalized, 2025, :media_type, '["Drama"]',
                         '["Drama"]', '[]', '["memory"]', '{"tone":"quiet"}',
                         'manual', '{"source":"fixture"}', '{"overview":"manual"}',
                         '2.0', :now, :now, :override)
                    """
                ),
                {
                    "id": catalog_id,
                    "title": title,
                    "normalized": normalized,
                    "media_type": media_type,
                    "override": override,
                    "now": now,
                },
            )
        for entry_id, catalog_id, rating, note in (
            (entry_a, catalog_a, 9.25, values["note"]),
            (entry_b, catalog_b, 7.5, "second synthetic note"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO watch_entries
                        (id, catalog_item_id, status, personal_rating, notes, user_tags,
                         started_date, finished_date, watched_date, view_count,
                         genre_additions, genre_removals, subgenre_additions,
                         subgenre_removals, import_context, is_favorite,
                         episode_progress_explicit, created_at, updated_at)
                    VALUES
                        (:id, :catalog, 'watched', :rating, :note, '["legacy"]',
                         '2025-06-01', '2025-06-07', :watched, 2, '["Mystery"]', '[]',
                         '["Slow burn"]', '[]', '{"source":"synthetic"}', 1, 1,
                         :now, :now)
                    """
                ),
                {
                    "id": entry_id,
                    "catalog": catalog_id,
                    "rating": rating,
                    "note": note,
                    "watched": values["watched_date"],
                    "now": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO viewing_events "
                "(id, entry_id, viewed_on, source, source_key, created_at) VALUES "
                "('60000000-0000-0000-0000-000000000001', :entry, :watched, "
                "'legacy-import', 'legacy-view-1', :now)"
            ),
            {"entry": entry_a, "watched": values["watched_date"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO audit_events "
                "(id, action, entity_type, entity_id, source, before_data, after_data, "
                "created_at) VALUES ('60000000-0000-0000-0000-000000000002', "
                "'update', 'watch_entry', :entry, 'fixture', :before, :after, :now)"
            ),
            {
                "entry": entry_a,
                "before": '{"rating":8}',
                "after": '{"rating":9.25}',
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO import_previews "
                "(id, source_hash, filename, import_kind, payload, created_at, expires_at) "
                "VALUES ('60000000-0000-0000-0000-000000000003', :hash, "
                "'legacy.csv', 'csv', '{\"rows\":[]}', :now, :expires)"
            ),
            {"hash": values["source_hash"], "now": now, "expires": expires},
        )
        connection.execute(
            text(
                "INSERT INTO import_history "
                "(id, source_hash, filename, import_kind, summary, created_at) VALUES "
                "('60000000-0000-0000-0000-000000000004', :hash, 'history.csv', "
                "'csv', :summary, :now)"
            ),
            {"hash": "c" * 64, "summary": '{"created":2}', "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO rating_assessments
                    (id, entry_id, mode, rubric_version, state, answers,
                     private_reflection, rubric_score, rubric_coverage, suggested_rating,
                     final_rating_snapshot, version, created_at, updated_at, completed_at)
                VALUES
                    ('60000000-0000-0000-0000-000000000005', :entry, 'guided_v2',
                     'guided-rubric-v2', 'completed', :answers, :reflection,
                     8.75, 1.0, 9.0, 9.25, 3, :now, :now, :now)
                """
            ),
            {
                "entry": entry_a,
                "answers": '{"impact":4.5}',
                "reflection": values["reflection"],
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO rating_comparisons
                    (id, entry_low_id, entry_high_id, displayed_left_entry_id, dimension,
                     result, selection_reason, algorithm_version, created_at, updated_at)
                VALUES
                    ('60000000-0000-0000-0000-000000000006', :low, :high, :low,
                     'overall_preference', 'low', 'nearby_score', 'advanced-ranking-v1',
                     :now, :now)
                """
            ),
            {"low": entry_a, "high": entry_b, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO rating_refinement_runs
                    (id, scope, state, stage, rubric_version, ranking_version,
                     target_entry_ids, completed_entry_ids, completed_pair_keys,
                     comparison_target, comparisons_completed, assessment_target,
                     assessments_completed, created_at, updated_at)
                VALUES
                    ('60000000-0000-0000-0000-000000000007', 'focused', 'active',
                     'assessments', 'guided-rubric-v2', 'advanced-ranking-v1', :targets,
                     '[]', '[]', 1, 1, 1, 0, :now, :now)
                """
            ),
            {"targets": json.dumps([entry_a]), "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO series_tracking_subscriptions
                    (id, entry_id, enabled, notify_new_episode, notify_new_season,
                     include_specials, failure_count, provider_cursor, created_at, updated_at)
                VALUES ('60000000-0000-0000-0000-000000000014', :entry,
                        1, 1, 1, 0, 0, '{}', :now, :now)
                """
            ),
            {"entry": entry_a, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO season_records
                    (id, entry_id, provider_source, provider_series_id,
                     provider_season_id, season_number, title, episode_count, fetched_at)
                VALUES (:id, :entry, 'tmdb_tv', 'legacy-series-1', 'legacy-season-1',
                        1, 'Legacy season', 1, :now)
                """
            ),
            {"id": fixture["season_id"], "entry": entry_a, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO episode_records
                    (id, season_id, provider_source, provider_episode_id, episode_number,
                     title, air_date, fetched_at)
                VALUES (:id, :season, 'tmdb_tv', 'legacy-episode-1', 1,
                        'Legacy episode', '2025-06-07', :now)
                """
            ),
            {"id": fixture["episode_id"], "season": fixture["season_id"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO episode_viewings "
                "(id, episode_id, entry_id, watched_on, source, source_key, created_at) "
                "VALUES ('60000000-0000-0000-0000-000000000008', :episode, :entry, "
                ":watched, 'manual', 'legacy-episode-view', :now)"
            ),
            {
                "episode": fixture["episode_id"],
                "entry": entry_a,
                "watched": values["watched_date"],
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO release_events
                    (id, entry_id, season_id, episode_id, event_type, effective_date,
                     dedupe_key, first_seen_at, updated_at)
                VALUES
                    ('60000000-0000-0000-0000-000000000009', :entry, :season, :episode,
                     'episode_announced', '2025-06-07', 'legacy-release-event', :now, :now)
                """
            ),
            {
                "entry": entry_a,
                "season": fixture["season_id"],
                "episode": fixture["episode_id"],
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO integration_connections
                    (id, provider_slug, label, enabled, configuration, remote_profile,
                     capabilities, schedule, failure_count, created_at, updated_at)
                VALUES
                    ('60000000-0000-0000-0000-000000000010', 'fixture',
                     'Legacy private connection', 1, '{"region":"US"}', '{}',
                     '{"pull":"on"}', :schedule, 0, :now, :now)
                """
            ),
            {"schedule": '{"hours":12}', "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO calendar_feed_tokens "
                "(id, token_hash, created_at) VALUES "
                "('60000000-0000-0000-0000-000000000011', :hash, :now)"
            ),
            {"hash": values["token_hash"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO media_lists (id, name, created_at, updated_at, "
                "pinned_to_navigation) VALUES "
                "('60000000-0000-0000-0000-000000000012', 'Legacy list', :now, :now, 1)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO media_list_items (id, list_id, entry_id, added_at) VALUES "
                "('60000000-0000-0000-0000-000000000013', "
                "'60000000-0000-0000-0000-000000000012', :entry, :now)"
            ),
            {"entry": entry_a, "now": now},
        )

    preserved_tables = (
        "catalog_items",
        "watch_entries",
        "viewing_events",
        "audit_events",
        "import_previews",
        "import_history",
        "rating_assessments",
        "rating_comparisons",
        "rating_refinement_runs",
        "series_tracking_subscriptions",
        "season_records",
        "episode_records",
        "episode_viewings",
        "release_events",
        "integration_connections",
        "calendar_feed_tokens",
        "media_lists",
        "media_list_items",
    )
    with engine.connect() as connection:
        counts_before = {
            table: connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in preserved_tables
        }

    command.upgrade(config, "head")
    owned_tables = (
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
    with engine.connect() as connection:
        counts_after = {
            table: connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            for table in preserved_tables
        }
        assert counts_after == counts_before
        migrated_user = connection.execute(
            text("SELECT id, username, password_hash, role, state FROM user_accounts")
        ).one()
        assert migrated_user == (
            owner,
            "legacy-owner",
            "synthetic-password-hash",
            "admin",
            "active",
        )
        for table in owned_tables:
            assert connection.execute(text(f"SELECT DISTINCT user_id FROM {table}")).all() == [
                (owner,)
            ], table
        record = connection.execute(
            text(
                "SELECT notes, personal_rating, watched_date, poster_override_url "
                "FROM watch_entries WHERE id = :id"
            ),
            {"id": entry_a},
        ).one()
        assert record == (
            values["note"],
            9.25,
            values["watched_date"],
            values["poster_override_url"],
        )
        assert (
            connection.scalar(text("SELECT private_reflection FROM rating_assessments"))
            == values["reflection"]
        )
        assert connection.execute(
            text("SELECT id, catalog_item_id FROM season_records")
        ).one() == (fixture["season_id"], catalog_a)
        assert (
            connection.scalar(text("SELECT token_hash FROM calendar_feed_tokens"))
            == values["token_hash"]
        )

    command.downgrade(config, "0011")
    inspector = inspect(engine)
    assert "user_accounts" not in inspector.get_table_names()
    assert "user_id" not in {
        column["name"] for column in inspector.get_columns("watch_entries")
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, entry_id FROM season_records")).one() == (
            fixture["season_id"],
            entry_a,
        )
        assert (
            connection.scalar(
                text("SELECT poster_override_url FROM catalog_items WHERE id = :id"),
                {"id": catalog_a},
            )
            == values["poster_override_url"]
        )


def test_multi_owner_downgrade_refuses_to_merge_private_records(tmp_path):
    path = tmp_path / "multi-owner-downgrade.sqlite3"
    url = f"sqlite:///{path}"
    config = alembic_config(url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    second_id = "90000000-0000-0000-0000-000000000002"
    with Session(engine) as session, session.begin():
        session.add(
            UserAccount(
                id=second_id,
                username="second",
                normalized_username="second",
                display_name="Second",
                role="member",
                state="active",
                locale="en",
                timezone="UTC",
            )
        )
        first_catalog = CatalogItem(
            canonical_title="First owner title",
            normalized_title="first owner title",
            media_type="movie",
        )
        second_catalog = CatalogItem(
            canonical_title="Second owner title",
            normalized_title="second owner title",
            media_type="movie",
        )
        session.add_all(
            (
                WatchEntry(
                    user_id=LOCAL_USER_ID,
                    catalog_item=first_catalog,
                    status="watched",
                ),
                WatchEntry(
                    user_id=second_id,
                    catalog_item=second_catalog,
                    status="watched",
                ),
            )
        )

    with pytest.raises(RuntimeError, match="multiple users own private records"):
        command.downgrade(config, "0012")
    assert database_revision(url) == "0015"


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
    assert "if (passwordInput) passwordInput.value" in javascript
    assert "event.currentTarget.querySelector(\"[name='password']\")" not in javascript
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
