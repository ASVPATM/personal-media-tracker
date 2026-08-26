from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO

import httpx
import pytest
from conftest import manual_payload
from sqlalchemy import func, select

from watchtracker.metadata import ProviderUnavailable
from watchtracker.metadata.cache import TTLCache
from watchtracker.metadata.http import ProviderError, ResilientHttpClient
from watchtracker.metadata.providers import TMDbClient
from watchtracker.models import (
    CatalogItem,
    EpisodeRecord,
    EpisodeViewing,
    ReleaseEvent,
    SeasonRecord,
    SyncJob,
)


def _series(client, title="Release Series", provider_id="9001"):
    response = client.post(
        "/api/entries/manual",
        json=manual_payload(
            title,
            media_type="tv",
            status="watching",
            provider_source="tmdb_tv",
            provider_id=provider_id,
            tmdb_tv_id=provider_id,
        ),
    )
    assert response.status_code == 201
    return response.json()["entry"]


def _follow(client, entry_id, **overrides):
    payload = {
        "notify_new_episode": True,
        "notify_new_season": True,
        "include_specials": False,
        **overrides,
    }
    response = client.put(f"/api/series/{entry_id}/subscription", json=payload)
    assert response.status_code == 200
    return response.json()


def test_follow_sync_progress_up_next_and_explicit_episode_actions(app, client):
    movie = client.post("/api/entries/manual", json=manual_payload("Movie")).json()["entry"]
    unsupported = client.put(f"/api/series/{movie['id']}/subscription", json={})
    assert unsupported.status_code == 409

    entry = _series(client)
    subscription = _follow(client, entry["id"])
    assert subscription["last_success_at"] is None
    synced = client.post(f"/api/series/{entry['id']}/sync")
    assert synced.status_code == 200
    detail = synced.json()
    assert [season["season_number"] for season in detail["seasons"]] == [0, 1]
    assert detail["progress"] == {"watched": 0, "released": 3, "total": 4}
    assert detail["up_next"]["title"] == "Released"
    assert client.get(f"/api/entries/{entry['id']}").json()["status"] == "watching"

    season = next(item for item in detail["seasons"] if item["season_number"] == 1)
    first, second = season["episodes"][:2]
    marked = client.put(f"/api/episodes/{first['id']}/viewing", json={}).json()
    assert marked["up_next"]["id"] == second["id"]
    assert marked["progress"]["watched"] == 1
    assert client.get(f"/api/entries/{entry['id']}").json()["view_count"] == 0
    assert (
        client.put(f"/api/seasons/{season['id']}/viewing", json={"watched": True}).status_code
        == 422
    )
    completed = client.put(
        f"/api/seasons/{season['id']}/viewing",
        json={"watched": True, "confirmed": True},
    ).json()
    assert completed["progress"]["watched"] == 3
    assert completed["up_next"] is None
    _follow(client, entry["id"], include_specials=True)
    specials_enabled = client.get(f"/api/series/{entry['id']}").json()
    assert specials_enabled["up_next"]["title"] == "A Special"
    assert client.delete(f"/api/episodes/{first['id']}/viewing").status_code == 200
    assert client.get(f"/api/entries/{entry['id']}").json()["status"] == "watching"

    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(SeasonRecord.id))) == 2
        assert session.scalar(select(func.count(EpisodeRecord.id))) == 4
        assert session.scalar(select(func.count(EpisodeViewing.id))) == 2


def test_episode_support_reads_provider_neutral_identity_ledger(app, client):
    entry = _series(client, "Ledger-backed Series", "ledger-9001")
    with app.state.session_factory() as session:
        catalog = session.get(CatalogItem, entry["catalog_item"]["id"])
        catalog.provider_source = "kitsu"
        catalog.provider_id = "anime-1"
        catalog.tmdb_tv_id = None
        session.commit()

    detail = client.get(f"/api/series/{entry['id']}")

    assert detail.status_code == 200
    assert detail.json()["supported"] is True
    assert detail.json()["provider_source"] == "tmdb_tv"


