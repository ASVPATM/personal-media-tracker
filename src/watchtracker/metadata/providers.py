from __future__ import annotations

from datetime import date
from typing import Any

from watchtracker.metadata.cache import TTLCache, cache_key
from watchtracker.metadata.http import ResilientHttpClient
from watchtracker.schemas import CatalogData, SearchResult


def _year(value: str | None) -> int | None:
    try:
        return int(str(value)[:4]) if value else None
    except ValueError:
        return None


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class TMDbClient:
    base_url = "https://api.themoviedb.org/3"
    image_base = "https://image.tmdb.org/t/p/w500"

    def __init__(
        self, token: str, http: ResilientHttpClient, cache: TTLCache, language: str, region: str
    ):
        self.token = token
        self.http = http
        self.cache = cache
        self.language = language
        self.region = region

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def search(self, query: str, media_type: str) -> list[SearchResult]:
        key = cache_key(
            "tmdb",
            "search",
            {
                "q": query.casefold(),
                "type": media_type,
                "language": self.language,
                "region": self.region,
            },
        )
        if (cached := self.cache.get(key)) is not None:
            return [SearchResult.model_validate(item) for item in cached]
        endpoint = "movie" if media_type == "movie" else "tv"
        payload = await self.http.request_json(
            "TMDb",
            "GET",
            f"{self.base_url}/search/{endpoint}",
            params={
                "query": query,
                "language": self.language,
                "region": self.region,
                "include_adult": "false",
            },
            headers=self.headers,
            secrets=[self.token],
        )
        results = []
        for row in payload.get("results", [])[:12]:
            title = row.get("title") if endpoint == "movie" else row.get("name")
            if not title or row.get("id") is None:
                continue
            original = (
                row.get("original_title") if endpoint == "movie" else row.get("original_name")
            )
            released = (
                row.get("release_date") if endpoint == "movie" else row.get("first_air_date")
            )
            results.append(
                SearchResult(
                    provider=f"tmdb_{endpoint}",
                    provider_id=str(row["id"]),
                    title=title,
                    original_title=original if original != title else None,
                    year=_year(released),
                    media_type="movie" if endpoint == "movie" else "tv",
                    poster_url=f"{self.image_base}{row['poster_path']}"
                    if row.get("poster_path")
                    else None,
                    overview=row.get("overview") or None,
                )
            )
        self.cache.set(key, [item.model_dump(mode="json") for item in results])
        return results

    async def detail(self, provider: str, provider_id: str) -> CatalogData:
        endpoint = "movie" if provider == "tmdb_movie" else "tv"
        key = cache_key(
            "tmdb", "detail", {"type": endpoint, "id": provider_id, "language": self.language}
        )
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "TMDb",
                "GET",
                f"{self.base_url}/{endpoint}/{provider_id}",
                params={"language": self.language, "append_to_response": "keywords"},
                headers=self.headers,
                secrets=[self.token],
            )
            self.cache.set(key, payload)
        title = payload.get("title") if endpoint == "movie" else payload.get("name")
        original = (
            payload.get("original_title")
            if endpoint == "movie"
            else payload.get("original_name")
        )
        released = (
            payload.get("release_date")
            if endpoint == "movie"
            else payload.get("first_air_date")
        )
        keyword_payload = payload.get("keywords") or {}
        keyword_rows = keyword_payload.get("keywords") or keyword_payload.get("results") or []
        countries = payload.get("production_countries") or payload.get("origin_country") or []
        country = None
        if countries:
            country = (
                countries[0].get("iso_3166_1")
                if isinstance(countries[0], dict)
                else countries[0]
            )
        runtime = payload.get("runtime")
        if endpoint == "tv" and not runtime:
            runtimes = payload.get("episode_run_time") or []
            runtime = runtimes[0] if runtimes else None
        provider_format = (
            "limited_series"
            if endpoint == "tv" and payload.get("type") == "Miniseries"
            else endpoint
        )
        return CatalogData(
            canonical_title=title or f"TMDb {provider_id}",
            original_title=original if original != title else None,
            release_year=_year(released),
            release_date=_date(released),
            media_type="movie" if endpoint == "movie" else "tv",
            provider_format=provider_format,
            provider_source=provider,
            provider_id=provider_id,
            tmdb_movie_id=provider_id if endpoint == "movie" else None,
            tmdb_tv_id=provider_id if endpoint == "tv" else None,
            poster_url=f"{self.image_base}{payload['poster_path']}"
            if payload.get("poster_path")
            else None,
            overview=payload.get("overview") or None,
            provider_genres=[
                row["name"] for row in payload.get("genres", []) if row.get("name")
            ],
            keywords=[row["name"] for row in keyword_rows if row.get("name")],
            country=country,
            language=payload.get("original_language"),
            runtime_minutes=runtime,
            episode_count=payload.get("number_of_episodes") if endpoint == "tv" else None,
            public_score=payload.get("vote_average"),
            raw_provider_payload=payload,
        )


