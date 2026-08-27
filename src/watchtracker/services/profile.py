from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from watchtracker.authorization import Principal
from watchtracker.services.entries import load_active_entries
from watchtracker.services.stats import calculate_stats


def build_profile(
    session: Session, *, today: date, principal: Principal | None = None
) -> dict[str, Any]:
    stats = calculate_stats(session, today=today, principal=principal)
    entries = load_active_entries(session, principal)
    unresolved = sum(
        1
        for entry in entries
        if not any(
            (
                entry.catalog_item.tmdb_movie_id,
                entry.catalog_item.tmdb_tv_id,
                entry.catalog_item.anilist_id,
                entry.catalog_item.mal_id,
            )
        )
    )
    patterns: list[dict[str, Any]] = []
    completed_types = sorted(
        stats["media_type_preferences"],
        key=lambda row: (-row["completed_count"], row["media_type"]),
    )
    if completed_types and completed_types[0]["completed_count"]:
        patterns.append(
            {
                "statement": f"Most completed titles are {completed_types[0]['media_type']}.",
                "support_count": completed_types[0]["completed_count"],
                "evidence": "completed-title media-type frequency",
            }
        )
    strongest = stats["strongest_weighted_genres"]
    if strongest:
        patterns.append(
            {
                "statement": f"{strongest[0]['name']} has the strongest rating-weighted genre affinity.",
                "support_count": strongest[0]["rated_support_count"],
                "evidence": strongest[0]["calculation_method"],
            }
        )
    return {
        "schema_version": "1.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"ratings_are_personal": True, "dated_activity_only": True},
        "viewer_summary": {
            **stats["summary"],
            "completion_rate": stats["completion"],
            "rewatch_rate": stats["rewatch"],
            "activity": stats["activity"],
        },
        "rating_profile": stats["rating_profile"],
        "media_type_preferences": stats["media_type_preferences"],
        "genre_affinity": stats["genre_affinity"],
        "subgenre_affinity": stats["subgenre_affinity"],
        "provider_tag_affinity": stats["provider_tag_affinity"],
        "format_preferences": stats["format_preferences"],
        "country_preferences": stats["country_preferences"],
        "language_preferences": stats["language_preferences"],
        "runtime_preferences": stats["runtime_preferences"],
        "episode_count_preferences": stats["episode_count_preferences"],
        "taste_dimensions": stats["taste_dimensions"],
        "positive_signals": stats["positive_signals"],
        "negative_signals": stats["negative_signals"],
        "rewatch_signals": stats["rewatch_signals"],
        "rewatch_genre_signals": stats["rewatch_genre_signals"],
        "patterns": patterns,
        "data_quality": {
            "rated_titles": stats["rating_profile"]["rated_count"],
            "unrated_titles": stats["rating_profile"]["unrated_completed_count"],
            "dated_viewings": stats["activity"]["dated_viewings"],
            "undated_viewings": stats["activity"]["undated_viewings_excluded_from_time_series"],
            "unresolved_or_manual_items": unresolved,
            "metadata_coverage": stats["metadata_coverage"],
        },
    }


def profile_markdown(profile: dict[str, Any]) -> str:
    summary = profile["viewer_summary"]
    rating = profile["rating_profile"]
    quality = profile["data_quality"]

    def affinity_table(title: str, rows: list[dict[str, Any]]) -> list[str]:
        lines = [
            f"## {title}",
            "",
            "| Name | Weighted affinity | Average rating | Support | Confidence |",
            "|---|---:|---:|---:|---|",
        ]
        if not rows:
            lines.append("| Insufficient data | — | — | 0 | insufficient_data |")
        for row in rows[:12]:
            weighted = (
                "—" if row["weighted_affinity"] is None else f"{row['weighted_affinity']:.3f}"
            )
            average = (
                "—"
                if row["average_personal_rating"] is None
                else f"{row['average_personal_rating']:.2f}"
            )
            lines.append(
                f"| {row['name']} | {weighted} | {average} | {row['support_count']} ({row['rated_support_count']} rated) | {row['confidence']} |"
            )
        lines.append("")
        return lines

    lines = [
        "# Personal Watch Preference Profile",
        "",
        f"Generated: {profile['generated_at']}",
        "",
        "> Ratings in this document are personal ratings. Time-series activity uses dated viewing events only.",
        "",
        "## Viewer summary",
        "",
        f"- Library titles: {summary['library_total']}",
        f"- Completed titles: {summary['completed_total']} ({summary['completed_movies']} movies, {summary['completed_tv']} TV, {summary['completed_anime']} anime)",
        f"- Completed viewings: {summary['activity']['all_time_completed_viewings']}",
        f"- Completion rate: {summary['completion_rate']['rate'] if summary['completion_rate']['rate'] is not None else 'insufficient data'} (n={summary['completion_rate']['denominator']})",
        f"- Rewatch rate: {summary['rewatch_rate']['rate'] if summary['rewatch_rate']['rate'] is not None else 'insufficient data'} (n={summary['rewatch_rate']['completed_titles']})",
        "",
        "## Rating style",
        "",
        f"- Tendency: {rating['tendency']}",
        f"- Average / median: {rating['average'] if rating['average'] is not None else '—'} / {rating['median'] if rating['median'] is not None else '—'}",
        f"- Rated / unrated completed titles: {rating['rated_count']} / {rating['unrated_completed_count']}",
        "",
    ]
    lines.extend(affinity_table("Genre affinity", profile["genre_affinity"]))
    lines.extend(affinity_table("Subgenre affinity", profile["subgenre_affinity"]))
    lines.extend(affinity_table("Provider tag affinity", profile["provider_tag_affinity"]))
    lines.extend(["## Taste dimensions", ""])
    if not profile["taste_dimensions"]:
        lines.append("Insufficient data to describe taste dimensions.")
    for row in profile["taste_dimensions"]:
        titles = ", ".join(row["representative_titles"]) or "none"
        score = "—" if row["score"] is None else f"{row['score']:.3f}"
        lines.append(
            f"- **{row['dimension']} — {row['value']}**: score {score}, support {row['support_count']}, confidence {row['confidence']}; examples: {titles}."
        )
    for heading, key in (
        ("Positive signals", "positive_signals"),
        ("Negative signals", "negative_signals"),
        ("Rewatch signals", "rewatch_signals"),
    ):
        lines.extend(["", f"## {heading}", ""])
        rows = profile[key]
        if not rows:
            lines.append("No supported signals yet.")
        for row in rows[:15]:
            reasons = row.get("reason")
            if isinstance(reasons, list):
                reasons = ", ".join(reasons)
            lines.append(
                f"- {row['title']} — rating {row['personal_rating'] if row['personal_rating'] is not None else 'unrated'}, views {row['view_count']}{f'; {reasons}' if reasons else ''}"
            )
    lines.extend(["", "## Patterns", ""])
    if not profile["patterns"]:
        lines.append("Insufficient data for supported patterns.")
    for row in profile["patterns"]:
        lines.append(
            f"- {row['statement']} (support: {row['support_count']}; {row['evidence']})"
        )
    lines.extend(
        [
            "",
            "## Data quality",
            "",
            f"- Rated titles: {quality['rated_titles']}",
            f"- Unrated completed titles: {quality['unrated_titles']}",
            f"- Dated viewings: {quality['dated_viewings']}",
            f"- Undated viewings excluded from time series: {quality['undated_viewings']}",
            f"- Manual or unresolved catalog items: {quality['unresolved_or_manual_items']}",
            "",
        ]
    )
    return "\n".join(lines)
