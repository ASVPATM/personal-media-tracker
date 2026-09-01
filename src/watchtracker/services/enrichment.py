from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from watchtracker.catalog_visibility import PUBLIC_METADATA_PROVIDERS
from watchtracker.metadata import ProviderUnavailable
from watchtracker.models import CatalogItem, WatchEntry
from watchtracker.schemas import MetadataEnrichmentStatus, ProviderReference, SearchResult
from watchtracker.services.entries import EntryConflict, EntryService
from watchtracker.taxonomy import normalize_title


def _now() -> datetime:
    return datetime.now(UTC)


def _needs_metadata(entry: WatchEntry) -> bool:
    catalog = entry.catalog_item
    provider_identity_needs_verification = bool(
        catalog.provider_source in PUBLIC_METADATA_PROVIDERS
        and catalog.provider_id
        and not (catalog.metadata_provenance or {}).get("provider_identity_verified")
    )
    stable_id = any(
        (
            catalog.tmdb_movie_id,
            catalog.tmdb_tv_id,
            catalog.anilist_id,
            catalog.mal_id,
        )
    ) or bool(catalog.external_identities)
    return provider_identity_needs_verification or not all(
        (
            stable_id,
            catalog.release_year,
            catalog.poster_url,
            catalog.overview,
            catalog.normalized_genres,
        )
    )


def _has_schedule_identity(entry: WatchEntry) -> bool:
    catalog = entry.catalog_item
    namespaces = {identity.namespace for identity in catalog.external_identities}
    return bool(
        catalog.tmdb_tv_id
        or (catalog.provider_source == "tvmaze" and catalog.provider_id)
        or namespaces.intersection({"tvmaze", "tmdb_tv"})
    )


def _can_resolve_schedule_identity(entry: WatchEntry, metadata: Any) -> bool:
    """Return whether a configured provider can add a schedule-capable ID.

    This deliberately follows provider capabilities instead of inspecting a
    concrete client such as TMDb. TV entries can use the keyless TVmaze adapter;
    anime entries become eligible when a schedule provider that searches anime
    (currently optional TMDb) is active.
    """
    media_type = entry.catalog_item.media_type
    if media_type not in {"tv", "anime"} or _has_schedule_identity(entry):
        return False
    try:
        providers = metadata.provider_catalog()
    except (AttributeError, TypeError):
        return False
    return any(
        {"search", "schedule"}.issubset(set(provider.get("capabilities", ())))
        and media_type in provider.get("media_types", ())
        for provider in providers
    )


def _needs_enrichment(entry: WatchEntry, metadata: Any) -> bool:
    return _needs_metadata(entry) or _can_resolve_schedule_identity(entry, metadata)


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
    if len(compatible) == 1:
        result = compatible[0]
        # A single provider answer is useful even when a localized or alternate
        # title is not textually identical. Known type/year contradictions remain
        # hard stops; the detail lookup must still succeed before attachment.
        return result if result in compatible else None

    def titles_for(result: SearchResult) -> set[str]:
        return {
            normalize_title(candidate)
            for candidate in (
                result.title,
                result.original_title or "",
                *result.aliases,
            )
            if candidate
        }

    exact = [result for result in compatible if normalized in titles_for(result)]
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
            scores = []
            for candidate in titles_for(result):
                ratio = SequenceMatcher(None, normalized_title, candidate).ratio()
                if len(normalized_title) >= 5 and (
                    candidate.startswith(f"{normalized_title} ")
                    or normalized_title.startswith(f"{candidate} ")
                ):
                    ratio = max(ratio, 0.9)
                scores.append(ratio)
            return max(scores, default=0)

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


