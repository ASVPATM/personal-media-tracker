from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from watchtracker.metadata import ProviderUnavailable
from watchtracker.models import WatchEntry
from watchtracker.schemas import MetadataEnrichmentStatus, SearchResult
from watchtracker.services.entries import EntryConflict, EntryService
from watchtracker.taxonomy import normalize_title


def _now() -> datetime:
    return datetime.now(UTC)


def _needs_metadata(entry: WatchEntry) -> bool:
    catalog = entry.catalog_item
    stable_id = any(
        (
            catalog.tmdb_movie_id,
            catalog.tmdb_tv_id,
            catalog.anilist_id,
            catalog.mal_id,
        )
    )
    return not all(
        (
            stable_id,
            catalog.release_year,
            catalog.poster_url,
            catalog.overview,
            catalog.normalized_genres,
        )
    )


def choose_conservative_match(
    title: str,
    year: int | None,
    results: list[SearchResult],
    media_type: str | None = None,
) -> SearchResult | None:
    """Choose only when one candidate has bounded, non-contradictory evidence.

    Provider order and popularity are supporting signals, never permission to
    override a conflicting title, year, or media type.
    """
    normalized = normalize_title(title)
    compatible = [
        result
        for result in results
        if (media_type is None or result.media_type == media_type)
        and (year is None or result.year is None or abs(result.year - year) <= 1)
    ]
    if len(results) == 1:
        result = results[0]
        # A single provider answer is useful even when a localized or alternate
        # title is not textually identical. Known type/year contradictions remain
        # hard stops; the detail lookup must still succeed before attachment.
        return result if result in compatible else None

    exact = [
        result
        for result in compatible
        if normalized
        in {
            normalize_title(result.title),
            normalize_title(result.original_title or ""),
        }
    ]
    if year is not None:
        matching_year = [result for result in exact if result.year == year]
        if 1 <= len(matching_year) <= 4:
            return max(matching_year, key=lambda result: result.popularity or 0)
        unknown_year = [result for result in exact if result.year is None]
        if not matching_year and 1 <= len(exact) <= 4 and len(unknown_year) == len(exact):
            return max(exact, key=lambda result: result.popularity or 0)
    elif 1 <= len(exact) <= 4:
        return max(exact, key=lambda result: result.popularity or 0)

    # A small strong-candidate set is meaningful evidence, but never use
    # popularity alone: require title similarity and a compatible year first.
    if compatible:
        normalized_title = normalize_title(title)

        def similarity(result: SearchResult) -> float:
            return max(
                SequenceMatcher(None, normalized_title, normalize_title(candidate)).ratio()
                for candidate in (result.title, result.original_title or "")
            )

        candidates = [
            result
            for result in compatible
            if similarity(result) >= 0.82
            and (year is None or result.year is None or abs(result.year - year) <= 1)
        ]
        if 1 <= len(candidates) <= 4:
            ranked = sorted(
                enumerate(candidates),
                key=lambda item: (
                    similarity(item[1]),
                    item[1].popularity or 0,
                    -item[0],
                ),
                reverse=True,
            )
            best = ranked[0][1]
            if len(ranked) == 1:
                return best
            runner_up = ranked[1][1]
            title_margin = similarity(best) - similarity(runner_up)
            popularity_margin = (best.popularity or 0) - (runner_up.popularity or 0)
            # A first-ranked result may win a small candidate set when it has a
            # clearly better title, or equal title evidence plus a meaningful
            # provider popularity lead. Near-ties stay manual.
            if title_margin >= 0.08 or (title_margin >= -0.01 and popularity_margin >= 20):
                return best
    return None


def verified_provider_result(entry: WatchEntry) -> SearchResult | None:
    """Build a detail lookup only from a provider ID already stored on the entry."""
    catalog = entry.catalog_item
    candidates = (
        ("tmdb_movie", catalog.tmdb_movie_id, "movie"),
        ("tmdb_tv", catalog.tmdb_tv_id, "tv"),
        ("anilist", catalog.anilist_id, "anime"),
        ("mal", catalog.mal_id, "anime"),
    )
    for provider, provider_id, media_type in candidates:
        if provider_id:
            return SearchResult(
                provider=provider,
                provider_id=provider_id,
                title=catalog.canonical_title,
                original_title=catalog.original_title,
                year=catalog.release_year,
                media_type=media_type,
                provider_format=catalog.provider_format,
                poster_url=catalog.poster_url,
                overview=catalog.overview,
            )
    return None


class MetadataEnrichmentManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        metadata: Any,
        *,
        today_factory,
    ):
        self.session_factory = session_factory
        self.metadata = metadata
        self.today_factory = today_factory
        self._task: asyncio.Task | None = None
        self._state = MetadataEnrichmentStatus(status="idle")

    def _skip(self, reason: str, *, failed: bool = False) -> None:
        self._state.skip_reasons[reason] = self._state.skip_reasons.get(reason, 0) + 1
        if failed:
            self._state.failed += 1
        else:
            self._state.needs_confirmation += 1
            self._state.skipped += 1

    def status(self) -> MetadataEnrichmentStatus:
        return self._state.model_copy(deep=True)

    def start(self, limit: int) -> MetadataEnrichmentStatus:
        if self._task and not self._task.done():
            raise EntryConflict("Metadata enrichment is already running")
        self._state = MetadataEnrichmentStatus(
            status="running",
            message="Finding entries with missing metadata…",
            started_at=_now(),
        )
        self._task = asyncio.create_task(self._run(limit))
        return self.status()

    def start_verified_if_needed(self, limit: int = 2_000) -> bool:
        """Start silently only when an incomplete entry has a stable provider ID."""
        with self.session_factory() as session:
            entries = session.scalars(
                select(WatchEntry)
                .where(WatchEntry.deleted_at.is_(None))
                .options(selectinload(WatchEntry.catalog_item))
            )
            found = any(
                _needs_metadata(entry) and verified_provider_result(entry) is not None
                for entry in entries
            )
        if found:
            self.start(limit)
        return found

    async def _run(self, limit: int) -> None:
        try:
            unavailable_media_types: set[str] = set()
            with self.session_factory() as session:
                entries = list(
                    session.scalars(
                        select(WatchEntry)
                        .where(WatchEntry.deleted_at.is_(None))
                        .options(selectinload(WatchEntry.catalog_item))
                    )
                )
                targets = [
                    {
                        "entry_id": entry.id,
                        "title": entry.catalog_item.canonical_title,
                        "year": entry.catalog_item.release_year,
                        "media_type": entry.catalog_item.media_type,
                        "result": verified_provider_result(entry),
                    }
                    for entry in entries
                    if _needs_metadata(entry)
                ][:limit]
            self._state.total = len(targets)
            if not targets:
                self._state.status = "completed"
                self._state.message = "All active entries already have core metadata."
                self._state.finished_at = _now()
                return

            for target in targets:
                self._state.message = f"Checking {target['title']}"
                if target["result"] is None:
                    if target["media_type"] in unavailable_media_types:
                        self._skip("provider_outage")
                        self._state.processed += 1
                        await asyncio.sleep(0)
                        continue
                    try:
                        search = None
                        search = await self.metadata.search(
                            target["title"], target["media_type"]
                        )
                        for warning in search.warnings:
                            if warning not in self._state.warnings:
                                self._state.warnings.append(warning)
                        if search.warnings and not search.results:
                            # Avoid sending hundreds of doomed requests during a
                            # provider outage. A later run will try the service again.
                            unavailable_media_types.add(target["media_type"])
                        target["result"] = choose_conservative_match(
                            target["title"],
                            target["year"],
                            search.results,
                            target["media_type"],
                        )
                    except Exception:
                        target["result"] = None
                    if target["result"] is None:
                        if search is None:
                            reason = "provider_outage"
                        elif not search.results:
                            reason = "provider_outage" if search.warnings else "no_results"
                        else:
                            compatible = [
                                result
                                for result in search.results
                                if result.media_type == target["media_type"]
                                and (
                                    target["year"] is None
                                    or result.year is None
                                    or abs(result.year - target["year"]) <= 1
                                )
                            ]
                            reason = (
                                "conflicting_year_or_type" if not compatible else "ambiguous"
                            )
                        self._skip(reason)
                        self._state.processed += 1
                        await asyncio.sleep(0)
                        continue
                try:
                    detail = await self.metadata.detail(target["result"])
                    with self.session_factory() as session:
                        EntryService(session, today=self.today_factory()).apply_metadata(
                            target["entry_id"],
                            detail,
                            source="metadata_enrichment",
                        )
                    self._state.enriched += 1
                except ProviderUnavailable:
                    self._skip("provider_outage", failed=True)
                except EntryConflict:
                    self._skip("duplicate_identity", failed=True)
                except Exception:
                    # Provider and persistence internals are intentionally not exposed
                    # through the status endpoint or logs containing personal titles.
                    self._skip("detail_failure", failed=True)
                finally:
                    self._state.processed += 1
                    await asyncio.sleep(0)
            self._state.status = "completed"
            self._state.message = (
                f"Resolved or refreshed {self._state.enriched} entr"
                f"{'y' if self._state.enriched == 1 else 'ies'}; "
                f"{self._state.needs_confirmation} unresolved need confirmation; "
                f"{self._state.failed} failed."
            )
            self._state.finished_at = _now()
        except asyncio.CancelledError:
            self._state.status = "cancelled"
            self._state.message = "Metadata enrichment stopped with the server."
            self._state.finished_at = _now()
            raise
        except Exception:
            self._state.status = "failed"
            self._state.message = "Metadata enrichment could not continue."
            self._state.finished_at = _now()

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
