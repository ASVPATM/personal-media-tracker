from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from watchtracker.models import CatalogItem

SUPPORTED_MEDIA_TYPES = frozenset({"movie", "tv", "anime"})


def normalized_strings(values: Iterable[Any], *, limit: int = 50) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(str(raw).split()).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value[:100])
        if len(result) >= limit:
            break
    return result


def eligible_catalog_item(
    item: CatalogItem,
    *,
    excluded_media_types: set[str],
    excluded_genres: set[str],
) -> bool:
    if item.media_type not in SUPPORTED_MEDIA_TYPES or item.media_type in excluded_media_types:
        return False
    item_genres = {
        str(value).casefold()
        for value in [*(item.normalized_genres or []), *(item.provider_genres or [])]
    }
    return not bool(item_genres.intersection(excluded_genres))


def confidence_label(value: float) -> str:
    if value >= 0.82:
        return "strong"
    if value >= 0.62:
        return "supported"
    if value >= 0.38:
        return "developing"
    return "limited"
