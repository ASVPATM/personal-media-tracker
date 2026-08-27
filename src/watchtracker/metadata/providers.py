from __future__ import annotations

import asyncio
import html
import re
import time
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import quote

from watchtracker import __version__
from watchtracker.metadata.base import MetadataProviderDefinition
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
                "result_schema": 2,
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
                    popularity=row.get("popularity"),
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
                params={
                    "language": self.language,
                    "append_to_response": "keywords,external_ids",
                },
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
        external = payload.get("external_ids") or {}
        external_ids = {
            namespace: str(value)
            for namespace, value in {
                f"tmdb_{endpoint}": provider_id,
                "imdb": external.get("imdb_id") or payload.get("imdb_id"),
                "thetvdb": external.get("tvdb_id"),
                "wikidata": external.get("wikidata_id"),
            }.items()
            if value not in {None, ""}
        }
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
            external_ids=external_ids,
            raw_provider_payload=payload,
        )

    async def posters(self, provider: str, provider_id: str) -> list[dict[str, Any]]:
        endpoint = "movie" if provider == "tmdb_movie" else "tv"
        language = self.language.split("-", 1)[0]
        key = cache_key(
            "tmdb",
            "posters",
            {"type": endpoint, "id": provider_id, "language": language},
        )
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "TMDb",
                "GET",
                f"{self.base_url}/{endpoint}/{provider_id}/images",
                params={"include_image_language": f"{language},en,null"},
                headers=self.headers,
                secrets=[self.token],
            )
            self.cache.set(key, payload)
        rows = [row for row in payload.get("posters", []) if row.get("file_path")]
        rows.sort(
            key=lambda row: (
                row.get("iso_639_1") not in {language, None},
                -(row.get("vote_count") or 0),
                -(row.get("vote_average") or 0),
                -(row.get("width") or 0),
            )
        )
        return [
            {
                "poster_url": f"{self.image_base}{row['file_path']}",
                "language": row.get("iso_639_1"),
                "width": row.get("width"),
                "height": row.get("height"),
                "vote_average": row.get("vote_average"),
            }
            for row in rows[:30]
        ]

    async def series_schedule(
        self, provider_id: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        """Fetch one complete, bounded TMDB series schedule before any database write."""
        details_key = cache_key(
            "tmdb", "series-schedule", {"id": provider_id, "language": self.language}
        )
        details = None if refresh else self.cache.get(details_key)
        if details is None:
            details = await self.http.request_json(
                "TMDb",
                "GET",
                f"{self.base_url}/tv/{provider_id}",
                params={"language": self.language},
                headers=self.headers,
                secrets=[self.token],
            )
            self.cache.set(details_key, details)
        season_summaries = [
            row
            for row in details.get("seasons", [])[:60]
            if isinstance(row, dict) and isinstance(row.get("season_number"), int)
        ]
        semaphore = asyncio.Semaphore(4)

        async def fetch_season(summary: dict[str, Any]) -> dict[str, Any]:
            number = summary["season_number"]
            key = cache_key(
                "tmdb",
                "season-schedule",
                {"id": provider_id, "season": number, "language": self.language},
            )
            payload = None if refresh else self.cache.get(key)
            if payload is None:
                async with semaphore:
                    payload = await self.http.request_json(
                        "TMDb",
                        "GET",
                        f"{self.base_url}/tv/{provider_id}/season/{number}",
                        params={"language": self.language},
                        headers=self.headers,
                        secrets=[self.token],
                    )
                self.cache.set(key, payload)
            episodes = []
            for episode in payload.get("episodes", []):
                if not isinstance(episode, dict) or episode.get("id") is None:
                    continue
                episodes.append(
                    {
                        "provider_episode_id": str(episode["id"]),
                        "episode_number": episode.get("episode_number"),
                        "title": episode.get("name") or None,
                        "overview": episode.get("overview") or None,
                        "air_date": episode.get("air_date") or None,
                        "runtime_minutes": episode.get("runtime"),
                        "production_code": episode.get("production_code") or None,
                    }
                )
            return {
                "provider_season_id": str(payload.get("id") or summary.get("id") or "") or None,
                "season_number": number,
                "title": payload.get("name") or summary.get("name") or None,
                "overview": payload.get("overview") or summary.get("overview") or None,
                "poster_url": (
                    f"{self.image_base}{payload['poster_path']}"
                    if payload.get("poster_path")
                    else (
                        f"{self.image_base}{summary['poster_path']}"
                        if summary.get("poster_path")
                        else None
                    )
                ),
                "air_date": payload.get("air_date") or summary.get("air_date") or None,
                "episode_count": len(episodes),
                "episodes": episodes,
            }

        seasons = await asyncio.gather(*(fetch_season(row) for row in season_summaries))
        return {
            "provider_source": "tmdb_tv",
            "provider_series_id": str(provider_id),
            "status": details.get("status") or None,
            "seasons": list(seasons),
        }


class AniListClient:
    url = "https://graphql.anilist.co"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache):
        self.http = http
        self.cache = cache

    async def _query(
        self,
        operation: str,
        query: str,
        variables: dict[str, Any],
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        key = cache_key("anilist", operation, {"result_schema": 3, **variables})
        if not refresh and (cached := self.cache.get(key)) is not None:
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
            id idMal title { romaji english native } synonyms startDate { year } format popularity description(asHtml:false)
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
                    aliases=list(
                        dict.fromkeys(
                            value
                            for value in [
                                titles.get("english"),
                                titles.get("romaji"),
                                titles.get("native"),
                                *(row.get("synonyms") or []),
                            ]
                            if value and value != title
                        )
                    ),
                    year=(row.get("startDate") or {}).get("year"),
                    media_type="anime",
                    provider_format=(row.get("format") or "anime").casefold(),
                    poster_url=(row.get("coverImage") or {}).get("large"),
                    overview=row.get("description"),
                    popularity=row.get("popularity"),
                    external_ids={
                        **({"anilist": str(row["id"])} if row.get("id") else {}),
                        **({"mal": str(row["idMal"])} if row.get("idMal") else {}),
                    },
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
            external_ids={
                "anilist": provider_id,
                **({"mal": str(row["idMal"])} if row.get("idMal") else {}),
            },
            raw_provider_payload=row,
        )


