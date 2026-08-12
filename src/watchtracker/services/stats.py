from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from watchtracker.models import WatchEntry
from watchtracker.services.entries import load_active_entries, serialize_entry


def _rounded(value: float | None, places: int = 3) -> float | None:
    return round(value, places) if value is not None else None


def _confidence(support: int) -> str:
    if support < 3:
        return "insufficient_data"
    if support < 5:
        return "low"
    if support < 10:
        return "medium"
    return "high"


def _title_signal(entry: WatchEntry, reason: str | list[str] | None = None) -> dict[str, Any]:
    return {
        "entry_id": entry.id,
        "title": entry.catalog_item.canonical_title,
        "media_type": entry.catalog_item.media_type,
        "personal_rating": entry.personal_rating,
        "view_count": entry.view_count,
        "reason": reason,
    }


def _effective(entry: WatchEntry, field: str) -> list[str]:
    if field == "keyword":
        return sorted(
            {value.strip() for value in entry.catalog_item.keywords or [] if value.strip()},
            key=str.casefold,
        )
    output = serialize_entry(entry, include_events=False)
    return output.effective_genres if field == "genre" else output.effective_subgenres


def _affinity(entries: list[WatchEntry], field: str) -> list[dict[str, Any]]:
    prevalence: defaultdict[str, float] = defaultdict(float)
    weighted: defaultdict[str, float] = defaultdict(float)
    rating_values: defaultdict[str, list[float]] = defaultdict(list)
    support: Counter[str] = Counter()
    total_prevalence = 0.0
    total_weighted = 0.0
    for entry in entries:
        values = _effective(entry, field)
        if not values:
            continue
        fraction = 1 / len(values)
        for value in values:
            prevalence[value] += fraction
            support[value] += 1
            total_prevalence += fraction
            if entry.personal_rating is not None:
                amount = fraction * (entry.personal_rating / 10)
                weighted[value] += amount
                total_weighted += amount
                rating_values[value].append(entry.personal_rating)
    rows = []
    for value in sorted(
        prevalence, key=lambda item: (-weighted[item], -prevalence[item], item.casefold())
    ):
        ratings = rating_values[value]
        rows.append(
            {
                "name": value,
                "prevalence_share": _rounded(
                    prevalence[value] / total_prevalence if total_prevalence else None, 8
                ),
                "fractional_title_count": _rounded(prevalence[value]),
                "weighted_affinity": _rounded(
                    weighted[value] / total_weighted if total_weighted else None, 8
                ),
                "average_personal_rating": _rounded(
                    statistics.fmean(ratings) if ratings else None, 2
                ),
                "support_count": support[value],
                "rated_support_count": len(ratings),
                "confidence": _confidence(len(ratings)),
                "calculation_method": f"fractional {field} allocation; weighted by personal_rating / 10",
            }
        )
    return rows


def _attribute_preferences(entries: list[WatchEntry], attribute: str) -> list[dict[str, Any]]:
    groups: defaultdict[str, list[WatchEntry]] = defaultdict(list)
    for entry in entries:
        value = getattr(entry.catalog_item, attribute)
        if value:
            groups[str(value).strip()].append(entry)
    known = sum(len(group) for group in groups.values())
    rows = []
    for value, supported in groups.items():
        ratings = [
            entry.personal_rating for entry in supported if entry.personal_rating is not None
        ]
        rows.append(
            {
                "name": value,
                "completed_count": len(supported),
                "share_of_known": _rounded(len(supported) / known if known else None),
                "average_personal_rating": _rounded(
                    statistics.fmean(ratings) if ratings else None, 2
                ),
                "rated_support_count": len(ratings),
                "confidence": _confidence(len(ratings)),
                "calculation_method": f"stored provider {attribute}; unknown values excluded",
            }
        )
    return sorted(rows, key=lambda row: (-row["completed_count"], row["name"].casefold()))


