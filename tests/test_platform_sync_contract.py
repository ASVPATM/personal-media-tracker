from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from conftest import FakeMetadata, MemoryKeyring, manual_payload
from fastapi.testclient import TestClient
from sqlalchemy import select

from watchtracker.app import create_app
from watchtracker.models import (
    CatalogItem,
    PlatformSyncImportBatch,
    PlatformSyncImportRecord,
    WatchEntry,
)
from watchtracker.services.secrets import SecretStore
from watchtracker.services.sync_contract import (
    PlatformSyncSnapshot,
    build_platform_sync_snapshot,
    import_platform_sync_snapshot,
)


def test_platform_sync_snapshot_is_versioned_and_excludes_replaceable_private_domains(
    app, client
):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Cross-platform title",
            provider_source="tvmaze",
            provider_id="123",
            external_ids={"tvmaze": "123", "imdb": "tt123"},
            raw_provider_payload={"provider_secret_value": "must-not-sync"},
            notes="A private note that is user-owned.",
            user_tags=["mobile"],
            is_favorite=True,
        ),
    ).json()["entry"]
    media_list = client.post("/api/lists", json={"name": "On phone"}).json()
    client.post(f"/api/lists/{media_list['id']}/entries/{entry['id']}")

    with app.state.session_factory() as session:
        catalog = session.scalar(
            select(CatalogItem).where(CatalogItem.id == entry["catalog_item"]["id"])
        )
        assert catalog.raw_provider_payload["provider_secret_value"] == "must-not-sync"
        snapshot = build_platform_sync_snapshot(session)

    assert snapshot.contract == "pmt.platform-sync"
    assert snapshot.version == 2
    assert snapshot.source.product == "pmt-desktop-web"
    assert "credentials" in snapshot.excluded_domains
    assert "private_developer_tools" in snapshot.excluded_domains
    serialized = snapshot.model_dump_json()
    assert "must-not-sync" not in serialized
    assert "raw_provider_payload" not in serialized
    assert "secret_reference" not in serialized
    entry_record = next(
        record
        for record in snapshot.records
        if record.record_type == "entry" and record.record_id == entry["id"]
    )
    assert entry_record.payload["notes"] == "A private note that is user-owned."
    identity_records = [
        record for record in snapshot.records if record.record_type == "external_identity"
    ]
    assert {
        (row.payload["namespace"], row.payload["external_id"]) for row in identity_records
    } == {
        ("imdb", "tt123"),
        ("tvmaze", "123"),
    }
    assert {record.record_type for record in snapshot.records} >= {
        "catalog",
        "entry",
        "list",
        "list_item",
    }
    assert all(record.origin_device_id for record in snapshot.records)
    assert all(record.origin_event_id for record in snapshot.records)
    assert all(record.created_at for record in snapshot.records)


def test_platform_sync_import_is_transactional_idempotent_and_keeps_unknown_dates(app, client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Undated portable title",
            status="watched",
            view_count=1,
            watched_date=None,
        ),
    ).json()["entry"]
    with app.state.session_factory() as session:
        snapshot = build_platform_sync_snapshot(session, device_id="fixture-desktop")
        viewing = next(row for row in snapshot.records if row.record_type == "viewing")
        viewing.payload["viewed_on"] = None
        entry_record = next(row for row in snapshot.records if row.record_type == "entry")
        entry_record.payload["watched_date"] = None
        snapshot.generated_at = snapshot.generated_at.replace(microsecond=0)
        first = import_platform_sync_snapshot(session, snapshot)
        assert first.duplicate_snapshot is False
        second = import_platform_sync_snapshot(session, snapshot)
        assert second.duplicate_snapshot is True
        assert second.batch_id == first.batch_id
        stored = session.get(WatchEntry, entry["id"])
        assert stored is not None
        assert stored.watched_date is None
        assert (
            session.scalar(
                select(PlatformSyncImportBatch).where(
                    PlatformSyncImportBatch.id == first.batch_id
                )
            )
            is not None
        )


