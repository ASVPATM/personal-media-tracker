from __future__ import annotations

import calendar
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import CatalogItem, EpisodeRecord, SeasonRecord, WatchEntry
from watchtracker.services.entries import serialize_entry

Period = Literal["all", "year", "90d", "30d", "custom"]
Aggregation = Literal["auto", "week", "month", "year"]


@dataclass(frozen=True)
class InsightFilters:
    period: Period = "year"
    date_from: date | None = None
    date_to: date | None = None
    media_type: str | None = None
    genre: str | None = None
    status: str | None = None
    watch_kind: Literal["all", "first", "rewatch"] = "all"
    aggregation: Aggregation = "auto"


def _entries(session: Session, principal: Principal | None = None) -> list[WatchEntry]:
    user_id = current_user_id(session, principal)
    return list(
        session.scalars(
            select(WatchEntry)
            .where(
                WatchEntry.user_id == user_id,
                WatchEntry.deleted_at.is_(None),
            )
            .options(
                selectinload(WatchEntry.catalog_item),
                selectinload(WatchEntry.viewing_events),
                selectinload(WatchEntry.catalog_item)
                .selectinload(CatalogItem.seasons)
                .selectinload(SeasonRecord.episodes)
                .selectinload(EpisodeRecord.viewings),
            )
        )
    )


def _range(filters: InsightFilters, today: date) -> tuple[date | None, date | None]:
    if filters.period == "all":
        return None, None
    if filters.period == "year":
        return date(today.year, 1, 1), today + timedelta(days=1)
    if filters.period in {"90d", "30d"}:
        days = 90 if filters.period == "90d" else 30
        return today - timedelta(days=days - 1), today + timedelta(days=1)
    if filters.date_from is None or filters.date_to is None:
        raise ValueError("Custom date ranges require both a start and an end date.")
    if filters.date_from > filters.date_to:
        raise ValueError("The start date cannot be after the end date.")
    return filters.date_from, filters.date_to + timedelta(days=1)


def _in_range(value: date | None, start: date | None, end: date | None) -> bool:
    if value is None:
        return start is None
    return (start is None or value >= start) and (end is None or value < end)


def _effective_genres(entry: WatchEntry) -> list[str]:
    return list(serialize_entry(entry, include_events=False).effective_genres)


def _matches(entry: WatchEntry, filters: InsightFilters) -> bool:
    if filters.media_type and entry.catalog_item.media_type != filters.media_type:
        return False
    if filters.status and entry.status != filters.status:
        return False
    if filters.genre:
        needle = filters.genre.casefold()
        if not any(value.casefold() == needle for value in _effective_genres(entry)):
            return False
    return True


def _title_events(entry: WatchEntry) -> list[date | None]:
    dated = [event.viewed_on for event in entry.viewing_events]
    missing = max(int(entry.view_count or 0) - len(dated), 0)
    return [*dated, *([None] * missing)]


def _episode_events(
    entry: WatchEntry, *, today: date
) -> list[tuple[date | None, int | None, str]]:
    output: list[tuple[date | None, int | None, str]] = []
    for season in entry.catalog_item.seasons:
        for episode in season.episodes:
            if episode.removed_at is not None:
                continue
            for viewing in episode.viewings:
                if viewing.entry_id == entry.id:
                    output.append((viewing.watched_on, episode.runtime_minutes, episode.id))
    if entry.episode_progress_explicit or entry.status != "watched":
        compact_count = int(entry.episode_progress_count or 0)
        if compact_count > len(output):
            output.extend(
                (None, entry.catalog_item.runtime_minutes, f"compact-count:{index}")
                for index in range(len(output), compact_count)
            )
        return output
    # A completed episodic title represents one completed pass unless the owner
    # has explicitly edited episode progress. The completion date is reused when
    # known; no date is invented for undated imports.
    assumed_on = entry.finished_date or entry.watched_date
    known = [
        episode
        for season in entry.catalog_item.seasons
        if season.removed_at is None
        for episode in season.episodes
        if episode.removed_at is None
        and episode.air_date is not None
        and episode.air_date <= today
    ]
    if known:
        return [
            (assumed_on, episode.runtime_minutes, f"assumed:{episode.id}") for episode in known
        ]
    assumed_total = (
        int(entry.catalog_item.released_episode_count)
        if entry.catalog_item.released_episode_count is not None
        else int(entry.catalog_item.episode_count or 0)
    )
    return [
        (assumed_on, entry.catalog_item.runtime_minutes, f"assumed-count:{index}")
        for index in range(assumed_total)
    ]