def test_sync_is_idempotent_updates_records_and_preserves_cache_on_failure(app, client, today):
    entry = _series(client, "Mutable Series", "9002")
    _follow(client, entry["id"])
    assert client.post(f"/api/series/{entry['id']}/sync").status_code == 200
    assert client.post(f"/api/series/{entry['id']}/sync").status_code == 200
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(SeasonRecord.id)).where(SeasonRecord.entry_id == entry["id"])
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(EpisodeRecord.id))
                .join(SeasonRecord)
                .where(SeasonRecord.entry_id == entry["id"])
            )
            == 4
        )
        assert session.scalar(select(func.count(ReleaseEvent.id))) == 2

    original = app.state.metadata.series_schedule

    async def changed(provider: str, provider_id: str, *, refresh: bool = False):
        payload = await original(provider, provider_id, refresh=refresh)
        season = payload["seasons"][1]
        season["episodes"][1]["title"] = "Renamed, not duplicated"
        season["episodes"][1]["air_date"] = today.isoformat()
        season["episodes"][1]["episode_number"] = 7
        season["episodes"] = season["episodes"][1:]
        season["episode_count"] = 2
        season["episodes"].append(
            {
                "provider_episode_id": "episode-new",
                "episode_number": 4,
                "title": "Newly announced",
                "air_date": (today + timedelta(days=4)).isoformat(),
            }
        )
        payload["seasons"].append(
            {
                "provider_season_id": "season-2",
                "season_number": 2,
                "title": "Season 2",
                "air_date": None,
                "episode_count": 1,
                "episodes": [
                    {
                        "provider_episode_id": "season-2-episode-1",
                        "episode_number": 1,
                        "title": "A new season, not a status change",
                        "air_date": (today + timedelta(days=30)).isoformat(),
                    }
                ],
            }
        )
        return payload

    app.state.metadata.series_schedule = changed
    updated = client.post(f"/api/series/{entry['id']}/sync").json()
    season = next(item for item in updated["seasons"] if item["season_number"] == 1)
    assert any(item["title"] == "Renamed, not duplicated" for item in season["episodes"])
    assert (
        next(item for item in season["episodes"] if item["title"] == "Renamed, not duplicated")[
            "episode_number"
        ]
        == 7
    )
    assert any(item["season_number"] == 2 for item in updated["seasons"])
    assert client.get(f"/api/entries/{entry['id']}").json()["status"] == "watching"
    with app.state.session_factory() as session:
        removed = session.scalar(
            select(EpisodeRecord).where(EpisodeRecord.provider_episode_id == "episode-1")
        )
        assert removed.removed_at is not None
        assert (
            session.scalar(
                select(func.count(EpisodeRecord.id))
                .join(SeasonRecord)
                .where(SeasonRecord.entry_id == entry["id"])
            )
            == 6
        )

    async def unavailable(_provider: str, _provider_id: str, *, refresh: bool = False):
        del refresh
        raise ProviderUnavailable("TMDb is temporarily unavailable.")

    app.state.metadata.series_schedule = unavailable
    failed = client.post(f"/api/series/{entry['id']}/sync")
    assert failed.status_code == 503
    retained = client.get(f"/api/series/{entry['id']}").json()
    assert retained["seasons"]
    assert retained["subscription"]["last_error_code"] == "provider_unavailable"
    assert retained["subscription"]["failure_count"] == 1
    app.state.metadata.series_schedule = original


