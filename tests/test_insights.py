from __future__ import annotations

from io import BytesIO

from PIL import Image

from tests.conftest import manual_payload


def _add(client, title: str, **values):
    response = client.post("/api/entries/manual", json=manual_payload(title, **values))
    assert response.status_code == 201, response.text
    return response.json()["entry"]


def test_insights_use_one_filter_scope_and_exclude_undated_from_timeline(client):
    first = _add(
        client,
        "Dated Drama",
        status="watching",
        provider_genres=["Drama"],
        personal_rating=9,
        view_count=0,
        watched_date=None,
    )
    _add(
        client,
        "Imported Drama",
        provider_genres=["Drama"],
        personal_rating=7,
        view_count=2,
        watched_date=None,
    )
    event = client.post(
        f"/api/entries/{first['id']}/viewings", json={"viewed_on": "2025-03-02"}
    )
    assert event.status_code == 200

    all_time = client.get("/api/insights?period=all&genre=Drama")
    assert all_time.status_code == 200
    payload = all_time.json()
    assert payload["summary"]["titles_watched"] == 2
    assert payload["summary"]["title_viewings"] == 3
    assert payload["coverage"]["undated_events"] == 1
    assert payload["coverage"]["dated_events"] == 2

    dated = client.get(
        "/api/insights?period=custom&date_from=2025-03-01&date_to=2025-03-31&genre=Drama"
    )
    assert dated.status_code == 200
    scoped = dated.json()
    assert scoped["summary"]["titles_watched"] == 1
    assert scoped["previous_summary"] is not None
    assert scoped["ratings"]["rated_count"] == 1


def test_insights_offer_interactive_release_eras_without_watch_dates(client):
    _add(
        client,
        "Undated Eighties",
        release_year=1987,
        status="watching",
        view_count=2,
        watched_date=None,
    )
    _add(
        client,
        "Undated Modern",
        release_year=2022,
        status="watching",
        view_count=1,
        watched_date=None,
    )
    _add(
        client,
        "Undated Unknown",
        release_year=None,
        status="watching",
        view_count=1,
        watched_date=None,
    )

    payload = client.get("/api/insights?period=all").json()
    assert payload["coverage"]["dated_events"] == 0
    assert payload["activity"]["items"] == []
    assert payload["date_free_activity"] == {
        "kind": "release_era",
        "items": [
            {
                "key": "1980s",
                "release_year_from": 1980,
                "release_year_to": 1989,
                "release_year_unknown": False,
                "titles": 1,
            },
            {
                "key": "2020s",
                "release_year_from": 2020,
                "release_year_to": 2029,
                "release_year_unknown": False,
                "titles": 1,
            },
            {
                "key": "Year unknown",
                "release_year_from": None,
                "release_year_to": None,
                "release_year_unknown": True,
                "titles": 1,
            },
        ],
        "known_year_titles": 2,
        "unknown_year_titles": 1,
    }

    era = client.get(
        "/api/insights/titles?period=all&activity_only=true"
        "&release_year_from=1980&release_year_to=1989"
    )
    assert era.status_code == 200
    assert [item["catalog_item"]["canonical_title"] for item in era.json()["items"]] == [
        "Undated Eighties"
    ]
    unknown = client.get(
        "/api/insights/titles?period=all&activity_only=true&release_year_unknown=true"
    )
    assert [item["catalog_item"]["canonical_title"] for item in unknown.json()["items"]] == [
        "Undated Unknown"
    ]
    assert (
        client.get(
            "/api/insights/titles?release_year_from=2000&release_year_to=1990"
        ).status_code
        == 422
    )


def test_insight_drilldown_returns_matching_titles(client):
    _add(client, "A Nine", personal_rating=9, view_count=1)
    _add(client, "An Eight", personal_rating=8, view_count=1)

    response = client.get("/api/insights/titles?period=all&rating_bucket=9")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["catalog_item"]["canonical_title"] == "A Nine"


def test_planned_titles_stay_in_library_mix_but_not_taste_metrics(client):
    _add(
        client,
        "Watched Rating",
        provider_genres=["Drama"],
        personal_rating=8,
        view_count=1,
    )
    _add(
        client,
        "Planned Without Rating",
        status="plan_to_watch",
        provider_genres=["Drama"],
        personal_rating=None,
        view_count=0,
        watched_date=None,
    )

    payload = client.get("/api/insights?period=all").json()
    assert payload["ratings"]["rated_count"] == 1
    assert payload["ratings"]["unrated_count"] == 0
    assert not any(item["kind"] == "unrated" for item in payload["callouts"])
    assert {item["value"]: item["count"] for item in payload["statuses"]} == {
        "plan_to_watch": 1,
        "watched": 1,
    }

    all_unrated = client.get("/api/insights/titles?period=all&rating_state=unrated")
    active_unrated = client.get(
        "/api/insights/titles?period=all&rating_state=unrated&activity_only=true"
    )
    assert all_unrated.json()["total"] == 1
    assert active_unrated.json()["total"] == 0


def test_custom_insight_range_validation(client):
    missing = client.get("/api/insights?period=custom")
    assert missing.status_code == 422
    reversed_range = client.get(
        "/api/insights?period=custom&date_from=2025-04-02&date_to=2025-04-01"
    )
    assert reversed_range.status_code == 422


def test_completed_show_assumes_known_episodes_until_progress_is_edited(client):
    entry = _add(
        client,
        "Completed episodic title",
        media_type="tv",
        status="watched",
        provider_source="tmdb_tv",
        provider_id="insights-series",
        tmdb_tv_id="insights-series",
    )
    followed = client.put(
        f"/api/series/{entry['id']}/subscription",
        json={
            "notify_new_episode": False,
            "notify_new_season": False,
            "include_specials": True,
        },
    )
    assert followed.status_code == 200
    synced = client.post(f"/api/series/{entry['id']}/sync")
    assert synced.status_code == 200

    assumed = client.get("/api/insights?period=all").json()
    assert assumed["summary"]["episodes_watched"] == 3
    assert (
        client.get(f"/api/entries/{entry['id']}").json()["episode_progress_explicit"] is False
    )

    first_episode = synced.json()["seasons"][0]["episodes"][0]
    edited = client.delete(f"/api/episodes/{first_episode['id']}/viewing")
    assert edited.status_code == 200
    explicit = client.get("/api/insights?period=all").json()
    assert explicit["summary"]["episodes_watched"] == 2
    assert client.get(f"/api/entries/{entry['id']}").json()["episode_progress_explicit"] is True


def test_workspace_background_is_device_local_and_validated(client, settings):
    image = Image.new("RGB", (80, 60), "#345b4c")
    content = BytesIO()
    image.save(content, "PNG")

    uploaded = client.put(
        "/api/settings/background-image",
        files={"file": ("background.png", content.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["available"] is True
    assert settings.preferences_path.exists()

    general = client.get("/api/settings/general").json()
    assert general["background_image_available"] is True
    assert general["background_image_enabled"] is True
    fetched = client.get("/api/settings/background-image")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/webp"

    invalid = client.put(
        "/api/settings/background-image",
        files={"file": ("background.png", b"not an image", "image/png")},
    )
    assert invalid.status_code == 422

    deleted = client.delete("/api/settings/background-image")
    assert deleted.status_code == 204
    assert client.get("/api/settings/background-image").status_code == 404
