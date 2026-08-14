from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Text, and_, asc, cast, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from watchtracker.models import AuditEvent, CatalogItem, ViewingEvent, WatchEntry
from watchtracker.schemas import (
    CatalogData,
    CatalogOut,
    EntryMutationResponse,
    EntryOptions,
    EntryOut,
    EntryPatch,
    MetadataReviewOut,
    PaginatedEntries,
    RatingReviewOut,
    ViewingOut,
)
from watchtracker.taxonomy import (
    INFERENCE_VERSION,
    classify_media_type,
    effective_values,
    infer_taxonomy,
    normalize_title,
)


class EntryNotFound(LookupError):
    pass


class EntryConflict(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_list(values: list[str] | None) -> list[str]:
    return sorted(
        {value.strip() for value in values or [] if value and value.strip()}, key=str.casefold
    )


def _snapshot(entry: WatchEntry) -> dict[str, Any]:
    return {
        "status": entry.status,
        "personal_rating": entry.personal_rating,
        "view_count": entry.view_count,
        "watched_date": entry.watched_date.isoformat() if entry.watched_date else None,
        "deleted": entry.deleted_at is not None,
    }


def _audit(
    session: Session,
    entry: WatchEntry,
    action: str,
    source: str,
    before: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            action=action,
            entity_id=entry.id,
            source=source,
            before_data=before,
            after_data=_snapshot(entry),
        )
    )


def serialize_entry(entry: WatchEntry, *, include_events: bool = True) -> EntryOut:
    catalog = entry.catalog_item
    genres = effective_values(
        catalog.normalized_genres or [], entry.genre_additions or [], entry.genre_removals or []
    )
    subgenres = effective_values(
        catalog.inferred_subgenres or [],
        entry.subgenre_additions or [],
        entry.subgenre_removals or [],
    )
    return EntryOut(
        id=entry.id,
        catalog_item=CatalogOut.model_validate(catalog),
        status=entry.status,
        personal_rating=entry.personal_rating,
        notes=entry.notes,
        user_tags=entry.user_tags or [],
        started_date=entry.started_date,
        finished_date=entry.finished_date,
        watched_date=entry.watched_date,
        view_count=entry.view_count,
        rewatch_count=entry.rewatch_count,
        effective_genres=genres,
        effective_subgenres=subgenres,
        genre_additions=entry.genre_additions or [],
        genre_removals=entry.genre_removals or [],
        subgenre_additions=entry.subgenre_additions or [],
        subgenre_removals=entry.subgenre_removals or [],
        import_context=entry.import_context or {},
        viewing_events=(
            [ViewingOut.model_validate(event) for event in entry.viewing_events]
            if include_events
            else []
        ),
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        deleted_at=entry.deleted_at,
    )