def test_upcoming_notifications_ical_unfollow_and_backup_counts(app, client, today):
    entry = _series(client, "Calendar Series", "9003")
    _follow(client, entry["id"])
    original = app.state.metadata.series_schedule

    async def calendar_payload(provider: str, provider_id: str, *, refresh: bool = False):
        payload = await original(provider, provider_id, refresh=refresh)
        payload["seasons"] = [payload["seasons"][1]]
        payload["seasons"][0]["episodes"] = [
            {
                "provider_episode_id": "calendar-1",
                "episode_number": 1,
                "title": "Tomorrow",
                "air_date": (today + timedelta(days=1)).isoformat(),
            }
        ]
        payload["seasons"][0]["episode_count"] = 1
        return payload

    app.state.metadata.series_schedule = calendar_payload
    client.post(f"/api/series/{entry['id']}/sync")
    client.post(f"/api/series/{entry['id']}/sync")
    upcoming = client.get("/api/releases/upcoming", params={"days": 7}).json()
    assert upcoming["items"][0]["kind"] == "air_date"
    assert "not streaming availability" in upcoming["disclaimer"]
    ical = client.get("/api/exports/upcoming-releases.ics")
    assert ical.headers["content-type"].startswith("text/calendar")
    assert "Tomorrow" not in ical.text  # private provider title is intentionally omitted
    assert "Calendar Series" in ical.text
    assert "streaming availability" in ical.text

    async def released_payload(provider: str, provider_id: str, *, refresh: bool = False):
        payload = await calendar_payload(provider, provider_id, refresh=refresh)
        payload["seasons"][0]["episodes"][0]["air_date"] = today.isoformat()
        return payload

    app.state.metadata.series_schedule = released_payload
    client.post(f"/api/series/{entry['id']}/sync")
    notifications = client.get("/api/releases/notifications").json()
    assert notifications["unread"] >= 1
    event = notifications["items"][0]
    read = client.patch(
        f"/api/releases/notifications/{event['id']}", json={"action": "read"}
    ).json()
    assert read["unread"] == notifications["unread"] - 1
    client.patch(f"/api/releases/notifications/{event['id']}", json={"action": "dismiss"})

    archive = client.get("/api/exports/portable-library.zip")
    with zipfile.ZipFile(BytesIO(archive.content)) as source:
        manifest = json.loads(source.read("manifest.json"))
    assert manifest["database"]["series_subscriptions"] >= 1
    assert manifest["database"]["episodes"] >= 1
    assert manifest["database"]["release_events"] >= 1
    assert client.delete(f"/api/series/{entry['id']}/subscription").status_code == 204
    assert client.get("/api/releases/upcoming", params={"days": 7}).json()["items"] == []
    assert client.post("/api/releases/sync").status_code == 200
    assert client.get(f"/api/series/{entry['id']}").json()["subscription"]["enabled"] is False
    assert client.get(f"/api/series/{entry['id']}").json()["seasons"]
    app.state.metadata.series_schedule = original


def test_library_release_check_discovers_only_confirmed_active_shows(app, client, today):
    entry = _series(client, "Discovered Active Series", "9010")
    original = app.state.metadata.series_schedule

    async def active_payload(provider: str, provider_id: str, *, refresh: bool = False):
        payload = await original(provider, provider_id, refresh=refresh)
        payload["seasons"] = [payload["seasons"][1]]
        payload["seasons"][0]["episodes"] = [
            {
                "provider_episode_id": "active-tomorrow",
                "episode_number": 4,
                "title": "Announced tomorrow",
                "air_date": (today + timedelta(days=1)).isoformat(),
            }
        ]
        payload["seasons"][0]["episode_count"] = 1
        return payload

    app.state.metadata.series_schedule = active_payload
    assert client.get("/api/releases/active-shows", params={"days": 60}).json()["items"] == []
    checked = client.post("/api/releases/sync")
    assert checked.status_code == 200
    assert checked.json()["synced"] == 1

    active = client.get("/api/releases/active-shows", params={"days": 60}).json()
    assert active["total"] == 1
    assert active["items"][0]["id"] == entry["id"]
    assert "not streaming availability" in active["disclaimer"]
    subscription = client.get(f"/api/series/{entry['id']}").json()["subscription"]
    assert subscription["enabled"] is True
    assert subscription["notify_new_episode"] is False
    assert subscription["notify_new_season"] is False

    async def distant_payload(provider: str, provider_id: str, *, refresh: bool = False):
        payload = await active_payload(provider, provider_id, refresh=refresh)
        payload["seasons"][0]["episodes"][0]["air_date"] = (
            today + timedelta(days=61)
        ).isoformat()
        return payload

    app.state.metadata.series_schedule = distant_payload
    assert client.post("/api/releases/sync").status_code == 200
    assert client.get("/api/releases/active-shows", params={"days": 60}).json()["items"] == []
    app.state.metadata.series_schedule = original