def _band_preferences(
    entries: list[WatchEntry],
    *,
    attribute: str,
    scope: str,
    band_for,
) -> list[dict[str, Any]]:
    known = [
        entry
        for entry in entries
        if (value := getattr(entry.catalog_item, attribute)) is not None and value > 0
    ]
    groups: defaultdict[str, list[WatchEntry]] = defaultdict(list)
    for entry in known:
        groups[band_for(getattr(entry.catalog_item, attribute))].append(entry)
    rows = []
    for band, supported in groups.items():
        ratings = [
            entry.personal_rating for entry in supported if entry.personal_rating is not None
        ]
        rows.append(
            {
                "name": band,
                "media_scope": scope,
                "completed_count": len(supported),
                "share_of_known": _rounded(len(supported) / len(known) if known else None),
                "average_personal_rating": _rounded(
                    statistics.fmean(ratings) if ratings else None, 2
                ),
                "rated_support_count": len(ratings),
                "confidence": _confidence(len(ratings)),
                "calculation_method": f"stored provider {attribute}; unknown values excluded",
            }
        )
    return sorted(rows, key=lambda row: (-row["completed_count"], row["name"]))


def _rewatch_genre_signals(entries: list[WatchEntry]) -> list[dict[str, Any]]:
    groups: defaultdict[str, list[WatchEntry]] = defaultdict(list)
    for entry in entries:
        for genre in _effective(entry, "genre"):
            groups[genre].append(entry)
    rows = []
    for genre, supported in groups.items():
        rewatched = [entry for entry in supported if entry.rewatch_count > 0]
        ratings = [
            entry.personal_rating for entry in supported if entry.personal_rating is not None
        ]
        rows.append(
            {
                "name": genre,
                "support_count": len(supported),
                "rewatched_title_count": len(rewatched),
                "rewatch_share": _rounded(
                    len(rewatched) / len(supported) if supported else None
                ),
                "total_rewatches": sum(entry.rewatch_count for entry in rewatched),
                "average_personal_rating": _rounded(
                    statistics.fmean(ratings) if ratings else None, 2
                ),
                "confidence": _confidence(len(supported)),
                "calculation_method": "stored viewing counts grouped by effective genre",
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -row["total_rewatches"],
            -(row["rewatch_share"] or 0),
            -row["support_count"],
            row["name"].casefold(),
        ),
    )


def _metadata_coverage(entries: list[WatchEntry]) -> list[dict[str, Any]]:
    series = [entry for entry in entries if entry.catalog_item.media_type in {"tv", "anime"}]

    def row(name: str, eligible: list[WatchEntry], predicate) -> dict[str, Any]:
        known = sum(1 for entry in eligible if predicate(entry.catalog_item))
        return {
            "name": name,
            "known_count": known,
            "eligible_count": len(eligible),
            "coverage": _rounded(known / len(eligible) if eligible else None),
        }

    return [
        row(
            "Verified provider identity",
            entries,
            lambda item: any(
                (item.tmdb_movie_id, item.tmdb_tv_id, item.anilist_id, item.mal_id)
            ),
        ),
        row("Poster", entries, lambda item: bool(item.poster_url)),
        row("Release year", entries, lambda item: bool(item.release_year)),
        row("Provider genres", entries, lambda item: bool(item.provider_genres)),
        row("Provider tags", entries, lambda item: bool(item.keywords)),
        row("Format", entries, lambda item: bool(item.provider_format)),
        row("Country", entries, lambda item: bool(item.country)),
        row("Language", entries, lambda item: bool(item.language)),
        row("Runtime", entries, lambda item: bool(item.runtime_minutes)),
        row("Episode count", series, lambda item: bool(item.episode_count)),
    ]


