"""Bounded, display-only cross-provider translation lookup; never relinks a library."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from watchtracker.metadata.cache import cache_key
from watchtracker.taxonomy import normalize_title


async def tmdb_translation_identity(
    client: Any, catalog: Any, identities: dict[str, str]
) -> tuple[str, str] | None:
    """Prefer stable cross-IDs, otherwise require unique exact title AND year/type.

    Anime movies must not resolve to TV adaptations. Manual/unverified titles,
    missing years, ambiguous matches and sequels never use popularity as identity.
    No notes, ratings or history are sent, and the result is not written to the DB.
    """
    endpoint = (
        "movie"
        if catalog.media_type == "movie"
        or str(catalog.provider_format or "").casefold() in {"movie", "film"}
        else "tv"
    )
    external_sources = {
        "imdb": ("imdb_id", r"tt\d+"),
        "thetvdb": ("tvdb_id", r"\d+"),
        "wikidata": ("wikidata_id", r"Q\d+"),
    }
    matches: set[str] = set()
    for namespace, (source, pattern) in external_sources.items():
        value = str(identities.get(namespace, ""))
        if not re.fullmatch(pattern, value) or (endpoint == "movie" and namespace == "thetvdb"):
            continue
        key = cache_key("tmdb", "translation-cross-id", {"source": source, "id": value})
        payload = client.cache.get(key)
        if payload is None:
            payload = await client.http.request_json(
                "TMDb",
                "GET",
                f"{client.base_url}/find/{quote(value, safe='')}",
                params={"external_source": source, "language": "en-US"},
                headers=client.headers,
                secrets=[client.token],
            )
            client.cache.set(key, payload)
        rows = payload.get(f"{endpoint}_results") or []
        matches.update(
            str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")
        )
    if matches:
        return (f"tmdb_{endpoint}", next(iter(matches))) if len(matches) == 1 else None

    if (
        catalog.provider_source not in {"mal", "anilist", "kitsu", "tvmaze", "wikidata"}
        or not catalog.provider_id
        or not catalog.release_year
    ):
        return None
    titles = list(
        dict.fromkeys(
            value for value in (catalog.original_title, catalog.canonical_title) if value
        )
    )[:2]
    wanted = {normalize_title(value) for value in titles}
    key = cache_key(
        "tmdb",
        "translation-title-identity-v1",
        {
            "titles": sorted(wanted),
            "year": catalog.release_year,
            "type": endpoint,
            "anime": catalog.media_type == "anime",
        },
    )
    cached = client.cache.get(key)
    if cached is not None:
        return tuple(cached) if cached else None
    for title in titles:
        payload = await client.http.request_json(
            "TMDb",
            "GET",
            f"{client.base_url}/search/{endpoint}",
            params={"query": title, "language": "en-US", "include_adult": "false"},
            headers=client.headers,
            secrets=[client.token],
        )
        # Never accept a supposedly unique candidate from a truncated result set.
        if payload.get("total_pages", 1) > 1:
            return None
        for row in payload.get("results") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            names = {
                normalize_title(str(row.get(name) or ""))
                for name in ("title", "name", "original_title", "original_name")
            }
            year = str(
                row.get("release_date" if endpoint == "movie" else "first_air_date") or ""
            )[:4]
            if not (wanted & names) or year != str(catalog.release_year):
                continue
            if catalog.media_type == "anime" and 16 not in (row.get("genre_ids") or []):
                continue
            matches.add(str(row["id"]))
    result = [f"tmdb_{endpoint}", next(iter(matches))] if len(matches) == 1 else []
    client.cache.set(key, result)
    return tuple(result) if result else None
