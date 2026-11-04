from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import statistics
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

try:
    import resource
except ImportError:  # Windows does not provide getrusage.
    resource = None

from PIL import Image
from sqlalchemy import insert, select

from watchtracker.authorization import LOCAL_USER_ID
from watchtracker.config import Settings
from watchtracker.db import make_engine, make_session_factory, upgrade_database
from watchtracker.models import BookRecord, CatalogItem, MusicAlbum, ViewingEvent, WatchEntry
from watchtracker.services.entries import EntryService
from watchtracker.services.stats import calculate_stats

TODAY = date(2026, 8, 12)


def settings_for(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        access_mode="local",
        database_url_override=None,
        release_mode=True,
        data_dir=root / "data",
        config_dir=root / "config",
        log_dir=root / "logs",
        backups_dir=root / "backups",
        database_path=root / "watchtracker.sqlite3",
        cache_dir=root / "cache",
        env_path=root / ".env",
        timezone="UTC",
    )


def seed_collections(session_factory, count):
    """Deterministic multilingual and large-payload fixtures; never a real library."""
    image = io.BytesIO()
    Image.new("RGB", (80, 80), "#24cd09").save(image, "JPEG")
    artwork = "data:image/jpeg;base64," + base64.b64encode(image.getvalue()).decode()
    tracks = [
        {
            "id": str(uuid5(NAMESPACE_URL, f"pmt:track:{n}")),
            "position": n + 1,
            "title": f"Synthetic track {n}",
            "duration_ms": 120000,
            "disc": 1,
        }
        for n in range(180)
    ]
    for model, domain, creator in (
        (MusicAlbum, "music", "artist"),
        (BookRecord, "books", "author"),
    ):
        for start in range(0, count, 250):
            rows = []
            for index in range(start, min(count, start + 250)):
                row = {
                    "id": str(uuid5(NAMESPACE_URL, f"pmt:{domain}:{index}")),
                    "user_id": LOCAL_USER_ID,
                    "identity_key": f"benchmark-{index}",
                    "title": f"{('Synthetic', '合成作品', 'Œuvre fictive')[index % 3]} {index:05d}",
                    creator: f"Synthetic creator {index % 80}",
                    "year": 1980 + index % 40,
                    "status": "collected",
                    "genres": ["Rock"] if index % 3 else [],
                    "notes": "Synthetic note " * (1000 if index % 4 == 0 else 1),
                    "artwork_data": artwork if index % 5 else None,
                    "artwork_url": None,
                    "provider_id": None,
                }
                if domain == "music":
                    row["tracks"] = tracks if index % 10 == 0 else []
                else:
                    row.update(
                        description="Synthetic description " * 1000,
                        chapters=[f"Synthetic chapter {n}" for n in range(100)],
                    )
                rows.append(row)
            with session_factory() as session:
                session.execute(insert(model), rows)
                session.commit()


def percentile(values, fraction=0.95):
    return round(sorted(values)[min(len(values) - 1, int(len(values) * fraction))], 3)


def measure_collections(entry_count, browser_name=None):
    from fastapi.encoders import jsonable_encoder

    from watchtracker.books.api import entries
    from watchtracker.music.api import albums

    with tempfile.TemporaryDirectory(prefix="pmt-collections-benchmark-") as temporary:
        settings = settings_for(Path(temporary))
        upgrade_database(settings)
        engine = make_engine(settings.database_url)
        factory = make_session_factory(engine)
        try:
            seed_collections(factory, entry_count)
            result = {"entries_per_domain": entry_count, "synthetic_only": True}
            for domain, model, endpoint in (
                ("music", MusicAlbum, albums),
                ("books", BookRecord, entries),
            ):
                timings, full_timings = [], []
                for _ in range(20):
                    with factory() as session:
                        begin = time.perf_counter()
                        data = endpoint(
                            session,
                            q="",
                            status="",
                            favorite=False,
                            sort="recent",
                            direction="desc",
                            page=1,
                            page_size=24,
                            list_id=None,
                        )
                        encoded = json.dumps(jsonable_encoder(data)).encode()
                        timings.append((time.perf_counter() - begin) * 1000)
                    with factory() as session:
                        begin = time.perf_counter()
                        list(
                            session.scalars(
                                select(model)
                                .where(
                                    model.user_id == LOCAL_USER_ID, model.deleted_at.is_(None)
                                )
                                .order_by(model.created_at.desc(), model.id)
                                .limit(24)
                            )
                        )
                        full_timings.append((time.perf_counter() - begin) * 1000)
                result[domain] = {
                    "page_p95_ms": percentile(timings),
                    "page_median_ms": round(statistics.median(timings), 3),
                    "unprojected_query_p95_ms": percentile(full_timings),
                    "page_bytes": len(encoded),
                }
            if browser_name:
                result["browser"] = browser_measure(settings, browser_name)
            result["cache_and_scheduling"] = asyncio.run(
                cache_measure(Path(temporary) / "metrics-cache")
            )
            usage = resource.getrusage(resource.RUSAGE_SELF) if resource else None
            result["peak_process_rss_bytes"] = (
                usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024) if usage else None
            )
            return result
        finally:
            engine.dispose()