class JikanClient:
    base_url = "https://api.jikan.moe/v4"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache):
        self.http = http
        self.cache = cache
        self._rate_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def _throttle(self) -> None:
        async with self._rate_lock:
            delay = self._next_request_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = time.monotonic() + 0.34

    async def search(self, query: str) -> list[SearchResult]:
        key = cache_key("jikan", "search", {"q": query.casefold(), "result_schema": 2})
        payload = self.cache.get(key)
        if payload is None:
            await self._throttle()
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
                    aliases=list(
                        dict.fromkeys(
                            value
                            for value in [
                                *(
                                    title_row.get("title")
                                    for title_row in row.get("titles", [])
                                    if isinstance(title_row, dict)
                                ),
                                *(row.get("title_synonyms") or []),
                            ]
                            if value
                            and value not in {row.get("title_english"), row.get("title")}
                        )
                    ),
                    year=row.get("year"),
                    media_type="anime",
                    provider_format=(row.get("type") or "anime").casefold(),
                    poster_url=images.get("large_image_url") or images.get("image_url"),
                    overview=row.get("synopsis"),
                    popularity=row.get("members"),
                    external_ids={"mal": str(row["mal_id"])},
                )
            )
        return results

    async def detail(self, provider_id: str) -> CatalogData:
        key = cache_key("jikan", "detail", {"id": provider_id})
        payload = self.cache.get(key)
        if payload is None:
            await self._throttle()
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
            external_ids={"mal": provider_id},
            raw_provider_payload=row,
        )

    async def posters(self, provider_id: str) -> list[dict[str, Any]]:
        key = cache_key("jikan", "posters", {"id": provider_id})
        payload = self.cache.get(key)
        if payload is None:
            await self._throttle()
            payload = await self.http.request_json(
                "Jikan", "GET", f"{self.base_url}/anime/{provider_id}/pictures"
            )
            self.cache.set(key, payload)
        rows = []
        for item in payload.get("data", [])[:30]:
            images = item.get("jpg") or {}
            url = images.get("large_image_url") or images.get("image_url")
            if url:
                rows.append({"poster_url": url})
        return rows


