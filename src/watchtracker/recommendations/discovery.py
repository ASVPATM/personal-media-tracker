"""Bounded public-catalog discovery; private taste is never uploaded by default."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from watchtracker.metadata.cache import cache_key
from watchtracker.metadata.http import ProviderError
from watchtracker.metadata.providers import (
    TMDB_GENRES,
    _wikidata_external_ids,
    _wikimedia_image,
)
from watchtracker.models import (
    CatalogItem,
    RecommendationSignalSnapshot,
    UserRecommendationPreference,
    utcnow,
)
from watchtracker.recommendations.candidates import TVMazeCatalogSource
from watchtracker.schemas import CatalogData
from watchtracker.services.entries import EntryService, replace_catalog_from_trusted_provider

MAX_DISCOVERED_ITEMS = 160
MAX_SEEDS = 3
DISCOVERY_SCHEMA = 1


class CatalogDiscovery:
    slug = "mixed_public_catalog"

    def __init__(self, metadata: Any):
        self.metadata = metadata
        self.failed_sources: list[str] = []

    @property
    def available(self) -> bool:
        return any(
            getattr(getattr(self.metadata, name, None), "http", None)
            for name in ("tmdb", "jikan", "tvmaze", "wikidata")
        )

    async def _request(self, client: Any, provider: str, path: str, params: dict) -> dict:
        key = cache_key(
            provider,
            "recommendation-discovery",
            {"path": path, "params": params, "schema": DISCOVERY_SCHEMA},
        )
        cached = client.cache.get(key)
        if cached is not None:
            return cached
        throttle = getattr(client, "_throttle", None)
        if throttle:
            await throttle()
        response = await client.http.request_json(
            provider,
            "GET",
            f"{client.base_url}{path}",
            params=params,
            headers=getattr(client, "headers", {}),
            secrets=[getattr(client, "token", None)],
        )
        client.cache.set(key, response)
        return response

    async def _tmdb(
        self,
        page: int,
        preferences: UserRecommendationPreference,
        seeds: list[tuple[str, str]],
        genres: list[str],
    ) -> list[CatalogData]:
        client = self.metadata.tmdb
        queries = [
            (f"/discover/{kind}", kind, {})
            for kind in ("movie", "tv")
            if kind not in (preferences.excluded_media_types or [])
        ]
        if "anime" not in (preferences.excluded_media_types or []):
            queries.append(
                ("/discover/tv", "tv", {"with_genres": "16", "with_original_language": "ja"})
            )
        if preferences.use_taste_discovery:
            queries.extend(
                (
                    f"/{provider.removeprefix('tmdb_')}/{identity}/recommendations",
                    provider.removeprefix("tmdb_"),
                    {},
                )
                for provider, identity in seeds[:MAX_SEEDS]
            )
        output = []
        for path, kind, extra in queries:
            params = {
                "language": client.language,
                "page": page if path.startswith("/discover/") else 1,
            }
            if path.startswith("/discover/"):
                params.update(
                    {
                        "include_adult": "false",
                        "sort_by": "popularity.desc",
                        "vote_count.gte": 30,
                    }
                )
                if preferences.discovery_language:
                    params["with_original_language"] = preferences.discovery_language
                if preferences.use_taste_discovery and genres and not extra:
                    ids = [
                        str(key)
                        for key, name in TMDB_GENRES.items()
                        if name.casefold() in genres
                    ]
                    if ids:
                        params["with_genres"] = "|".join(ids[:3])
            params.update(extra)
            try:
                response = await self._request(client, "tmdb", path, params)
            except ProviderError:
                self.failed_sources.append("tmdb")
                continue
            for raw in (response.get("results") or [])[:20]:
                try:
                    if raw.get("adult") or not raw.get("id"):
                        continue
                    genre_ids = raw.get("genre_ids") or []
                    anime = 16 in genre_ids and raw.get("original_language") == "ja"
                    data = CatalogData(
                        canonical_title=raw.get("title") or raw.get("name"),
                        original_title=raw.get("original_title") or raw.get("original_name"),
                        release_year=_year(
                            raw.get("release_date") or raw.get("first_air_date")
                        ),
                        media_type="anime" if anime else kind,
                        provider_source=f"tmdb_{kind}",
                        provider_id=str(raw["id"]),
                        external_ids={f"tmdb_{kind}": str(raw["id"])},
                        provider_genres=[
                            TMDB_GENRES[key] for key in genre_ids if key in TMDB_GENRES
                        ],
                        overview=raw.get("overview") or None,
                        poster_url=f"{client.image_base}{raw['poster_path']}"
                        if raw.get("poster_path")
                        else None,
                        language=raw.get("original_language"),
                        country=next(iter(raw.get("origin_country") or []), None),
                        provider_format=kind,
                        public_score=raw.get("vote_average"),
                    )
                    output.append(data)
                except (TypeError, KeyError, ValueError, ValidationError):
                    continue
        return output

    async def _anime(
        self, page: int, preferences: UserRecommendationPreference, genres: list[str]
    ) -> list[CatalogData]:
        client = self.metadata.jikan
        path = "/top/anime"
        params = {"page": page, "limit": 25, "sfw": "true", "filter": "bypopularity"}
        if preferences.use_taste_discovery and genres:
            listing = await self._request(client, "jikan", "/genres/anime", {})
            identifiers = [
                str(row["mal_id"])
                for row in listing.get("data", [])
                if str(row.get("name", "")).casefold() in genres and row.get("mal_id")
            ]
            if identifiers:
                path = "/anime"
                params.pop("filter")
                params.update(
                    {"genres": ",".join(identifiers[:2]), "order_by": "members", "sort": "desc"}
                )
        response = await self._request(client, "jikan", path, params)
        output = []
        for raw in (response.get("data") or [])[:25]:
            try:
                if not raw.get("mal_id"):
                    continue
                images = (raw.get("images") or {}).get("jpg") or {}
                data = CatalogData(
                    canonical_title=raw.get("title_english") or raw.get("title"),
                    original_title=raw.get("title_japanese"),
                    release_year=raw.get("year") or _year((raw.get("aired") or {}).get("from")),
                    media_type="anime",
                    provider_source="mal",
                    provider_id=str(raw["mal_id"]),
                    external_ids={"mal": str(raw["mal_id"])},
                    provider_format=str(raw.get("type") or "anime").casefold(),
                    provider_genres=[
                        row["name"]
                        for key in ("genres", "themes", "demographics")
                        for row in raw.get(key, [])
                        if row.get("name")
                    ],
                    overview=raw.get("synopsis"),
                    public_score=raw.get("score"),
                    poster_url=images.get("large_image_url") or images.get("image_url"),
                    episode_count=raw.get("episodes"),
                )
                output.append(data)
            except (TypeError, KeyError, ValueError, ValidationError):
                continue
        return output

    async def _movies_without_key(self, page: int) -> list[CatalogData]:
        client = self.metadata.wikidata
        key = cache_key(
            "wikidata",
            "recommendation-films",
            {"page": page, "language": client.language, "schema": DISCOVERY_SCHEMA},
        )
        cached = client.cache.get(key)
        if cached is not None:
            return [CatalogData.model_validate(row) for row in cached]
        # Public catalog selection only: no title from the user's library is sent.
        query = (
            "SELECT ?item WHERE { ?item wdt:P31 wd:Q11424; wikibase:sitelinks ?n. "
            "FILTER(?n >= 70) } ORDER BY DESC(?n) ?item LIMIT 20 OFFSET " + str((page - 1) * 20)
        )
        payload = await client.http.request_json(
            "Wikidata",
            "GET",
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers=client.headers,
        )
        ids = [
            row["item"]["value"].rsplit("/", 1)[-1]
            for row in (payload.get("results") or {}).get("bindings", [])
            if re.fullmatch(
                r"Q[1-9]\d*", row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
            )
        ][:20]
        entities = await client._entities(ids)
        genre_ids = {
            claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            for entity in entities.values()
            for claim in entity.get("claims", {}).get("P136", [])
        }
        linked = await client._entities(sorted(value for value in genre_ids if value))
        output = []
        for identity, entity in entities.items():
            try:
                labels = entity.get("labels") or {}
                title = (labels.get(client.language) or labels.get("en") or {}).get("value")
                if not title:
                    continue
                claims = entity.get("claims") or {}
                genre_names = []
                for claim in claims.get("P136", []):
                    genre_id = (
                        claim.get("mainsnak", {})
                        .get("datavalue", {})
                        .get("value", {})
                        .get("id")
                    )
                    # Prefer stable English labels for scoring; display translates
                    # known taxonomy locally, independent of provider text locale.
                    genre_labels = linked.get(genre_id, {}).get("labels") or {}
                    genre = (genre_labels.get("en") or {}).get("value")
                    if genre:
                        genre_names.append(genre.removesuffix(" film"))
                dates = claims.get("P577") or []
                date_value = (
                    dates[0]
                    .get("mainsnak", {})
                    .get("datavalue", {})
                    .get("value", {})
                    .get("time", "")
                    if dates
                    else ""
                )
                external_ids = _wikidata_external_ids(entity)
                external_ids["wikidata"] = identity
                output.append(
                    CatalogData(
                        canonical_title=title,
                        media_type="movie",
                        provider_source="wikidata",
                        provider_id=identity,
                        release_year=_year(date_value.lstrip("+")),
                        provider_genres=genre_names,
                        overview=(
                            entity.get("descriptions", {}).get(client.language)
                            or entity.get("descriptions", {}).get("en")
                            or {}
                        ).get("value"),
                        poster_url=_wikimedia_image(entity),
                        external_ids=external_ids,
                    )
                )
            except (TypeError, KeyError, ValueError, ValidationError):
                continue
        client.cache.set(key, [row.model_dump(mode="json") for row in output])
        return output

    async def refresh_for_user(
        self,
        session: Session,
        *,
        user_id: str,
        preferences: UserRecommendationPreference,
        signals: RecommendationSignalSnapshot,
    ) -> int:
        self.failed_sources = []
        if not preferences.use_live_discovery:
            return 0
        page = 1 + ((datetime.now(UTC).date().toordinal() // 7) % 5)
        genres: list[str] = []
        seeds: list[tuple[str, str]] = []
        if preferences.use_taste_discovery:
            positive = sorted(
                (
                    signal
                    for signal in signals.signals
                    if signal["polarity"] == "positive"
                    and signal["source"] in {"personal_rating", "favorite"}
                ),
                key=lambda signal: -signal["value"] * signal["strength"] * signal["confidence"],
            )
            anchors = {anchor["catalog_id"]: anchor for anchor in signals.evidence_anchors}
            seen = set()
            for signal in positive:
                for identity in signal["source_catalog_ids"]:
                    if identity in seen:
                        continue
                    seen.add(identity)
                    item = session.get(CatalogItem, identity)
                    if item is None or not (item.metadata_provenance or {}).get(
                        "provider_identity_verified"
                    ):
                        continue
                    for genre in anchors.get(identity, {}).get("genres", []):
                        if genre not in genres:
                            genres.append(genre)
                    if (
                        item.provider_source in {"tmdb_movie", "tmdb_tv"}
                        and str(item.provider_id or "").isdigit()
                    ):
                        seeds.append((item.provider_source, item.provider_id))
                    if len(seen) >= MAX_SEEDS:
                        break
                if len(seen) >= MAX_SEEDS:
                    break
        tasks: list[tuple[str, Callable]] = []
        has_tmdb = bool(getattr(getattr(self.metadata, "tmdb", None), "http", None))
        if has_tmdb:
            tasks.append(("tmdb", lambda: self._tmdb(page, preferences, seeds, genres[:3])))
        elif "movie" not in (preferences.excluded_media_types or []) and getattr(
            getattr(self.metadata, "wikidata", None), "http", None
        ):
            tasks.append(("wikidata", lambda: self._movies_without_key(page)))
        if "anime" not in (preferences.excluded_media_types or []) and getattr(
            getattr(self.metadata, "jikan", None), "http", None
        ):
            tasks.append(("jikan", lambda: self._anime(page, preferences, genres[:3])))

        async def bounded(name, operation):
            try:
                async with asyncio.timeout(24):
                    return await operation()
            except (ProviderError, TimeoutError, ValueError, TypeError, KeyError):
                self.failed_sources.append(name)
                return []

        batches = await asyncio.gather(*(bounded(name, operation) for name, operation in tasks))
        entries = EntryService(session, today=datetime.now(UTC).date(), trusted_user_id=user_id)
        count = 0
        # Interleave providers so a busy source cannot consume the entire budget.
        for index in range(max((len(batch) for batch in batches), default=0)):
            for batch in batches:
                if index >= len(batch) or count >= MAX_DISCOVERED_ITEMS:
                    continue
                data = batch[index]
                if data.media_type in (preferences.excluded_media_types or []):
                    continue
                if _cache_public_catalog(entries, data):
                    count += 1
        tvmaze = TVMazeCatalogSource(self.metadata)
        if (
            count < MAX_DISCOVERED_ITEMS
            and tvmaze.available
            and "tv" not in (preferences.excluded_media_types or [])
        ):
            try:
                async with asyncio.timeout(10):
                    count += await tvmaze.refresh(
                        session, limit=min(40, MAX_DISCOVERED_ITEMS - count), page=page - 1
                    )
            except (ProviderError, TimeoutError):
                self.failed_sources.append("tvmaze")
        return count


def _year(value: Any) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() and 1878 <= int(text) <= 2200 else None


def _cache_public_catalog(entries: EntryService, data: CatalogData) -> bool:
    """Exact identities only; discovery must never adopt a manual title by name."""
    try:
        with entries.session.begin_nested():
            matches = entries._catalog_identity_matches(data)
            if len(matches) > 1:
                return False
            if not matches:
                item = entries._catalog_from_data(data, trusted_metadata=True)
            else:
                item = matches[0]
                if not (item.metadata_provenance or {}).get("provider_identity_verified"):
                    replace_catalog_from_trusted_provider(entries.session, item, data)
                else:
                    # Discovery is shallower than a detail refresh. Keep richer
                    # cached fields, user poster choices, and canonical identity.
                    for field in (
                        "poster_url",
                        "overview",
                        "release_year",
                        "language",
                        "country",
                        "public_score",
                    ):
                        if not getattr(item, field) and getattr(data, field):
                            setattr(item, field, getattr(data, field))
                    if not item.provider_genres and data.provider_genres:
                        from watchtracker.taxonomy import infer_taxonomy

                        taxonomy = infer_taxonomy(
                            data.provider_genres, data.keywords, media_type=item.media_type
                        )
                        item.provider_genres = data.provider_genres
                        item.normalized_genres = taxonomy.genres
                    item.metadata_fetched_at = utcnow()
            item.metadata_provenance = {
                **(item.metadata_provenance or {}),
                "discovery": "public-catalog-v2",
            }
            entries.session.flush()
        return True
    except (IntegrityError, ValueError):
        return False