def test_manual_library_release_check_is_not_limited_to_background_batch(app, client, today):
    first = _series(client, "Earlier Series", "9011")
    _follow(client, first["id"])
    newest = _series(client, "New Ongoing Series", "9012")
    original = app.state.metadata.series_schedule
    original_batch_size = app.state.release_scheduler.batch_size

    async def active_payload(provider: str, provider_id: str, *, refresh: bool = False):
        payload = await original(provider, provider_id, refresh=refresh)
        payload["seasons"] = [payload["seasons"][1]]
        payload["seasons"][0]["episodes"] = [
            {
                "provider_episode_id": f"active-{provider_id}",
                "episode_number": 1,
                "title": "Next episode",
                "air_date": (today + timedelta(days=1)).isoformat(),
            }
        ]
        payload["seasons"][0]["episode_count"] = 1
        return payload

    app.state.metadata.series_schedule = active_payload
    app.state.release_scheduler.batch_size = 1
    try:
        checked = client.post("/api/releases/sync")
        assert checked.status_code == 200
        assert checked.json()["total"] == 2
        assert checked.json()["synced"] == 2
        active_ids = {
            item["id"]
            for item in client.get("/api/releases/active-shows", params={"days": 60}).json()[
                "items"
            ]
        }
        assert newest["id"] in active_ids
    finally:
        app.state.metadata.series_schedule = original
        app.state.release_scheduler.batch_size = original_batch_size


def test_scheduler_lease_prevents_overlap(app, client):
    # Manual mode does not create a scheduler row until the owner asks for a check.
    assert client.post("/api/releases/sync").json()["status"] == "completed"
    now = datetime.now(UTC)
    with app.state.session_factory() as session:
        job = session.scalar(select(SyncJob).where(SyncJob.name == "release-sync"))
        assert job is not None
        job.owner_id = "another-process"
        job.lease_until = now + timedelta(minutes=5)
        job.state = "running"
        session.commit()
    response = client.post("/api/releases/sync")
    assert response.status_code == 200
    assert response.json()["status"] == "already_running"


@pytest.mark.asyncio
async def test_tmdb_series_schedule_uses_series_and_season_details(tmp_path):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request.url.path)
        if request.url.path == "/3/tv/42":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "status": "Returning Series",
                    "seasons": [
                        {"id": 100, "season_number": 0, "name": "Specials"},
                        {"id": 101, "season_number": 1, "name": "Season 1"},
                    ],
                },
            )
        number = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(
            200,
            json={
                "id": 100 + number,
                "season_number": number,
                "name": "Specials" if number == 0 else "Season 1",
                "air_date": None if number == 0 else "2026-01-01",
                "episodes": [
                    {
                        "id": 500 + number,
                        "episode_number": None if number == 0 else 1,
                        "name": "Partial episode",
                        "air_date": None,
                        "runtime": None,
                    },
                    {"bad": "malformed row without stable id"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        tmdb = TMDbClient(
            "secret", ResilientHttpClient(raw, attempts=1), TTLCache(tmp_path), "en-US", "US"
        )
        result = await tmdb.series_schedule("42", refresh=True)
    assert requests == ["/3/tv/42", "/3/tv/42/season/0", "/3/tv/42/season/1"]
    assert result["seasons"][0]["air_date"] is None
    assert result["seasons"][0]["episodes"][0]["episode_number"] is None
    assert len(result["seasons"][1]["episodes"]) == 1


@pytest.mark.asyncio
async def test_release_provider_honors_rate_backoff_and_bounds_timeouts(tmp_path):
    calls = 0
    sleeps = []

    def rate_limited(_request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.05"})
        return httpx.Response(200, json={"id": 42, "seasons": []})

    async def fake_sleep(delay):
        sleeps.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_limited)) as raw:
        tmdb = TMDbClient(
            "secret",
            ResilientHttpClient(raw, attempts=2, sleep=fake_sleep),
            TTLCache(tmp_path / "rate"),
            "en-US",
            "US",
        )
        result = await tmdb.series_schedule("42", refresh=True)
    assert result["seasons"] == []
    assert calls == 2
    assert sleeps == [0.05]

    timeout_calls = 0

    def timeout(request: httpx.Request):
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as raw:
        tmdb = TMDbClient(
            "secret",
            ResilientHttpClient(raw, attempts=2, base_delay=0, sleep=fake_sleep),
            TTLCache(tmp_path / "timeout"),
            "en-US",
            "US",
        )
        with pytest.raises(ProviderError) as caught:
            await tmdb.series_schedule("42", refresh=True)
    assert caught.value.retryable is True
    assert timeout_calls == 2
