"""Optional, bounded multilingual identity bridge; never supplies guessed artwork."""

import re
from uuid import UUID

from watchtracker.music.matching import album_key, artist_strength, one_typo
from watchtracker.music.provider import PublicCatalogClient


def values(entity, property_id):
    return [
        claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        for claim in entity.get("claims", {}).get(property_id, [])
        if claim.get("rank") != "deprecated"
        and claim.get("mainsnak", {}).get("snaktype") == "value"
    ]


def names(entity):
    return [
        row["value"]
        for row in [
            *entity.get("labels", {}).values(),
            *(alias for rows in entity.get("aliases", {}).values() for alias in rows),
        ]
        if isinstance(row, dict) and isinstance(row.get("value"), str)
    ]


def mbids(entity, property_id):
    result = []
    for value in values(entity, property_id):
        try:
            result.append(str(UUID(value)))
        except (ValueError, TypeError, AttributeError):
            continue
    return list(dict.fromkeys(result))


class WikidataAlbumBridge(PublicCatalogClient):
    api_root = "https://www.wikidata.org/w/api.php"
    provider_name = "Wikidata"
    default_params = {"format": "json", "maxlag": 5}

    async def entities(self, ids):
        if not ids:
            return {}
        data = await self._search_get(
            "",
            action="wbgetentities",
            ids="|".join(ids),
            props="labels|aliases|claims",
            languages="en|fr|zh|zh-hans|ru|ja|pt|es|de",
        )
        return data.get("entities") or {}

    async def find(self, source):
        # At most three Wikidata requests: five works, then their (at most ten)
        # performers in one batch. Never search by ratings/notes/listening data.
        title = source["title"]
        language = (
            "zh"
            if re.search(r"[\u3400-\u9fff]", title)
            else "ru"
            if re.search(r"[\u0400-\u04ff]", title)
            else "en"
        )
        search = await self._search_get(
            "",
            action="wbsearchentities",
            search=title,
            language=language,
            limit=5,
        )
        ids = [
            row["id"]
            for row in search.get("search", [])[:5]
            if re.fullmatch(r"Q\d+", str(row.get("id", "")))
        ]
        works = await self.entities(ids)
        performer_ids = list(
            dict.fromkeys(
                value["id"]
                for entity in works.values()
                for value in values(entity, "P175")
                if isinstance(value, dict) and re.fullmatch(r"Q\d+", str(value.get("id", "")))
            )
        )
        if not performer_ids or len(performer_ids) > 10:
            return None
        performers = await self.entities(performer_ids)
        matches = {}
        for entity in works.values():
            group_ids = mbids(entity, "P436")
            if len(group_ids) != 1:
                continue
            titles = names(entity)
            exact = album_key(title) in {album_key(value) for value in titles}
            if not exact and not any(
                one_typo(album_key(title), album_key(value), minimum=8) for value in titles
            ):
                continue
            artists = {}
            for value in values(entity, "P175"):
                artist = performers.get(value.get("id"), {}) if isinstance(value, dict) else {}
                aliases = names(artist)
                strength = artist_strength(source["artist"], aliases)
                if not strength or (not exact and strength != 3):
                    continue
                for identifier in mbids(artist, "P434"):
                    artists[identifier] = aliases
            if artists:
                matches[group_ids[0]] = {
                    "id": group_ids[0],
                    "titles": titles,
                    "artists": artists,
                }
        # Missing or conflicting crosswalks never become a popularity guess.
        return next(iter(matches.values())) if len(matches) == 1 else None
