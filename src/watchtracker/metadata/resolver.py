from __future__ import annotations

from watchtracker.schemas import ProviderReference, SearchResult
from watchtracker.taxonomy import normalize_title


def _titles(result: SearchResult) -> set[str]:
    return {
        normalize_title(value)
        for value in (result.title, result.original_title or "", *result.aliases)
        if value
    }


def _compatible(left: SearchResult, right: SearchResult) -> bool:
    return left.media_type == right.media_type or {left.media_type, right.media_type} == {
        "anime",
        "tv",
    }


def _same_identity(left: SearchResult, right: SearchResult) -> bool:
    if left.provider == right.provider or not _compatible(left, right):
        return False
    shared = set(left.external_ids) & set(right.external_ids)
    if any(left.external_ids[key] == right.external_ids[key] for key in shared):
        return True
    if left.year is None or right.year is None or left.year != right.year:
        return False
    return bool(_titles(left) & _titles(right))


def cluster_search_results(
    results: list[SearchResult], *, provider_priority: dict[str, int]
) -> list[SearchResult]:
    """Collapse only cross-provider candidates with stable or exact/year evidence."""
    groups: list[list[SearchResult]] = []
    for result in results:
        group = next(
            (
                candidate
                for candidate in groups
                if all(result.provider != row.provider for row in candidate)
                and any(_same_identity(result, row) for row in candidate)
            ),
            None,
        )
        if group is None:
            groups.append([result])
        else:
            group.append(result)

    merged: list[SearchResult] = []
    for group in groups:
        ordered = sorted(
            group,
            key=lambda row: (
                provider_priority.get(row.provider, 999),
                -(row.popularity or 0),
                row.provider,
            ),
        )
        primary = ordered[0]
        aliases = list(
            dict.fromkeys(
                value
                for row in ordered
                for value in (row.title, row.original_title or "", *row.aliases)
                if value and value != primary.title
            )
        )
        external_ids: dict[str, str] = {}
        for row in ordered:
            for namespace, value in row.external_ids.items():
                external_ids.setdefault(namespace, value)
        merged.append(
            primary.model_copy(
                update={
                    "aliases": aliases,
                    "poster_url": primary.poster_url
                    or next((row.poster_url for row in ordered if row.poster_url), None),
                    "overview": primary.overview
                    or next((row.overview for row in ordered if row.overview), None),
                    "external_ids": external_ids,
                    "corroborating_results": [
                        ProviderReference(provider=row.provider, provider_id=row.provider_id)
                        for row in ordered[1:]
                    ],
                }
            )
        )
    return merged
