from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from watchtracker.authorization import current_user_id
from watchtracker.metadata.cache import TTLCache
from watchtracker.metadata.http import ResilientHttpClient
from watchtracker.metadata.providers import (
    JikanClient,
    TMDbClient,
    TVMazeClient,
    WikidataClient,
)
from watchtracker.models import CatalogItem, WatchEntry
from watchtracker.recommendations.discovery import CatalogDiscovery
from watchtracker.recommendations.signals import signal_snapshot


def _preferences(**values):
    return SimpleNamespace(
        use_taste_discovery=False,
        use_live_discovery=True,
        discovery_language="",
        excluded_media_types=[],
        **values,
    )


@pytest.mark.asyncio
async def test_tmdb_discovery_is_multitype_cached_localized_and_explicitly_opt_in(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        anime = request.url.params.get("with_original_language") == "ja"
        movie = "/movie" in request.url.path
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 3 if anime else 1 if movie else 2,
                        "name": "动画" if anime else "作品",
                        "title": "作品" if movie else None,
                        "original_language": "ja" if anime else "fr",
                        "genre_ids": [16] if anime else [18],
                        "overview": "本地化简介",
                        "vote_average": 8.0,
                        "poster_path": "/poster.jpg",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = TMDbClient(
            "test-token",
            ResilientHttpClient(raw, attempts=1),
            TTLCache(tmp_path),
            "zh-CN",
            "US",
        )
        source = CatalogDiscovery(SimpleNamespace(tmdb=client))
        preferences = _preferences()
        result = await source._tmdb(1, preferences, [("tmdb_movie", "999")], ["drama"])
        assert {item.media_type for item in result} == {"movie", "tv", "anime"}
        assert len(requests) == 3
        assert all(request.url.params["language"] == "zh-CN" for request in requests)
        assert not any("999" in str(request.url) for request in requests)
        assert not any(request.url.params.get("with_genres") == "18" for request in requests)
        await source._tmdb(1, preferences, [], [])
        assert len(requests) == 3
        preferences.use_taste_discovery = True
        preferences.discovery_language = "fr"
        await source._tmdb(1, preferences, [("tmdb_movie", "999")], ["drama"])
        assert any(request.url.path == "/3/movie/999/recommendations" for request in requests)
        assert any(
            request.url.params.get("with_original_language") == "fr"
            and request.url.params.get("with_genres") == "18"
            for request in requests
        )
        assert all(request.method == "GET" and not request.content for request in requests)


@pytest.mark.asyncio
async def test_tmdb_one_failed_discovery_path_keeps_other_types(tmp_path):
    def handler(request):
        if request.url.path.endswith("/discover/movie"):
            return httpx.Response(503)
        return httpx.Response(
            200, json={"results": [{"id": 2, "name": "Series", "genre_ids": [18]}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        source = CatalogDiscovery(
            SimpleNamespace(
                tmdb=TMDbClient(
                    "test",
                    ResilientHttpClient(raw, attempts=1),
                    TTLCache(tmp_path),
                    "fr-FR",
                    "FR",
                )
            )
        )
        result = await source._tmdb(1, _preferences(), [], [])
        assert result and all(item.media_type == "tv" for item in result)
        assert "tmdb" in source.failed_sources


@pytest.mark.asyncio
async def test_keyless_movie_tv_and_anime_discovery_never_creates_user_entries(
    client, app, tmp_path
):
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/sparql":
            assert "SELECT ?item" in request.url.params["query"]
            return httpx.Response(
                200,
                json={
                    "results": {
                        "bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q100"}}]
                    }
                },
            )
        if path == "/w/api.php":
            if request.url.params["ids"] == "Q100":
                return httpx.Response(
                    200,
                    json={
                        "entities": {
                            "Q100": {
                                "labels": {"en": {"value": "Synthetic movie"}},
                                "claims": {
                                    "P136": [
                                        {"mainsnak": {"datavalue": {"value": {"id": "Q200"}}}}
                                    ]
                                },
                            }
                        }
                    },
                )
            return httpx.Response(
                200, json={"entities": {"Q200": {"labels": {"en": {"value": "drama film"}}}}}
            )
        if path == "/v4/top/anime":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "mal_id": 301,
                            "title": "Synthetic anime",
                            "genres": [{"name": "Drama"}],
                            "score": 8,
                            "images": {
                                "jpg": {"image_url": "https://images.invalid/anime.jpg"}
                            },
                        }
                    ]
                },
            )
        if path == "/shows":
            return httpx.Response(
                200, json=[{"id": 401, "name": "Synthetic series", "genres": ["Drama"]}]
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        http = ResilientHttpClient(raw, attempts=1)
        cache = TTLCache(tmp_path / "cache")
        metadata = SimpleNamespace(
            tmdb=None,
            jikan=JikanClient(http, cache),
            tvmaze=TVMazeClient(http, cache),
            wikidata=WikidataClient(http, cache, "en-US"),
        )
        source = CatalogDiscovery(metadata)
        with app.state.session_factory() as session:
            user_id = current_user_id(session)
            preferences = app.state.recommendations.preference_row(session, user_id)
            signals = signal_snapshot(session, user_id=user_id, preferences=preferences)
            assert (
                await source.refresh_for_user(
                    session, user_id=user_id, preferences=preferences, signals=signals
                )
                == 3
            )
            assert source.failed_sources == []
            assert set(session.scalars(select(CatalogItem.media_type))) == {
                "movie",
                "tv",
                "anime",
            }
            assert session.scalar(select(func.count()).select_from(WatchEntry)) == 0
            assert all(
                item.metadata_provenance["provider_identity_verified"]
                for item in session.scalars(select(CatalogItem))
            )
            count = len(requests)
            await source.refresh_for_user(
                session, user_id=user_id, preferences=preferences, signals=signals
            )
            assert len(requests) == count
            assert session.scalar(select(func.count()).select_from(CatalogItem)) == 3
            preferences.use_live_discovery = False
            assert (
                await source.refresh_for_user(
                    session, user_id=user_id, preferences=preferences, signals=signals
                )
                == 0
            )
            assert len(requests) == count