class EntryService:
    def __init__(self, session: Session, *, today: date):
        self.session = session
        self.today = today

    def _loaded_entry(self, entry_id: str, *, include_deleted: bool = True) -> WatchEntry:
        statement = (
            select(WatchEntry)
            .where(WatchEntry.id == entry_id)
            .options(
                selectinload(WatchEntry.catalog_item), selectinload(WatchEntry.viewing_events)
            )
        )
        if not include_deleted:
            statement = statement.where(WatchEntry.deleted_at.is_(None))
        entry = self.session.scalar(statement)
        if not entry:
            raise EntryNotFound("Watch entry not found")
        return entry

    def find_catalog(self, data: CatalogData) -> CatalogItem | None:
        media_type = classify_media_type(
            data.media_type,
            provider_source=data.provider_source,
            anilist_id=data.anilist_id,
            mal_id=data.mal_id,
            provider_genres=data.provider_genres,
            keywords=data.keywords,
            country=data.country,
            language=data.language,
        )
        checks = []
        if data.provider_source and data.provider_id:
            checks.append(
                and_(
                    CatalogItem.provider_source == data.provider_source,
                    CatalogItem.provider_id == data.provider_id,
                )
            )
        for column_name in ("tmdb_movie_id", "tmdb_tv_id", "anilist_id", "mal_id"):
            value = getattr(data, column_name)
            if value:
                checks.append(getattr(CatalogItem, column_name) == value)
        if checks:
            found = self.session.scalar(select(CatalogItem).where(or_(*checks)).limit(1))
            if found:
                return found
        statement = select(CatalogItem).where(
            CatalogItem.normalized_title == normalize_title(data.canonical_title),
            CatalogItem.media_type == media_type,
        )
        if data.release_year is None:
            statement = statement.where(CatalogItem.release_year.is_(None))
        else:
            statement = statement.where(
                or_(
                    CatalogItem.release_year == data.release_year,
                    CatalogItem.release_year.is_(None),
                )
            )
        if checks:
            # Provider-backed incoming metadata may cautiously adopt one unresolved
            # local/imported title, but never another resolved provider record.
            statement = statement.where(
                CatalogItem.provider_source.is_(None),
                CatalogItem.provider_id.is_(None),
                CatalogItem.tmdb_movie_id.is_(None),
                CatalogItem.tmdb_tv_id.is_(None),
                CatalogItem.anilist_id.is_(None),
                CatalogItem.mal_id.is_(None),
            )
        candidates = list(self.session.scalars(statement.limit(2)))
        return candidates[0] if len(candidates) == 1 else None

    def _catalog_from_data(self, data: CatalogData) -> CatalogItem:
        media_type = classify_media_type(
            data.media_type,
            provider_source=data.provider_source,
            anilist_id=data.anilist_id,
            mal_id=data.mal_id,
            provider_genres=data.provider_genres,
            keywords=data.keywords,
            country=data.country,
            language=data.language,
        )
        taxonomy = infer_taxonomy(data.provider_genres, data.keywords, media_type=media_type)
        catalog = CatalogItem(
            canonical_title=data.canonical_title.strip(),
            original_title=data.original_title,
            normalized_title=normalize_title(data.canonical_title),
            release_year=data.release_year,
            release_date=data.release_date,
            media_type=media_type,
            provider_format=data.provider_format,
            provider_source=data.provider_source,
            provider_id=data.provider_id,
            tmdb_movie_id=data.tmdb_movie_id,
            tmdb_tv_id=data.tmdb_tv_id,
            anilist_id=data.anilist_id,
            mal_id=data.mal_id,
            poster_url=data.poster_url,
            overview=data.overview,
            provider_genres=_clean_list(data.provider_genres),
            normalized_genres=taxonomy.genres,
            inferred_subgenres=taxonomy.subgenres,
            keywords=_clean_list(data.keywords),
            country=data.country,
            language=data.language,
            runtime_minutes=data.runtime_minutes,
            episode_count=data.episode_count,
            public_score=data.public_score,
            taste_evidence=taxonomy.taste_evidence,
            metadata_source=data.provider_source or "manual",
            metadata_provenance=taxonomy.provenance,
            inference_version=INFERENCE_VERSION,
            metadata_fetched_at=_now() if data.provider_source else None,
            raw_provider_payload=data.raw_provider_payload,
        )
        self.session.add(catalog)
        self.session.flush()
        return catalog

    def _merge_catalog(self, catalog: CatalogItem, data: CatalogData) -> None:
        """Fill metadata gaps without erasing provider data or user overrides."""
        for field in (
            "original_title",
            "release_year",
            "release_date",
            "provider_format",
            "provider_source",
            "provider_id",
            "tmdb_movie_id",
            "tmdb_tv_id",
            "anilist_id",
            "mal_id",
            "poster_url",
            "overview",
            "country",
            "language",
            "runtime_minutes",
            "episode_count",
            "public_score",
        ):
            if getattr(catalog, field) in (None, "") and getattr(data, field) not in (None, ""):
                setattr(catalog, field, getattr(data, field))
        catalog.media_type = classify_media_type(
            data.media_type,
            provider_source=data.provider_source or catalog.provider_source,
            anilist_id=data.anilist_id or catalog.anilist_id,
            mal_id=data.mal_id or catalog.mal_id,
            provider_genres=[*(catalog.provider_genres or []), *data.provider_genres],
            keywords=[*(catalog.keywords or []), *data.keywords],
            country=data.country or catalog.country,
            language=data.language or catalog.language,
            existing_media_type=catalog.media_type,
        )
        if data.provider_genres or data.keywords:
            catalog.provider_genres = _clean_list(
                [*(catalog.provider_genres or []), *data.provider_genres]
            )
            catalog.keywords = _clean_list([*(catalog.keywords or []), *data.keywords])
            taxonomy = infer_taxonomy(
                catalog.provider_genres, catalog.keywords, media_type=catalog.media_type
            )
            catalog.normalized_genres = taxonomy.genres
            catalog.inferred_subgenres = taxonomy.subgenres
            catalog.taste_evidence = taxonomy.taste_evidence
            catalog.metadata_provenance = taxonomy.provenance
            catalog.inference_version = INFERENCE_VERSION
        catalog.updated_at = _now()

    def apply_metadata(
        self,
        entry_id: str,
        data: CatalogData,
        *,
        source: str = "ui",
        commit: bool = True,
    ) -> EntryOut:
        entry = self._loaded_entry(entry_id, include_deleted=False)
        catalog = entry.catalog_item
        matched = self.find_catalog(data)
        if matched and matched.id != catalog.id:
            raise EntryConflict("That provider title is already attached to another entry")
        before = _snapshot(entry)
        media_type = classify_media_type(
            data.media_type,
            provider_source=data.provider_source,
            anilist_id=data.anilist_id,
            mal_id=data.mal_id,
            provider_genres=data.provider_genres,
            keywords=data.keywords,
            country=data.country,
            language=data.language,
            existing_media_type=catalog.media_type,
        )
        taxonomy = infer_taxonomy(data.provider_genres, data.keywords, media_type=media_type)
        catalog.canonical_title = data.canonical_title.strip()
        catalog.original_title = data.original_title
        catalog.normalized_title = normalize_title(data.canonical_title)
        catalog.release_year = data.release_year
        catalog.release_date = data.release_date
        catalog.media_type = media_type
        catalog.provider_format = data.provider_format
        catalog.provider_source = data.provider_source
        catalog.provider_id = data.provider_id
        catalog.tmdb_movie_id = data.tmdb_movie_id
        catalog.tmdb_tv_id = data.tmdb_tv_id
        catalog.anilist_id = data.anilist_id
        catalog.mal_id = data.mal_id
        catalog.poster_url = data.poster_url
        catalog.overview = data.overview
        catalog.provider_genres = _clean_list(data.provider_genres)
        catalog.normalized_genres = taxonomy.genres
        catalog.inferred_subgenres = taxonomy.subgenres
        catalog.keywords = _clean_list(data.keywords)
        catalog.country = data.country
        catalog.language = data.language
        catalog.runtime_minutes = data.runtime_minutes
        catalog.episode_count = data.episode_count
        catalog.public_score = data.public_score
        catalog.taste_evidence = taxonomy.taste_evidence
        catalog.metadata_source = data.provider_source or "manual"
        catalog.metadata_provenance = taxonomy.provenance
        catalog.inference_version = INFERENCE_VERSION
        catalog.metadata_fetched_at = _now()
        catalog.raw_provider_payload = data.raw_provider_payload
        catalog.updated_at = _now()
        entry.updated_at = _now()
        _audit(self.session, entry, "metadata_enrich", source, before)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return serialize_entry(entry)

    def create_or_handle_duplicate(
        self,
        data: CatalogData,
        options: EntryOptions,
        *,
        source: str = "ui",
        if_existing: str = "return_existing",
        default_watched_date: bool = True,
        commit: bool = True,
    ) -> EntryMutationResponse:
        catalog = self.find_catalog(data)
        if catalog:
            self._merge_catalog(catalog, data)
            existing = self.session.scalar(
                select(WatchEntry)
                .where(WatchEntry.catalog_item_id == catalog.id)
                .options(
                    selectinload(WatchEntry.catalog_item),
                    selectinload(WatchEntry.viewing_events),
                )
            )
            if existing:
                if if_existing == "rewatch":
                    self._add_viewing(
                        existing, options.watched_date or self.today, source=source
                    )
                    action = "rewatched"
                elif if_existing == "mark_watched" and existing.view_count == 0:
                    self._add_viewing(
                        existing, options.watched_date or self.today, source=source
                    )
                    existing.status = "watched"
                    action = "marked_watched"
                else:
                    action = "existing"
                if existing.deleted_at and if_existing != "return_existing":
                    existing.deleted_at = None
                if commit:
                    self.session.commit()
                else:
                    self.session.flush()
                return EntryMutationResponse(
                    entry=serialize_entry(existing),
                    created=False,
                    duplicate=True,
                    action=action,
                )
        else:
            catalog = self._catalog_from_data(data)

        view_count = options.view_count
        if view_count is None:
            view_count = 1 if options.status == "watched" else 0
        watched_on = options.watched_date
        if (
            options.status == "watched"
            and view_count > 0
            and watched_on is None
            and default_watched_date
        ):
            watched_on = self.today
        entry = WatchEntry(
            catalog_item=catalog,
            status=options.status,
            personal_rating=options.personal_rating,
            notes=options.notes or None,
            user_tags=_clean_list(options.user_tags),
            started_date=options.started_date,
            finished_date=options.finished_date,
            watched_date=watched_on,
            view_count=view_count,
        )
        self.session.add(entry)
        self.session.flush()
        # A single dated event is honest even when an aggregate import reports more total views.
        if view_count > 0 and watched_on:
            self.session.add(ViewingEvent(entry=entry, viewed_on=watched_on, source=source))
        _audit(self.session, entry, "create", source)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return EntryMutationResponse(
            entry=serialize_entry(entry), created=True, action="created"
        )

    def get(self, entry_id: str) -> EntryOut:
        return serialize_entry(self._loaded_entry(entry_id))

    def metadata_review(self, *, after_entry_id: str | None = None) -> MetadataReviewOut:
        missing_identity = and_(
            CatalogItem.tmdb_movie_id.is_(None),
            CatalogItem.tmdb_tv_id.is_(None),
            CatalogItem.anilist_id.is_(None),
            CatalogItem.mal_id.is_(None),
        )
        filters = (WatchEntry.deleted_at.is_(None), missing_identity)
        total = (
            self.session.scalar(
                select(func.count()).select_from(WatchEntry).join(CatalogItem).where(*filters)
            )
            or 0
        )

        statement = select(WatchEntry).join(CatalogItem).where(*filters)
        if after_entry_id:
            current = self._loaded_entry(after_entry_id)
            cursor_title = current.catalog_item.normalized_title
            statement = statement.where(
                or_(
                    CatalogItem.normalized_title > cursor_title,
                    and_(
                        CatalogItem.normalized_title == cursor_title,
                        WatchEntry.id > current.id,
                    ),
                )
            )
        entry = self.session.scalar(
            statement.order_by(CatalogItem.normalized_title, WatchEntry.id)
            .limit(1)
            .options(selectinload(WatchEntry.catalog_item))
        )
        return MetadataReviewOut(
            total=total,
            entry=serialize_entry(entry, include_events=False) if entry else None,
        )

    def rating_review(self, *, after_entry_id: str | None = None) -> RatingReviewOut:
        filters = (
            WatchEntry.deleted_at.is_(None),
            WatchEntry.personal_rating.is_not(None),
        )
        total = (
            self.session.scalar(select(func.count()).select_from(WatchEntry).where(*filters))
            or 0
        )
        statement = select(WatchEntry).join(CatalogItem).where(*filters)
        if after_entry_id:
            current = self._loaded_entry(after_entry_id)
            cursor_title = current.catalog_item.normalized_title
            statement = statement.where(
                or_(
                    CatalogItem.normalized_title > cursor_title,
                    and_(
                        CatalogItem.normalized_title == cursor_title,
                        WatchEntry.id > current.id,
                    ),
                )
            )
        entry = self.session.scalar(
            statement.order_by(CatalogItem.normalized_title, WatchEntry.id)
            .limit(1)
            .options(selectinload(WatchEntry.catalog_item))
        )
        return RatingReviewOut(
            total=total,
            entry=serialize_entry(entry, include_events=False) if entry else None,
        )

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 24,
        sort: str = "recently_watched",
        direction: str = "desc",
        media_type: str | None = None,
        status: str | None = None,
        genre: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        rating_min: float | None = None,
        rating_max: float | None = None,
        rated: str = "all",
        q: str | None = None,
        include_deleted: bool = False,
    ) -> PaginatedEntries:
        filters = []
        if not include_deleted:
            filters.append(WatchEntry.deleted_at.is_(None))
        if media_type:
            filters.append(CatalogItem.media_type == media_type)
        if status == "active":
            filters.append(WatchEntry.status.in_(("watching", "rewatching")))
        elif status:
            filters.append(WatchEntry.status == status)
        if year_min is not None:
            filters.append(CatalogItem.release_year >= year_min)
        if year_max is not None:
            filters.append(CatalogItem.release_year <= year_max)
        if rating_min is not None:
            filters.append(WatchEntry.personal_rating >= rating_min)
        if rating_max is not None:
            filters.append(WatchEntry.personal_rating <= rating_max)
        if rated == "rated":
            filters.append(WatchEntry.personal_rating.is_not(None))
        elif rated == "unrated":
            filters.append(WatchEntry.personal_rating.is_(None))
        if q:
            filters.append(func.lower(CatalogItem.canonical_title).contains(q.strip().lower()))
        if genre:
            needle = genre.strip().lower()
            derived_genres = func.lower(cast(CatalogItem.normalized_genres, Text)).contains(
                needle
            )
            derived_subgenres = func.lower(cast(CatalogItem.inferred_subgenres, Text)).contains(
                needle
            )
            removed_genres = func.lower(cast(WatchEntry.genre_removals, Text)).contains(needle)
            removed_subgenres = func.lower(cast(WatchEntry.subgenre_removals, Text)).contains(
                needle
            )
            filters.append(
                or_(
                    and_(derived_genres, ~removed_genres),
                    and_(derived_subgenres, ~removed_subgenres),
                    func.lower(cast(WatchEntry.genre_additions, Text)).contains(needle),
                    func.lower(cast(WatchEntry.subgenre_additions, Text)).contains(needle),
                )
            )

        base = select(WatchEntry).join(CatalogItem).where(*filters)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        columns = {
            "recently_watched": func.coalesce(WatchEntry.watched_date, date(1, 1, 1)),
            "recently_added": WatchEntry.created_at,
            "personal_rating": func.coalesce(WatchEntry.personal_rating, -1),
            "title": func.lower(CatalogItem.canonical_title),
            "release_year": func.coalesce(CatalogItem.release_year, 0),
            "media_type": CatalogItem.media_type,
        }
        order_column = columns[sort]
        order = asc(order_column) if direction == "asc" else desc(order_column)
        statement = (
            base.order_by(order, asc(func.lower(CatalogItem.canonical_title)), WatchEntry.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(
                selectinload(WatchEntry.catalog_item), selectinload(WatchEntry.viewing_events)
            )
        )
        items = [
            serialize_entry(entry, include_events=False)
            for entry in self.session.scalars(statement)
        ]
        return PaginatedEntries(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    def patch(self, entry_id: str, patch: EntryPatch, *, source: str = "ui") -> EntryOut:
        entry = self._loaded_entry(entry_id, include_deleted=False)
        before = _snapshot(entry)
        fields = patch.model_fields_set
        if "status" in fields and patch.status:
            if (
                patch.status == "watched"
                and entry.view_count == 0
                and "view_count" not in fields
            ):
                self._add_viewing(
                    entry, patch.watched_date or self.today, source=source, audit=False
                )
            entry.status = patch.status
        if "view_count" in fields and patch.view_count is not None:
            dated_events = sum(1 for event in entry.viewing_events if event.viewed_on)
            if patch.view_count < len(entry.viewing_events) or patch.view_count < dated_events:
                raise EntryConflict(
                    "view_count cannot be lower than the stored viewing history"
                )
            if entry.status == "watched" and patch.view_count == 0:
                raise EntryConflict("watched entries must have at least one completed viewing")
            entry.view_count = patch.view_count
        for field in (
            "personal_rating",
            "notes",
            "started_date",
            "finished_date",
            "watched_date",
        ):
            if field in fields:
                setattr(entry, field, getattr(patch, field))
        for field in (
            "user_tags",
            "genre_additions",
            "genre_removals",
            "subgenre_additions",
            "subgenre_removals",
        ):
            if field in fields:
                setattr(entry, field, _clean_list(getattr(patch, field)))
        entry.updated_at = _now()
        _audit(self.session, entry, "edit", source, before)
        self.session.commit()
        return serialize_entry(entry)

    def _add_viewing(
        self,
        entry: WatchEntry,
        viewed_on: date | None,
        *,
        source: str,
        source_key: str | None = None,
        audit: bool = True,
    ) -> ViewingEvent:
        before = _snapshot(entry)
        event = ViewingEvent(
            entry=entry, viewed_on=viewed_on, source=source, source_key=source_key
        )
        self.session.add(event)
        entry.view_count += 1
        if viewed_on and (entry.watched_date is None or viewed_on >= entry.watched_date):
            entry.watched_date = viewed_on
        entry.updated_at = _now()
        if audit:
            _audit(
                self.session,
                entry,
                "rewatch" if entry.view_count > 1 else "first_watch",
                source,
                before,
            )
        self.session.flush()
        return event

    def add_viewing(
        self, entry_id: str, viewed_on: date | None, *, source: str = "ui"
    ) -> EntryOut:
        entry = self._loaded_entry(entry_id, include_deleted=False)
        self._add_viewing(
            entry, viewed_on if viewed_on is not None else self.today, source=source
        )
        if entry.status in {"plan_to_watch", "watching"}:
            entry.status = "watched"
        self.session.commit()
        return serialize_entry(entry)

    def delete_viewing(self, entry_id: str, event_id: str, *, source: str = "ui") -> EntryOut:
        entry = self._loaded_entry(entry_id, include_deleted=False)
        event = next((item for item in entry.viewing_events if item.id == event_id), None)
        if not event:
            raise EntryNotFound("Viewing event not found for this entry")
        if entry.view_count <= 0:
            raise EntryConflict("view_count is already zero")
        before = _snapshot(entry)
        self.session.delete(event)
        entry.viewing_events.remove(event)
        entry.view_count -= 1
        dated = [item.viewed_on for item in entry.viewing_events if item.viewed_on]
        entry.watched_date = max(dated) if dated else None
        if entry.view_count == 0 and entry.status == "watched":
            entry.status = "plan_to_watch"
        entry.updated_at = _now()
        _audit(self.session, entry, "delete_viewing", source, before)
        self.session.commit()
        return serialize_entry(entry)

    def soft_delete(self, entry_id: str, *, source: str = "ui") -> None:
        entry = self._loaded_entry(entry_id, include_deleted=False)
        before = _snapshot(entry)
        entry.deleted_at = _now()
        entry.updated_at = _now()
        _audit(self.session, entry, "soft_delete", source, before)
        self.session.commit()

    def restore(self, entry_id: str, *, source: str = "ui") -> EntryOut:
        entry = self._loaded_entry(entry_id)
        if entry.deleted_at is None:
            raise EntryConflict("Entry is not deleted")
        before = _snapshot(entry)
        entry.deleted_at = None
        entry.updated_at = _now()
        _audit(self.session, entry, "restore", source, before)
        self.session.commit()
        return serialize_entry(entry)


def load_active_entries(session: Session) -> list[WatchEntry]:
    return list(
        session.scalars(
            select(WatchEntry)
            .where(WatchEntry.deleted_at.is_(None))
            .options(
                selectinload(WatchEntry.catalog_item), selectinload(WatchEntry.viewing_events)
            )
        )
    )


def refresh_catalog_taxonomy(session: Session) -> int:
    """Refresh versioned taxonomy and strongly evidenced media classifications."""
    changed = 0
    for catalog in session.scalars(select(CatalogItem)):
        item_changed = False
        media_type = classify_media_type(
            catalog.media_type,
            provider_source=catalog.provider_source,
            anilist_id=catalog.anilist_id,
            mal_id=catalog.mal_id,
            provider_genres=catalog.provider_genres or [],
            keywords=catalog.keywords or [],
            country=catalog.country,
            language=catalog.language,
        )
        if media_type != catalog.media_type:
            catalog.media_type = media_type
            item_changed = True
        if catalog.inference_version != INFERENCE_VERSION:
            taxonomy = infer_taxonomy(
                catalog.provider_genres or [],
                catalog.keywords or [],
                media_type=media_type,
            )
            catalog.normalized_genres = taxonomy.genres
            catalog.inferred_subgenres = taxonomy.subgenres
            catalog.taste_evidence = taxonomy.taste_evidence
            catalog.metadata_provenance = taxonomy.provenance
            catalog.inference_version = INFERENCE_VERSION
            catalog.normalized_title = normalize_title(catalog.canonical_title)
            item_changed = True
        if item_changed:
            changed += 1
    if changed:
        session.commit()
    return changed
