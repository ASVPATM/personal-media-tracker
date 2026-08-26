from __future__ import annotations

from conftest import FakeMetadata, manual_payload

from watchtracker.metadata import ProviderUnavailable


def test_favorites_and_simple_lists_are_persistent(client):
    first = client.post("/api/entries/manual", json=manual_payload("First title")).json()[
        "entry"
    ]
    second = client.post("/api/entries/manual", json=manual_payload("Second title")).json()[
        "entry"
    ]

    favorite = client.patch(f"/api/entries/{first['id']}", json={"is_favorite": True})
    assert favorite.status_code == 200
    assert favorite.json()["is_favorite"] is True

    created = client.post("/api/lists", json={"name": "Weekend picks"})
    assert created.status_code == 201
    media_list = created.json()
    assert media_list["items"] == []

    added = client.post(f"/api/lists/{media_list['id']}/entries/{first['id']}")
    assert added.status_code == 200
    assert [item["entry"]["id"] for item in added.json()["items"]] == [first["id"]]
    duplicate = client.post(f"/api/lists/{media_list['id']}/entries/{first['id']}")
    assert duplicate.status_code == 200
    assert len(duplicate.json()["items"]) == 1

    client.post(f"/api/lists/{media_list['id']}/entries/{second['id']}")
    listed = client.get("/api/lists").json()
    assert [item["entry"]["id"] for item in listed[0]["items"]] == [
        first["id"],
        second["id"],
    ]

    removed = client.delete(f"/api/lists/{media_list['id']}/entries/{first['id']}")
    assert removed.status_code == 200
    assert [item["entry"]["id"] for item in removed.json()["items"]] == [second["id"]]
    assert client.delete(f"/api/lists/{media_list['id']}").status_code == 204
    assert client.get("/api/lists").json() == []


def test_duplicate_list_names_are_rejected_case_insensitively(client):
    assert client.post("/api/lists", json={"name": "Favorites"}).status_code == 201
    response = client.post("/api/lists", json={"name": " favorites "})
    assert response.status_code == 409


def test_list_detail_sorting_and_five_navigation_pin_limit(client):
    lists = [
        client.post("/api/lists", json={"name": f"List {index}"}).json() for index in range(6)
    ]
    detail = client.get(f"/api/lists/{lists[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "List 0"

    for media_list in lists[:5]:
        pinned = client.patch(
            f"/api/lists/{media_list['id']}",
            json={"pinned_to_navigation": True},
        )
        assert pinned.status_code == 200
        assert pinned.json()["pinned_to_navigation"] is True
    rejected = client.patch(f"/api/lists/{lists[5]['id']}", json={"pinned_to_navigation": True})
    assert rejected.status_code == 409

    descending = client.get("/api/lists?sort=name&direction=desc").json()
    assert [row["name"] for row in descending] == [
        f"List {index}" for index in range(5, -1, -1)
    ]


def test_selected_artwork_survives_metadata_refresh_and_can_reset(client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "The Test Film",
            release_year=2024,
            provider_source="tmdb_movie",
            provider_id="101",
            tmdb_movie_id="101",
            poster_url="https://images.invalid/poster.jpg",
        ),
    ).json()["entry"]

    choices = client.get(f"/api/entries/{entry['id']}/artwork")
    assert choices.status_code == 200
    assert choices.json()["supported"] is True
    assert len(choices.json()["options"]) == 2

    selected = client.put(
        f"/api/entries/{entry['id']}/artwork",
        json={"poster_url": "https://images.invalid/alternate.jpg"},
    )
    assert selected.status_code == 200
    assert (
        selected.json()["catalog_item"]["poster_override_url"]
        == "https://images.invalid/alternate.jpg"
    )

    refreshed = client.post(
        f"/api/entries/{entry['id']}/metadata",
        json=FakeMetadata.result.model_dump(mode="json"),
    )
    assert refreshed.status_code == 200
    assert (
        refreshed.json()["catalog_item"]["poster_override_url"]
        == "https://images.invalid/alternate.jpg"
    )

    reset = client.put(f"/api/entries/{entry['id']}/artwork", json={"poster_url": None})
    assert reset.status_code == 200
    assert reset.json()["catalog_item"]["poster_override_url"] is None


def test_artwork_rejects_a_url_not_returned_for_the_title(client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "The Test Film",
            provider_source="tmdb_movie",
            provider_id="101",
            tmdb_movie_id="101",
        ),
    ).json()["entry"]
    response = client.put(
        f"/api/entries/{entry['id']}/artwork",
        json={"poster_url": "https://unrelated.invalid/image.jpg"},
    )
    assert response.status_code == 422


def test_artwork_keeps_current_image_when_provider_refresh_fails(app, client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Cached artwork",
            provider_source="tmdb_movie",
            provider_id="101",
            tmdb_movie_id="101",
            poster_url="https://images.invalid/cached.jpg",
        ),
    ).json()["entry"]

    async def unavailable(_provider: str, _provider_id: str):
        raise ProviderUnavailable("Provider temporarily unavailable.")

    app.state.metadata.artwork_options = unavailable
    response = client.get(f"/api/entries/{entry['id']}/artwork")
    assert response.status_code == 200
    assert response.json()["options"][0]["poster_url"] == ("https://images.invalid/cached.jpg")
    assert "could not be refreshed" in response.json()["warning"]
