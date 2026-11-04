"""Personal undated progress, favorites ordering and portable glass preferences."""

import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from conftest import manual_payload
from test_releases import _follow, _series

from watchtracker.models import EpisodeRecord, WatchEntry
from watchtracker.schemas import CatalogData
from watchtracker.services.entries import replace_catalog_from_trusted_provider


@pytest.mark.parametrize("assumed_watched", [False, True])
def test_undated_episodes_can_be_marked_cleared_and_reloaded(app, client, assumed_watched):
    entry = _series(client)
    _follow(client, entry["id"])
    detail = client.post(f"/api/series/{entry['id']}/sync").json()
    season = next(s for s in detail["seasons"] if s["season_number"] == 1)
    first, second, future = season["episodes"]
    with app.state.session_factory() as session:
        for episode in (first, second):
            session.get(EpisodeRecord, episode["id"]).air_date = None
        if assumed_watched:
            row = session.get(WatchEntry, entry["id"])
            row.status = "watched"
            row.episode_progress_explicit = False
        session.commit()
    marked = client.put(f"/api/episodes/{first['id']}/viewing", json={})
    assert marked.status_code == 200, marked.text
    assert marked.json()["progress"]["watched"] >= 1
    assert client.put(f"/api/episodes/{future['id']}/viewing", json={}).status_code == 409
    completed = client.put(
        f"/api/seasons/{season['id']}/viewing", json={"watched": True, "confirmed": True}
    )
    assert completed.status_code == 200
    viewed = next(s for s in completed.json()["seasons"] if s["id"] == season["id"])
    assert [e["watched"] for e in viewed["episodes"]] == [True, True, False]
    # Unknown dates never turn into invented dates or upcoming-release alerts.
    assert viewed["episodes"][0]["air_date"] is None
    card = client.get(f"/api/entries/{entry['id']}").json()
    assert card["episode_progress"]["watched"] >= 2
    assert card["episode_progress"]["total"] >= 2
    released_count = completed.json()["progress"]["released"]
    assert released_count == 1  # Only the dated special from the fixture.
    again = client.put(f"/api/episodes/{first['id']}/viewing", json={}).json()
    assert again["progress"] == completed.json()["progress"]
    cleared = client.delete(f"/api/episodes/{first['id']}/viewing").json()
    assert cleared["progress"]["watched"] == again["progress"]["watched"] - 1
    reloaded = client.get(f"/api/series/{entry['id']}").json()
    assert reloaded["progress"] == cleared["progress"]
    reset = client.put(
        f"/api/seasons/{season['id']}/viewing", json={"watched": False, "confirmed": True}
    ).json()
    assert next(s for s in reset["seasons"] if s["id"] == season["id"])["watched_count"] == 0
    assert client.get(f"/api/entries/{entry['id']}").json()["view_count"] == entry["view_count"]


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
def test_favorites_sort_is_global_paginated_order_not_a_filter(client, domain):
    path = (
        "/api/entries"
        if domain == "screen"
        else f"/api/{domain}/{'albums' if domain == 'music' else 'entries'}"
    )
    ids = []
    for name, favorite in [("A ordinary", False), ("Z favorite", True), ("B favorite", True)]:
        if domain == "screen":
            result = client.post(path + "/manual", json=manual_payload(name))
            row = result.json()["entry"]
            assert (
                client.patch(path + "/" + row["id"], json={"is_favorite": favorite}).status_code
                == 200
            )
        else:
            result = client.post(
                path,
                json={
                    "title": name,
                    "artist" if domain == "music" else "author": "Example",
                    "favorite": favorite,
                },
            )
            row = result.json()
        assert result.status_code == 201, result.text
        ids.append(row["id"])
    descending = client.get(
        path, params={"sort": "favorites", "direction": "desc", "page_size": 2}
    ).json()
    assert descending["total"] == 3
    assert [r["id"] for r in descending["items"]] == [ids[2], ids[1]]
    assert (
        client.get(
            path, params={"sort": "favorites", "direction": "desc", "page_size": 2, "page": 2}
        ).json()["items"][0]["id"]
        == ids[0]
    )
    assert (
        client.get(path, params={"sort": "favorites", "direction": "asc"}).json()["items"][0][
            "id"
        ]
        == ids[0]
    )


def test_interface_transparency_survives_export_and_validates_range(client):
    assert (
        client.put("/api/settings/general", json={"interface_transparency": 82}).status_code
        == 200
    )
    assert client.get("/api/settings/general").json()["interface_transparency"] == 82
    archive = client.get("/api/exports/portable-library.zip")
    assert archive.status_code == 200
    with ZipFile(BytesIO(archive.content)) as content:
        assert (
            json.loads(content.read("settings/preferences.json"))["interface_transparency"]
            == 82
        )
    for value in (-1, 101):
        assert (
            client.put(
                "/api/settings/general", json={"interface_transparency": value}
            ).status_code
            == 422
        )


def test_metadata_refresh_keeps_cached_undated_progress(app, client):
    entry = _series(client)
    _follow(client, entry["id"])
    data = client.post(f"/api/series/{entry['id']}/sync").json()
    season = next(s for s in data["seasons"] if s["season_number"] == 1)
    first = season["episodes"][0]
    with app.state.session_factory() as session:
        for episode in season["episodes"][:2]:
            session.get(EpisodeRecord, episode["id"]).air_date = None
        session.get(WatchEntry, entry["id"]).catalog_item.released_episode_count = 0
        session.commit()
    assert client.put(f"/api/episodes/{first['id']}/viewing", json={}).status_code == 200
    before = client.get(f"/api/entries/{entry['id']}").json()["episode_progress"]
    assert before == {"watched": 1, "total": 2}
    with app.state.session_factory() as session:
        catalog = session.get(WatchEntry, entry["id"]).catalog_item
        replace_catalog_from_trusted_provider(
            session,
            catalog,
            CatalogData(
                canonical_title="Refreshed series",
                media_type="tv",
                episode_count=3,
                provider_source="tmdb_tv",
                provider_id="9001",
                tmdb_tv_id="9001",
            ),
        )
        session.commit()
    assert client.get(f"/api/entries/{entry['id']}").json()["episode_progress"] == before
    # The tile's own stepper uses the same undated-episode eligibility rule.
    result = client.patch(f"/api/entries/{entry['id']}", json={"episode_progress_count": 2})
    assert result.status_code == 200, result.text
    assert result.json()["episode_progress"] == {"watched": 2, "total": 2}
