from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from watchtracker.config import Settings
from watchtracker.metadata.base import MetadataProviderRegistry
from watchtracker.metadata.cache import TTLCache
from watchtracker.metadata.http import ProviderError, ResilientHttpClient
from watchtracker.metadata.providers import (
    AniListClient,
    AnimeMetadataProvider,
    JikanClient,
    KitsuClient,
    TMDbClient,
    TMDbMetadataProvider,
    TVMazeClient,
    TVMazeMetadataProvider,
    WikidataClient,
    WikidataMetadataProvider,
)
from watchtracker.metadata.resolver import cluster_search_results
from watchtracker.schemas import (
    CatalogData,
    MetadataSourceSnapshot,
    ProviderReference,
    SearchResponse,
    SearchResult,
)
from watchtracker.taxonomy import normalize_title


class ProviderUnavailable(RuntimeError):
    pass


class MetadataService:
    """Provider-neutral metadata coordinator with partial-failure isolation."""

    def __init__(
        self,
        settings: Settings,
        *,
        http: ResilientHttpClient | None = None,
        tmdb: Any | None = None,
        anilist: Any | None = None,
        jikan: Any | None = None,
        kitsu: Any | None = None,
        tvmaze: Any | None = None,
        wikidata: Any | None = None,
    ):
        self.settings = settings
        self.http = http or ResilientHttpClient()
        self.cache = TTLCache(
            settings.resolved_cache_dir,
            settings.cache_ttl_seconds,
            settings.cache_max_entries,
        )
        self.tmdb = tmdb or (
            TMDbClient(
                settings.tmdb_token,
                self.http,
                self.cache,
                settings.language,
                settings.region,
            )
            if settings.tmdb_token
            else None
        )
        self.anilist = anilist or AniListClient(self.http, self.cache)
        self.jikan = jikan or JikanClient(self.http, self.cache)
        self.kitsu = kitsu or KitsuClient(self.http, self.cache)
        self.tvmaze = tvmaze or TVMazeClient(self.http, self.cache)
        self.wikidata = wikidata or WikidataClient(self.http, self.cache, settings.language)
        self.anilist_enabled = settings.anilist_enabled or anilist is not None
        self._jikan_unavailable_until = 0.0
        self.registry = MetadataProviderRegistry()
        self._build_registry()

    def _build_registry(self) -> None:
        self.registry = MetadataProviderRegistry()
        if self.tvmaze:
            self.registry.register(TVMazeMetadataProvider(self.tvmaze))
        if self.tmdb:
            self.registry.register(TMDbMetadataProvider(self.tmdb))
        if self.jikan:
            self.registry.register(AnimeMetadataProvider("mal", self.jikan, priority=10))
        if self.kitsu:
            self.registry.register(AnimeMetadataProvider("kitsu", self.kitsu, priority=12))
        if self.anilist_enabled and self.anilist:
            self.registry.register(AnimeMetadataProvider("anilist", self.anilist, priority=15))
        if self.wikidata:
            self.registry.register(WikidataMetadataProvider(self.wikidata))

    def configure_tmdb(self, token: str | None) -> None:
        """Refresh TMDb configuration immediately without restarting the server."""
        self.settings.tmdb_token = token
        self.tmdb = (
            TMDbClient(
                token,
                self.http,
                self.cache,
                self.settings.language,
                self.settings.region,
            )
            if token
            else None
        )
        self._build_registry()

    def with_tmdb_token(self, token: str | None) -> MetadataService:
        """Return a request-scoped coordinator without mutating shared provider state."""
        if (self.tmdb is None) == (token is None):
            current = getattr(self.tmdb, "token", None) if self.tmdb else None
            if current == token:
                return self
        scoped = object.__new__(MetadataService)
        scoped.settings = self.settings
        scoped.http = self.http
        scoped.cache = self.cache
        scoped.tmdb = (
            TMDbClient(
                token,
                self.http,
                self.cache,
                self.settings.language,
                self.settings.region,
            )
            if token
            else None
        )
        scoped.anilist = self.anilist
        scoped.jikan = self.jikan
        scoped.kitsu = self.kitsu
        scoped.tvmaze = self.tvmaze
        scoped.wikidata = self.wikidata
        scoped.anilist_enabled = self.anilist_enabled
        scoped._jikan_unavailable_until = self._jikan_unavailable_until
        scoped.registry = MetadataProviderRegistry()
        scoped._build_registry()
        return scoped

    def provider_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "slug": definition.slug,
                "media_types": list(definition.media_types),
                "capabilities": sorted(definition.capabilities),
                "requires_credential": definition.requires_credential,
                "attribution": definition.attribution,
            }
            for definition in self.registry.definitions()
        ]

    def preferred_identity(
        self,
        external_ids: dict[str, str],
        *,
        capability: str,
        primary: tuple[str | None, str | None] = (None, None),
    ) -> tuple[str, str] | None:
        candidates = []
        if primary[0] and primary[1]:
            candidates.append((primary[0], primary[1]))
        candidates.extend(
            (provider, external_ids[provider])
            for provider in (
                "tvmaze",
                "tmdb_movie",
                "tmdb_tv",
                "mal",
                "kitsu",
                "anilist",
                "wikidata",
            )
            if provider in external_ids
        )
        for provider_slug, provider_id in dict.fromkeys(candidates):
            provider = self.registry.for_result(provider_slug)
            if provider and capability in provider.definition.capabilities:
                return provider_slug, provider_id
        return None

    async def search(self, query: str, media_type: str | None = None) -> SearchResponse:
        query = " ".join(query.split())
        if len(query) < 1:
            return SearchResponse(results=[], warnings=[])
        warnings: list[str] = []
        requests: list[tuple[Any, str]] = []
        requested_types = ("movie", "tv", "anime") if media_type is None else (media_type,)

        seen_requests: set[tuple[str, str]] = set()
        for requested_type in requested_types:
            for provider in self.registry.searchers(requested_type):
                slug = provider.definition.slug
                if slug == "wikidata" and self.tmdb is not None:
                    continue
                if media_type is None and slug == "tmdb" and requested_type == "anime":
                    continue
                if slug == "mal" and time.monotonic() < self._jikan_unavailable_until:
                    warnings.append("Jikan search is temporarily unavailable.")
                    continue
                key = (slug, requested_type)
                if key not in seen_requests:
                    requests.append((provider, requested_type))
                    seen_requests.add(key)

        outcomes = await asyncio.gather(
            *(provider.search(query, requested_type) for provider, requested_type in requests),
            return_exceptions=True,
        )
        results: list[SearchResult] = []
        tmdb_movie_failed = False
        for (provider, requested_type), outcome in zip(requests, outcomes, strict=True):
            name = provider.definition.slug
            if isinstance(outcome, Exception):
                if name == "mal":
                    self._jikan_unavailable_until = time.monotonic() + 60
                if name == "tmdb" and requested_type == "movie":
                    tmdb_movie_failed = True
                warnings.append(
                    f"{self._display_name(name)} search is temporarily unavailable."
                )
                continue
            results.extend(outcome)

        if (
            (media_type in {None, "movie"})
            and self.tmdb is not None
            and tmdb_movie_failed
            and self.wikidata is not None
        ):
            try:
                results.extend(await self.wikidata.search(query, "movie"))
            except Exception:
                warnings.append("Wikidata search is temporarily unavailable.")

        provider_priority = self._provider_priority(media_type)
        results = cluster_search_results(results, provider_priority=provider_priority)
        normalized_query = normalize_title(query)

        def relevance(item: SearchResult) -> int:
            titles = {
                normalize_title(item.title),
                normalize_title(item.original_title or ""),
                *(normalize_title(alias) for alias in item.aliases),
            }
            if normalized_query in titles:
                return 0
            if any(title.startswith(normalized_query) for title in titles):
                return 1
            if any(normalized_query in title for title in titles):
                return 2
            return 3

        results.sort(
            key=lambda item: (
                relevance(item),
                provider_priority.get(item.provider, 999),
                -(item.popularity or 0),
                item.title.casefold(),
                item.year or 0,
            )
        )
        return SearchResponse(results=results[:30], warnings=list(dict.fromkeys(warnings)))

    @staticmethod
    def _display_name(slug: str) -> str:
        return {
            "tmdb": "TMDb",
            "tvmaze": "TVmaze",
            "mal": "Jikan",
            "kitsu": "Kitsu",
            "anilist": "AniList",
            "wikidata": "Wikidata",
        }.get(slug, slug)

    @staticmethod
    def _provider_priority(media_type: str | None) -> dict[str, int]:
        if media_type == "anime":
            return {
                "mal": 0,
                "kitsu": 1,
                "anilist": 2,
                "tmdb_tv": 3,
                "tmdb_movie": 4,
            }
        if media_type == "tv":
            return {"tvmaze": 0, "tmdb_tv": 1}
        if media_type == "movie":
            return {"tmdb_movie": 0, "wikidata": 10}
        return {
            "tmdb_movie": 0,
            "tvmaze": 1,
            "tmdb_tv": 2,
            "mal": 3,
            "kitsu": 4,
            "anilist": 5,
            "wikidata": 10,
        }

    async def _detail_reference(self, reference: ProviderReference) -> CatalogData:
        provider = self.registry.for_result(reference.provider)
        if not provider:
            raise ProviderUnavailable(f"{reference.provider} metadata is not configured.")
        try:
            return await provider.detail(reference.provider, reference.provider_id)
        except ProviderError as exc:
            raise ProviderUnavailable(exc.public_message) from exc
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable(
                f"{self._display_name(provider.definition.slug)} is temporarily unavailable."
            ) from exc

    async def detail(self, result: SearchResult) -> CatalogData:
        references = [
            ProviderReference(provider=result.provider, provider_id=result.provider_id),
            *result.corroborating_results[:3],
        ]
        outcomes = await asyncio.gather(
            *(self._detail_reference(reference) for reference in references),
            return_exceptions=True,
        )
        successful = [
            (reference, outcome)
            for reference, outcome in zip(references, outcomes, strict=True)
            if isinstance(outcome, CatalogData)
        ]
        if not successful:
            first = next(
                (outcome for outcome in outcomes if isinstance(outcome, Exception)), None
            )
            raise ProviderUnavailable(str(first or "Metadata providers are unavailable."))

        primary_reference, primary = successful[0]
        if result.media_type == "anime" and primary.provider_source in {
            "tmdb_movie",
            "tmdb_tv",
        }:
            primary.media_type = "anime"
        merged = primary.model_copy(deep=True)
        merged.external_ids = {**result.external_ids, **primary.external_ids}
        merged.source_snapshots = []
        merged.field_sources = {}
        scalar_fields = (
            "canonical_title",
            "original_title",
            "release_year",
            "release_date",
            "provider_format",
            "poster_url",
            "overview",
            "country",
            "language",
            "runtime_minutes",
            "episode_count",
            "public_score",
        )
        for reference, data in successful:
            if result.media_type == "anime" and data.provider_source in {
                "tmdb_movie",
                "tmdb_tv",
            }:
                data.media_type = "anime"
            fields = data.model_dump(
                mode="json",
                exclude={"raw_provider_payload", "source_snapshots", "field_sources"},
            )
            merged.source_snapshots.append(
                MetadataSourceSnapshot(
                    provider=reference.provider,
                    provider_id=reference.provider_id,
                    fields=fields,
                    external_ids=data.external_ids,
                )
            )
            merged.external_ids.update(data.external_ids)
            for field in scalar_fields:
                current = getattr(merged, field)
                incoming = getattr(data, field)
                if current in {None, ""} and incoming not in {None, ""}:
                    setattr(merged, field, incoming)
                    merged.field_sources[field] = reference.provider
                elif current not in {None, ""} and field not in merged.field_sources:
                    merged.field_sources[field] = primary_reference.provider
            merged.provider_genres = list(
                dict.fromkeys([*merged.provider_genres, *data.provider_genres])
            )
            merged.keywords = list(dict.fromkeys([*merged.keywords, *data.keywords]))
        merged.tmdb_movie_id = merged.tmdb_movie_id or merged.external_ids.get("tmdb_movie")
        merged.tmdb_tv_id = merged.tmdb_tv_id or merged.external_ids.get("tmdb_tv")
        merged.anilist_id = merged.anilist_id or merged.external_ids.get("anilist")
        merged.mal_id = merged.mal_id or merged.external_ids.get("mal")
        if not merged.poster_url:
            merged.poster_url = result.poster_url
        if not merged.overview:
            merged.overview = result.overview
        return merged

    async def series_schedule(
        self, provider_slug: str, provider_id: str, *, refresh: bool = False
    ) -> dict:
        provider = self.registry.for_result(provider_slug)
        if not provider or "schedule" not in provider.definition.capabilities:
            raise ProviderUnavailable(
                "No supported episode provider is configured for this title."
            )
        try:
            return await provider.series_schedule(provider_slug, provider_id, refresh=refresh)
        except ProviderError as exc:
            raise ProviderUnavailable(exc.public_message) from exc

    async def artwork_options(self, provider_slug: str, provider_id: str) -> list[dict]:
        provider = self.registry.for_result(provider_slug)
        if not provider or "artwork" not in provider.definition.capabilities:
            raise ProviderUnavailable(
                "Alternative artwork is not available from this title's metadata source."
            )
        try:
            return await provider.artwork_options(provider_slug, provider_id)
        except ProviderError as exc:
            raise ProviderUnavailable(exc.public_message) from exc

    async def close(self) -> None:
        await self.http.close()


def metadata_timestamp() -> datetime:
    return datetime.now(UTC)
