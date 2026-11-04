"""Performance work must not weaken identity, ownership or private-data boundaries."""

import asyncio
import json
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from test_collection_metadata_fill import create, setup_fill

from watchtracker.authorization import LOCAL_USER_ID
from watchtracker.models import MusicAlbum, ScheduledJob
from watchtracker.music.provider import PublicCatalogClient
from watchtracker.services.catalog_cache import CatalogDiskCache, CatalogLane, catalog_work


def test_catalog_disk_restart_negative_retry_and_corruption(tmp_path):
    calls = []
    data = {"release-groups": []}

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json=data)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
            first = PublicCatalogClient(http)
            first.configure_cache(tmp_path)
            assert await first._get("release-group", query="synthetic") == data
            second = PublicCatalogClient(http)
            second.configure_cache(tmp_path)
            assert await second._get("release-group", query="synthetic") == data
            assert len(calls) == 1
            data["release-groups"].append({"id": str(uuid4()), "title": "Synthetic"})
            with catalog_work(retry=True):
                assert await second._get("release-group", query="synthetic") == data
            assert len(calls) == 2
            third = PublicCatalogClient(http)
            third.configure_cache(tmp_path)
            cached = await third._get("release-group", query="synthetic")
            cached["release-groups"].clear()
            assert (await third._get("release-group", query="synthetic"))["release-groups"]
            path = next((tmp_path / "public-catalog-v1").glob("*.json"))
            path.write_text("not JSON")
            fourth = PublicCatalogClient(http)
            fourth.configure_cache(tmp_path)
            assert await fourth._get("release-group", query="synthetic") == data
            assert len(calls) == 3

    asyncio.run(scenario())


def test_catalog_lane_interactive_priority_and_bounded_fairness():
    async def scenario():
        lane, order, release = CatalogLane(), [], asyncio.Event()

        async def task(name, background=False):
            with catalog_work(background=background):
                async with lane.acquire():
                    order.append(name)
                    if name == "first":
                        await release.wait()

        first = asyncio.create_task(task("first", True))
        await asyncio.sleep(0)
        bulk = asyncio.create_task(task("bulk", True))
        foreground = [asyncio.create_task(task(f"ui-{n}")) for n in range(7)]
        await asyncio.sleep(0)
        cancelled = asyncio.create_task(task("cancelled"))
        await asyncio.sleep(0)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        release.set()
        await asyncio.gather(first, bulk, *foreground)
        assert order == [
            "first",
            "ui-0",
            "ui-1",
            "ui-2",
            "ui-3",
            "bulk",
            "ui-4",
            "ui-5",
            "ui-6",
        ]
        assert not lane.waiters and not lane.active

    asyncio.run(scenario())


def test_catalog_limits_symlinks_ttl_and_no_cached_rate_limit(tmp_path):
    cache = CatalogDiskCache(tmp_path)
    cache.MAX_FILES = 2
    cache.MAX_BYTES = 1500
    for number in range(4):
        cache.write(f"{number:064x}", {"title": "Fixture" * 40})
    assert len(list(cache.directory.glob("*.json"))) <= 2
    key = "a" * 64
    saved = cache.write(key, {"images": []})
    assert 890 < saved["expires"] - time.time() <= 900
    assert not cache.read(key, retry=True)
    assert cache.read(key)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(saved))
    (cache.directory / f"{key}.json").unlink()
    (cache.directory / f"{key}.json").symlink_to(outside)
    assert cache.read(key) is None

    async def scenario():
        with httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "30"})
        ) as transport:
            async with httpx.AsyncClient(transport=transport) as http:
                provider = PublicCatalogClient(http)
                provider.configure_cache(tmp_path / "rate")
                from watchtracker.metadata.http import ProviderError

                with pytest.raises(ProviderError):
                    await provider._get("release-group", query="fixture")
                assert not provider.cache
                assert not provider.disk_cache.directory.exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ["music", "books"])
