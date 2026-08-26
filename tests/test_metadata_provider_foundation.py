from __future__ import annotations

import httpx
import pytest

from watchtracker.config import Settings
from watchtracker.metadata.cache import TTLCache
from watchtracker.metadata.http import ResilientHttpClient
from watchtracker.metadata.providers import KitsuClient, TVMazeClient, WikidataClient
from watchtracker.metadata.resolver import cluster_search_results
from watchtracker.metadata.service import MetadataService
from watchtracker.schemas import CatalogData, ProviderReference, SearchResult


@pytest.mark.asyncio
async def test_optional_tmdb_activates_immediately_without_restarting(tmp_path):
    settings = Settings(database_path=tmp_path / "db.sqlite3", cache_dir=tmp_path / "cache")
    service = MetadataService(settings)

    assert "tmdb" not in {row["slug"] for row in service.provider_catalog()}
    service.configure_tmdb("tmdb-read-token-" + "x" * 32)
    assert "tmdb" in {row["slug"] for row in service.provider_catalog()}
    assert settings.tmdb_token

    service.configure_tmdb(None)
    assert "tmdb" not in {row["slug"] for row in service.provider_catalog()}
    await service.close()


@pytest.mark.asyncio
async def test_tvmaze_normalizes_keyless_search_detail_artwork_and_schedule(tmp_path):
    requests: list[str] = []

    def handler(request: httpx.Request):
        requests.append(request.url.path)
        assert request.headers["user-agent"].startswith("PersonalMediaTracker/")
        if request.url.path == "/search/shows":
            return httpx.Response(
                200,
                json=[
                    {
                        "score": 0.99,
                        "show": {
                            "id": 123,
                            "name": "Example Show",
                            "premiered": "2024-04-01",
                            "type": "Scripted",
                            "summary": "<p>A <b>useful</b> summary.</p>",
                            "externals": {"imdb": "tt123", "thetvdb": 456},
                            "image": {"original": "https://images.invalid/show.jpg"},
                        },
                    }
                ],
            )
        if request.url.path == "/shows/123/images":
            return httpx.Response(
                200,
                json=[
                    {
                        "type": "poster",
                        "resolutions": {
                            "original": {
                                "url": "https://images.invalid/poster.jpg",
                                "width": 680,
                                "height": 1000,
                            }
                        },
                    }
                ],
            )
        if request.url.path == "/shows/123/episodes":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 900,
                        "season": 1,
                        "number": 1,
                        "name": "Pilot",
                        "airdate": "2024-04-01",
                        "runtime": 45,
                    }
                ],
            )
        if request.url.path == "/shows/123":
            return httpx.Response(
                200,
                json={
                    "id": 123,
                    "name": "Example Show",
                    "premiered": "2024-04-01",
                    "type": "Scripted",
                    "status": "Running",
                    "summary": "<p>A useful summary.</p>",
                    "genres": ["Drama"],
                    "language": "English",
                    "averageRuntime": 45,
                    "rating": {"average": 8.1},
                    "externals": {"imdb": "tt123", "thetvdb": 456},
                    "image": {"original": "https://images.invalid/show.jpg"},
                },
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = TVMazeClient(
            ResilientHttpClient(raw, attempts=1), TTLCache(tmp_path / "cache")
        )
        search = await client.search("Example")
        detail = await client.detail("123")
        artwork = await client.posters("123")
        schedule = await client.series_schedule("123")
        cached_schedule = await client.series_schedule("123")

    assert search[0].provider == "tvmaze"
    assert search[0].external_ids == {"imdb": "tt123", "thetvdb": "456"}
    assert search[0].overview == "A useful summary."
    assert detail.external_ids == {
        "tvmaze": "123",
        "imdb": "tt123",
        "thetvdb": "456",
    }
    assert artwork[0]["poster_url"] == "https://images.invalid/poster.jpg"
    assert schedule["provider_source"] == "tvmaze"
    assert schedule["seasons"][0]["episodes"][0]["title"] == "Pilot"
    assert cached_schedule == schedule
    assert requests.count("/shows/123/episodes") == 1


@pytest.mark.asyncio
async def test_kitsu_supplies_keyless_anime_detail_artwork_and_external_ids(tmp_path):
    def handler(request: httpx.Request):
        assert request.headers["user-agent"].startswith("PersonalMediaTracker/")
        mapping = {
            "type": "mappings",
            "id": "map-1",
            "attributes": {
                "externalSite": "myanimelist/anime",
                "externalId": "52991",
            },
        }
        attributes = {
            "canonicalTitle": "Sousou no Frieren",
            "titles": {
                "en": "Frieren: Beyond Journey’s End",
                "en_jp": "Sousou no Frieren",
            },
            "startDate": "2023-09-29",
            "subtype": "TV",
            "synopsis": "An exact anime summary.",
            "posterImage": {
                "large": "https://images.invalid/frieren-large.jpg",
                "original": "https://images.invalid/frieren-original.jpg",
            },
            "userCount": 500_000,
            "episodeCount": 28,
            "episodeLength": 24,
            "averageRating": "88.8",
        }
        row = {
            "type": "anime",
            "id": "46474",
            "attributes": attributes,
            "relationships": {
                "mappings": {"data": [{"type": "mappings", "id": "map-1"}]},
                "categories": {"data": [{"type": "categories", "id": "cat-1"}]},
            },
        }
        if request.url.path == "/api/edge/anime":
            return httpx.Response(200, json={"data": [row], "included": [mapping]})
        if request.url.path == "/api/edge/anime/46474":
            category = {
                "type": "categories",
                "id": "cat-1",
                "attributes": {"title": "Fantasy"},
            }
            return httpx.Response(200, json={"data": row, "included": [mapping, category]})
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = KitsuClient(ResilientHttpClient(raw, attempts=1), TTLCache(tmp_path / "cache"))
        search = await client.search("Frieren")
        detail = await client.detail("46474")
        artwork = await client.posters("46474")

    assert search[0].title == "Frieren: Beyond Journey’s End"
    assert "Sousou no Frieren" in search[0].aliases
    assert search[0].external_ids == {"kitsu": "46474", "mal": "52991"}
    assert detail.provider_source == "kitsu"
    assert detail.provider_genres == ["Fantasy"]
    assert detail.episode_count == 28
    assert detail.runtime_minutes == 24
    assert detail.public_score == 8.88
    assert artwork == [{"poster_url": "https://images.invalid/frieren-original.jpg"}]


@pytest.mark.asyncio
async def test_wikidata_movie_fallback_normalizes_commons_artwork_and_core_fields(tmp_path):
    def entity_claim(value):
        return [{"mainsnak": {"datavalue": {"value": value}}}]

    movie = {
        "labels": {"en": {"value": "Example Film"}},
        "descriptions": {"en": {"value": "2024 drama film"}},
        "aliases": {},
        "claims": {
            "P18": entity_claim("Example Poster.jpg"),
            "P577": entity_claim({"time": "+2024-05-01T00:00:00Z"}),
            "P345": entity_claim("tt123"),
            "P136": entity_claim({"id": "QDRAMA"}),
            "P495": entity_claim({"id": "QUS"}),
            "P364": entity_claim({"id": "QEN"}),
            "P2047": entity_claim({"amount": "+121", "unit": "minutes"}),
        },
    }
    linked = {
        "QDRAMA": {"labels": {"en": {"value": "Drama"}}, "claims": {}},
        "QUS": {"labels": {"en": {"value": "United States"}}, "claims": {}},
        "QEN": {"labels": {"en": {"value": "English"}}, "claims": {}},
    }

    def handler(request: httpx.Request):
        action = request.url.params.get("action")
        if action == "wbsearchentities":
            return httpx.Response(
                200,
                json={
                    "search": [
                        {
                            "id": "QFILM",
                            "label": "Example Film",
                            "description": "2024 drama film",
                        }
                    ]
                },
            )
        if action == "wbgetentities":
            ids = set(str(request.url.params.get("ids")).split("|"))
            entities = {"QFILM": movie} if ids == {"QFILM"} else linked
            return httpx.Response(200, json={"entities": entities})
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = WikidataClient(
            ResilientHttpClient(raw, attempts=1), TTLCache(tmp_path / "cache"), "en-US"
        )
        search = await client.search("Example Film", "movie")
        detail = await client.detail("QFILM")

    assert len(search) == 1
    assert search[0].poster_url.endswith("Example%20Poster.jpg?width=500")
    assert detail.poster_url == search[0].poster_url
    assert detail.provider_genres == ["Drama"]
    assert detail.runtime_minutes == 121
    assert detail.country == "United States"
    assert detail.language == "English"
    assert detail.external_ids == {"wikidata": "QFILM", "imdb": "tt123"}


def test_cross_provider_clustering_requires_strong_non_conflicting_evidence():
    tvmaze = SearchResult(
        provider="tvmaze",
        provider_id="1",
        title="Shared Show",
        year=2024,
        media_type="tv",
        external_ids={"imdb": "tt123"},
    )
    tmdb = SearchResult(
        provider="tmdb_tv",
        provider_id="2",
        title="Shared Show",
        year=2024,
        media_type="tv",
        external_ids={"imdb": "tt123"},
    )
    remake = SearchResult(
        provider="tmdb_tv",
        provider_id="3",
        title="Shared Show",
        year=1999,
        media_type="tv",
    )
    same_provider_duplicate = tvmaze.model_copy(update={"provider_id": "4"})

    clustered = cluster_search_results(
        [tmdb, remake, tvmaze, same_provider_duplicate],
        provider_priority={"tvmaze": 0, "tmdb_tv": 1},
    )

    assert len(clustered) == 3
    primary = next(item for item in clustered if item.provider_id == "1")
    assert primary.corroborating_results[0].provider == "tmdb_tv"
    assert primary.external_ids["imdb"] == "tt123"
    assert any(item.provider_id == "3" for item in clustered)
    assert any(item.provider_id == "4" for item in clustered)


@pytest.mark.asyncio
async def test_detail_merges_corroborating_source_without_overwriting_primary_identity(
    tmp_path,
):
    class TMDb:
        async def detail(self, provider, provider_id):
            assert (provider, provider_id) == ("tmdb_tv", "10")
            return CatalogData(
                canonical_title="Merged Show",
                release_year=2024,
                media_type="tv",
                provider_source="tmdb_tv",
                provider_id="10",
                tmdb_tv_id="10",
                overview="Primary description",
                external_ids={"tmdb_tv": "10", "imdb": "tt10"},
            )

    class TVMaze:
        async def detail(self, provider_id):
            assert provider_id == "20"
            return CatalogData(
                canonical_title="Merged Show",
                release_year=2024,
                media_type="tv",
                provider_source="tvmaze",
                provider_id="20",
                poster_url="https://images.invalid/merged.jpg",
                provider_genres=["Drama"],
                external_ids={"tvmaze": "20", "imdb": "tt10"},
            )

    service = MetadataService(
        Settings(database_path=tmp_path / "db.sqlite3", cache_dir=tmp_path / "cache"),
        tmdb=TMDb(),
        tvmaze=TVMaze(),
    )
    result = SearchResult(
        provider="tmdb_tv",
        provider_id="10",
        title="Merged Show",
        year=2024,
        media_type="tv",
        external_ids={"imdb": "tt10"},
        corroborating_results=[ProviderReference(provider="tvmaze", provider_id="20")],
    )

    detail = await service.detail(result)

    assert detail.provider_source == "tmdb_tv"
    assert detail.poster_url == "https://images.invalid/merged.jpg"
    assert detail.provider_genres == ["Drama"]
    assert detail.external_ids == {
        "imdb": "tt10",
        "tmdb_tv": "10",
        "tvmaze": "20",
    }
    assert detail.field_sources["overview"] == "tmdb_tv"
    assert detail.field_sources["poster_url"] == "tvmaze"
    assert {source.provider for source in detail.source_snapshots} == {
        "tmdb_tv",
        "tvmaze",
    }
    await service.close()
