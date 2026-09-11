from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from watchtracker.metadata.cache import TTLCache
from watchtracker.metadata.http import ProviderError, ResilientHttpClient
from watchtracker.metadata.providers import TMDbClient
from watchtracker.metadata.service import MetadataService, ProviderUnavailable
from watchtracker.schemas import CatalogData, ProviderReference


@pytest.mark.parametrize(
    ("interface", "metadata"), [("fr", "fr-FR"), ("zh-CN", "zh-CN"), ("en", "en-US")]
)
def test_metadata_language_follows_interface_even_with_legacy_selection(
    client, interface, metadata
):
    response = client.put(
        "/api/settings/general", json={"interface_language": interface, "language": "ja-JP"}
    )
    assert response.status_code == 200
    assert client.get("/api/settings/general").json()["language"] == metadata


@pytest.mark.asyncio
async def test_request_locales_do_not_mutate_shared_provider_or_credentials(settings):
    service = MetadataService(settings)
    try:
        chinese = service.with_tmdb_token("synthetic-zh-token").with_locale("zh-CN", "CN")
        french = service.with_tmdb_token("synthetic-fr-token").with_locale("fr-FR", "FR")
        assert chinese.tmdb.language == "zh-CN"
        assert french.tmdb.language == "fr-FR"
        assert chinese.tmdb.token == "synthetic-zh-token"
        assert french.tmdb.token == "synthetic-fr-token"
        assert service.tmdb is None
        assert service.settings.language == "en-US"
        assert (
            service.registry is not chinese.registry and service.registry is not french.registry
        )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_tmdb_translations_and_detail_cache_are_language_safe(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/translations"):
            return httpx.Response(
                200,
                json={
                    "translations": [
                        {
                            "iso_639_1": "fr",
                            "iso_3166_1": "FR",
                            "data": {"title": "Titre français", "overview": "Résumé français"},
                        },
                        {
                            "iso_639_1": "zh",
                            "iso_3166_1": "CN",
                            "data": {"title": "简体标题", "overview": ""},
                        },
                        {
                            "iso_639_1": "zh",
                            "iso_3166_1": "TW",
                            "data": {"title": "繁體標題", "overview": "繁體簡介"},
                        },
                    ]
                },
            )
        locale = request.url.params["language"]
        return httpx.Response(
            200,
            json={
                "id": 101,
                "title": "标题" if locale == "zh-CN" else "Titre",
                "genres": [{"id": 18, "name": "剧情" if locale == "zh-CN" else "Drame"}],
                "overview": "",
                "original_language": "en",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        http, cache = ResilientHttpClient(raw, attempts=1), TTLCache(tmp_path)
        zh = TMDbClient("synthetic", http, cache, "zh-CN", "US")
        fr = TMDbClient("synthetic", http, cache, "fr-FR", "US")
        assert await zh.localized_text("tmdb_movie", "101") == {"title": "简体标题"}
        assert await fr.localized_text("tmdb_movie", "101") == {
            "title": "Titre français",
            "overview": "Résumé français",
        }
        assert len(requests) == 1  # all provider translations share one public cache
        zh_detail = await zh.detail("tmdb_movie", "101")
        fr_detail = await fr.detail("tmdb_movie", "101")
        assert zh_detail.provider_genres == fr_detail.provider_genres == ["Drama"]
        assert zh_detail.canonical_title == "标题" and fr_detail.canonical_title == "Titre"
        assert await zh.detail("tmdb_movie", "101") == zh_detail
        assert len(requests) == 3


@pytest.mark.parametrize("language", ["en", "fr", "zh-CN"])
def test_quick_add_translation_uses_only_valid_public_identity(
    client, app, monkeypatch, language
):
    client.put("/api/settings/general", json={"interface_language": language})
    reader = AsyncMock(return_value={"title": "Official localized name", "provider": "tmdb_tv"})
    monkeypatch.setattr(app.state.metadata, "localized_reference", reader, raising=False)
    before = client.get("/api/entries").json()
    response = client.get(
        "/api/metadata/localized-metadata", params={"provider": "kitsu", "provider_id": "42"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "language": language,
        "status": "translated",
        "title": "Official localized name",
        "provider": "tmdb_tv",
    }
    reader.assert_awaited_once_with(ProviderReference(provider="kitsu", provider_id="42"))
    assert client.get("/api/entries").json() == before
    for provider, identity in [
        ("unknown", "42"),
        ("tmdb_tv", "../42"),
        ("tvmaze", "42?x=1"),
        ("wikidata", "Q"),
        ("tmdb_tv", "9" * 200),
    ]:
        assert (
            client.get(
                "/api/metadata/localized-metadata",
                params={"provider": provider, "provider_id": identity},
            ).status_code
            == 422
        )
    assert reader.await_count == 1


@pytest.mark.parametrize(
    "error",
    [ProviderUnavailable("Offline"), ProviderError("TMDb", "Unavailable"), TimeoutError()],
)
def test_quick_translation_outages_return_fallback_without_creating_entries(
    client, app, monkeypatch, error
):
    monkeypatch.setattr(
        app.state.metadata, "localized_reference", AsyncMock(side_effect=error), raising=False
    )
    response = client.get(
        "/api/metadata/localized-metadata",
        params={"provider": "tmdb_movie", "provider_id": "12"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "temporarily_unavailable"
    assert "title" not in response.json()
    assert client.get("/api/entries").json()["total"] == 0


@pytest.mark.asyncio
async def test_quick_translation_refetches_provider_identity_before_cross_matching(
    settings, monkeypatch
):
    service = MetadataService(settings)
    catalog = CatalogData(
        canonical_title="Provider-fetched identity",
        media_type="anime",
        provider_source="kitsu",
        provider_id="42",
        release_year=2020,
    )
    detail = AsyncMock(return_value=catalog)
    reader = AsyncMock(return_value={"title": "Official title"})
    monkeypatch.setattr(service, "_detail_reference", detail)
    monkeypatch.setattr(service, "localized_text", reader)
    reference = ProviderReference(provider="kitsu", provider_id="42")
    try:
        assert await service.localized_reference(reference) == {"title": "Official title"}
        detail.assert_awaited_once_with(reference)
        reader.assert_awaited_once_with(catalog)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_partial_provider_summary_does_not_prevent_alternative_official_title(
    settings, monkeypatch
):
    service = MetadataService(
        settings.model_copy(update={"tmdb_token": "synthetic", "language": "zh-CN"})
    )
    try:
        monkeypatch.setattr(
            service.tmdb, "localized_text", AsyncMock(return_value={"overview": "中文简介"})
        )
        monkeypatch.setattr(
            service.wikidata, "localized_text", AsyncMock(return_value={"title": "官方名称"})
        )
        catalog = CatalogData(
            canonical_title="Original",
            media_type="movie",
            external_ids={"tmdb_movie": "12", "wikidata": "Q42"},
        )
        result = await service.localized_text(catalog)
        assert result["title"] == "官方名称"
        assert result["title_provider"] == "wikidata"
        assert result["overview_provider"] == "tmdb_movie"
        assert catalog.canonical_title == "Original"
    finally:
        await service.close()


def test_display_translation_is_read_only_and_provider_failure_keeps_saved_text(
    client, app, monkeypatch
):
    created = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "My unchanged title",
            "media_type": "movie",
            "notes": "My unchanged notes",
            "provider_source": "tmdb_movie",
            "provider_id": "101",
            "overview": "Original summary",
        },
    )
    assert created.status_code == 201
    entry = created.json()["entry"]
    client.put("/api/settings/general", json={"interface_language": "fr"})

    async def translated(catalog):
        assert catalog.provider_id == "101"
        return {"title": "Titre traduit", "overview": "Résumé", "provider": "tmdb_movie"}

    monkeypatch.setattr(app.state.metadata, "localized_text", translated, raising=False)
    response = client.get(f"/api/entries/{entry['id']}/localized-metadata")
    assert response.json()["title"] == "Titre traduit"
    assert response.json()["language"] == "fr"
    current = client.get(f"/api/entries/{entry['id']}").json()
    assert current["catalog_item"] == entry["catalog_item"]
    assert current["notes"] == entry["notes"]
    assert current["version"] == entry["version"]

    async def unavailable(_catalog):
        raise ProviderUnavailable("Synthetic outage")

    monkeypatch.setattr(app.state.metadata, "localized_text", unavailable)
    response = client.get(f"/api/entries/{entry['id']}/localized-metadata")
    assert response.json() == {"language": "fr", "status": "temporarily_unavailable"}
    assert client.get("/api/entries/does-not-exist/localized-metadata").status_code == 404
    assert client.get(f"/api/entries/{entry['id']}").json()["notes"] == "My unchanged notes"


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["fr-FR", "zh-CN"])
@pytest.mark.parametrize(
    "namespace,value,source",
    [
        ("imdb", "tt12345", "imdb_id"),
        ("thetvdb", "100", "tvdb_id"),
        ("wikidata", "Q123", "wikidata_id"),
    ],
)
async def test_existing_keyless_series_gets_translation_by_stable_cross_id(
    settings, locale, namespace, value, source
):
    calls = []

    def handler(request):
        calls.append(request)
        if "/find/" in request.url.path:
            assert request.url.params["external_source"] == source
            return httpx.Response(
                200, json={"tv_results": [{"id": 20}], "movie_results": [{"id": 999}]}
            )
        assert request.url.path == "/3/tv/20/translations"
        language, region = locale.split("-")
        return httpx.Response(
            200,
            json={
                "translations": [
                    {
                        "iso_639_1": language,
                        "iso_3166_1": region,
                        "data": {"name": "Translated", "overview": "Translated summary"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        service = MetadataService(
            settings.model_copy(update={"tmdb_token": "synthetic", "language": locale}),
            http=ResilientHttpClient(raw, attempts=1),
        )
        catalog = CatalogData(
            canonical_title="Saved TV title",
            overview="Saved English",
            media_type="tv",
            provider_source="tvmaze",
            provider_id="1",
            external_ids={namespace: value},
        )
        before = catalog.model_dump()
        assert (await service.localized_text(catalog))["overview"] == "Translated summary"
        assert (await service.localized_text(catalog))["overview"] == "Translated summary"
        assert len(calls) == 2
        assert catalog.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "exact",
        "movie",
        "wrong_year",
        "sequel",
        "ambiguous",
        "live_action",
        "manual",
        "no_year",
        "truncated",
    ],
)
async def test_anime_translation_search_is_conservative_and_never_relinks(settings, variant):
    calls = []

    def handler(request):
        calls.append(request)
        if "/search/" in request.url.path:
            assert request.url.params["language"] == "en-US"
            assert request.url.path.endswith("movie" if variant == "movie" else "tv")
            row = {
                "id": 20,
                "name": "Example Anime 2" if variant == "sequel" else "Example Anime",
                "title": "Example Anime" if variant == "movie" else None,
                "first_air_date": "2021-01-01" if variant == "wrong_year" else "2020-01-01",
                "release_date": "2020-01-01",
                "genre_ids": [18] if variant == "live_action" else [16],
            }
            return httpx.Response(
                200,
                json={
                    "total_pages": 2 if variant == "truncated" else 1,
                    "results": [row, {**row, "id": 21}] if variant == "ambiguous" else [row],
                },
            )
        return httpx.Response(
            200,
            json={
                "translations": [
                    {
                        "iso_639_1": "fr",
                        "iso_3166_1": "CA",
                        "data": {"overview": "Résumé français"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        service = MetadataService(
            settings.model_copy(update={"tmdb_token": "synthetic", "language": "fr-FR"}),
            http=ResilientHttpClient(raw, attempts=1),
        )
        catalog = CatalogData(
            canonical_title="Example Anime",
            media_type="anime",
            provider_format="movie" if variant == "movie" else "tv",
            release_year=None if variant == "no_year" else 2020,
            provider_source=None if variant == "manual" else "mal",
            provider_id="1",
        )
        before = catalog.model_dump()
        result = await service.localized_text(catalog)
        assert bool(result.get("overview")) == (variant in {"exact", "movie"})
        assert catalog.model_dump() == before
        if variant in {"manual", "no_year"}:
            assert not calls
        elif variant not in {"exact", "movie"}:
            assert not any("translations" in request.url.path for request in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_partial_translation_and_outage_do_not_block_description_fallback(
    settings, monkeypatch, failure
):
    service = MetadataService(settings.model_copy(update={"tmdb_token": "synthetic"}))
    try:
        monkeypatch.setattr(
            service.tmdb,
            "localized_text",
            AsyncMock(
                side_effect=ProviderError("TMDb", "outage") if failure else None,
                return_value={"title": "Titre"},
            ),
        )
        monkeypatch.setattr(
            service.wikidata,
            "localized_text",
            AsyncMock(
                return_value={"title": "Autre titre", "overview": "Description traduite"}
            ),
        )
        catalog = CatalogData(
            canonical_title="Saved",
            media_type="movie",
            provider_source="tmdb_movie",
            provider_id="1",
            external_ids={"wikidata": "Q123"},
        )
        result = await service.localized_text(catalog)
        assert result["overview"] == "Description traduite"
        assert result["overview_provider"] == "wikidata"
        assert result["title"] == ("Autre titre" if failure else "Titre")
        assert bool(result.get("partial_failure")) == failure
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_conflicting_external_ids_never_guess_a_translation(settings):
    def handler(request):
        assert "/find/" in request.url.path
        return httpx.Response(
            200, json={"tv_results": [{"id": 1 if "tt" in request.url.path else 2}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        service = MetadataService(
            settings.model_copy(update={"tmdb_token": "synthetic"}),
            http=ResilientHttpClient(raw, attempts=1),
        )
        catalog = CatalogData(
            canonical_title="Saved",
            media_type="tv",
            provider_source="tvmaze",
            provider_id="1",
            external_ids={"imdb": "tt123", "thetvdb": "20"},
        )
        assert await service.localized_text(catalog) == {}
