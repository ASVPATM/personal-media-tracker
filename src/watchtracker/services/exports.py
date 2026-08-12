from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.orm import Session

from watchtracker.services.entries import load_active_entries, serialize_entry

CSV_FIELDS = [
    "entry_id",
    "title",
    "original_title",
    "release_year",
    "media_type",
    "provider_format",
    "provider_source",
    "provider_id",
    "tmdb_movie_id",
    "tmdb_tv_id",
    "anilist_id",
    "mal_id",
    "status",
    "personal_rating",
    "started_date",
    "finished_date",
    "watched_date",
    "view_count",
    "rewatch_count",
    "viewing_dates",
    "genres",
    "subgenres",
    "tags",
    "notes",
    "import_context",
    "created_at",
    "updated_at",
]


def safe_csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def unescape_csv_cell(value: str | None) -> str | None:
    if value and len(value) > 1 and value[0] == "'" and value[1] in "=+-@":
        return value[1:]
    return value


def watch_log_csv(session: Session) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    entries = sorted(
        load_active_entries(session),
        key=lambda entry: (entry.catalog_item.canonical_title.casefold(), entry.id),
    )
    for entry in entries:
        serialized = serialize_entry(entry, include_events=False)
        catalog = entry.catalog_item
        row = {
            "entry_id": entry.id,
            "title": catalog.canonical_title,
            "original_title": catalog.original_title,
            "release_year": catalog.release_year,
            "media_type": catalog.media_type,
            "provider_format": catalog.provider_format,
            "provider_source": catalog.provider_source,
            "provider_id": catalog.provider_id,
            "tmdb_movie_id": catalog.tmdb_movie_id,
            "tmdb_tv_id": catalog.tmdb_tv_id,
            "anilist_id": catalog.anilist_id,
            "mal_id": catalog.mal_id,
            "status": entry.status,
            "personal_rating": entry.personal_rating,
            "started_date": entry.started_date,
            "finished_date": entry.finished_date,
            "watched_date": entry.watched_date,
            "view_count": entry.view_count,
            "rewatch_count": entry.rewatch_count,
            "viewing_dates": "|".join(
                event.viewed_on.isoformat() if event.viewed_on else "undated"
                for event in entry.viewing_events
            ),
            "genres": "|".join(serialized.effective_genres),
            "subgenres": "|".join(serialized.effective_subgenres),
            "tags": "|".join(entry.user_tags or []),
            "notes": entry.notes,
            "import_context": (
                json.dumps(entry.import_context, sort_keys=True, ensure_ascii=False)
                if entry.import_context
                else ""
            ),
            "created_at": serialized.created_at.isoformat(),
            "updated_at": serialized.updated_at.isoformat(),
        }
        writer.writerow({key: safe_csv_cell(value) for key, value in row.items()})
    return output.getvalue()
