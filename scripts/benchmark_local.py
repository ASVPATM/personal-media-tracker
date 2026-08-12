from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from watchtracker.config import Settings
from watchtracker.db import make_engine, make_session_factory, upgrade_database
from watchtracker.models import CatalogItem, ViewingEvent, WatchEntry
from watchtracker.services.entries import EntryService
from watchtracker.services.stats import calculate_stats

TODAY = date(2026, 8, 12)


def settings_for(root: Path) -> Settings:
    return Settings(
        data_dir=root / "data",
        config_dir=root / "config",
        log_dir=root / "logs",
        backups_dir=root / "backups",
        database_path=root / "watchtracker.sqlite3",
        cache_dir=root / "cache",
        env_path=root / ".env",
        timezone="UTC",
    )


def seed(session_factory, entry_count: int, events_per_entry: int) -> float:
    started = time.perf_counter()
    catalogs = []
    entries = []
    events = []
    genres = ("Drama", "Comedy", "Science Fiction", "Thriller")
    media_types = ("movie", "tv", "anime")
    for index in range(entry_count):
        catalog_id = f"catalog-{index:08d}"
        entry_id = f"entry-{index:08d}"
        media_type = media_types[index % len(media_types)]
        catalogs.append(
            CatalogItem(
                id=catalog_id,
                canonical_title=f"Synthetic title {index:05d}",
                normalized_title=f"synthetic title {index:05d}",
                release_year=1980 + index % 46,
                media_type=media_type,
                provider_format="movie" if media_type == "movie" else "series",
                normalized_genres=[genres[index % len(genres)]],
                inferred_subgenres=["Character Study"] if index % 5 == 0 else [],
                keywords=["friendship", "journey"] if index % 7 == 0 else [],
                runtime_minutes=80 + index % 100,
                episode_count=None if media_type == "movie" else 6 + index % 24,
                metadata_source="synthetic_benchmark",
            )
        )
        entries.append(
            WatchEntry(
                id=entry_id,
                catalog_item_id=catalog_id,
                status="watched",
                personal_rating=None if index % 4 == 0 else 1 + (index % 91) / 10,
                user_tags=["favorite"] if index % 25 == 0 else [],
                watched_date=TODAY - timedelta(days=index % 1_800),
                view_count=events_per_entry,
            )
        )
        for event_index in range(events_per_entry):
            events.append(
                ViewingEvent(
                    id=f"view-{index:08d}-{event_index:02d}",
                    entry_id=entry_id,
                    viewed_on=TODAY - timedelta(days=(index + event_index * 97) % 1_800),
                    source="synthetic_benchmark",
                )
            )
    with session_factory() as session:
        session.add_all(catalogs)
        session.add_all(entries)
        session.add_all(events)
        session.commit()
    return time.perf_counter() - started


def measure(entry_count: int, events_per_entry: int) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory(prefix="watchtracker-benchmark-") as temporary:
        settings = settings_for(Path(temporary))
        upgrade_database(settings)
        engine = make_engine(settings.database_url)
        session_factory = make_session_factory(engine)
        try:
            seed_seconds = seed(session_factory, entry_count, events_per_entry)
            with session_factory() as session:
                service = EntryService(session, today=TODAY)
                started = time.perf_counter()
                first_page = service.list(page=1, page_size=24)
                library_seconds = time.perf_counter() - started

                started = time.perf_counter()
                filtered = service.list(
                    page=1,
                    page_size=24,
                    media_type="anime",
                    rating_min=7,
                    sort="personal_rating",
                )
                filtered_seconds = time.perf_counter() - started

                started = time.perf_counter()
                stats = calculate_stats(session, today=TODAY)
                insights_seconds = time.perf_counter() - started
            return {
                "entries": entry_count,
                "viewing_events": entry_count * events_per_entry,
                "seed_seconds": round(seed_seconds, 4),
                "library_first_page_seconds": round(library_seconds, 4),
                "filtered_page_seconds": round(filtered_seconds, 4),
                "insights_seconds": round(insights_seconds, 4),
                "library_total": first_page.total,
                "filtered_total": filtered.total,
                "insights_total_views": stats["activity"]["all_time_completed_viewings"],
            }
        finally:
            engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark synthetic local libraries")
    parser.add_argument("--sizes", type=int, nargs="+", default=[300, 3_000])
    parser.add_argument("--events-per-entry", type=int, default=4)
    parser.add_argument("--max-library-seconds", type=float, default=2.0)
    parser.add_argument("--max-insights-seconds", type=float, default=15.0)
    arguments = parser.parse_args()

    results = [measure(size, arguments.events_per_entry) for size in arguments.sizes]
    print(json.dumps(results, indent=2))
    slow = [
        result
        for result in results
        if result["library_first_page_seconds"] > arguments.max_library_seconds
        or result["filtered_page_seconds"] > arguments.max_library_seconds
        or result["insights_seconds"] > arguments.max_insights_seconds
    ]
    if slow:
        raise SystemExit("Synthetic performance threshold exceeded")


if __name__ == "__main__":
    main()