class AniListClient:
    url = "https://graphql.anilist.co"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache):
        self.http = http
        self.cache = cache

    async def _query(
        self, operation: str, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        key = cache_key("anilist", operation, variables)
        if (cached := self.cache.get(key)) is not None:
            return cached
        payload = await self.http.request_json(
            "AniList", "POST", self.url, json={"query": query, "variables": variables}
        )
        if payload.get("errors"):
            from watchtracker.metadata.http import ProviderError

            raise ProviderError("AniList", "GraphQL response contained errors")
        self.cache.set(key, payload)
        return payload

    async def search(self, query: str) -> list[SearchResult]:
        document = """
        query ($search: String) { Page(page: 1, perPage: 12) {
          media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
            id idMal title { romaji english native } startDate { year } format description(asHtml:false)
            coverImage { large }
          }
        }}"""
        payload = await self._query("search", document, {"search": query})
        results = []
        for row in payload.get("data", {}).get("Page", {}).get("media", []):
            titles = row.get("title") or {}
            title = titles.get("english") or titles.get("romaji") or titles.get("native")
            if not title:
                continue
            results.append(
                SearchResult(
                    provider="anilist",
                    provider_id=str(row["id"]),
                    title=title,
                    original_title=titles.get("romaji")
                    if titles.get("romaji") != title
                    else None,
                    year=(row.get("startDate") or {}).get("year"),
                    media_type="anime",
                    provider_format=(row.get("format") or "anime").casefold(),
                    poster_url=(row.get("coverImage") or {}).get("large"),
                    overview=row.get("description"),
                )
            )
        return results

    async def detail(self, provider_id: str) -> CatalogData:
        document = """
        query ($id: Int) { Media(id: $id, type: ANIME) {
          id idMal title { romaji english native } startDate { year month day } format status episodes duration
          description(asHtml:false) genres tags { name rank isMediaSpoiler } countryOfOrigin source
          coverImage { extraLarge } averageScore
        }}"""
        payload = await self._query("detail", document, {"id": int(provider_id)})
        row = payload.get("data", {}).get("Media") or {}
        titles = row.get("title") or {}
        title = (
            titles.get("english")
            or titles.get("romaji")
            or titles.get("native")
            or f"AniList {provider_id}"
        )
        start = row.get("startDate") or {}
        release_date = None
        if all(start.get(part) for part in ("year", "month", "day")):
            release_date = date(start["year"], start["month"], start["day"])
        tags = [
            item["name"]
            for item in row.get("tags", [])
            if item.get("name") and item.get("rank", 0) >= 40 and not item.get("isMediaSpoiler")
        ]
        return CatalogData(
            canonical_title=title,
            original_title=titles.get("romaji") if titles.get("romaji") != title else None,
            release_year=start.get("year"),
            release_date=release_date,
            media_type="anime",
            provider_format=(row.get("format") or "anime").casefold(),
            provider_source="anilist",
            provider_id=provider_id,
            anilist_id=provider_id,
            mal_id=str(row["idMal"]) if row.get("idMal") else None,
            poster_url=(row.get("coverImage") or {}).get("extraLarge"),
            overview=row.get("description"),
            provider_genres=row.get("genres") or [],
            keywords=tags,
            country=row.get("countryOfOrigin"),
            runtime_minutes=row.get("duration"),
            episode_count=row.get("episodes"),
            public_score=(row.get("averageScore") or 0) / 10 or None,
            raw_provider_payload=row,
        )


class JikanClient:
    base_url = "https://api.jikan.moe/v4"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache):
        self.http = http
        self.cache = cache

    async def search(self, query: str) -> list[SearchResult]:
        key = cache_key("jikan", "search", {"q": query.casefold()})
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "Jikan",
                "GET",
                f"{self.base_url}/anime",
                params={"q": query, "limit": 12, "sfw": "true"},
            )
            self.cache.set(key, payload)
        results = []
        for row in payload.get("data", [])[:12]:
            if not row.get("title") or row.get("mal_id") is None:
                continue
            images = row.get("images", {}).get("jpg", {})
            results.append(
                SearchResult(
                    provider="mal",
                    provider_id=str(row["mal_id"]),
                    title=row["title_english"] or row["title"],
                    original_title=row["title"] if row.get("title_english") else None,
                    year=row.get("year"),
                    media_type="anime",
                    provider_format=(row.get("type") or "anime").casefold(),
                    poster_url=images.get("large_image_url") or images.get("image_url"),
                    overview=row.get("synopsis"),
                )
            )
        return results

    async def detail(self, provider_id: str) -> CatalogData:
        key = cache_key("jikan", "detail", {"id": provider_id})
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "Jikan", "GET", f"{self.base_url}/anime/{provider_id}/full"
            )
            self.cache.set(key, payload)
        row = payload.get("data") or {}
        images = row.get("images", {}).get("jpg", {})
        aired = row.get("aired", {}).get("from")
        genres = [
            item["name"]
            for group in ("genres", "explicit_genres", "themes", "demographics")
            for item in row.get(group, [])
            if item.get("name")
        ]
        return CatalogData(
            canonical_title=row.get("title_english")
            or row.get("title")
            or f"MAL {provider_id}",
            original_title=row.get("title") if row.get("title_english") else None,
            release_year=row.get("year") or _year(aired),
            release_date=_date(aired[:10]) if aired else None,
            media_type="anime",
            provider_format=(row.get("type") or "anime").casefold(),
            provider_source="mal",
            provider_id=provider_id,
            mal_id=provider_id,
            poster_url=images.get("large_image_url") or images.get("image_url"),
            overview=row.get("synopsis"),
            provider_genres=genres,
            keywords=[item["name"] for item in row.get("themes", []) if item.get("name")],
            country="JP",
            runtime_minutes=None,
            episode_count=row.get("episodes"),
            public_score=row.get("score"),
            raw_provider_payload=row,
        )
