from __future__ import annotations

from conftest import manual_payload
from sqlalchemy import select

from watchtracker.models import CatalogItem
from watchtracker.services.sync_contract import build_platform_sync_snapshot


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
    assert snapshot.version == 1
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
    catalog_record = next(
        record
        for record in snapshot.records
        if record.record_type == "catalog" and record.record_id == entry["catalog_item"]["id"]
    )
    assert catalog_record.payload["external_ids"] == {
        "imdb": "tt123",
        "tvmaze": "123",
    }
    assert {record.record_type for record in snapshot.records} >= {
        "catalog",
        "entry",
        "list",
        "list_item",
    }