def match_evidence_reason(title: str, result: SearchResult) -> str:
    """Return a privacy-safe explanation bucket for enrichment reporting."""
    normalized = normalize_title(title)
    primary = {
        normalize_title(result.title),
        normalize_title(result.original_title or ""),
    }
    aliases = {normalize_title(alias) for alias in result.aliases}
    if normalized in primary:
        return "exact_title"
    if normalized in aliases:
        return "exact_alias"
    if any(
        len(normalized) >= 5
        and (candidate.startswith(f"{normalized} ") or normalized.startswith(f"{candidate} "))
        for candidate in primary | aliases
        if candidate
    ):
        return "strong_title_prefix"
    return "single_compatible_candidate"


def verified_provider_result(entry: WatchEntry) -> SearchResult | None:
    """Build a detail lookup only from a provider ID already stored on the entry."""
    catalog = entry.catalog_item
    identities = {
        identity.namespace: identity.external_id for identity in catalog.external_identities
    }
    identities.update(
        {
            namespace: value
            for namespace, value in {
                "tmdb_movie": catalog.tmdb_movie_id,
                "tmdb_tv": catalog.tmdb_tv_id,
                "anilist": catalog.anilist_id,
                "mal": catalog.mal_id,
            }.items()
            if value
        }
    )
    if catalog.provider_source and catalog.provider_id:
        identities[catalog.provider_source] = catalog.provider_id
    supported = {
        "tmdb_movie",
        "tmdb_tv",
        "tvmaze",
        "anilist",
        "mal",
        "kitsu",
        "wikidata",
    }
    ordered = [
        provider
        for provider in (
            catalog.provider_source,
            "tvmaze",
            "tmdb_tv",
            "tmdb_movie",
            "mal",
            "kitsu",
            "anilist",
            "wikidata",
        )
        if provider in supported and provider in identities
    ]
    ordered = list(dict.fromkeys(ordered))
    if not ordered:
        return None
    primary = ordered[0]
    return SearchResult(
        provider=primary,
        provider_id=identities[primary],
        title=catalog.canonical_title,
        original_title=catalog.original_title,
        year=catalog.release_year,
        media_type=catalog.media_type,
        provider_format=catalog.provider_format,
        poster_url=catalog.poster_url,
        overview=catalog.overview,
        external_ids=identities,
        corroborating_results=[
            ProviderReference(provider=provider, provider_id=identities[provider])
            for provider in ordered[1:]
        ],
    )


