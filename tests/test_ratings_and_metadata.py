from __future__ import annotations

import time

import httpx
import pytest
from pydantic import ValidationError

from watchtracker.config import Settings
from watchtracker.imports.parsers import parse_rating
from watchtracker.metadata.cache import TTLCache, cache_key
from watchtracker.metadata.http import ProviderError, ResilientHttpClient, redact_secrets
from watchtracker.metadata.providers import TMDbClient
from watchtracker.metadata.service import MetadataService
from watchtracker.schemas import CatalogData, EntryOptions, SearchResult


@pytest.mark.parametrize("rating", [1, 1.1, 5.7, 9.5, 10, None])
def test_personal_rating_accepts_null_and_tenth_steps(rating):
    assert EntryOptions(personal_rating=rating).personal_rating == rating


@pytest.mark.parametrize("rating", [0, 10.5, 7.25, float("nan"), float("inf")])
def test_personal_rating_rejects_out_of_range_or_sub_tenth_steps(rating):
    with pytest.raises(ValidationError):
        EntryOptions(personal_rating=rating)


def test_letterboxd_rating_is_scaled_exactly_once():
    assert parse_rating("4.5", letterboxd=True) == 9
    assert parse_rating(9, letterboxd=False) == 9
    with pytest.raises(ValueError):
        parse_rating(9, letterboxd=True)


def test_cache_key_is_deterministic_and_cache_obeys_ttl_and_bound(tmp_path, monkeypatch):
    one = cache_key("provider", "search", {"q": "Alien", "page": 1})
    two = cache_key("provider", "search", {"page": 1, "q": "Alien"})
    assert one == two
    cache = TTLCache(tmp_path, ttl_seconds=10, max_entries=2)
    clock = 100.0
    monkeypatch.setattr(time, "time", lambda: clock)
    cache.set(one, {"ok": True})
    assert cache.get(one) == {"ok": True}
    clock = 111.0
    assert cache.get(one) is None
    for number in range(3):
        cache.set(str(number), number)
    assert len(list(tmp_path.glob("*.json"))) == 2


@pytest.mark.asyncio
async def test_http_retry_stops_at_boundary_and_redacts_token():
    attempts = 0
    sleeps = []

    def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "later"})

    async def fake_sleep(delay):
        sleeps.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = ResilientHttpClient(
            raw,
            attempts=3,
            base_delay=0.1,
            sleep=fake_sleep,
            jitter=lambda delay: delay,
        )
        with pytest.raises(Exception) as caught:
            await client.request_json(
                "Test provider",
                "GET",
                "https://provider.invalid/data?token=super-secret",
                secrets=["super-secret"],
            )
    assert attempts == 3
    assert sleeps == [0.1, 0.2]
    assert "super-secret" not in redact_secrets(str(caught.value), ["super-secret"])
    assert "[REDACTED]" in redact_secrets("token=super-secret", ["super-secret"])


@pytest.mark.asyncio
async def test_tmdb_search_normalizes_provider_result(tmp_path):
    def handler(request):
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 12,
                        "title": "Arrival",
                        "original_title": "Arrival",
                        "release_date": "2016-11-11",
                        "poster_path": "/a.jpg",
                        "overview": "Language and time.",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        http = ResilientHttpClient(raw, attempts=1)
        tmdb = TMDbClient("secret", http, TTLCache(tmp_path), "en-US", "US")
        results = await tmdb.search("arrival", "movie")
    assert results == [
        SearchResult(
            provider="tmdb_movie",
            provider_id="12",
            title="Arrival",
            year=2016,
            media_type="movie",
            poster_url="https://image.tmdb.org/t/p/w500/a.jpg",
            overview="Language and time.",
        )
    ]


@pytest.mark.asyncio
async def test_unified_search_keeps_partial_results(tmp_path):
    class BrokenTMDb:
        async def search(self, query, media_type):
            raise RuntimeError("provider secret failure")

    class Anime:
        async def search(self, query):
            return [
                SearchResult(
                    provider="anilist",
                    provider_id="1",
                    title="Monster",
                    year=2004,
                    media_type="anime",
                )
            ]

    class Jikan:
        async def search(self, query):
            return []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as raw:
        service = MetadataService(
            Settings(database_path=tmp_path / "db", cache_dir=tmp_path),
            http=ResilientHttpClient(raw, attempts=1),
            tmdb=BrokenTMDb(),
            anilist=Anime(),
            jikan=Jikan(),
        )
        response = await service.search("monster")
    assert [row.title for row in response.results] == ["Monster"]
    assert response.warnings == ["TMDb search is temporarily unavailable."]


@pytest.mark.asyncio
async def test_unified_search_ranks_exact_title_across_media_types(tmp_path):
    class TMDb:
        async def search(self, _query, media_type):
            if media_type == "movie":
                return [
                    SearchResult(
                        provider="tmdb_movie",
                        provider_id="1",
                        title="Beef Cattle",
                        media_type="movie",
                    )
                ]
            return [
                SearchResult(
                    provider="tmdb_tv",
                    provider_id="2",
                    title="BEEF",
                    media_type="tv",
                )
            ]

    class Anime:
        async def search(self, _query):
            return []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as raw:
        service = MetadataService(
            Settings(database_path=tmp_path / "db", cache_dir=tmp_path),
            http=ResilientHttpClient(raw, attempts=1),
            tmdb=TMDb(),
            anilist=Anime(),
            jikan=Anime(),
        )
        response = await service.search("Beef")
    assert response.results[0].provider == "tmdb_tv"


@pytest.mark.asyncio
async def test_anime_search_includes_tmdb_fallback_and_preserves_anime_detail(tmp_path):
    class TMDb:
        async def search(self, query, media_type):
            assert query == "Attack on Titan"
            if media_type == "tv":
                return [
                    SearchResult(
                        provider="tmdb_tv",
                        provider_id="1429",
                        title="Attack on Titan",
                        year=2013,
                        media_type="tv",
                        popularity=100,
                    )
                ]
            return []

        async def detail(self, provider, provider_id):
            assert (provider, provider_id) == ("tmdb_tv", "1429")
            return CatalogData(
                canonical_title="Attack on Titan",
                release_year=2013,
                media_type="tv",
                provider_source="tmdb_tv",
                provider_id="1429",
                tmdb_tv_id="1429",
            )

    class BrokenJikan:
        calls = 0

        async def search(self, _query):
            self.calls += 1
            raise ProviderError("Jikan", "HTTP 504")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as raw:
        service = MetadataService(
            Settings(database_path=tmp_path / "db", cache_dir=tmp_path),
            http=ResilientHttpClient(raw, attempts=1),
            tmdb=TMDb(),
            jikan=BrokenJikan(),
        )
        response = await service.search("Attack on Titan", "anime")
        repeated = await service.search("Attack on Titan", "anime")
        detail = await service.detail(response.results[0])

    assert response.results[0].provider == "tmdb_tv"
    assert response.results[0].media_type == "anime"
    assert "Anime fallback search is temporarily unavailable." in response.warnings
    assert repeated.results[0].provider == "tmdb_tv"
    assert service.jikan.calls == 1
    assert detail.media_type == "anime"
