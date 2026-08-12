from __future__ import annotations

from conftest import FakeMetadata, manual_payload


def test_health_main_and_search_smoke(client):
    assert client.get("/health").json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "Quick add" in page.text
    search = client.get("/api/search", params={"q": "test"})
    assert search.status_code == 200
    assert search.json()["results"][0]["provider_id"] == "101"
    assert client.get("/api/search", params={"q": "x"}).status_code == 200
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_one_click_add_duplicate_and_provider_error(client, today):
    payload = {"result": FakeMetadata.result.model_dump(mode="json")}
    response = client.post("/api/entries/from-search", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["entry"]["view_count"] == 1
    assert body["entry"]["watched_date"] == today.isoformat()
    assert len(body["entry"]["viewing_events"]) == 1

    duplicate = client.post("/api/entries/from-search", json=payload).json()
    assert duplicate["duplicate"] is True
    assert duplicate["action"] == "existing"
    assert client.get("/api/entries").json()["total"] == 1

    payload["if_existing"] = "rewatch"
    rewatch = client.post("/api/entries/from-search", json=payload).json()
    assert rewatch["entry"]["view_count"] == 2
    assert len(rewatch["entry"]["viewing_events"]) == 2

    broken = FakeMetadata.result.model_copy(update={"provider_id": "unavailable"})
    response = client.post(
        "/api/entries/from-search", json={"result": broken.model_dump(mode="json")}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_crud_filter_sort_pagination_inline_edit_delete_restore(client):
    first = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Zeta",
            personal_rating=7.5,
            release_year=2010,
            media_type="movie",
            provider_genres=["Drama"],
        ),
    ).json()["entry"]
    second = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Alpha",
            personal_rating=9,
            release_year=2020,
            media_type="anime",
            provider_genres=["Psychological", "Thriller"],
        ),
    ).json()["entry"]
    client.post(
        "/api/entries/manual",
        json=manual_payload("Plan", status="plan_to_watch", media_type="tv"),
    )

    page = client.get(
        "/api/entries",
        params={"sort": "title", "direction": "asc", "page_size": 2, "page": 1},
    ).json()
    assert page["total"] == 3
    assert page["pages"] == 2
    assert [item["catalog_item"]["canonical_title"] for item in page["items"]] == [
        "Alpha",
        "Plan",
    ]
    filtered = client.get(
        "/api/entries",
        params={
            "media_type": "anime",
            "status": "watched",
            "rating_min": 8,
            "rated": "rated",
            "genre": "Psychological Thriller",
            "q": "alp",
        },
    ).json()
    assert filtered["total"] == 1

    updated = client.patch(
        f"/api/entries/{first['id']}",
        json={
            "status": "watching",
            "personal_rating": None,
            "notes": "Patiently paced",
            "genre_additions": ["Mystery"],
            "genre_removals": ["Drama"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["personal_rating"] is None
    assert updated.json()["effective_genres"] == ["Mystery"]
    assert client.get("/api/entries", params={"genre": "Drama"}).json()["total"] == 1
    assert client.get("/api/entries", params={"genre": "Mystery"}).json()["total"] == 1

    bad_count = client.patch(f"/api/entries/{second['id']}", json={"view_count": 0})
    assert bad_count.status_code == 409
    assert client.get("/api/entries/not-real").status_code == 404
    assert client.get("/api/entries", params={"sort": "unsafe"}).status_code == 422

    assert client.delete(f"/api/entries/{first['id']}").status_code == 204
    assert client.get("/api/entries").json()["total"] == 2
    deleted = client.get("/api/entries", params={"include_deleted": True}).json()
    assert deleted["total"] == 3
    restored = client.post(f"/api/entries/{first['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


def test_status_first_watch_rewatch_and_delete_viewing_invariants(client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload("Future", status="plan_to_watch", view_count=0),
    ).json()["entry"]
    assert entry["viewing_events"] == []
    watched = client.patch(f"/api/entries/{entry['id']}", json={"status": "watched"}).json()
    assert watched["view_count"] == 1
    assert len(watched["viewing_events"]) == 1
    rewatched = client.post(
        f"/api/entries/{entry['id']}/viewings", json={"viewed_on": "2020-01-02"}
    ).json()
    assert rewatched["view_count"] == 2
    event_id = rewatched["viewing_events"][1]["id"]
    reduced = client.delete(f"/api/entries/{entry['id']}/viewings/{event_id}").json()
    assert reduced["view_count"] == 1
    last_id = reduced["viewing_events"][0]["id"]
    empty = client.delete(f"/api/entries/{entry['id']}/viewings/{last_id}").json()
    assert empty["view_count"] == 0
    assert empty["status"] == "plan_to_watch"


def test_validation_and_payload_limit(client):
    invalid = client.post(
        "/api/entries/manual", json=manual_payload("Bad", personal_rating=7.25)
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    huge = b"title\n" + b"x" * (2 * 1024 * 1024)
    response = client.post(
        "/api/imports/preview",
        files={"file": ("large.csv", huge, "text/csv")},
        data={"import_kind": "csv"},
    )
    assert response.status_code == 413


def test_decimal_rating_review_queue(client):
    later = client.post(
        "/api/entries/manual", json=manual_payload("Zulu", personal_rating=7.2)
    ).json()["entry"]
    first = client.post(
        "/api/entries/manual", json=manual_payload("Alpha", personal_rating=8.1)
    ).json()["entry"]
    client.post("/api/entries/manual", json=manual_payload("Unrated", personal_rating=None))

    review = client.get("/api/ratings/review").json()
    assert review["total"] == 2
    assert review["entry"]["id"] == first["id"]
    updated = client.patch(f"/api/entries/{first['id']}", json={"personal_rating": 8.3}).json()
    assert updated["personal_rating"] == 8.3
    following = client.get("/api/ratings/review", params={"after_entry_id": first["id"]}).json()
    assert following["entry"]["id"] == later["id"]


def test_strong_anime_evidence_overrides_provider_tv_format(client):
    anime = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Provider Anime",
            media_type="tv",
            provider_source="tmdb_tv",
            provider_id="200",
            tmdb_tv_id="200",
            provider_genres=["Animation", "Action"],
            keywords=["anime"],
            country="JP",
            language="ja",
        ),
    ).json()["entry"]
    japanese_animation = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Japanese Animation",
            media_type="tv",
            provider_source="tmdb_tv",
            provider_id="201",
            tmdb_tv_id="201",
            provider_genres=["Animation"],
            country="JP",
            language="ja",
        ),
    ).json()["entry"]
    live_action = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Japanese Drama",
            media_type="tv",
            provider_source="tmdb_tv",
            provider_id="202",
            tmdb_tv_id="202",
            provider_genres=["Drama"],
            country="JP",
            language="ja",
        ),
    ).json()["entry"]

    assert anime["catalog_item"]["media_type"] == "anime"
    assert japanese_animation["catalog_item"]["media_type"] == "anime"
    assert live_action["catalog_item"]["media_type"] == "tv"
