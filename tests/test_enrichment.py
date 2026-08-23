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


def test_batch_enrichment_attaches_one_exact_title_and_year_match(client):
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

    assert status["enriched"] == 1
    assert status["needs_confirmation"] == 0
    enriched = client.get(f"/api/entries/{entry['id']}").json()
    assert enriched["catalog_item"]["provider_source"] == "tmdb_movie"


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


def test_conservative_match_uses_popularity_for_small_exact_tie():
    results = [
        SearchResult(
            provider="tmdb_movie",
            provider_id=str(year),
            title="Shared Title",
            year=year,
            media_type="movie",
            popularity=10 if year == 1999 else 80,
        )
        for year in (1999, 2024)
    ]
    assert choose_conservative_match("Shared Title", None, results) == results[1]
    assert choose_conservative_match("Shared Title", 2024, results) == results[1]


def test_conservative_match_accepts_popular_similar_title_only_in_small_result_set():
    results = [
        SearchResult(
            provider="tmdb_movie",
            provider_id="1",
            title="The Grand Budapest Hotel",
            year=2014,
            media_type="movie",
            popularity=75,
        ),
        SearchResult(
            provider="tmdb_movie",
            provider_id="2",
            title="Hotel Budapest",
            year=2017,
            media_type="movie",
            popularity=5,
        ),
    ]
    assert choose_conservative_match("Grand Budapest Hotel", None, results) == results[0]
    assert choose_conservative_match("Grand Budapest Hotel", 2020, results) is None

    crowded = [
        result.model_copy(update={"provider_id": str(index)})
        for index, result in enumerate([results[0]] * 5)
    ]
    assert choose_conservative_match("The Grand Budapest Hotel", None, crowded) is None


def test_conservative_match_accepts_single_alias_but_rejects_contradictions():
    alias = SearchResult(
        provider="tmdb_tv",
        provider_id="1",
        title="Shingeki no Kyojin",
        original_title="進撃の巨人",
        year=2013,
        media_type="anime",
    )
    assert choose_conservative_match("Attack on Titan", 2013, [alias], "anime") == alias
    assert choose_conservative_match("Attack on Titan", 1999, [alias], "anime") is None
    assert choose_conservative_match("Attack on Titan", 2013, [alias], "movie") is None


def test_conservative_match_uses_a_dominant_first_ranked_candidate():
    results = [
        SearchResult(
            provider="tmdb_tv",
            provider_id="1",
            title="The Bear",
            year=2022,
            media_type="tv",
            popularity=90,
        ),
        SearchResult(
            provider="tmdb_tv",
            provider_id="2",
            title="Bear in the Big Blue House",
            year=1997,
            media_type="tv",
            popularity=8,
        ),
    ]
    assert choose_conservative_match("The Bear", None, results, "tv") == results[0]


def _wait_for_enrichment(client):
    status = {}
    for _ in range(50):
        status = client.get("/api/metadata/enrichment").json()
        if status["status"] != "running":
            return status
        time.sleep(0.01)
    return status


def test_enrichment_reports_duplicate_identity_reason(client):
    for title in ("Alias One", "Alias Two"):
        client.post(
            "/api/entries/manual",
            json=manual_payload(title, release_year=2024, provider_genres=[]),
        )
    client.post("/api/metadata/enrichment", json={})
    status = _wait_for_enrichment(client)
    assert status["enriched"] == 1
    assert status["skip_reasons"]["duplicate_identity"] == 1


def test_enrichment_reports_detail_failure_without_exposing_title(client):
    class BrokenDetail:
        async def search(self, _query, _media_type=None):
            return type("Search", (), {"results": [FakeMetadata.result], "warnings": []})()

        async def detail(self, _result):
            raise RuntimeError("private provider detail")

    client.app.state.enrichment.metadata = BrokenDetail()
    client.post(
        "/api/entries/manual",
        json=manual_payload("Provider Alias", release_year=2024, provider_genres=[]),
    )
    client.post("/api/metadata/enrichment", json={})
    status = _wait_for_enrichment(client)
    assert status["skip_reasons"]["detail_failure"] == 1
    assert "Provider Alias" not in status["message"]