def _activity_for_entry(
    entry: WatchEntry,
    filters: InsightFilters,
    start: date | None,
    end: date | None,
    today: date,
) -> tuple[
    list[date | None],
    list[tuple[date | None, int | None, str]],
    int,
    int,
]:
    titles = sorted(
        _title_events(entry), key=lambda value: (value is not None, value or date.min)
    )
    tagged_titles = [(value, index > 0) for index, value in enumerate(titles)]
    episodes_by_id: defaultdict[str, list[tuple[date | None, int | None, str]]] = defaultdict(
        list
    )
    for row in _episode_events(entry, today=today):
        episodes_by_id[row[2]].append(row)
    tagged_episodes = [
        (row, index > 0)
        for episode_rows in episodes_by_id.values()
        for index, row in enumerate(
            sorted(episode_rows, key=lambda item: (item[0] is not None, item[0] or date.min))
        )
    ]
    if filters.watch_kind == "first":
        tagged_titles = [item for item in tagged_titles if not item[1]]
        tagged_episodes = [item for item in tagged_episodes if not item[1]]
    elif filters.watch_kind == "rewatch":
        tagged_titles = [item for item in tagged_titles if item[1]]
        tagged_episodes = [item for item in tagged_episodes if item[1]]
    selected_titles = [item for item in tagged_titles if _in_range(item[0], start, end)]
    selected_episodes = [item for item in tagged_episodes if _in_range(item[0][0], start, end)]
    return (
        [item[0] for item in selected_titles],
        [item[0] for item in selected_episodes],
        sum(item[1] for item in selected_titles),
        sum(item[1] for item in selected_episodes),
    )


def _scope(
    entries: list[WatchEntry], filters: InsightFilters, today: date
) -> tuple[list[dict[str, Any]], date | None, date | None]:
    start, end = _range(filters, today)
    rows = []
    for entry in entries:
        if not _matches(entry, filters):
            continue
        title_events, episode_events, title_rewatches, episode_rewatches = _activity_for_entry(
            entry, filters, start, end, today
        )
        # All-time is also a library snapshot; period views include only titles
        # with activity in that window so every card shares the selected scope.
        if (
            (start is not None or filters.watch_kind != "all")
            and not title_events
            and not episode_events
        ):
            continue
        rows.append(
            {
                "entry": entry,
                "title_events": title_events,
                "episode_events": episode_events,
                "title_rewatches": title_rewatches,
                "episode_rewatches": episode_rewatches,
            }
        )
    return rows, start, end


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    title_events = sum(len(row["title_events"]) for row in rows)
    episode_events = sum(len(row["episode_events"]) for row in rows)
    watched_entries = [
        row["entry"] for row in rows if row["title_events"] or row["episode_events"]
    ]
    ratings = [entry.personal_rating for entry in watched_entries if entry.personal_rating]
    minutes = 0
    estimated_events = 0
    for row in rows:
        entry = row["entry"]
        runtime = entry.catalog_item.runtime_minutes
        if runtime and entry.catalog_item.media_type == "movie":
            minutes += len(row["title_events"]) * runtime
            estimated_events += len(row["title_events"])
        for _watched_on, episode_runtime, _episode_id in row["episode_events"]:
            resolved = episode_runtime or runtime
            if resolved:
                minutes += resolved
                estimated_events += 1
    rewatches = sum(row["title_rewatches"] + row["episode_rewatches"] for row in rows)
    return {
        "titles_watched": len(watched_entries),
        "title_viewings": title_events,
        "episodes_watched": episode_events,
        "estimated_minutes": minutes,
        "estimated_hours": round(minutes / 60, 1),
        "estimated_event_count": estimated_events,
        "average_rating": round(statistics.fmean(ratings), 2) if ratings else None,
        "rewatches": rewatches,
    }


def _previous_filters(
    filters: InsightFilters, start: date | None, end: date | None
) -> InsightFilters | None:
    if start is None or end is None:
        return None
    span = end - start
    return InsightFilters(
        period="custom",
        date_from=start - span,
        date_to=start - timedelta(days=1),
        media_type=filters.media_type,
        genre=filters.genre,
        status=filters.status,
        watch_kind=filters.watch_kind,
        aggregation=filters.aggregation,
    )