def _kitsu_titles(attributes: dict[str, Any]) -> tuple[str, str | None, list[str]]:
    titles = attributes.get("titles") or {}
    canonical = attributes.get("canonicalTitle")
    english = titles.get("en") or titles.get("en_us")
    romanized = titles.get("en_jp") or canonical
    native = titles.get("ja_jp")
    title = english or romanized or native or "Untitled anime"
    aliases = list(
        dict.fromkeys(
            value
            for value in [
                canonical,
                *titles.values(),
                *(attributes.get("abbreviatedTitles") or []),
            ]
            if value and value != title
        )
    )
    return title, romanized if romanized and romanized != title else None, aliases


def _kitsu_external_ids(
    row: dict[str, Any], included_by_id: dict[str, dict[str, Any]]
) -> dict[str, str]:
    external_ids = {"kitsu": str(row["id"])}
    mappings = ((row.get("relationships") or {}).get("mappings") or {}).get("data") or []
    for reference in mappings:
        mapping = included_by_id.get(str(reference.get("id"))) or {}
        attributes = mapping.get("attributes") or {}
        site = str(attributes.get("externalSite") or "").casefold()
        external_id = attributes.get("externalId")
        if not external_id:
            continue
        if site == "myanimelist/anime":
            external_ids["mal"] = str(external_id)
        elif site == "anilist/anime":
            external_ids["anilist"] = str(external_id)
    return external_ids


