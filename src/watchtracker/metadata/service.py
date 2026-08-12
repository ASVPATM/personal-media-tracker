from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from watchtracker.config import Settings
from watchtracker.metadata.cache import TTLCache
from watchtracker.metadata.http import ProviderError, ResilientHttpClient
from watchtracker.metadata.providers import AniListClient, JikanClient, TMDbClient
from watchtracker.schemas import CatalogData, SearchResponse, SearchResult
from watchtracker.taxonomy import normalize_title


class ProviderUnavailable(RuntimeError):
    pass


class MetadataService:
    def __init__(
        self,
        settings: Settings,
        *,
        http: ResilientHttpClient | None = None,
        tmdb: TMDbClient | None = None,
        anilist: AniListClient | None = None,
        jikan: JikanClient | None = None,
    ):
        self.settings = settings
        self.http = http or ResilientHttpClient()
        self.cache = TTLCache(
            settings.resolved_cache_dir, settings.cache_ttl_seconds, settings.cache_max_entries
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
        self.anilist_enabled = settings.anilist_enabled or anilist is not None

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

    async def search(self, query: str, media_type: str | None = None) -> SearchResponse:
        query = " ".join(query.split())
        if len(query) < 1:
            return SearchResponse(results=[], warnings=[])
        warnings: list[str] = []
        tasks: list[tuple[str, object]] = []
        if media_type in (None, "movie", "tv"):
            if self.tmdb:
                for kind in ("movie", "tv"):
                    if media_type in (None, kind):
                        tasks.append(("TMDb", self.tmdb.search(query, kind)))
            elif media_type in (None, "movie", "tv"):
                warnings.append(
                    "Movie and TV search needs a TMDb token; anime and manual add still work."
                )
        if media_type in (None, "anime") and self.anilist_enabled:
            tasks.append(("AniList", self.anilist.search(query)))

        outcomes = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        results: list[SearchResult] = []
        anime_success = False
        for (name, _), outcome in zip(tasks, outcomes, strict=True):
            if isinstance(outcome, Exception):
                warnings.append(f"{name} search is temporarily unavailable.")
            else:
                results.extend(outcome)
                if name == "AniList" and outcome:
                    anime_success = True
        if media_type in (None, "anime") and not anime_success:
            try:
                results.extend(await self.jikan.search(query))
            except ProviderError:
                warnings.append("Anime fallback search is temporarily unavailable.")

        provider_order = {"tmdb_movie": 0, "tmdb_tv": 1, "anilist": 2, "mal": 3}
        normalized_query = normalize_title(query)

        def relevance(item: SearchResult) -> int:
            titles = {
                normalize_title(item.title),
                normalize_title(item.original_title or ""),
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
                provider_order[item.provider],
                item.title.casefold(),
                item.year or 0,
            )
        )
        return SearchResponse(results=results[:30], warnings=list(dict.fromkeys(warnings)))

    async def detail(self, result: SearchResult) -> CatalogData:
        try:
            if result.provider.startswith("tmdb_"):
                if not self.tmdb:
                    raise ProviderUnavailable("TMDb is not configured.")
                data = await self.tmdb.detail(result.provider, result.provider_id)
            elif result.provider == "anilist":
                if not self.anilist_enabled:
                    raise ProviderUnavailable(
                        "AniList is disabled in this build; Jikan and manual metadata remain available."
                    )
                data = await self.anilist.detail(result.provider_id)
            else:
                data = await self.jikan.detail(result.provider_id)
        except ProviderError as exc:
            raise ProviderUnavailable(exc.public_message) from exc
        # Provider result text is retained only as a fallback for unexpectedly sparse detail records.
        if not data.poster_url:
            data.poster_url = result.poster_url
        if not data.overview:
            data.overview = result.overview
        return data

    async def close(self) -> None:
        await self.http.close()


def metadata_timestamp() -> datetime:
    return datetime.now(UTC)