def _bucket(value: date, aggregation: str) -> tuple[str, date, date]:
    if aggregation == "year":
        start = date(value.year, 1, 1)
        return str(value.year), start, date(value.year + 1, 1, 1)
    if aggregation == "month":
        start = date(value.year, value.month, 1)
        last = calendar.monthrange(value.year, value.month)[1]
        return value.strftime("%Y-%m"), start, start + timedelta(days=last)
    start = value - timedelta(days=value.weekday())
    return start.isoformat(), start, start + timedelta(days=7)


def _aggregation(
    requested: Aggregation, rows: list[dict[str, Any]], start: date | None, end: date | None
) -> str:
    if requested != "auto":
        return requested
    dated = [
        event
        for row in rows
        for event in [
            *[value for value in row["title_events"] if value],
            *[item[0] for item in row["episode_events"] if item[0]],
        ]
    ]
    if start and end:
        days = (end - start).days
    elif dated:
        days = (max(dated) - min(dated)).days + 1
    else:
        days = 0
    if days <= 120:
        return "week"
    if days <= 730:
        return "month"
    return "year"


def _timeline(
    rows: list[dict[str, Any]], start: date | None, end: date | None, requested: Aggregation
) -> dict[str, Any]:
    aggregation = _aggregation(requested, rows, start, end)
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = row["entry"]
        runtime = entry.catalog_item.runtime_minutes
        for watched_on in row["title_events"]:
            if not watched_on:
                continue
            key, bucket_start, bucket_end = _bucket(watched_on, aggregation)
            target = buckets.setdefault(
                key,
                {
                    "key": key,
                    "date_from": bucket_start,
                    "date_to": bucket_end - timedelta(days=1),
                    "titles": set(),
                    "episodes": 0,
                    "estimated_minutes": 0,
                },
            )
            target["titles"].add(entry.id)
            if runtime and entry.catalog_item.media_type == "movie":
                target["estimated_minutes"] += runtime
        for watched_on, episode_runtime, _episode_id in row["episode_events"]:
            if not watched_on:
                continue
            key, bucket_start, bucket_end = _bucket(watched_on, aggregation)
            target = buckets.setdefault(
                key,
                {
                    "key": key,
                    "date_from": bucket_start,
                    "date_to": bucket_end - timedelta(days=1),
                    "titles": set(),
                    "episodes": 0,
                    "estimated_minutes": 0,
                },
            )
            target["titles"].add(entry.id)
            target["episodes"] += 1
            resolved = episode_runtime or runtime
            if resolved:
                target["estimated_minutes"] += resolved
    values = []
    for key in sorted(buckets):
        item = buckets[key]
        values.append(
            {
                **item,
                "titles": len(item["titles"]),
                "estimated_hours": round(item["estimated_minutes"] / 60, 1),
            }
        )
    return {"aggregation": aggregation, "items": values}