def _taste_dimensions(entries: list[WatchEntry]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        evidence = entry.catalog_item.taste_evidence or {}
        for dimension, matches in evidence.items():
            for match in matches:
                key = (dimension, match["value"])
                group = groups.setdefault(key, {"entries": {}, "evidence": set()})
                group["entries"][entry.id] = entry
                group["evidence"].add(match["evidence"])
    rows = []
    for (dimension, value), group in groups.items():
        supported = list(group["entries"].values())
        rated = [
            entry.personal_rating for entry in supported if entry.personal_rating is not None
        ]
        representatives = sorted(
            supported,
            key=lambda entry: (
                -(entry.personal_rating if entry.personal_rating is not None else -1),
                entry.catalog_item.canonical_title.casefold(),
                entry.id,
            ),
        )[:3]
        support_count = len(supported)
        rows.append(
            {
                "dimension": dimension,
                "value": value,
                "score": _rounded(statistics.fmean(rated) / 10 if rated else None),
                "support_count": support_count,
                "rated_support_count": len(rated),
                "confidence": _confidence(support_count),
                "state": "supported" if support_count >= 3 else "insufficient_data",
                "representative_titles": [
                    entry.catalog_item.canonical_title for entry in representatives
                ],
                "evidence": sorted(group["evidence"]),
                "calculation_method": "deterministic provider genre/tag evidence; score is mean personal rating / 10",
            }
        )
    return sorted(rows, key=lambda row: (-row["support_count"], row["dimension"], row["value"]))


def calculate_stats(session: Session, *, today: date) -> dict[str, Any]:
    entries = load_active_entries(session)
    completed = [entry for entry in entries if entry.view_count >= 1]
    rated_completed = [entry for entry in completed if entry.personal_rating is not None]
    dropped = [
        entry for entry in entries if entry.status == "dropped" and entry.view_count == 0
    ]
    ratings = [
        entry.personal_rating for entry in rated_completed if entry.personal_rating is not None
    ]

    dated_events = [
        event
        for entry in entries
        for event in entry.viewing_events
        if event.viewed_on is not None
    ]
    total_views = sum(entry.view_count for entry in completed)
    undated_views = max(total_views - len(dated_events), 0)
    this_month = sum(
        1
        for event in dated_events
        if event.viewed_on.year == today.year and event.viewed_on.month == today.month
    )
    this_year = sum(1 for event in dated_events if event.viewed_on.year == today.year)
    monthly_activity = Counter(event.viewed_on.strftime("%Y-%m") for event in dated_events)
    weekday_activity = Counter(event.viewed_on.weekday() for event in dated_events)
    yearly_activity = Counter(str(event.viewed_on.year) for event in dated_events)
    activity_state = "available" if dated_events else "insufficient_data"
    if dated_events:
        first_date = min(event.viewed_on for event in dated_events)
        last_month = max(max(event.viewed_on for event in dated_events), today)
        cursor_year, cursor_month = first_date.year, first_date.month
        while (cursor_year, cursor_month) <= (last_month.year, last_month.month):
            monthly_activity.setdefault(f"{cursor_year:04d}-{cursor_month:02d}", 0)
            if cursor_month == 12:
                cursor_year, cursor_month = cursor_year + 1, 1
            else:
                cursor_month += 1
        span_days = max((today - first_date).days + 1, 1)
        avg_week = len(dated_events) / max(span_days / 7, 1)
        avg_month = len(dated_events) / max(span_days / 30.4375, 1)
    else:
        first_date, span_days, avg_week, avg_month = None, 0, None, None

    completion_denominator = len(completed) + len(dropped)
    completion_rate = (
        len(completed) / completion_denominator if completion_denominator else None
    )
    rewatched = [entry for entry in completed if entry.view_count > 1]
    rewatch_rate = len(rewatched) / len(completed) if completed else None

    genre_affinity = _affinity(completed, "genre")
    subgenre_affinity = _affinity(completed, "subgenre")
    keyword_affinity = _affinity(completed, "keyword")

    movie_runtime = _band_preferences(
        [entry for entry in completed if entry.catalog_item.media_type == "movie"],
        attribute="runtime_minutes",
        scope="movies",
        band_for=lambda value: (
            "Under 90 min"
            if value < 90
            else "90–119 min"
            if value < 120
            else "120–149 min"
            if value < 150
            else "150+ min"
        ),
    )
    episode_runtime = _band_preferences(
        [entry for entry in completed if entry.catalog_item.media_type in {"tv", "anime"}],
        attribute="runtime_minutes",
        scope="TV / anime episodes",
        band_for=lambda value: (
            "Under 25 min"
            if value < 25
            else "25–44 min"
            if value < 45
            else "45–69 min"
            if value < 70
            else "70+ min"
        ),
    )
    episode_counts = _band_preferences(
        [entry for entry in completed if entry.catalog_item.media_type in {"tv", "anime"}],
        attribute="episode_count",
        scope="TV / anime",
        band_for=lambda value: (
            "1–6 episodes"
            if value <= 6
            else "7–13 episodes"
            if value <= 13
            else "14–26 episodes"
            if value <= 26
            else "27–52 episodes"
            if value <= 52
            else "53+ episodes"
        ),
    )

    histogram = {f"{value / 10:g}": 0 for value in range(10, 101)}
    for rating in ratings:
        histogram[f"{rating:g}"] += 1
    average_rating = statistics.fmean(ratings) if ratings else None
    median_rating = statistics.median(ratings) if ratings else None
    if average_rating is None:
        tendency = "insufficient data"
    elif average_rating >= 8:
        tendency = "highly selective, strongly positive ratings"
    elif average_rating >= 6.5:
        tendency = "generally positive ratings"
    elif average_rating >= 5:
        tendency = "balanced ratings"
    else:
        tendency = "critical ratings"

    type_rows = []
    completed_by_type = Counter(entry.catalog_item.media_type for entry in completed)
    library_by_type = Counter(entry.catalog_item.media_type for entry in entries)
    for media_type in ("movie", "tv", "anime"):
        typed_ratings = [
            entry.personal_rating
            for entry in completed
            if entry.catalog_item.media_type == media_type and entry.personal_rating is not None
        ]
        type_rows.append(
            {
                "media_type": media_type,
                "library_count": library_by_type[media_type],
                "completed_count": completed_by_type[media_type],
                "share": _rounded(
                    completed_by_type[media_type] / len(completed) if completed else None
                ),
                "average_personal_rating": _rounded(
                    statistics.fmean(typed_ratings) if typed_ratings else None, 2
                ),
                "rated_support_count": len(typed_ratings),
            }
        )

    decades: Counter[str] = Counter()
    for entry in completed:
        if entry.catalog_item.release_year:
            decade = entry.catalog_item.release_year // 10 * 10
            decades[f"{decade}s"] += 1

    ranked = sorted(
        rated_completed,
        key=lambda entry: (
            -entry.personal_rating,
            -entry.view_count,
            entry.catalog_item.canonical_title.casefold(),
            entry.id,
        ),
    )
    top_by_type = {
        media_type: [
            _title_signal(entry)
            for entry in ranked
            if entry.catalog_item.media_type == media_type
        ][:5]
        for media_type in ("movie", "tv", "anime")
    }
    positive = [
        _title_signal(entry, "personal_rating >= 8")
        for entry in ranked
        if entry.personal_rating >= 8
    ]
    negative = []
    for entry in entries:
        reasons = []
        if entry.personal_rating is not None and entry.personal_rating <= 4:
            reasons.append("personal_rating <= 4")
        if entry.status == "dropped":
            reasons.append("dropped")
        if reasons:
            negative.append(_title_signal(entry, reasons))
    negative.sort(
        key=lambda row: (
            row["personal_rating"] if row["personal_rating"] is not None else 11,
            row["title"].casefold(),
            row["entry_id"],
        )
    )
    most_rewatched = [
        _title_signal(entry, f"{entry.rewatch_count} rewatch(es)")
        for entry in sorted(
            rewatched,
            key=lambda item: (
                -item.view_count,
                -(item.personal_rating or 0),
                item.catalog_item.canonical_title.casefold(),
                item.id,
            ),
        )[:10]
    ]

    return {
        "summary": {
            "library_total": len(entries),
            "completed_total": len(completed),
            "completed_movies": completed_by_type["movie"],
            "completed_tv": completed_by_type["tv"],
            "completed_anime": completed_by_type["anime"],
        },
        "activity": {
            "this_month": this_month,
            "this_year": this_year,
            "all_time_completed_viewings": total_views,
            "dated_viewings": len(dated_events),
            "undated_viewings_excluded_from_time_series": undated_views,
            "first_dated_viewing": first_date.isoformat() if first_date else None,
            "observed_days": span_days,
            "average_per_week": _rounded(avg_week, 2),
            "average_per_month": _rounded(avg_month, 2),
            "monthly": [
                {"period": period, "count": count}
                for period, count in sorted(monthly_activity.items())
            ],
            "by_weekday": [
                {
                    "weekday": name,
                    "weekday_index": index,
                    "count": weekday_activity[index],
                }
                for index, name in enumerate(
                    (
                        "Monday",
                        "Tuesday",
                        "Wednesday",
                        "Thursday",
                        "Friday",
                        "Saturday",
                        "Sunday",
                    )
                )
            ],
            "by_year": [
                {"year": year, "count": count}
                for year, count in sorted(yearly_activity.items())
            ],
            "state": activity_state,
        },
        "status_distribution": [
            {"status": status, "count": count}
            for status, count in sorted(Counter(entry.status for entry in entries).items())
        ],
        "completion": {
            "rate": _rounded(completion_rate),
            "completed": len(completed),
            "dropped_without_completion": len(dropped),
            "denominator": completion_denominator,
        },
        "rewatch": {
            "rate": _rounded(rewatch_rate),
            "rewatched_titles": len(rewatched),
            "completed_titles": len(completed),
        },
        "rating_profile": {
            "histogram": histogram,
            "average": _rounded(average_rating, 2),
            "median": _rounded(median_rating, 2),
            "rated_count": len(ratings),
            "unrated_completed_count": len(completed) - len(ratings),
            "tendency": tendency,
            "tendency_thresholds": "average >=8 strongly positive; >=6.5 positive; >=5 balanced; <5 critical",
        },
        "media_type_preferences": type_rows,
        "genre_affinity": genre_affinity,
        "subgenre_affinity": subgenre_affinity,
        "provider_tag_affinity": keyword_affinity,
        "format_preferences": _attribute_preferences(completed, "provider_format"),
        "country_preferences": _attribute_preferences(completed, "country"),
        "language_preferences": _attribute_preferences(completed, "language"),
        "runtime_preferences": [*movie_runtime, *episode_runtime],
        "episode_count_preferences": episode_counts,
        "release_decades": [
            {"decade": decade, "count": count}
            for decade, count in sorted(decades.items(), key=lambda item: item[0])
        ],
        "top_titles": {
            "overall": [_title_signal(entry) for entry in ranked[:10]],
            "by_media_type": top_by_type,
        },
        "positive_signals": positive,
        "negative_signals": negative,
        "rewatch_signals": most_rewatched,
        "rewatch_genre_signals": _rewatch_genre_signals(completed),
        "taste_dimensions": _taste_dimensions(completed),
        "metadata_coverage": _metadata_coverage(entries),
        "strongest_weighted_genres": [
            row for row in genre_affinity if row["weighted_affinity"] is not None
        ][:10],
        "sample_sizes": {
            "library_titles": len(entries),
            "completed_titles": len(completed),
            "rated_completed_titles": len(ratings),
            "dated_viewings": len(dated_events),
        },
    }