class KitsuClient:
    """Keyless anime fallback using Kitsu's public JSON:API."""

    base_url = "https://kitsu.io/api/edge"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache):
        self.http = http
        self.cache = cache
        self.headers = {
            "Accept": "application/vnd.api+json",
            "User-Agent": f"PersonalMediaTracker/{__version__} (+https://github.com/ASVPATM/personal-media-tracker)",
        }

    async def search(self, query: str) -> list[SearchResult]:
        key = cache_key("kitsu", "search", {"q": query.casefold(), "schema": 1})
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "Kitsu",
                "GET",
                f"{self.base_url}/anime",
                params={"filter[text]": query, "page[limit]": 12, "include": "mappings"},
                headers=self.headers,
            )
            self.cache.set(key, payload)
        included_by_id = {
            str(item.get("id")): item
            for item in payload.get("included", [])
            if item.get("type") == "mappings" and item.get("id") is not None
        }
        results = []
        for row in payload.get("data", [])[:12]:
            if row.get("id") is None:
                continue
            attributes = row.get("attributes") or {}
            title, original_title, aliases = _kitsu_titles(attributes)
            poster = attributes.get("posterImage") or {}
            results.append(
                SearchResult(
                    provider="kitsu",
                    provider_id=str(row["id"]),
                    title=title,
                    original_title=original_title,
                    aliases=aliases,
                    year=_year(attributes.get("startDate")),
                    media_type="anime",
                    provider_format=(attributes.get("subtype") or "anime").casefold(),
                    poster_url=poster.get("large") or poster.get("original"),
                    overview=attributes.get("synopsis") or attributes.get("description"),
                    popularity=float(
                        attributes.get("userCount") or attributes.get("favoritesCount") or 0
                    ),
                    external_ids=_kitsu_external_ids(row, included_by_id),
                )
            )
        return results

    async def detail(self, provider_id: str) -> CatalogData:
        key = cache_key("kitsu", "detail", {"id": provider_id, "schema": 1})
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "Kitsu",
                "GET",
                f"{self.base_url}/anime/{provider_id}",
                params={"include": "categories,mappings"},
                headers=self.headers,
            )
            self.cache.set(key, payload)
        row = payload.get("data") or {}
        attributes = row.get("attributes") or {}
        title, original_title, _aliases = _kitsu_titles(attributes)
        included_by_id = {
            str(item.get("id")): item
            for item in payload.get("included", [])
            if item.get("id") is not None
        }
        category_refs = ((row.get("relationships") or {}).get("categories") or {}).get(
            "data"
        ) or []
        genres = [
            (included_by_id.get(str(reference.get("id"))) or {})
            .get("attributes", {})
            .get("title")
            for reference in category_refs
        ]
        genres = [value for value in genres if value]
        poster = attributes.get("posterImage") or {}
        score = attributes.get("averageRating")
        return CatalogData(
            canonical_title=title,
            original_title=original_title,
            release_year=_year(attributes.get("startDate")),
            release_date=_date(attributes.get("startDate")),
            media_type="anime",
            provider_format=(attributes.get("subtype") or "anime").casefold(),
            provider_source="kitsu",
            provider_id=provider_id,
            poster_url=poster.get("original") or poster.get("large"),
            overview=attributes.get("synopsis") or attributes.get("description"),
            provider_genres=genres,
            country="JP",
            language="ja",
            runtime_minutes=attributes.get("episodeLength"),
            episode_count=attributes.get("episodeCount"),
            public_score=round(float(score) / 10, 2) if score else None,
            external_ids=_kitsu_external_ids(row, included_by_id),
            raw_provider_payload=payload,
        )

    async def posters(self, provider_id: str) -> list[dict[str, Any]]:
        detail = await self.detail(provider_id)
        return [{"poster_url": detail.poster_url}] if detail.poster_url else []

    async def series_schedule(
        self, provider_id: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        """Return Kitsu-confirmed episode dates without requiring a user credential."""
        detail_key = cache_key("kitsu", "schedule-detail", {"id": provider_id, "schema": 1})
        episode_key = cache_key("kitsu", "schedule-episodes", {"id": provider_id, "schema": 1})
        detail_payload = None if refresh else self.cache.get(detail_key)
        episode_payload = None if refresh else self.cache.get(episode_key)
        if detail_payload is None:
            detail_payload = await self.http.request_json(
                "Kitsu",
                "GET",
                f"{self.base_url}/anime/{provider_id}",
                headers=self.headers,
            )
            self.cache.set(detail_key, detail_payload)
        if episode_payload is None:
            episode_payload = await self.http.request_json(
                "Kitsu",
                "GET",
                f"{self.base_url}/anime/{provider_id}/episodes",
                params={"page[limit]": 20, "page[offset]": 0},
                headers=self.headers,
            )
            count = int((episode_payload.get("meta") or {}).get("count") or 0)
            if count > 20:
                tail = await self.http.request_json(
                    "Kitsu",
                    "GET",
                    f"{self.base_url}/anime/{provider_id}/episodes",
                    params={"page[limit]": 20, "page[offset]": count - 20},
                    headers=self.headers,
                )
                rows_by_id = {
                    str(item.get("id")): item
                    for item in [
                        *episode_payload.get("data", []),
                        *tail.get("data", []),
                    ]
                    if item.get("id") is not None
                }
                episode_payload = {**episode_payload, "data": list(rows_by_id.values())}
            self.cache.set(episode_key, episode_payload)

        attributes = (detail_payload.get("data") or {}).get("attributes") or {}
        declared_total = attributes.get("episodeCount")
        if not isinstance(declared_total, int) or declared_total < 0:
            declared_total = 0
        grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in episode_payload.get("data", [])[:40]:
            if row.get("id") is None:
                continue
            item = row.get("attributes") or {}
            number = item.get("relativeNumber") or item.get("number")
            season_number = item.get("seasonNumber") or 1
            if not isinstance(number, int) or not isinstance(season_number, int):
                continue
            air_date = _date(item.get("airDate") or item.get("airdate"))
            titles = item.get("titles") or {}
            grouped[season_number].append(
                {
                    "provider_episode_id": str(row["id"]),
                    "episode_number": number,
                    "title": item.get("canonicalTitle")
                    or titles.get("en")
                    or titles.get("en_jp")
                    or f"Episode {number}",
                    "overview": item.get("synopsis") or item.get("description"),
                    "air_date": air_date.isoformat() if air_date else None,
                    "runtime_minutes": item.get("length") or attributes.get("episodeLength"),
                    "production_code": None,
                }
            )
        status = str(attributes.get("status") or "").casefold()
        released_count = declared_total if status == "finished" and declared_total else None
        seasons = [
            {
                "provider_season_id": f"{provider_id}:{season_number}",
                "season_number": season_number,
                "title": f"Season {season_number}",
                "overview": None,
                "poster_url": None,
                "air_date": None,
                "episode_count": declared_total if len(grouped) == 1 else len(episodes),
                "episodes": sorted(episodes, key=lambda item: item["episode_number"]),
            }
            for season_number, episodes in sorted(grouped.items())
        ]
        if not seasons:
            seasons = [
                {
                    "provider_season_id": f"{provider_id}:1",
                    "season_number": 1,
                    "title": "Episodes",
                    "overview": None,
                    "poster_url": None,
                    "air_date": None,
                    "episode_count": declared_total or None,
                    "episodes": [],
                }
            ]
        return {
            "provider_source": "kitsu",
            "provider_series_id": str(provider_id),
            "status": attributes.get("status"),
            "released_episode_count": released_count,
            "seasons": seasons,
        }


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split()) or None