def browser_measure(settings, browser_name):
    from playwright.sync_api import sync_playwright

    from watchtracker.app import create_app
    from watchtracker.launcher import ServerController

    app = create_app(settings)
    server = ServerController(app, "127.0.0.1", 0)
    server.start()
    try:
        with sync_playwright() as playwright:
            browser = getattr(playwright, browser_name).launch()
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("https://**", lambda route: route.abort())
            base = f"http://127.0.0.1:{server.port}"
            page.request.put(base + "/api/settings/general", data={"onboarding_complete": True})
            page.goto(base + "/?mode=music&view=music_library")
            page.wait_for_selector(".music-card")
            timings, first, images = [], [], []
            # Browser-local monotonic milestones; no title, query or URL export.
            page.evaluate("""() => {
              window.benchmarkPaint = {cards: 0, first: 0, all: 0};
              const root = document.querySelector('#music-content');
              new MutationObserver(() => {
                if (root.getAttribute('aria-busy') === 'true') return;
                const marks = window.benchmarkPaint;
                if (marks.cards) return;
                marks.cards = performance.now();
                const visible = [...root.querySelectorAll('img')].filter(img => {const r = img.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0;});
                let done = 0;
                const ready = () => { if (!marks.first) marks.first = performance.now(); if (++done >= visible.length) marks.all = performance.now(); };
                if (!visible.length) marks.first = marks.all = marks.cards;
                visible.forEach(img => { if (img.complete) ready(); else {img.addEventListener('load', ready, {once:true}); img.addEventListener('error', ready, {once:true});} });
              }).observe(root, {attributes:true, childList:true, subtree:true});
            }""")
            for index in range(20):
                target = 2 if index % 2 == 0 else 1
                start = page.evaluate(
                    """target => {
                    window.scrollTo({top:0, behavior:'instant'});
                    window.benchmarkPaint = {cards:0,first:0,all:0};
                    const start = performance.now();
                    document.querySelector(`#music-pagination button[data-page="${target}"]`).click();
                    return start;
                }""",
                    target,
                )
                page.wait_for_function("() => window.benchmarkPaint.all > 0")
                marks = page.evaluate("window.benchmarkPaint")
                timings.append(marks["cards"] - start)
                first.append(marks["first"] - start)
                images.append(marks["all"] - start)
            diagnostics = page.evaluate("window.PMTMusic.diagnostics()")
            browser.close()
            if errors:
                raise RuntimeError("Browser scenario raised a JavaScript error")
            return {
                "engine": browser_name,
                "cycles": 20,
                "cards_p95_ms": percentile(timings),
                "first_visible_image_p95_ms": percentile(first),
                "all_visible_images_p95_ms": percentile(images),
                "diagnostics": diagnostics,
                "external_network_allowed": False,
            }
    finally:
        server.stop()


async def cache_measure(directory):
    import os

    from watchtracker.services.catalog_cache import CatalogLane, catalog_work
    from watchtracker.services.collection_artwork import FRESH_SECONDS, CollectionArtworkCache

    image = io.BytesIO()
    Image.new("RGB", (80, 80), "green").save(image, "JPEG")
    data = image.getvalue()
    cache = CollectionArtworkCache(directory)
    url = "https://covers.openlibrary.org/b/id/123-M.jpg"
    transfers = 0

    async def download(_url):
        nonlocal transfers
        transfers += 1
        await asyncio.sleep(0.01)
        return data

    cache.download = download
    result = {}
    for label in ("cold", "memory", "disk", "cached_fallback", "stale"):
        if label in {"disk", "stale"}:
            cache.memory.clear()
            cache.memory_bytes = 0
        if label == "stale":
            path = next(cache.directory.glob("*.jpg"))
            old = time.time() - FRESH_SECONDS - 10
            os.utime(path, (old, old))
        urls = (
            ["https://covers.openlibrary.org/b/id/404-M.jpg", url]
            if label == "cached_fallback"
            else [url]
        )
        before, count = time.perf_counter(), transfers
        assert await cache.get(urls) == data
        result[label] = {
            "response_ms": round((time.perf_counter() - before) * 1000, 3),
            "upstream_before_return": transfers - count,
        }
    await cache.close()
    lane, gate = CatalogLane(), asyncio.Event()

    async def bulk():
        with catalog_work(background=True):
            async with lane.acquire():
                gate.set()
                await asyncio.sleep(0.01)

    tasks = [asyncio.create_task(bulk()) for _ in range(20)]
    await gate.wait()
    before = time.perf_counter()
    async with lane.acquire():
        result["foreground_queue_during_20_bulk_ms"] = round(
            (time.perf_counter() - before) * 1000, 3
        )
    await asyncio.gather(*tasks)
    result["synthetic_provider_delay_ms"] = 10
    result["counts"] = dict(cache.metrics)
    return result


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
                user_id=LOCAL_USER_ID,
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
                    user_id=LOCAL_USER_ID,
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
    parser.add_argument("--sizes", type=int, nargs="+", default=[500, 5_000])
    parser.add_argument("--collections-only", action="store_true")
    parser.add_argument("--browser", choices=["chromium", "webkit"])
    parser.add_argument(
        "--output", type=Path, help="Compact synthetic metrics JSON; no trace by default"
    )
    parser.add_argument("--events-per-entry", type=int, default=4)
    parser.add_argument("--max-library-seconds", type=float, default=2.0)
    parser.add_argument("--max-insights-seconds", type=float, default=15.0)
    arguments = parser.parse_args()

    results = (
        []
        if arguments.collections_only
        else [measure(size, arguments.events_per_entry) for size in arguments.sizes]
    )
    collections = [measure_collections(size, arguments.browser) for size in arguments.sizes]
    report = {"screen": results, "collections": collections}
    if arguments.output:
        arguments.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    slow = [
        result
        for result in results
        if result["library_first_page_seconds"] > arguments.max_library_seconds
        or result["filtered_page_seconds"] > arguments.max_library_seconds
        or result["insights_seconds"] > arguments.max_insights_seconds
    ]
    if slow:
        raise SystemExit("Synthetic performance threshold exceeded")
    if any(
        row[domain]["page_p95_ms"] > 100 for row in collections for domain in ("music", "books")
    ):
        print(
            "Warning: collection page p95 exceeded the 100 ms reference budget", file=sys.stderr
        )


if __name__ == "__main__":
    main()
