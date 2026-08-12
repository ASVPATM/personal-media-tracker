from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any

from watchtracker.services.exports import unescape_csv_cell
from watchtracker.taxonomy import normalize_title

STATUS_MAP = {
    "watched": "watched",
    "complete": "watched",
    "completed": "watched",
    "completed_unrated": "watched",
    "rewatched": "watched",
    "rewatch": "watched",
    "started": "watching",
    "started_not_finished": "watching",
    "in_progress": "watching",
    "partial": "watching",
    "watching": "watching",
    "watchlist": "plan_to_watch",
    "plan_to_watch": "plan_to_watch",
    "planned": "plan_to_watch",
    "dropped": "dropped",
    "did_not_finish": "dropped",
    "dnf": "dropped",
    "rewatching": "rewatching",
}


@dataclass(frozen=True)
class ImportLimits:
    max_members: int = 50
    max_rows: int = 100_000
    max_cell_chars: int = 100_000
    max_decompressed_bytes: int = 100 * 1024 * 1024
    max_member_bytes: int = 25 * 1024 * 1024
    max_compression_ratio: int = 200


def _blank(value: Any) -> bool:
    return value is None or str(value).strip().casefold() in {"", "none", "null", "nan", "n/a"}


def _first(row: dict[str, str], *names: str) -> str | None:
    lowered = {key.casefold().strip(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if not _blank(value):
            return unescape_csv_cell(str(value).strip())
    return None


def parse_rating(value: str | float | None, *, letterboxd: bool = False) -> float | None:
    if _blank(value):
        return None
    rating = float(value)
    if letterboxd:
        if rating < 0.5 or rating > 5 or rating * 2 != int(rating * 2):
            raise ValueError("Letterboxd rating must be 0.5-5 in half-star increments")
        rating *= 2
    try:
        precise = Decimal(str(rating))
    except InvalidOperation as exc:
        raise ValueError("personal rating must be a number") from exc
    if (
        not precise.is_finite()
        or precise < Decimal("1")
        or precise > Decimal("10")
        or precise != precise.quantize(Decimal("0.1"))
    ):
        raise ValueError("personal rating must be 1.0-10.0 in 0.1 increments")
    return rating


def parse_date(value: Any) -> date | None:
    if _blank(value):
        return None
    text = str(value).strip()[:10]
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date: {text}")


def parse_year(value: Any) -> int | None:
    if _blank(value):
        return None
    match = re.search(r"\b(18|19|20|21)\d{2}\b", str(value))
    if not match:
        raise ValueError(f"invalid release year: {value}")
    return int(match.group())


def parse_list(value: Any) -> list[str]:
    if _blank(value):
        return []
    return sorted(
        {part.strip() for part in re.split(r"[|,]", str(value)) if part.strip()},
        key=str.casefold,
    )


def normalize_media_type(value: str | None) -> str:
    normalized = (value or "movie").strip().casefold().replace("-", "_").replace(" ", "_")
    if "anime" in normalized:
        return "anime"
    if normalized in {
        "tv",
        "show",
        "shows",
        "tv_series",
        "limited_series",
        "tv_season",
        "tv_episode",
        "series",
    }:
        return "tv"
    if "show" in normalized or "series" in normalized or normalized.startswith("tv_"):
        return "tv"
    return "movie"


def normalize_status(value: str | None) -> tuple[str, dict[str, Any] | None]:
    raw = (value or "watched").strip().casefold().replace("-", "_").replace(" ", "_")
    if raw in STATUS_MAP:
        mapped = STATUS_MAP[raw]
        return mapped, (
            {"from": raw, "to": mapped, "uncertain": False} if raw != mapped else None
        )
    return "plan_to_watch", {
        "from": raw,
        "to": "plan_to_watch",
        "uncertain": True,
        "note": "Unsupported status requires review; proposed as plan_to_watch.",
    }


def _stable_row_key(row: dict[str, str], index: int) -> str:
    preferred = _first(
        row,
        "source_row_id",
        "record_id",
        "letterboxd uri",
        "url",
        "entry_id",
        "library_id",
    )
    if preferred:
        return hashlib.sha256(preferred.encode()).hexdigest()[:24]
    canonical = "|".join(f"{key}={row[key]}" for key in sorted(row))
    return hashlib.sha256(f"{index}|{canonical}".encode()).hexdigest()[:24]


def parse_manual_csv(
    content: bytes,
    *,
    limits: ImportLimits | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    limits = limits or ImportLimits()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        enumerated_rows = enumerate(reader, start=2)
        for index, raw in enumerated_rows:
            if index - 1 > limits.max_rows:
                raise ValueError(f"CSV exceeds the {limits.max_rows:,}-row safety limit")
            if any(len(str(value or "")) > limits.max_cell_chars for value in raw.values()):
                invalid.append(
                    {"row_number": index, "error": "a cell exceeds the configured size limit"}
                )
                continue
            _parse_manual_row(raw, index, rows, invalid)
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV near row {reader.line_num}: {exc}") from exc
    if invalid:
        warnings.append(
            f"{len(invalid)} invalid row(s) will not be imported unless explicitly allowed."
        )
    return rows, invalid, warnings


def _parse_manual_row(
    raw: dict[str, str],
    index: int,
    rows: list[dict[str, Any]],
    invalid: list[dict[str, Any]],
) -> None:
    try:
        title = _first(raw, "title", "name", "raw_title", "canonical_title")
        if not title:
            raise ValueError("missing title")
        raw_status = _first(raw, "status", "watched_status", "view_status") or "watched"
        status, mapping = normalize_status(raw_status)
        media_type = normalize_media_type(
            _first(raw, "media_type", "media_type_hint", "type")
            or _first(raw, "source_sections", "source_section")
        )
        direct_view_count = _first(raw, "view_count")
        times_watched = _first(raw, "times_watched")
        explicit_view_count = direct_view_count or times_watched
        legacy_count = _first(raw, "rewatch_count")
        supplied_count = (
            explicit_view_count if explicit_view_count is not None else legacy_count
        )
        if supplied_count is not None:
            numeric_count = float(supplied_count)
            if numeric_count < 0 or not numeric_count.is_integer():
                raise ValueError("view count must be a non-negative whole number")
        normalization_note = None
        if explicit_view_count is not None:
            view_count = int(float(explicit_view_count))
            if status in {"watched", "rewatching"} and view_count == 0:
                view_count = 1
                normalization_note = (
                    f"{('times_watched' if times_watched is not None else 'view_count')}=0 "
                    "for a completed status normalized to total view_count=1"
                )
            elif times_watched and not direct_view_count:
                normalization_note = (
                    f"times_watched={times_watched} imported as total view_count={view_count}"
                )
        elif status in {"watched", "rewatching"}:
            legacy = int(float(legacy_count or 0))
            if raw_status.casefold() in {"rewatched", "rewatch"} and legacy < 2:
                view_count = 2
                normalization_note = "rewatched status normalized to view_count=2"
            else:
                view_count = legacy if legacy > 0 else 1
                normalization_note = f"legacy rewatch_count={legacy} interpreted as total view_count={view_count}"
        else:
            view_count = int(float(legacy_count or 0)) if legacy_count else 0
        rating = parse_rating(
            _first(raw, "personal_rating", "user_rating", "rating_10", "rating")
        )
        watched_date = parse_date(_first(raw, "watched_date", "watched_at", "date"))
        viewing_events = []
        viewing_dates = _first(raw, "viewing_dates")
        if viewing_dates:
            for event_index, event_value in enumerate(viewing_dates.split("|")):
                event_value = event_value.strip()
                viewed_on = (
                    None if event_value.casefold() == "undated" else parse_date(event_value)
                )
                event_key = hashlib.sha256(
                    f"{_stable_row_key(raw, index)}|{event_index}|{event_value}".encode()
                ).hexdigest()[:24]
                viewing_events.append(
                    {
                        "viewed_on": viewed_on.isoformat() if viewed_on else None,
                        "event_key": event_key,
                    }
                )
        provider_source = _first(raw, "provider_source", "provider", "resolution_provider")
        provider_id = _first(raw, "provider_id", "resolved_provider_id", "external_id")
        tmdb_movie_id = _first(raw, "tmdb_movie_id")
        tmdb_tv_id = _first(raw, "tmdb_tv_id")
        external_tmdb = _first(raw, "external_tmdb_id")
        if external_tmdb and not (tmdb_movie_id or tmdb_tv_id):
            if media_type == "movie":
                tmdb_movie_id = external_tmdb
            elif media_type == "tv":
                tmdb_tv_id = external_tmdb
        anilist_id = _first(raw, "anilist_id", "external_anilist_id")
        mal_id = _first(raw, "mal_id", "external_mal_id")
        if not provider_source:
            if tmdb_movie_id:
                provider_source, provider_id = "tmdb_movie", tmdb_movie_id
            elif tmdb_tv_id:
                provider_source, provider_id = "tmdb_tv", tmdb_tv_id
            elif anilist_id:
                provider_source, provider_id = "anilist", anilist_id
            elif mal_id:
                provider_source, provider_id = "mal", mal_id
        import_context: dict[str, Any] = {}
        serialized_context = _first(raw, "import_context")
        if serialized_context:
            parsed_context = json.loads(serialized_context)
            if isinstance(parsed_context, dict):
                import_context.update(parsed_context)
        for source_field in (
            "record_id",
            "source_title",
            "rating_label",
            "rank_position",
            "rank_status",
            "season_scope",
            "progress",
            "source_occurrences",
            "source_sections",
            "source_order",
        ):
            if source_value := _first(raw, source_field):
                import_context[source_field] = source_value
        row = {
            "row_number": index,
            "row_key": _stable_row_key(raw, index),
            "title": title,
            "original_title": _first(raw, "original_title"),
            "release_year": parse_year(_first(raw, "release_year", "year")),
            "media_type": media_type,
            "provider_format": _first(raw, "provider_format"),
            "provider_source": provider_source,
            "provider_id": provider_id,
            "tmdb_movie_id": tmdb_movie_id,
            "tmdb_tv_id": tmdb_tv_id,
            "anilist_id": anilist_id,
            "mal_id": mal_id,
            "status": status,
            "personal_rating": rating,
            "notes": _first(raw, "notes", "review"),
            "tags": parse_list(_first(raw, "tags", "user_tags")),
            "started_date": (
                parsed.isoformat()
                if (parsed := parse_date(_first(raw, "started_date")))
                else None
            ),
            "finished_date": (
                parsed.isoformat()
                if (parsed := parse_date(_first(raw, "finished_date")))
                else None
            ),
            "watched_date": watched_date.isoformat() if watched_date else None,
            "view_count": view_count,
            "genres": parse_list(_first(raw, "genres", "normalized_genres")),
            "subgenres": parse_list(_first(raw, "subgenres", "inferred_subgenres")),
            "viewing_events": viewing_events,
            "import_context": import_context,
            "status_mapping": mapping,
            "normalization_note": normalization_note,
        }
        rows.append(row)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        invalid.append({"row_number": index, "error": str(exc)})


def _archive_csv_rows(
    archive: zipfile.ZipFile,
    member: str,
    limits: ImportLimits,
) -> list[dict[str, str]]:
    if archive.getinfo(member).file_size > limits.max_member_bytes:
        raise ValueError(f"Archive member {PurePosixPath(member).name} is too large")
    with archive.open(member) as raw:
        reader = csv.DictReader(
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), strict=True
        )
        rows = []
        try:
            for row in reader:
                if len(rows) >= limits.max_rows:
                    raise ValueError(
                        f"Archive exceeds the {limits.max_rows:,}-row safety limit"
                    )
                if any(len(str(value or "")) > limits.max_cell_chars for value in row.values()):
                    raise ValueError(
                        f"Archive member {PurePosixPath(member).name} contains an oversized cell"
                    )
                rows.append(row)
        except csv.Error as exc:
            raise ValueError(
                f"Malformed CSV in {PurePosixPath(member).name} near row {reader.line_num}"
            ) from exc
        return rows


def parse_letterboxd_zip(
    content: bytes,
    *,
    limits: ImportLimits | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    limits = limits or ImportLimits()
    grouped: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("File is not a valid Letterboxd ZIP export") from exc
    with archive:
        members = archive.infolist()
        if len(members) > limits.max_members:
            raise ValueError(f"ZIP exceeds the {limits.max_members}-member safety limit")
        if len({item.filename for item in members}) != len(members):
            raise ValueError("ZIP contains duplicate member names")
        total_size = 0
        executable_suffixes = {".exe", ".dll", ".com", ".bat", ".cmd", ".js", ".html"}
        for info in members:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise ValueError("ZIP contains an unsafe traversal filename")
            if info.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP members are not supported")
            if path.suffix.casefold() in {".zip", ".rar", ".7z", ".tar", ".gz"}:
                raise ValueError("Nested archives are not supported")
            if path.suffix.casefold() in executable_suffixes:
                raise ValueError("ZIP contains unexpected executable content")
            if info.file_size > limits.max_member_bytes:
                raise ValueError(f"Archive member {path.name} is too large")
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > limits.max_compression_ratio:
                raise ValueError("ZIP contains a suspicious compression ratio")
            total_size += info.file_size
        if total_size > limits.max_decompressed_bytes:
            raise ValueError("ZIP exceeds the decompressed-size safety limit")
        expected_csv = {
            "diary.csv",
            "watched.csv",
            "ratings.csv",
            "reviews.csv",
            "watchlist.csv",
            "tags.csv",
        }
        csv_members = [
            name
            for name in archive.namelist()
            if (
                PurePosixPath(name).name.casefold() in expected_csv
                or "lists" in {part.casefold() for part in PurePosixPath(name).parts[:-1]}
            )
            and name.casefold().endswith(".csv")
            and not name.casefold().startswith("deleted/")
            and not PurePosixPath(name).is_absolute()
            and ".." not in PurePosixPath(name).parts
        ]
        if not csv_members:
            raise ValueError("ZIP contains no Letterboxd CSV files")
        parsed_archive_rows = 0
        for member in csv_members:
            basename = PurePosixPath(member).name.casefold()
            try:
                member_rows = _archive_csv_rows(archive, member, limits)
            except (UnicodeDecodeError, ValueError, csv.Error) as exc:
                invalid.append({"file": basename, "error": str(exc)})
                continue
            parsed_archive_rows += len(member_rows)
            if parsed_archive_rows > limits.max_rows:
                raise ValueError(f"Archive exceeds the {limits.max_rows:,}-row safety limit")
            for index, raw in enumerate(member_rows, start=2):
                title = _first(raw, "name", "title")
                if not title or basename in {"profile.csv", "comments.csv", "likes.csv"}:
                    continue
                uri = _first(raw, "letterboxd uri", "url")
                slug = uri.rstrip("/").split("/")[-1] if uri else None
                try:
                    year = parse_year(_first(raw, "year"))
                    key = slug or f"{normalize_title(title)}::{year or ''}"
                    item = grouped.setdefault(
                        key,
                        {
                            "row_number": index,
                            "row_key": hashlib.sha256(key.encode()).hexdigest()[:24],
                            "title": title,
                            "original_title": None,
                            "release_year": year,
                            "media_type": "movie",
                            "provider_format": "movie",
                            "provider_source": "letterboxd" if slug else None,
                            "provider_id": slug,
                            "tmdb_movie_id": None,
                            "tmdb_tv_id": None,
                            "anilist_id": None,
                            "mal_id": None,
                            "status": "plan_to_watch",
                            "personal_rating": None,
                            "notes": None,
                            "tags": [],
                            "started_date": None,
                            "finished_date": None,
                            "watched_date": None,
                            "view_count": 0,
                            "genres": [],
                            "subgenres": [],
                            "viewing_events": [],
                            "import_context": {
                                "letterboxd_uri": uri,
                                "letterboxd_files": [],
                            },
                            "status_mapping": None,
                            "normalization_note": None,
                            "_notes": [],
                            "_tags": set(),
                        },
                    )
                    if _first(raw, "rating"):
                        item["personal_rating"] = parse_rating(
                            _first(raw, "rating"), letterboxd=True
                        )
                    if (review := _first(raw, "review")) and review not in item["_notes"]:
                        item["_notes"].append(review)
                    item["_tags"].update(parse_list(_first(raw, "tags")))
                    if basename == "diary.csv":
                        watched = parse_date(_first(raw, "watched date"))
                        event_key = hashlib.sha256(
                            f"{member}|{index}|{key}".encode()
                        ).hexdigest()[:24]
                        item["viewing_events"].append(
                            {
                                "viewed_on": watched.isoformat() if watched else None,
                                "event_key": event_key,
                            }
                        )
                        item["view_count"] += 1
                        item["status"] = "watched"
                    elif basename in {"watched.csv", "ratings.csv", "reviews.csv"}:
                        item["view_count"] = max(item["view_count"], 1)
                        item["status"] = "watched"
                    elif (
                        basename == "watchlist.csv"
                        and item["view_count"] == 0
                        or "/lists/" in member.casefold()
                        and item["view_count"] == 0
                    ):
                        item["status"] = "plan_to_watch"
                    if member not in item["import_context"]["letterboxd_files"]:
                        item["import_context"]["letterboxd_files"].append(member)
                except (ValueError, TypeError) as exc:
                    invalid.append({"file": basename, "row_number": index, "error": str(exc)})
        for item in grouped.values():
            item["notes"] = "\n\n".join(item.pop("_notes")) or None
            item["tags"] = sorted(item.pop("_tags"), key=str.casefold)
            dated = [
                event["viewed_on"] for event in item["viewing_events"] if event["viewed_on"]
            ]
            item["watched_date"] = max(dated) if dated else None
            if item["view_count"] > 1:
                item["normalization_note"] = (
                    f"{item['view_count']} diary viewings preserved as distinct events"
                )
    if invalid:
        warnings.append(f"{len(invalid)} invalid Letterboxd row(s) were found.")
    return list(grouped.values()), invalid, warnings


def import_breakdown(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(row[key] for row in rows).items()))