def _tvmaze_external_ids(row: dict[str, Any]) -> dict[str, str]:
    external = row.get("externals") or {}
    return {
        namespace: str(value)
        for namespace, value in {
            "imdb": external.get("imdb"),
            "thetvdb": external.get("thetvdb"),
            "tvrage": external.get("tvrage"),
        }.items()
        if value not in {None, ""}
    }


class TVMazeClient:
    base_url = "https://api.tvmaze.com"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache):
        self.http = http
        self.cache = cache
        self.headers = {
            "User-Agent": f"PersonalMediaTracker/{__version__} (+https://github.com/ASVPATM/personal-media-tracker)"
        }

    async def search(self, query: str) -> list[SearchResult]:
        key = cache_key("tvmaze", "search", {"q": query.casefold(), "schema": 1})
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json_value(
                "TVmaze",
                "GET",
                f"{self.base_url}/search/shows",
                params={"q": query},
                headers=self.headers,
            )
            if not isinstance(payload, list):
                raise ValueError("Unexpected TVmaze search response")
            self.cache.set(key, payload)
        results = []
        for result in payload[:12]:
            row = result.get("show") or {}
            if row.get("id") is None or not row.get("name"):
                continue
            image = row.get("image") or {}
            results.append(
                SearchResult(
                    provider="tvmaze",
                    provider_id=str(row["id"]),
                    title=row["name"],
                    year=_year(row.get("premiered")),
                    media_type="tv",
                    provider_format=(row.get("type") or "tv").casefold(),
                    poster_url=image.get("original") or image.get("medium"),
                    overview=_plain_text(row.get("summary")),
                    popularity=float(result.get("score") or row.get("weight") or 0),
                    external_ids=_tvmaze_external_ids(row),
                )
            )
        return results

    async def _show(self, provider_id: str, *, refresh: bool = False) -> dict[str, Any]:
        key = cache_key("tvmaze", "detail", {"id": provider_id, "schema": 1})
        payload = None if refresh else self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json(
                "TVmaze",
                "GET",
                f"{self.base_url}/shows/{provider_id}",
                headers=self.headers,
            )
            self.cache.set(key, payload)
        return payload

    async def detail(self, provider_id: str) -> CatalogData:
        row = await self._show(provider_id)
        image = row.get("image") or {}
        network = row.get("network") or row.get("webChannel") or {}
        country = (network.get("country") or {}).get("code")
        external_ids = {"tvmaze": provider_id, **_tvmaze_external_ids(row)}
        return CatalogData(
            canonical_title=row.get("name") or f"TVmaze {provider_id}",
            release_year=_year(row.get("premiered")),
            release_date=_date(row.get("premiered")),
            media_type="tv",
            provider_format=(row.get("type") or "tv").casefold(),
            provider_source="tvmaze",
            provider_id=provider_id,
            poster_url=image.get("original") or image.get("medium"),
            overview=_plain_text(row.get("summary")),
            provider_genres=row.get("genres") or [],
            country=country,
            language=row.get("language"),
            runtime_minutes=row.get("averageRuntime") or row.get("runtime"),
            public_score=(row.get("rating") or {}).get("average"),
            external_ids=external_ids,
            raw_provider_payload=row,
        )

    async def posters(self, provider_id: str) -> list[dict[str, Any]]:
        key = cache_key("tvmaze", "posters", {"id": provider_id})
        payload = self.cache.get(key)
        if payload is None:
            payload = await self.http.request_json_value(
                "TVmaze",
                "GET",
                f"{self.base_url}/shows/{provider_id}/images",
                headers=self.headers,
            )
            if not isinstance(payload, list):
                raise ValueError("Unexpected TVmaze image response")
            self.cache.set(key, payload)
        rows = []
        for item in payload:
            if item.get("type") != "poster":
                continue
            resolutions = item.get("resolutions") or {}
            image = resolutions.get("original") or resolutions.get("medium") or {}
            if image.get("url"):
                rows.append(
                    {
                        "poster_url": image["url"],
                        "width": image.get("width"),
                        "height": image.get("height"),
                    }
                )
        return rows[:30]

    async def series_schedule(
        self, provider_id: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        episode_key = cache_key("tvmaze", "episodes", {"id": provider_id, "specials": True})
        episodes = None if refresh else self.cache.get(episode_key)
        if episodes is None:
            episodes = await self.http.request_json_value(
                "TVmaze",
                "GET",
                f"{self.base_url}/shows/{provider_id}/episodes",
                params={"specials": "1"},
                headers=self.headers,
            )
            self.cache.set(episode_key, episodes)
        show = await self._show(provider_id, refresh=refresh)
        if not isinstance(episodes, list):
            raise ValueError("Unexpected TVmaze episode response")
        grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in episodes:
            number = row.get("season")
            if not isinstance(number, int) or row.get("id") is None:
                continue
            grouped[number].append(
                {
                    "provider_episode_id": str(row["id"]),
                    "episode_number": row.get("number"),
                    "title": row.get("name") or None,
                    "overview": _plain_text(row.get("summary")),
                    "air_date": row.get("airdate") or None,
                    "runtime_minutes": row.get("runtime"),
                    "production_code": None,
                }
            )
        return {
            "provider_source": "tvmaze",
            "provider_series_id": str(provider_id),
            "status": show.get("status") or None,
            "seasons": [
                {
                    "provider_season_id": f"{provider_id}:{number}",
                    "season_number": number,
                    "title": "Specials" if number == 0 else f"Season {number}",
                    "overview": None,
                    "poster_url": None,
                    "air_date": next(
                        (row["air_date"] for row in rows if row.get("air_date")), None
                    ),
                    "episode_count": len(rows),
                    "episodes": rows,
                }
                for number, rows in sorted(grouped.items())
            ],
        }


def _claim_value(entity: dict[str, Any], property_id: str) -> Any | None:
    claims = (entity.get("claims") or {}).get(property_id) or []
    for claim in claims:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict):
            return value.get("time") or value.get("id") or value.get("numeric-id")
        if value not in {None, ""}:
            return value
    return None


