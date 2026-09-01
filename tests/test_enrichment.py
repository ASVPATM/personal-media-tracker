from __future__ import annotations

import time

from conftest import FakeMetadata, manual_payload

from watchtracker.models import CatalogItem
from watchtracker.schemas import CatalogData, SearchResponse, SearchResult
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


def test_complete_anime_gains_schedule_identity_when_provider_becomes_available(client):
    class ScheduleIdentityMetadata:
        def provider_catalog(self):
            return [
                {
                    "slug": "tmdb",
                    "media_types": ["movie", "tv", "anime"],
                    "capabilities": ["search", "detail", "artwork", "schedule"],
                }
            ]

        async def search(self, _query, _media_type=None):
            return SearchResponse(
                results=[
                    SearchResult(
                        provider="tmdb_tv",
                        provider_id="777",
                        title="Complete Anime",
                        year=2020,
                        media_type="anime",
                    )
                ]
            )

        async def detail(self, result):
            assert any(
                reference.provider == "tmdb_tv" and reference.provider_id == "777"
                for reference in result.corroborating_results
            )
            return CatalogData(
                canonical_title="Complete Anime",
                release_year=2020,
                media_type="anime",
                provider_source="kitsu",
                provider_id="44",
                tmdb_tv_id="777",
                poster_url="https://images.invalid/complete-anime.jpg",
                overview="Already complete before a schedule provider was configured.",
                provider_genres=["Adventure"],
                external_ids={"kitsu": "44", "tmdb_tv": "777"},
            )

    entry = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Complete Anime",
            media_type="anime",
            provider_source="kitsu",
            provider_id="44",
            external_ids={"kitsu": "44"},
            poster_url="https://images.invalid/complete-anime.jpg",
            overview="Already complete before a schedule provider was configured.",
            provider_genres=["Adventure"],
        ),
    ).json()["entry"]
    client.app.state.enrichment.metadata = ScheduleIdentityMetadata()

    assert client.post("/api/metadata/enrichment", json={}).status_code == 202
    status = _wait_for_enrichment(client)

    assert status["enriched"] == 1
    refreshed = client.get(f"/api/entries/{entry['id']}").json()
    assert refreshed["catalog_item"]["external_ids"]["tmdb_tv"] == "777"
    assert client.get(f"/api/series/{entry['id']}").json()["supported"] is True


def test_metadata_review_is_ordered_and_excludes_verified_entries(client):
    later = client.post(
        "/api/entries/manual", json=manual_payload("Zulu", provider_genres=[])
    ).json()["entry"]
    first = client.post(
        "/api/entries/manual", json=manual_payload("Alpha", provider_genres=[])
    ).json()["entry"]
    verified_rows = [
        client.post(
            "/api/entries/manual",
            json=manual_payload(
                "Verified",
                provider_source="tmdb_movie",
                provider_id="101",
                tmdb_movie_id="101",
            ),
        ).json()["entry"]
    ]
    verified_rows.append(
        client.post(
            "/api/entries/manual",
            json=manual_payload(
                "TVmaze verified",
                media_type="tv",
                provider_source="tvmaze",
                provider_id="56116",
                external_ids={"tvmaze": "56116"},
            ),
        ).json()["entry"]
    )
    verified_rows.append(
        client.post(
            "/api/entries/manual",
            json=manual_payload(
                "Kitsu verified",
                media_type="anime",
                provider_source="kitsu",
                provider_id="46474",
                external_ids={"kitsu": "46474"},
            ),
        ).json()["entry"]
    )
    with client.app.state.session_factory() as session:
        for row in verified_rows:
            item = session.get(CatalogItem, row["catalog_item"]["id"])
            item.metadata_provenance = {
                **(item.metadata_provenance or {}),
                "provider_identity_verified": True,
                "provider_identity_source": item.provider_source,
            }
        session.commit()

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


def test_conservative_match_uses_provider_aliases_and_one_compatible_result():
    frieren = SearchResult(
        provider="anilist",
        provider_id="154587",
        title="Frieren: Beyond Journey's End",
        aliases=["Frieren", "Sousou no Frieren", "葬送のフリーレン"],
        year=2023,
        media_type="anime",
        popularity=90,
    )
    wrong_type = SearchResult(
        provider="tmdb_movie",
        provider_id="2",
        title="Frieren Documentary",
        year=2023,
        media_type="movie",
        popularity=100,
    )
    assert choose_conservative_match("Frieren", 2023, [frieren, wrong_type], "anime") == frieren


def test_conservative_match_accepts_frieren_title_prefix_across_providers():
    results = [
        SearchResult(
            provider=provider,
            provider_id=str(index),
            title="Frieren: Beyond Journey's End",
            year=2023,
            media_type="anime",
            popularity=100 - index * 30,
        )
        for index, provider in enumerate(("anilist", "mal", "tmdb_tv"), start=1)
    ]
    assert choose_conservative_match("Frieren", 2023, results, "anime") == results[0]


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