def corroborate_provider_result(stored: SearchResult, discovered: SearchResult) -> SearchResult:
    """Keep the verified identity primary while adding compatible refresh sources."""
    primary = (stored.provider, stored.provider_id)
    references = [
        *stored.corroborating_results,
        ProviderReference(
            provider=discovered.provider,
            provider_id=discovered.provider_id,
        ),
        *discovered.corroborating_results,
    ]
    unique = []
    seen = {primary}
    for reference in references:
        key = (reference.provider, reference.provider_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return stored.model_copy(
        update={
            "poster_url": stored.poster_url or discovered.poster_url,
            "overview": stored.overview or discovered.overview,
            "external_ids": {
                **stored.external_ids,
                **discovered.external_ids,
            },
            "corroborating_results": unique[:5],
        }
    )


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
        self._active_user_id: str | None = None

    def _skip(self, reason: str, *, failed: bool = False) -> None:
        self._state.skip_reasons[reason] = self._state.skip_reasons.get(reason, 0) + 1
        if failed:
            self._state.failed += 1
        else:
            self._state.needs_confirmation += 1
            self._state.skipped += 1

    def status(self, user_id: str | None = None) -> MetadataEnrichmentStatus:
        if user_id is not None and self._active_user_id != user_id:
            if self._active_user_id is None and self._state.status == "running":
                # Installation-wide startup maintenance must not reveal another
                # tenant's title or aggregate library counts through shared state.
                return MetadataEnrichmentStatus(
                    status="running",
                    message="Server metadata maintenance is running.",
                    started_at=self._state.started_at,
                )
            return MetadataEnrichmentStatus(status="idle")
        return self._state.model_copy(deep=True)

    def start(
        self, limit: int, *, user_id: str | None = None, metadata: Any | None = None
    ) -> MetadataEnrichmentStatus:
        if self._task and not self._task.done():
            raise EntryConflict("Metadata enrichment is already running")
        self._state = MetadataEnrichmentStatus(
            status="running",
            message="Finding entries with missing metadata…",
            started_at=_now(),
        )
        self._active_user_id = user_id
        self._task = asyncio.create_task(
            self._run(limit, user_id=user_id, metadata=metadata or self.metadata)
        )
        return self.status(user_id)

    def start_verified_if_needed(self, limit: int = 2_000) -> bool:
        """Start silently when a refreshable entry has a stable provider ID."""
        with self.session_factory() as session:
            entries = list(
                session.scalars(
                    select(WatchEntry)
                    .where(WatchEntry.deleted_at.is_(None))
                    .options(
                        selectinload(WatchEntry.catalog_item).selectinload(
                            CatalogItem.external_identities
                        )
                    )
                )
            )
            found = any(
                _needs_enrichment(entry, self.metadata)
                and verified_provider_result(entry) is not None
                for entry in entries
            )
        if found:
            owners = {entry.user_id for entry in entries}
            self.start(limit, user_id=next(iter(owners)) if len(owners) == 1 else None)
        return found

    async def _run(self, limit: int, *, user_id: str | None, metadata: Any) -> None:
        try:
            unavailable_media_types: set[str] = set()
            with self.session_factory() as session:
                statement = (
                    select(WatchEntry)
                    .where(WatchEntry.deleted_at.is_(None))
                    .options(
                        selectinload(WatchEntry.catalog_item).selectinload(
                            CatalogItem.external_identities
                        )
                    )
                )
                if user_id is not None:
                    statement = statement.where(WatchEntry.user_id == user_id)
                entries = list(session.scalars(statement))
                targets = [
                    {
                        "entry_id": entry.id,
                        "user_id": entry.user_id,
                        "title": entry.catalog_item.canonical_title,
                        "year": entry.catalog_item.release_year,
                        "media_type": entry.catalog_item.media_type,
                        "result": verified_provider_result(entry),
                        "match_reason": "stable_provider_id",
                    }
                    for entry in entries
                    if _needs_enrichment(entry, metadata)
                ][:limit]
            self._state.total = len(targets)
            if not targets:
                self._state.status = "completed"
                self._state.message = (
                    "All active entries already have core metadata and available "
                    "series identities."
                )
                self._state.finished_at = _now()
                return

            for target in targets:
                self._state.message = f"Checking {target['title']}"
                if target["result"] is not None:
                    try:
                        search = await metadata.search(target["title"], target["media_type"])
                        for warning in search.warnings:
                            if warning not in self._state.warnings:
                                self._state.warnings.append(warning)
                        discovered = choose_conservative_match(
                            target["title"],
                            target["year"],
                            search.results,
                            target["media_type"],
                        )
                        if discovered is not None:
                            target["result"] = corroborate_provider_result(
                                target["result"], discovered
                            )
                    except Exception:
                        # The already verified provider remains usable when an
                        # optional corroborating source is unavailable.
                        pass
                if target["result"] is None:
                    if target["media_type"] in unavailable_media_types:
                        self._skip("provider_outage")
                        self._state.processed += 1
                        await asyncio.sleep(0)
                        continue
                    try:
                        search = None
                        search = await metadata.search(target["title"], target["media_type"])
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
                        if target["result"] is not None:
                            target["match_reason"] = match_evidence_reason(
                                target["title"], target["result"]
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
                    detail = await metadata.detail(target["result"])
                    with self.session_factory() as session:
                        EntryService(
                            session,
                            today=self.today_factory(),
                            trusted_user_id=target["user_id"],
                        ).apply_metadata(
                            target["entry_id"],
                            detail,
                            source="metadata_enrichment",
                            trusted_metadata=True,
                        )
                    self._state.enriched += 1
                    reason = target["match_reason"]
                    self._state.match_reasons[reason] = (
                        self._state.match_reasons.get(reason, 0) + 1
                    )
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
