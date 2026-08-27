from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from watchtracker.authorization import Principal
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


def watch_log_csv(session: Session, principal: Principal | None = None) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    entries = sorted(
        load_active_entries(session, principal),
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


def _obsidian_note_name(title: str, year: int | None, entry_id: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .") or "Untitled"
    cleaned = cleaned[:140].rstrip(" .")
    year_suffix = f" ({year})" if year else ""
    return f"{cleaned}{year_suffix} [{entry_id[:8]}]"


def _frontmatter(value: Any) -> str:
    if isinstance(value, (date,)):
        value = value.isoformat()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def obsidian_vault_zip(
    session: Session, *, generated_on: date, principal: Principal | None = None
) -> bytes:
    """Create a one-way, vault-ready Markdown snapshot without touching a vault."""
    entries = sorted(
        load_active_entries(session, principal),
        key=lambda entry: (entry.catalog_item.canonical_title.casefold(), entry.id),
    )
    root = "Personal Media Tracker"
    note_names: list[tuple[str, Any]] = [
        (
            _obsidian_note_name(
                entry.catalog_item.canonical_title,
                entry.catalog_item.release_year,
                entry.id,
            ),
            entry,
        )
        for entry in entries
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        index_lines = [
            "---",
            "type: pmt-library-index",
            f"generated_on: {_frontmatter(generated_on)}",
            f"title_count: {len(entries)}",
            "---",
            "",
            "# Personal Media Tracker library",
            "",
            "One-way snapshot generated by Personal Media Tracker.",
            "",
        ]
        for note_name, entry in note_names:
            rating = (
                f" · {entry.personal_rating:g}/10" if entry.personal_rating is not None else ""
            )
            index_lines.append(
                f"- [[Titles/{note_name}|{entry.catalog_item.canonical_title}]] · {entry.status}{rating}"
            )
        archive.writestr(f"{root}/Media Library.md", "\n".join(index_lines) + "\n")

        for note_name, entry in note_names:
            catalog = entry.catalog_item
            serialized = serialize_entry(entry, include_events=False)
            tags = sorted(
                {
                    *(str(tag).strip() for tag in (entry.user_tags or []) if str(tag).strip()),
                    "personal-media-tracker",
                    f"status/{entry.status.replace('_', '-')}",
                    f"media/{catalog.media_type}",
                },
                key=str.casefold,
            )
            aliases = [catalog.original_title] if catalog.original_title else []
            properties = {
                "type": "pmt-media-title",
                "pmt_id": entry.id,
                "title": catalog.canonical_title,
                "aliases": aliases,
                "media_type": catalog.media_type,
                "status": entry.status,
                "personal_rating": entry.personal_rating,
                "release_year": catalog.release_year,
                "started_date": entry.started_date,
                "finished_date": entry.finished_date,
                "watched_date": entry.watched_date,
                "view_count": entry.view_count,
                "tags": tags,
                "genres": list(serialized.effective_genres),
                "subgenres": list(serialized.effective_subgenres),
                "provider_source": catalog.provider_source,
                "provider_id": catalog.provider_id,
                "tmdb_movie_id": catalog.tmdb_movie_id,
                "tmdb_tv_id": catalog.tmdb_tv_id,
                "anilist_id": catalog.anilist_id,
                "mal_id": catalog.mal_id,
                "poster_url": catalog.poster_url,
                "pmt_created_at": entry.created_at.isoformat(),
                "pmt_updated_at": entry.updated_at.isoformat(),
            }
            lines = ["---"]
            lines.extend(f"{key}: {_frontmatter(value)}" for key, value in properties.items())
            lines.extend(["---", "", f"# {catalog.canonical_title}", ""])
            summary = f"**Status:** {entry.status.replace('_', ' ').title()}"
            if entry.personal_rating is not None:
                summary += f" · **Personal rating:** {entry.personal_rating:g}/10"
            lines.extend([summary, ""])
            parsed_poster = urlsplit(catalog.poster_url or "")
            if parsed_poster.scheme == "https" and parsed_poster.netloc:
                lines.extend([f"![Poster](<{catalog.poster_url}>)", ""])
            if catalog.overview:
                lines.extend(["## Overview", "", catalog.overview.strip(), ""])
            if entry.notes:
                lines.extend(["## Notes", "", entry.notes.strip(), ""])
            viewing_dates = [
                event.viewed_on.isoformat() if event.viewed_on else "Date not recorded"
                for event in entry.viewing_events
            ]
            if viewing_dates:
                lines.extend(["## Viewing history", ""])
                lines.extend(f"- {value}" for value in viewing_dates)
                lines.append("")
            archive.writestr(f"{root}/Titles/{note_name}.md", "\n".join(lines))

        archive.writestr(
            f"{root}/README.md",
            "# Using this export in Obsidian\n\n"
            "Unzip the `Personal Media Tracker` folder anywhere inside an existing "
            "Obsidian vault, then open `Media Library.md`. Each title is a separate "
            "Markdown note with searchable YAML properties.\n\n"
            "This is a one-way snapshot, not two-way sync. Re-export when you want a "
            "fresh PMT snapshot; keep your own Obsidian notes outside this folder or "
            "merge them before replacing it. Private PMT notes are included. Poster "
            "images remain remote links and are not downloaded.\n",
        )
    return output.getvalue()
