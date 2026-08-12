from __future__ import annotations

import time

from conftest import FakeMetadata, manual_payload

from watchtracker.schemas import SearchResult
from watchtracker.services.enrichment import choose_conservative_match


def test_manual_metadata_match_fills_catalog_without_changing_personal_data(client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "The Test Film",
            release_year=None,
            personal_rating=9,
            notes="keep this",
            provider_genres=[],
        ),
    ).json()["entry"]

    response = client.post(
        f"/api/entries/{entry['id']}/metadata",
        json=FakeMetadata.result.model_dump(mode="json"),
    )
    assert response.status_code == 200
    enriched = response.json()
    assert enriched["personal_rating"] == 9
    assert enriched["notes"] == "keep this"
    assert enriched["catalog_item"]["release_year"] == 2024
    assert enriched["catalog_item"]["tmdb_movie_id"] == "101"
    assert enriched["catalog_item"]["poster_url"].endswith("poster.jpg")
    assert "Drama" in enriched["effective_genres"]


def test_batch_enrichment_refreshes_only_stable_provider_identity(client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "The Test Film",
            release_year=2024,
            provider_source="tmdb_movie",
            provider_id="101",
            tmdb_movie_id="101",
            provider_genres=[],
            personal_rating=8,
        ),
    ).json()["entry"]

    started = client.post("/api/metadata/enrichment", json={})
    assert started.status_code == 202
    status = started.json()
    for _ in range(50):
        status = client.get("/api/metadata/enrichment").json()
        if status["status"] != "running":
            break
        time.sleep(0.01)
    assert status["status"] == "completed"
    assert status["enriched"] == 1
    assert status["failed"] == 0

    enriched = client.get(f"/api/entries/{entry['id']}").json()
    assert enriched["catalog_item"]["provider_source"] == "tmdb_movie"
    assert enriched["catalog_item"]["poster_url"].endswith("poster.jpg")
    assert enriched["personal_rating"] == 8


def test_batch_enrichment_never_guesses_title_only_identity(client):
    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "The Test Film", release_year=2024, provider_genres=[], personal_rating=8
        ),
    ).json()["entry"]

    client.post("/api/metadata/enrichment", json={})
    for _ in range(50):
        status = client.get("/api/metadata/enrichment").json()
        if status["status"] != "running":
            break
        time.sleep(0.01)

    assert status["enriched"] == 0
    assert status["needs_confirmation"] == 1
    unchanged = client.get(f"/api/entries/{entry['id']}").json()
    assert unchanged["catalog_item"]["provider_source"] is None


def test_metadata_review_is_ordered_and_excludes_verified_entries(client):
    later = client.post(
        "/api/entries/manual", json=manual_payload("Zulu", provider_genres=[])
    ).json()["entry"]
    first = client.post(
        "/api/entries/manual", json=manual_payload("Alpha", provider_genres=[])
    ).json()["entry"]
    client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Verified",
            provider_source="tmdb_movie",
            provider_id="101",
            tmdb_movie_id="101",
        ),
    )

    review = client.get("/api/metadata/review").json()
    assert review["total"] == 2
    assert review["entry"]["id"] == first["id"]
    next_review = client.get(
        "/api/metadata/review", params={"after_entry_id": first["id"]}
    ).json()
    assert next_review["entry"]["id"] == later["id"]


def test_conservative_match_rejects_ambiguous_title_without_year():
    results = [
        SearchResult(
            provider="tmdb_movie",
            provider_id=str(year),
            title="Shared Title",
            year=year,
            media_type="movie",
        )
        for year in (1999, 2024)
    ]
    assert choose_conservative_match("Shared Title", None, results) is None
    assert choose_conservative_match("Shared Title", 2024, results) == results[1]