def _release_era_distribution(
    entries: list[WatchEntry], filters: InsightFilters, *, today: date
) -> dict[str, Any]:
    """Build an honest date-free visual from title metadata, never inferred watches."""
    decades: Counter[int] = Counter()
    unknown = 0
    for entry in entries:
        if not _matches(entry, filters):
            continue
        title_events, episode_events, _title_rewatches, _episode_rewatches = (
            _activity_for_entry(entry, filters, None, None, today)
        )
        if not title_events and not episode_events:
            continue
        year = entry.catalog_item.release_year
        if year is None:
            unknown += 1
        else:
            decades[(int(year) // 10) * 10] += 1
    items = [
        {
            "key": f"{decade}s",
            "release_year_from": decade,
            "release_year_to": decade + 9,
            "release_year_unknown": False,
            "titles": count,
        }
        for decade, count in sorted(decades.items())
    ]
    if unknown:
        items.append(
            {
                "key": "Year unknown",
                "release_year_from": None,
                "release_year_to": None,
                "release_year_unknown": True,
                "titles": unknown,
            }
        )
    return {
        "kind": "release_era",
        "items": items,
        "known_year_titles": sum(decades.values()),
        "unknown_year_titles": unknown,
    }


def _rating_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ratings = [
        float(row["entry"].personal_rating)
        for row in rows
        if row["entry"].personal_rating is not None
    ]
    counts = Counter(round(value * 2) / 2 for value in ratings)
    return {
        "items": [
            {"rating": value / 2, "count": counts.get(value / 2, 0)} for value in range(2, 21)
        ],
        "rated_count": len(ratings),
        "unrated_count": len(rows) - len(ratings),
        "average": round(statistics.fmean(ratings), 2) if ratings else None,
        "median": round(statistics.median(ratings), 2) if ratings else None,
    }


def _genre_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ratings: defaultdict[str, list[float]] = defaultdict(list)
    support: Counter[str] = Counter()
    for row in rows:
        entry = row["entry"]
        for genre in _effective_genres(entry):
            support[genre] += 1
            if entry.personal_rating is not None:
                ratings[genre].append(float(entry.personal_rating))
    output = []
    for genre, count in support.items():
        values = ratings[genre]
        raw = statistics.fmean(values) if values else None
        # A small Bayesian pull prevents a three-title perfect score from
        # outranking a substantial body of evidence without hiding the raw mean.
        adjusted = ((raw * len(values) + 7.0 * 3) / (len(values) + 3)) if raw else None
        output.append(
            {
                "genre": genre,
                "title_count": count,
                "rated_count": len(values),
                "average_rating": round(raw, 2) if raw is not None else None,
                "confidence_adjusted_rating": round(adjusted, 3)
                if adjusted is not None
                else None,
                "eligible_favourite": len(values) >= 3,
            }
        )
    return sorted(
        output,
        key=lambda item: (
            -(item["confidence_adjusted_rating"] or -1),
            -item["title_count"],
            item["genre"].casefold(),
        ),
    )


def _breakdown(rows: list[dict[str, Any]], attribute: str) -> list[dict[str, Any]]:
    counts = Counter(
        getattr(row["entry"], attribute)
        if attribute == "status"
        else getattr(row["entry"].catalog_item, attribute)
        for row in rows
    )
    total = sum(counts.values())
    return [
        {"value": value, "count": count, "share": round(count / total, 4) if total else 0}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _callouts(
    rows: list[dict[str, Any]], timeline: dict[str, Any], genres: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    def counted(value: int, singular: str, plural: str | None = None) -> str:
        return f"{value} {singular if value == 1 else (plural or singular + 's')}"

    output = []
    if timeline["items"]:
        peak = max(
            timeline["items"], key=lambda item: (item["titles"] + item["episodes"], item["key"])
        )
        output.append(
            {
                "kind": "peak_activity",
                "title": "Your busiest period",
                "value": peak["key"],
                "detail": (
                    f"{counted(peak['titles'], 'title')} and "
                    f"{counted(peak['episodes'], 'episode')} recorded."
                ),
                "title_count": peak["titles"],
                "episode_count": peak["episodes"],
                "drilldown": {"date_from": peak["date_from"], "date_to": peak["date_to"]},
            }
        )
    favourite = next((item for item in genres if item["eligible_favourite"]), None)
    if favourite:
        output.append(
            {
                "kind": "favourite_genre",
                "title": "A well-supported favourite",
                "value": favourite["genre"],
                "detail": (
                    f"{favourite['average_rating']}/10 across "
                    f"{counted(favourite['rated_count'], 'rated title')}."
                ),
                "average_rating": favourite["average_rating"],
                "rated_count": favourite["rated_count"],
                "drilldown": {"genre": favourite["genre"], "activity_only": True},
            }
        )
    unrated = [row for row in rows if row["entry"].personal_rating is None]
    if unrated:
        output.append(
            {
                "kind": "unrated",
                "title": "Ratings can sharpen your profile",
                "value": str(len(unrated)),
                "detail": (
                    f"{counted(len(unrated), 'title')} in this scope "
                    f"{'has' if len(unrated) == 1 else 'have'} no personal rating."
                ),
                "title_count": len(unrated),
                "drilldown": {"rating_state": "unrated", "activity_only": True},
            }
        )
    rewatched = [row for row in rows if row["title_rewatches"] > 0]
    if rewatched:
        output.append(
            {
                "kind": "rewatch",
                "title": "Titles you returned to",
                "value": str(len(rewatched)),
                "detail": (
                    f"{counted(len(rewatched), 'title')} "
                    f"{'has' if len(rewatched) == 1 else 'have'} repeat viewing "
                    f"{'record' if len(rewatched) == 1 else 'records'} in this scope."
                ),
                "title_count": len(rewatched),
                "drilldown": {"watch_kind": "rewatch"},
            }
        )
    return output[:4]


def calculate_insights(
    session: Session,
    *,
    today: date,
    filters: InsightFilters,
    principal: Principal | None = None,
) -> dict[str, Any]:
    entries = _entries(session, principal)
    rows, start, end = _scope(entries, filters, today)
    activity_rows = [row for row in rows if row["title_events"] or row["episode_events"]]
    summary = _summary(rows)
    previous_filter = _previous_filters(filters, start, end)
    previous = None
    if previous_filter:
        previous_rows, _previous_start, _previous_end = _scope(entries, previous_filter, today)
        previous = _summary(previous_rows)
    timeline = _timeline(rows, start, end, filters.aggregation)
    genres = _genre_rows(activity_rows)
    dated = sum(
        1
        for row in rows
        for value in [
            *row["title_events"],
            *[item[0] for item in row["episode_events"]],
        ]
        if value is not None
    )
    undated = sum(
        1
        for row in rows
        for value in [
            *row["title_events"],
            *[item[0] for item in row["episode_events"]],
        ]
        if value is None
    )
    return {
        "filters": {
            **filters.__dict__,
            "effective_date_from": start,
            "effective_date_to": end - timedelta(days=1) if end else None,
        },
        "summary": summary,
        "previous_summary": previous,
        "activity": timeline,
        "date_free_activity": _release_era_distribution(entries, filters, today=today),
        "ratings": _rating_distribution(activity_rows),
        "genres": genres,
        "media_types": _breakdown(rows, "media_type"),
        "statuses": _breakdown(rows, "status"),
        "callouts": _callouts(activity_rows, timeline, genres),
        "coverage": {
            "dated_events": dated,
            "undated_events": undated,
            "timeline_coverage": round(dated / (dated + undated), 3)
            if dated + undated
            else None,
            "rated_titles": sum(
                row["entry"].personal_rating is not None for row in activity_rows
            ),
            "titles_in_scope": len(rows),
        },
        "definitions": {
            "titles_watched": "Distinct library titles with a title or episode viewing in the selected scope.",
            "episodes_watched": "Stored episode-viewing records, or all released known episodes for a completed show until episode progress is edited explicitly; future and TBA episodes are excluded.",
            "estimated_time": "Movie runtime multiplied by movie viewings plus stored episode runtimes for episodic media. Missing runtimes are excluded.",
            "repeat_viewings": "Title rewatches plus repeat viewings of the same stored episode in the selected scope.",
            "periods": "Date ranges are inclusive in the interface and evaluated with a half-open end boundary.",
            "undated": "Undated imported counts appear in all-time totals but never in the activity timeline or dated comparisons.",
        },
    }


def insight_titles(
    session: Session,
    *,
    today: date,
    filters: InsightFilters,
    rating_bucket: float | None = None,
    rating_state: Literal["rated", "unrated"] | None = None,
    activity_only: bool = False,
    release_year_from: int | None = None,
    release_year_to: int | None = None,
    release_year_unknown: bool = False,
    principal: Principal | None = None,
) -> dict[str, Any]:
    rows, _start, _end = _scope(_entries(session, principal), filters, today)
    items = []
    for row in rows:
        entry = row["entry"]
        if activity_only and not row["title_events"] and not row["episode_events"]:
            continue
        if rating_bucket is not None and (
            entry.personal_rating is None
            or math.floor(float(entry.personal_rating) * 2 + 0.5) / 2 != rating_bucket
        ):
            continue
        if rating_state == "rated" and entry.personal_rating is None:
            continue
        if rating_state == "unrated" and entry.personal_rating is not None:
            continue
        release_year = entry.catalog_item.release_year
        if release_year_unknown and release_year is not None:
            continue
        if (
            not release_year_unknown
            and release_year_from is not None
            and (release_year is None or release_year < release_year_from)
        ):
            continue
        if (
            not release_year_unknown
            and release_year_to is not None
            and (release_year is None or release_year > release_year_to)
        ):
            continue
        item = serialize_entry(entry, include_events=False).model_dump(mode="json")
        item["scope_title_viewings"] = len(row["title_events"])
        item["scope_episode_viewings"] = len(row["episode_events"])
        item["scope_dates"] = sorted(
            {
                value.isoformat()
                for value in [
                    *row["title_events"],
                    *[event[0] for event in row["episode_events"]],
                ]
                if value is not None
            },
            reverse=True,
        )
        items.append(item)
    items.sort(
        key=lambda item: (
            -(item["personal_rating"] or 0),
            item["catalog_item"]["canonical_title"].casefold(),
        )
    )
    return {"items": items, "total": len(items)}