def _claim_values(entity: dict[str, Any], property_id: str) -> list[Any]:
    values = []
    for claim in (entity.get("claims") or {}).get(property_id) or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is None or value == "":
            continue
        values.append(value)
    return values


def _claim_entity_ids(entity: dict[str, Any], property_id: str) -> list[str]:
    return [
        str(value["id"])
        for value in _claim_values(entity, property_id)
        if isinstance(value, dict) and value.get("id")
    ]


def _claim_quantity(entity: dict[str, Any], property_id: str) -> int | None:
    for value in _claim_values(entity, property_id):
        if not isinstance(value, dict) or value.get("amount") in {None, ""}:
            continue
        try:
            return round(float(value["amount"]))
        except (TypeError, ValueError):
            continue
    return None


def _wikimedia_image(entity: dict[str, Any]) -> str | None:
    filename = _claim_value(entity, "P18")
    if not filename:
        return None
    return f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{quote(str(filename))}?width=500"


def _entity_label(entity: dict[str, Any], language: str) -> str | None:
    labels = entity.get("labels") or {}
    return (labels.get(language) or labels.get("en") or {}).get("value")


def _wikidata_external_ids(entity: dict[str, Any]) -> dict[str, str]:
    return {
        namespace: str(value)
        for namespace, value in {
            "imdb": _claim_value(entity, "P345"),
            "tmdb_movie": _claim_value(entity, "P4947"),
            "tmdb_tv": _claim_value(entity, "P4983"),
            "thetvdb": _claim_value(entity, "P4835"),
            "mal": _claim_value(entity, "P4086"),
        }.items()
        if value not in {None, ""}
    }