def test_manual_review_opt_out_is_versioned_and_does_not_fake_success(client, domain):
    service, _, _ = setup_fill(client, domain)
    entry, path = create(client, domain)
    endpoint = f"/api/collections/{domain}/review/{entry['id']}"
    response = client.post(endpoint, json={"version": entry["version"], "action": "manual"})
    assert response.status_code == 200, response.text
    assert service.schedule(LOCAL_USER_ID, domain)["pending"] == 0
    unchanged = client.get(f"{path}/{entry['id']}").json()
    for name in entry:
        if name not in {"created_at", "updated_at"}:
            assert unchanged[name] == entry[name]
    assert not unchanged["provider_id"]
    response = client.post(
        endpoint,
        json={
            "version": entry["version"],
            "action": "spelling",
            "title": "Corrected Synthetic",
            "creator": "Complete Credited Creator",
        },
    )
    assert response.status_code == 200, response.text
    assert service.schedule(LOCAL_USER_ID, domain)["pending"] == 1
    assert (
        client.post(
            endpoint, json={"version": entry["version"], "action": "manual"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("domain", ["music", "books"])
def test_review_apply_preserves_personal_fields_and_rejects_concurrent_change(client, domain):
    _, provider, _ = setup_fill(client, domain)
    entry, path = create(client, domain, favorite=True)
    provider.data = {
        "title": "Verified Synthetic",
        provider.creator: "Verified Creator",
        "provider_id": provider.identifier,
    }
    endpoint = f"/api/collections/{domain}/review/{entry['id']}"
    response = client.post(
        endpoint,
        json={
            "version": entry["version"],
            "action": "apply",
            "provider_id": provider.identifier,
        },
    )
    assert response.status_code == 200, response.text
    result = client.get(f"{path}/{entry['id']}").json()
    assert result["provider_id"] == provider.identifier
    assert result[provider.creator] == "Verified Creator"
    for key in ("notes", "tags", "rating", "status", "favorite"):
        assert result[key] == entry[key]
    assert (
        client.post(
            endpoint,
            json={
                "version": entry["version"],
                "action": "apply",
                "provider_id": provider.identifier,
            },
        ).status_code
        == 409
    )


@pytest.mark.parametrize("domain", ["music", "books"])
def test_thin_page_does_not_transfer_large_personal_fields(client, domain):
    entry, path = create(client, domain, notes="Private note " * 1000)
    row = client.get(path).json()["items"][0]
    assert row["id"] == entry["id"]
    assert {"notes", "artwork_data", "tracks", "chapters", "description"}.isdisjoint(row)
    assert client.get(f"{path}/{entry['id']}").json()["notes"] == entry["notes"]


def test_clear_cover_cache_preserves_uploads_and_unknown_files(client, tmp_path):
    cache = client.app.state.collection_artwork
    cache.directory.mkdir(parents=True, exist_ok=True)
    generated = cache.directory / ("a" * 64 + ".jpg")
    generated.write_bytes(b"cached")
    personal = cache.directory / "do-not-delete.json"
    personal.write_text("keep")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"keep")
    (cache.directory / ("b" * 64 + ".jpg")).symlink_to(outside)
    before = client.get("/api/collections/cache").json()
    assert before["files"] == 1 and before["can_clear"]
    assert client.delete("/api/collections/cache").status_code == 200
    assert not generated.exists()
    assert personal.read_text() == "keep" and outside.read_bytes() == b"keep"


def test_missing_provider_fields_checked_once_and_retry_is_explicit(client):
    service, provider, runner = setup_fill(client, "music")
    entry, _ = create(client, "music")
    provider.results = []
    service.schedule(LOCAL_USER_ID, "music")
    client.portal.call(runner.run_once)
    assert service.schedule(LOCAL_USER_ID, "music")["pending"] == 0
    assert service.schedule(LOCAL_USER_ID, "music", retry_review=True)["pending"] == 1
    with client.app.state.session_factory() as session:
        row = session.get(MusicAlbum, entry["id"])
        checkpoint = session.scalar(
            select(ScheduledJob).where(ScheduledJob.kind == "collection.resolution")
        )
        assert checkpoint.payload["version"] == row.version