def test_platform_sync_fixture_accepts_unknown_future_record_with_warning():
    fixture = (
        __import__("pathlib").Path(__file__).parents[1]
        / "contracts/platform-sync/fixtures/tombstone-and-future.json"
    )
    snapshot = PlatformSyncSnapshot.model_validate_json(fixture.read_text())
    assert any(row.record_type == "future_private_annotation" for row in snapshot.records)
    assert any(row.deleted_at is not None for row in snapshot.records)


def test_platform_sync_round_trip_and_older_snapshot_cannot_restore_tombstone(
    app, client, settings, tmp_path
):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Round-trip fixture",
            status="watched",
            view_count=1,
            watched_date=None,
            notes="Portable user-owned note.",
            user_tags=["portable"],
        ),
    ).json()["entry"]
    media_list = client.post("/api/lists", json={"name": "Portable list"}).json()
    client.post(f"/api/lists/{media_list['id']}/entries/{entry['id']}")
    with app.state.session_factory() as session:
        source = build_platform_sync_snapshot(session, device_id="source-fixture")

    target_root = tmp_path / "round-trip-target"
    target_settings = settings.model_copy(
        update={
            "data_dir": target_root / "data",
            "config_dir": target_root / "config",
            "log_dir": target_root / "logs",
            "backups_dir": target_root / "backups",
            "database_path": target_root / "watchtracker.sqlite3",
            "cache_dir": target_root / "cache",
            "env_path": target_root / ".env",
        }
    )
    target_app = create_app(
        target_settings,
        metadata_service=FakeMetadata(),
        secret_store=SecretStore(target_settings, keyring_backend=MemoryKeyring()),
    )
    with TestClient(target_app):
        with target_app.state.session_factory() as target_session:
            report = import_platform_sync_snapshot(target_session, source)
            outcomes = [
                (row.record_type, row.outcome, row.safe_message)
                for row in target_session.scalars(
                    select(PlatformSyncImportRecord).where(
                        PlatformSyncImportRecord.batch_id == report.batch_id
                    )
                )
            ]
            assert report.counts["applied"] == len(source.records), outcomes
            imported = build_platform_sync_snapshot(target_session, device_id="target-fixture")

        def portable(value):
            return {
                (row.record_type, row.record_id): (
                    row.relationships,
                    row.payload,
                    row.deleted_at,
                )
                for row in value.records
            }

        assert portable(imported) == portable(source)

        assert client.delete(f"/api/entries/{entry['id']}").status_code == 204
        with app.state.session_factory() as source_session:
            tombstone = build_platform_sync_snapshot(source_session, device_id="source-fixture")
        with target_app.state.session_factory() as target_session:
            import_platform_sync_snapshot(target_session, tombstone)
            older_with_new_envelope = source.model_copy(deep=True)
            older_with_new_envelope.generated_at += timedelta(seconds=1)
            old_report = import_platform_sync_snapshot(target_session, older_with_new_envelope)
            assert old_report.counts["skipped"] >= 1
            stored = target_session.get(WatchEntry, entry["id"])
            assert stored is not None and stored.deleted_at is not None


def test_platform_sync_dry_run_is_transactional_and_future_records_are_visible(app, client):
    fixture = Path(__file__).parents[1] / "contracts/platform-sync/fixtures/unknown-date.json"
    snapshot = PlatformSyncSnapshot.model_validate_json(fixture.read_text())
    future = PlatformSyncSnapshot.model_validate_json(
        (
            Path(__file__).parents[1]
            / "contracts/platform-sync/fixtures/tombstone-and-future.json"
        ).read_text()
    )
    with app.state.session_factory() as session:
        preview = import_platform_sync_snapshot(session, snapshot, dry_run=True)
        assert preview.counts["applied"] == 3
        assert session.get(CatalogItem, "10000000-0000-0000-0000-000000000001") is None
        report = import_platform_sync_snapshot(session, future)
        assert report.counts == {"applied": 2, "skipped": 1, "warnings": 1}
        assert "Unknown future record type" in report.warnings[0]