class WikidataClient:
    base_url = "https://www.wikidata.org/w/api.php"

    def __init__(self, http: ResilientHttpClient, cache: TTLCache, language: str):
        self.http = http
        self.cache = cache
        self.language = language.split("-", 1)[0]
        self._media_types: dict[str, str] = {}
        self.headers = {
            "User-Agent": f"PersonalMediaTracker/{__version__} (+https://github.com/ASVPATM/personal-media-tracker)"
        }

    async def _entities(self, ids: list[str]) -> dict[str, Any]:
        if not ids:
            return {}
        payload = await self.http.request_json(
            "Wikidata",
            "GET",
            self.base_url,
            params={
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "props": "labels|descriptions|aliases|claims",
                "languages": f"{self.language}|en",
                "format": "json",
                "origin": "*",
            },
            headers=self.headers,
        )
        return payload.get("entities") or {}

    async def search(self, query: str, media_type: str) -> list[SearchResult]:
        key = cache_key(
            "wikidata",
            "search",
            {
                "q": query.casefold(),
                "type": media_type,
                "language": self.language,
                "schema": 2,
            },
        )
        cached = self.cache.get(key)
        if cached is not None:
            return [SearchResult.model_validate(item) for item in cached]
        base_query = re.sub(r"[()]", " ", query)
        search_terms = list(dict.fromkeys([query, f"{base_query} film"]))
        payloads = await asyncio.gather(
            *(
                self.http.request_json(
                    "Wikidata",
                    "GET",
                    self.base_url,
                    params={
                        "action": "wbsearchentities",
                        "search": term,
                        "language": self.language,
                        "uselang": self.language,
                        "type": "item",
                        "limit": 8,
                        "format": "json",
                        "origin": "*",
                    },
                    headers=self.headers,
                )
                for term in search_terms
            )
        )
        search_rows = list(
            {
                row["id"]: row
                for payload in payloads
                for row in payload.get("search", [])
                if row.get("id")
            }.values()
        )
        entities = await self._entities([row["id"] for row in search_rows])
        results = []
        for rank, row in enumerate(search_rows):
            entity = entities.get(row["id"]) or {}
            description = str(row.get("description") or "").casefold()
            external_ids = _wikidata_external_ids(entity)
            if media_type == "movie" and not (
                "film" in description
                or "movie" in description
                or external_ids.get("tmdb_movie")
            ):
                continue
            released = _claim_value(entity, "P577")
            aliases = [
                alias.get("value")
                for language_rows in (entity.get("aliases") or {}).values()
                for alias in language_rows
                if alias.get("value")
            ]
            self._media_types[row["id"]] = media_type
            results.append(
                SearchResult(
                    provider="wikidata",
                    provider_id=row["id"],
                    title=row.get("label") or row["id"],
                    aliases=aliases[:30],
                    year=_year(str(released).lstrip("+")) if released else None,
                    media_type=media_type,
                    poster_url=_wikimedia_image(entity),
                    overview=row.get("description") or None,
                    popularity=max(0, 8 - rank),
                    external_ids={"wikidata": row["id"], **external_ids},
                )
            )
        self.cache.set(key, [item.model_dump(mode="json") for item in results])
        return results

    async def detail(self, provider_id: str) -> CatalogData:
        entity = (await self._entities([provider_id])).get(provider_id) or {}
        labels = entity.get("labels") or {}
        descriptions = entity.get("descriptions") or {}
        title = (labels.get(self.language) or labels.get("en") or {}).get("value")
        description = (descriptions.get(self.language) or descriptions.get("en") or {}).get(
            "value"
        )
        released = _claim_value(entity, "P577")
        released_text = str(released).lstrip("+")[:10] if released else None
        media_type = self._media_types.get(provider_id, "movie")
        external_ids = {"wikidata": provider_id, **_wikidata_external_ids(entity)}
        linked_ids = list(
            dict.fromkeys(
                [
                    *_claim_entity_ids(entity, "P136"),
                    *_claim_entity_ids(entity, "P495"),
                    *_claim_entity_ids(entity, "P364"),
                ]
            )
        )
        linked = await self._entities(linked_ids)
        genres = [
            _entity_label(linked.get(item_id) or {}, self.language)
            for item_id in _claim_entity_ids(entity, "P136")
        ]
        country_id = next(iter(_claim_entity_ids(entity, "P495")), None)
        language_id = next(iter(_claim_entity_ids(entity, "P364")), None)
        return CatalogData(
            canonical_title=title or f"Wikidata {provider_id}",
            release_year=_year(released_text),
            release_date=_date(released_text),
            media_type=media_type,
            provider_format=media_type,
            provider_source="wikidata",
            provider_id=provider_id,
            poster_url=_wikimedia_image(entity),
            overview=description,
            provider_genres=[value for value in genres if value],
            country=_entity_label(linked.get(country_id) or {}, self.language)
            if country_id
            else None,
            language=_entity_label(linked.get(language_id) or {}, self.language)
            if language_id
            else None,
            runtime_minutes=_claim_quantity(entity, "P2047"),
            external_ids=external_ids,
            raw_provider_payload=entity,
        )


class TMDbMetadataProvider:
    definition = MetadataProviderDefinition(
        slug="tmdb",
        result_slugs=("tmdb_movie", "tmdb_tv"),
        media_types=("movie", "tv", "anime"),
        capabilities=frozenset({"search", "detail", "artwork", "schedule"}),
        priority=20,
        requires_credential=True,
    )

    def __init__(self, client: TMDbClient):
        self.client = client

    async def search(self, query: str, media_type: str) -> list[SearchResult]:
        kinds = ("tv", "movie") if media_type == "anime" else (media_type,)
        rows = [row for kind in kinds for row in await self.client.search(query, kind)]
        return (
            [row.model_copy(update={"media_type": "anime"}) for row in rows]
            if media_type == "anime"
            else rows
        )

    async def detail(self, provider: str, provider_id: str) -> CatalogData:
        return await self.client.detail(provider, provider_id)

    async def artwork_options(self, provider: str, provider_id: str) -> list[dict]:
        return await self.client.posters(provider, provider_id)

    async def series_schedule(
        self, provider: str, provider_id: str, *, refresh: bool = False
    ) -> dict:
        del provider
        return await self.client.series_schedule(provider_id, refresh=refresh)


class AnimeMetadataProvider:
    def __init__(self, slug: str, client: Any, *, priority: int):
        self.client = client
        schedule_capability = hasattr(client, "series_schedule")
        self.definition = MetadataProviderDefinition(
            slug=slug,
            result_slugs=(slug,),
            media_types=("anime",),
            capabilities=frozenset(
                {
                    "search",
                    "detail",
                    *(["artwork"] if hasattr(client, "posters") else []),
                    *(["schedule"] if schedule_capability else []),
                }
            ),
            priority=priority,
        )

    async def search(self, query: str, media_type: str) -> list[SearchResult]:
        del media_type
        return await self.client.search(query)

    async def detail(self, provider: str, provider_id: str) -> CatalogData:
        del provider
        return await self.client.detail(provider_id)

    async def artwork_options(self, provider: str, provider_id: str) -> list[dict]:
        del provider
        if hasattr(self.client, "posters"):
            return await self.client.posters(provider_id)
        return []

    async def series_schedule(
        self, provider: str, provider_id: str, *, refresh: bool = False
    ) -> dict:
        del provider
        if not hasattr(self.client, "series_schedule"):
            raise NotImplementedError
        return await self.client.series_schedule(provider_id, refresh=refresh)


class TVMazeMetadataProvider:
    definition = MetadataProviderDefinition(
        slug="tvmaze",
        result_slugs=("tvmaze",),
        media_types=("tv",),
        capabilities=frozenset({"search", "detail", "artwork", "schedule"}),
        priority=10,
        attribution="TV data by TVmaze (CC BY-SA)",
    )

    def __init__(self, client: TVMazeClient):
        self.client = client

    async def search(self, query: str, media_type: str) -> list[SearchResult]:
        del media_type
        return await self.client.search(query)

    async def detail(self, provider: str, provider_id: str) -> CatalogData:
        del provider
        return await self.client.detail(provider_id)

    async def artwork_options(self, provider: str, provider_id: str) -> list[dict]:
        del provider
        return await self.client.posters(provider_id)

    async def series_schedule(
        self, provider: str, provider_id: str, *, refresh: bool = False
    ) -> dict:
        del provider
        return await self.client.series_schedule(provider_id, refresh=refresh)


class WikidataMetadataProvider:
    definition = MetadataProviderDefinition(
        slug="wikidata",
        result_slugs=("wikidata",),
        media_types=("movie",),
        capabilities=frozenset({"search", "detail"}),
        priority=90,
        attribution="Includes data from Wikidata (CC0)",
    )

    def __init__(self, client: WikidataClient):
        self.client = client

    async def search(self, query: str, media_type: str) -> list[SearchResult]:
        return await self.client.search(query, media_type)

    async def detail(self, provider: str, provider_id: str) -> CatalogData:
        del provider
        return await self.client.detail(provider_id)

    async def artwork_options(self, provider: str, provider_id: str) -> list[dict]:
        del provider, provider_id
        return []

    async def series_schedule(
        self, provider: str, provider_id: str, *, refresh: bool = False
    ) -> dict:
        del provider, provider_id, refresh
        raise NotImplementedError
