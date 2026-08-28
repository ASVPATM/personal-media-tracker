from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from watchtracker import __version__
from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import (
    CatalogItem,
    EpisodeRecord,
    EpisodeViewing,
    ExternalIdentity,
    MediaList,
    MediaListItem,
    MediaListMembership,
    PlatformSyncImportBatch,
    PlatformSyncImportRecord,
    ProviderProgressClaim,
    RatingAssessment,
    RatingComparison,
    SeasonRecord,
    SeriesTrackingSubscription,
    ViewingCorrection,
    ViewingCycle,
    ViewingEvent,
    WatchEntry,
    new_id,
    utcnow,
)
from watchtracker.taxonomy import normalize_title

CONTRACT_NAME = "pmt.platform-sync"
CONTRACT_VERSION = 2
KNOWN_RECORD_TYPES = frozenset(
    {
        "catalog",
        "external_identity",
        "season",
        "episode",
        "entry",
        "viewing_cycle",
        "viewing",
        "episode_viewing",
        "provider_progress_claim",
        "viewing_correction",
        "rating_assessment",
        "rating_comparison",
        "series_preference",
        "list",
        "list_item",
    }
)
EXCLUDED_DOMAINS = [
    "credentials",
    "oauth_grants",
    "server_sessions",
    "provider_raw_payloads",
    "provider_response_cache",
    "artwork_cache",
    "release_schedule_cache",
    "integration_runtime_state",
    "notification_delivery_state",
    "cloudkit_system_fields",
    "private_developer_tools",
]


class PlatformSyncRecord(BaseModel):
    """One individually addressable logical record.

    The type stays open so a future client can skip unknown records with a visible
    import-ledger result instead of rejecting an otherwise readable snapshot.
    """

    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=60)
    record_id: str = Field(min_length=1, max_length=200)
    created_at: datetime
    modified_at: datetime
    deleted_at: datetime | None = None
    origin_device_id: str
    origin_event_id: str
    field_versions: dict[str, int] = Field(default_factory=dict)
    relationships: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class PlatformSyncSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str = "pmt-desktop-web"
    product_version: str
    device_id: str


class PlatformSyncSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["pmt.platform-sync"] = "pmt.platform-sync"
    version: Literal[2] = 2
    generated_at: datetime
    source: PlatformSyncSource
    records: list[PlatformSyncRecord]
    excluded_domains: list[str] = Field(default_factory=lambda: list(EXCLUDED_DOMAINS))

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class PlatformSyncImportReport(BaseModel):
    batch_id: str
    duplicate_snapshot: bool = False
    counts: dict[str, int]
    warnings: list[str] = Field(default_factory=list)


def _timestamp(value: datetime | None, fallback: datetime | None = None) -> datetime:
    result = value or fallback or datetime.now(UTC)
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _date_value(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _datetime_value(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return _timestamp(value)
    return _timestamp(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _record(
    record_type: str,
    record_id: str,
    *,
    created_at: datetime,
    modified_at: datetime,
    device_id: str,
    deleted_at: datetime | None = None,
    origin_device_id: str | None = None,
    origin_event_id: str | None = None,
    field_versions: dict[str, Any] | None = None,
    version: int = 1,
    relationships: dict[str, str | None] | None = None,
    payload: dict[str, Any] | None = None,
) -> PlatformSyncRecord:
    return PlatformSyncRecord(
        record_type=record_type,
        record_id=record_id,
        created_at=_timestamp(created_at),
        modified_at=_timestamp(modified_at),
        deleted_at=_timestamp(deleted_at) if deleted_at else None,
        origin_device_id=origin_device_id or device_id,
        origin_event_id=origin_event_id or record_id,
        field_versions={
            str(key): int(value) for key, value in (field_versions or {"*": version}).items()
        },
        relationships={
            key: value for key, value in (relationships or {}).items() if value is not None
        },
        payload=payload or {},
    )


def build_platform_sync_snapshot(
    session: Session,
    principal: Principal | None = None,
    *,
    device_id: str | None = None,
) -> PlatformSyncSnapshot:
    """Build deterministic v2 records without credentials or raw provider payloads."""

    generated_at = datetime.now(UTC)
    user_id = current_user_id(session, principal)
    device = device_id or f"desktop:{user_id}"
    records: list[PlatformSyncRecord] = []
    entries = list(session.scalars(select(WatchEntry).where(WatchEntry.user_id == user_id)))
    catalog_ids = {entry.catalog_item_id for entry in entries}

    for catalog in session.scalars(
        select(CatalogItem).where(CatalogItem.id.in_(catalog_ids)).order_by(CatalogItem.id)
    ):
        records.append(
            _record(
                "catalog",
                catalog.id,
                created_at=catalog.created_at,
                modified_at=catalog.updated_at,
                device_id=device,
                payload={
                    "canonical_title": catalog.canonical_title,
                    "original_title": catalog.original_title,
                    "release_year": catalog.release_year,
                    "release_date": catalog.release_date,
                    "media_type": catalog.media_type,
                    "provider_format": catalog.provider_format,
                    "provider_source": catalog.provider_source,
                    "provider_id": catalog.provider_id,
                    "poster_url": catalog.poster_url,
                    "overview": catalog.overview,
                    "provider_genres": catalog.provider_genres or [],
                    "normalized_genres": catalog.normalized_genres or [],
                    "inferred_subgenres": catalog.inferred_subgenres or [],
                    "country": catalog.country,
                    "language": catalog.language,
                    "runtime_minutes": catalog.runtime_minutes,
                    "episode_count": catalog.episode_count,
                    "released_episode_count": catalog.released_episode_count,
                },
            )
        )
    for identity in session.scalars(
        select(ExternalIdentity)
        .where(ExternalIdentity.catalog_item_id.in_(catalog_ids))
        .order_by(ExternalIdentity.id)
    ):
        records.append(
            _record(
                "external_identity",
                identity.id,
                created_at=identity.created_at,
                modified_at=identity.updated_at,
                device_id=device,
                relationships={"catalog_id": identity.catalog_item_id},
                payload={
                    "namespace": identity.namespace,
                    "external_id": identity.external_id,
                    "provenance": identity.provenance,
                    "confidence": identity.confidence,
                    "verified_at": identity.verified_at,
                },
            )
        )
    seasons = list(
        session.scalars(
            select(SeasonRecord)
            .where(SeasonRecord.catalog_item_id.in_(catalog_ids))
            .order_by(SeasonRecord.id)
        )
    )
    season_ids = {season.id for season in seasons}
    for season in seasons:
        records.append(
            _record(
                "season",
                season.id,
                created_at=season.fetched_at,
                modified_at=season.provider_updated_at or season.fetched_at,
                deleted_at=season.removed_at,
                device_id=device,
                relationships={"catalog_id": season.catalog_item_id},
                payload={
                    "provider_source": season.provider_source,
                    "provider_series_id": season.provider_series_id,
                    "provider_season_id": season.provider_season_id,
                    "season_number": season.season_number,
                    "title": season.title,
                    "overview": season.overview,
                    "poster_url": season.poster_url,
                    "air_date": season.air_date,
                    "episode_count": season.episode_count,
                    "provider_status": season.provider_status,
                },
            )
        )
    for episode in session.scalars(
        select(EpisodeRecord)
        .where(EpisodeRecord.season_id.in_(season_ids))
        .order_by(EpisodeRecord.id)
    ):
        records.append(
            _record(
                "episode",
                episode.id,
                created_at=episode.fetched_at,
                modified_at=episode.provider_updated_at or episode.fetched_at,
                deleted_at=episode.removed_at,
                device_id=device,
                relationships={"season_id": episode.season_id},
                payload={
                    "provider_source": episode.provider_source,
                    "provider_episode_id": episode.provider_episode_id,
                    "episode_number": episode.episode_number,
                    "title": episode.title,
                    "overview": episode.overview,
                    "air_date": episode.air_date,
                    "runtime_minutes": episode.runtime_minutes,
                    "production_code": episode.production_code,
                },
            )
        )

    for entry in sorted(entries, key=lambda value: value.id):
        records.append(
            _record(
                "entry",
                entry.id,
                created_at=entry.created_at,
                modified_at=entry.updated_at,
                deleted_at=entry.deleted_at,
                device_id=device,
                version=entry.version,
                relationships={"catalog_id": entry.catalog_item_id},
                payload={
                    "status": entry.status,
                    "personal_rating": entry.personal_rating,
                    "notes": entry.notes,
                    "user_tags": entry.user_tags or [],
                    "started_date": entry.started_date,
                    "finished_date": entry.finished_date,
                    "watched_date": entry.watched_date,
                    "view_count": entry.view_count,
                    "is_favorite": entry.is_favorite,
                    "poster_override_url": entry.poster_override_url,
                    "episode_progress_explicit": entry.episode_progress_explicit,
                    "episode_progress_count": entry.episode_progress_count,
                    "genre_additions": entry.genre_additions or [],
                    "genre_removals": entry.genre_removals or [],
                    "subgenre_additions": entry.subgenre_additions or [],
                    "subgenre_removals": entry.subgenre_removals or [],
                },
            )
        )

    owned_queries: list[tuple[str, Any]] = [
        ("viewing_cycle", ViewingCycle),
        ("viewing", ViewingEvent),
        ("episode_viewing", EpisodeViewing),
        ("provider_progress_claim", ProviderProgressClaim),
        ("viewing_correction", ViewingCorrection),
    ]
    for record_type, model in owned_queries:
        for row in session.scalars(
            select(model).where(model.user_id == user_id).order_by(model.id)
        ):
            relationships: dict[str, str | None] = {"entry_id": row.entry_id}
            if record_type == "viewing_cycle":
                payload = {
                    "kind": row.kind,
                    "scope": row.scope,
                    "scope_data": row.scope_data or {},
                    "target_episode_ids": row.target_episode_ids or [],
                    "state": row.state,
                    "initiated_by": row.initiated_by,
                    "started_at": row.started_at,
                    "ended_at": row.ended_at,
                }
            elif record_type == "viewing":
                relationships["cycle_id"] = row.cycle_id
                payload = {
                    "viewed_on": row.viewed_on,
                    "source": row.source,
                    "source_key": row.source_key,
                    "occurrence_kind": row.occurrence_kind,
                    "confidence": row.confidence,
                    "source_event_keys": row.source_event_keys or [],
                }
            elif record_type == "episode_viewing":
                relationships.update({"cycle_id": row.cycle_id, "episode_id": row.episode_id})
                payload = {
                    "watched_on": row.watched_on,
                    "source": row.source,
                    "source_key": row.source_key,
                    "occurrence_kind": row.occurrence_kind,
                    "confidence": row.confidence,
                    "source_event_keys": row.source_event_keys or [],
                }
            elif record_type == "provider_progress_claim":
                payload = {
                    "provider": row.provider,
                    "source_key": row.source_key,
                    "claim": row.claim or {},
                    "accepted_values": row.accepted_values or {},
                    "observed_at": row.observed_at,
                }
            else:
                payload = {
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "action": row.action,
                    "before_value": row.before_value or {},
                    "after_value": row.after_value or {},
                    "reason": row.reason,
                }
            records.append(
                _record(
                    record_type,
                    row.id,
                    created_at=row.created_at,
                    modified_at=row.updated_at,
                    deleted_at=row.deleted_at,
                    device_id=device,
                    origin_device_id=row.origin_device_id,
                    origin_event_id=row.origin_event_id,
                    field_versions=row.field_versions,
                    version=getattr(row, "version", 1),
                    relationships=relationships,
                    payload=payload,
                )
            )

    for assessment in session.scalars(
        select(RatingAssessment)
        .join(WatchEntry, RatingAssessment.entry_id == WatchEntry.id)
        .where(WatchEntry.user_id == user_id)
        .order_by(RatingAssessment.id)
    ):
        records.append(
            _record(
                "rating_assessment",
                assessment.id,
                created_at=assessment.created_at,
                modified_at=assessment.updated_at,
                device_id=device,
                version=assessment.version,
                relationships={"entry_id": assessment.entry_id},
                payload={
                    "mode": assessment.mode,
                    "rubric_version": assessment.rubric_version,
                    "state": assessment.state,
                    "answers": assessment.answers or {},
                    "private_reflection": assessment.private_reflection,
                    "rubric_score": assessment.rubric_score,
                    "rubric_coverage": assessment.rubric_coverage,
                    "suggested_rating": assessment.suggested_rating,
                    "final_rating_snapshot": assessment.final_rating_snapshot,
                    "completed_at": assessment.completed_at,
                },
            )
        )
    for comparison in session.scalars(
        select(RatingComparison)
        .where(RatingComparison.user_id == user_id)
        .order_by(RatingComparison.id)
    ):
        records.append(
            _record(
                "rating_comparison",
                comparison.id,
                created_at=comparison.created_at,
                modified_at=comparison.updated_at,
                device_id=device,
                relationships={
                    "entry_low_id": comparison.entry_low_id,
                    "entry_high_id": comparison.entry_high_id,
                    "displayed_left_entry_id": comparison.displayed_left_entry_id,
                },
                payload={
                    "dimension": comparison.dimension,
                    "result": comparison.result,
                    "selection_reason": comparison.selection_reason,
                    "algorithm_version": comparison.algorithm_version,
                    "skipped_until": comparison.skipped_until,
                },
            )
        )
    for preference in session.scalars(
        select(SeriesTrackingSubscription)
        .join(WatchEntry, SeriesTrackingSubscription.entry_id == WatchEntry.id)
        .where(WatchEntry.user_id == user_id)
        .order_by(SeriesTrackingSubscription.id)
    ):
        records.append(
            _record(
                "series_preference",
                preference.id,
                created_at=preference.created_at,
                modified_at=preference.updated_at,
                device_id=device,
                relationships={"entry_id": preference.entry_id},
                payload={
                    "enabled": preference.enabled,
                    "notify_new_episode": preference.notify_new_episode,
                    "notify_new_season": preference.notify_new_season,
                    "include_specials": preference.include_specials,
                    "region": preference.region,
                    "provider_preference": preference.provider_preference,
                },
            )
        )
    lists = list(
        session.scalars(
            select(MediaList).where(MediaList.user_id == user_id).order_by(MediaList.id)
        )
    )
    list_ids = {row.id for row in lists}
    for row in lists:
        records.append(
            _record(
                "list",
                row.id,
                created_at=row.created_at,
                modified_at=row.updated_at,
                deleted_at=row.deleted_at,
                device_id=device,
                origin_device_id=row.origin_device_id,
                origin_event_id=row.origin_event_id,
                field_versions=row.field_versions,
                version=row.version,
                payload={
                    "name": row.name,
                    "pinned_to_navigation": row.pinned_to_navigation,
                },
            )
        )
    for item in session.scalars(
        select(MediaListItem)
        .where(MediaListItem.list_id.in_(list_ids))
        .order_by(MediaListItem.id)
    ):
        records.append(
            _record(
                "list_item",
                item.id,
                created_at=item.added_at,
                modified_at=item.updated_at,
                deleted_at=item.deleted_at,
                device_id=device,
                origin_device_id=item.origin_device_id,
                origin_event_id=item.origin_event_id,
                field_versions=item.field_versions,
                relationships={
                    "list_id": item.list_id,
                    "catalog_id": item.catalog_item_id,
                },
                payload={"position": item.position, "shared_note": item.shared_note},
            )
        )

    records.sort(key=lambda value: (value.record_type, value.record_id))
    return PlatformSyncSnapshot(
        generated_at=generated_at,
        source=PlatformSyncSource(product_version=__version__, device_id=device),
        records=records,
    )


_IMPORT_PRIORITY = {
    "catalog": 10,
    "external_identity": 20,
    "season": 30,
    "episode": 40,
    "entry": 50,
    "viewing_cycle": 60,
    "viewing": 70,
    "episode_viewing": 70,
    "provider_progress_claim": 75,
    "viewing_correction": 76,
    "rating_assessment": 80,
    "rating_comparison": 81,
    "series_preference": 82,
    "list": 90,
    "list_item": 91,
}


def _newer_or_equal(incoming: datetime, local: datetime | None) -> bool:
    return _timestamp(incoming) >= _timestamp(local, datetime.min.replace(tzinfo=UTC))


def _entry_for_user(session: Session, entry_id: str, user_id: str) -> WatchEntry | None:
    return session.scalar(
        select(WatchEntry).where(WatchEntry.id == entry_id, WatchEntry.user_id == user_id)
    )


def _apply_common_sync_fields(row: Any, record: PlatformSyncRecord) -> None:
    row.created_at = record.created_at
    row.updated_at = record.modified_at
    row.deleted_at = record.deleted_at
    row.origin_device_id = record.origin_device_id
    row.origin_event_id = record.origin_event_id
    row.field_versions = record.field_versions
    if hasattr(row, "version"):
        row.version = max(record.field_versions.values(), default=1)


def _apply_record(
    session: Session, record: PlatformSyncRecord, *, user_id: str
) -> tuple[str, str | None]:
    p = record.payload
    r = record.relationships
    if record.record_type not in KNOWN_RECORD_TYPES:
        return "skipped_unknown", "Unknown future record type was safely skipped."
    if record.record_type == "catalog":
        row = session.get(CatalogItem, record.record_id)
        if row is None:
            row = CatalogItem(
                id=record.record_id,
                canonical_title=str(p["canonical_title"]),
                normalized_title=normalize_title(str(p["canonical_title"])),
                media_type=str(p["media_type"]),
                metadata_source="platform_sync",
                created_at=record.created_at,
                updated_at=record.modified_at,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        for field in (
            "canonical_title",
            "original_title",
            "release_year",
            "release_date",
            "media_type",
            "provider_format",
            "provider_source",
            "provider_id",
            "poster_url",
            "overview",
            "provider_genres",
            "normalized_genres",
            "inferred_subgenres",
            "country",
            "language",
            "runtime_minutes",
            "episode_count",
            "released_episode_count",
        ):
            if field in p:
                setattr(
                    row, field, _date_value(p[field]) if field == "release_date" else p[field]
                )
        row.normalized_title = normalize_title(row.canonical_title)
        row.updated_at = record.modified_at
        return "applied", None
    if record.record_type == "external_identity":
        if not session.get(CatalogItem, r.get("catalog_id")):
            return "skipped_dependency", "Catalog record is missing."
        row = session.get(ExternalIdentity, record.record_id)
        if row is None:
            existing = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.namespace == str(p["namespace"]),
                    ExternalIdentity.external_id == str(p["external_id"]),
                )
            )
            if existing:
                return "skipped_existing_identity", None
            session.add(
                ExternalIdentity(
                    id=record.record_id,
                    catalog_item_id=r["catalog_id"],
                    namespace=str(p["namespace"]),
                    external_id=str(p["external_id"]),
                    provenance=str(p.get("provenance") or "platform_sync"),
                    confidence=float(p.get("confidence") or 1),
                    verified_at=_datetime_value(p.get("verified_at")),
                    created_at=record.created_at,
                    updated_at=record.modified_at,
                )
            )
        return "applied", None
    if record.record_type == "season":
        if not session.get(CatalogItem, r.get("catalog_id")):
            return "skipped_dependency", "Catalog record is missing."
        row = session.get(SeasonRecord, record.record_id)
        if row is None:
            row = SeasonRecord(
                id=record.record_id,
                catalog_item_id=r["catalog_id"],
                provider_source=str(p["provider_source"]),
                provider_series_id=str(p["provider_series_id"]),
                season_number=int(p["season_number"]),
                fetched_at=record.created_at,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.provider_updated_at or row.fetched_at):
            return "skipped_older", None
        for field in (
            "provider_season_id",
            "title",
            "overview",
            "poster_url",
            "episode_count",
            "provider_status",
        ):
            if field in p:
                setattr(row, field, p[field])
        row.air_date = _date_value(p.get("air_date"))
        row.provider_updated_at = record.modified_at
        row.removed_at = record.deleted_at
        return "applied", None
    if record.record_type == "episode":
        if not session.get(SeasonRecord, r.get("season_id")):
            return "skipped_dependency", "Season record is missing."
        row = session.get(EpisodeRecord, record.record_id)
        if row is None:
            row = EpisodeRecord(
                id=record.record_id,
                season_id=r["season_id"],
                provider_source=str(p["provider_source"]),
                provider_episode_id=str(p["provider_episode_id"]),
                fetched_at=record.created_at,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.provider_updated_at or row.fetched_at):
            return "skipped_older", None
        for field in (
            "episode_number",
            "title",
            "overview",
            "runtime_minutes",
            "production_code",
        ):
            if field in p:
                setattr(row, field, p[field])
        row.air_date = _date_value(p.get("air_date"))
        row.provider_updated_at = record.modified_at
        row.removed_at = record.deleted_at
        return "applied", None
    if record.record_type == "entry":
        catalog_id = r.get("catalog_id")
        if not session.get(CatalogItem, catalog_id):
            return "skipped_dependency", "Catalog record is missing."
        row = session.get(WatchEntry, record.record_id)
        if row is not None and row.user_id != user_id:
            return "skipped_ownership", "Record ID belongs to another user."
        if row is None:
            row = WatchEntry(
                id=record.record_id,
                user_id=user_id,
                catalog_item_id=catalog_id,
                created_at=record.created_at,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        for field in (
            "status",
            "personal_rating",
            "notes",
            "user_tags",
            "view_count",
            "is_favorite",
            "poster_override_url",
            "episode_progress_explicit",
            "episode_progress_count",
            "genre_additions",
            "genre_removals",
            "subgenre_additions",
            "subgenre_removals",
        ):
            if field in p:
                setattr(row, field, p[field])
        for field in ("started_date", "finished_date", "watched_date"):
            if field in p:
                setattr(row, field, _date_value(p[field]))
        row.deleted_at = record.deleted_at
        row.updated_at = record.modified_at
        row.version = max(record.field_versions.values(), default=1)
        return "applied", None

    entry_id = r.get("entry_id")
    entry = _entry_for_user(session, entry_id or "", user_id) if entry_id else None
    if (
        record.record_type
        in {
            "viewing_cycle",
            "viewing",
            "episode_viewing",
            "provider_progress_claim",
            "viewing_correction",
            "rating_assessment",
            "series_preference",
        }
        and entry is None
    ):
        return "skipped_dependency", "Watch entry is missing."
    if record.record_type == "viewing_cycle":
        row = session.get(ViewingCycle, record.record_id)
        if row is None:
            row = ViewingCycle(id=record.record_id, user_id=user_id, entry_id=entry_id)
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        for field in (
            "kind",
            "scope",
            "scope_data",
            "target_episode_ids",
            "state",
            "initiated_by",
        ):
            if field in p:
                setattr(row, field, p[field])
        row.started_at = _datetime_value(p.get("started_at")) or record.created_at
        row.ended_at = _datetime_value(p.get("ended_at"))
        _apply_common_sync_fields(row, record)
        return "applied", None
    if record.record_type == "viewing":
        row = session.get(ViewingEvent, record.record_id)
        if row is None:
            row = ViewingEvent(id=record.record_id, user_id=user_id, entry_id=entry_id)
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        cycle_id = r.get("cycle_id")
        row.cycle_id = cycle_id if cycle_id and session.get(ViewingCycle, cycle_id) else None
        row.viewed_on = _date_value(p.get("viewed_on"))
        row.source = str(p.get("source") or "platform_sync")
        row.source_key = p.get("source_key")
        row.occurrence_kind = str(p.get("occurrence_kind") or "completion")
        row.confidence = float(p.get("confidence") or 1)
        row.source_event_keys = list(p.get("source_event_keys") or [])
        _apply_common_sync_fields(row, record)
        return "applied", None
    if record.record_type == "episode_viewing":
        episode_id = r.get("episode_id")
        if not session.get(EpisodeRecord, episode_id):
            return "skipped_dependency", "Episode record is missing."
        row = session.get(EpisodeViewing, record.record_id)
        if row is None:
            row = EpisodeViewing(
                id=record.record_id,
                user_id=user_id,
                entry_id=entry_id,
                episode_id=episode_id,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        cycle_id = r.get("cycle_id")
        row.cycle_id = cycle_id if cycle_id and session.get(ViewingCycle, cycle_id) else None
        row.watched_on = _date_value(p.get("watched_on"))
        row.source = str(p.get("source") or "platform_sync")
        row.source_key = p.get("source_key")
        row.occurrence_kind = str(p.get("occurrence_kind") or "completion")
        row.confidence = float(p.get("confidence") or 1)
        row.source_event_keys = list(p.get("source_event_keys") or [])
        _apply_common_sync_fields(row, record)
        return "applied", None
    if record.record_type == "provider_progress_claim":
        row = session.get(ProviderProgressClaim, record.record_id)
        if row is None:
            row = ProviderProgressClaim(
                id=record.record_id,
                user_id=user_id,
                entry_id=entry_id,
                provider=str(p["provider"]),
                source_key=str(p["source_key"]),
                observed_at=_datetime_value(p.get("observed_at")) or record.created_at,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        row.claim = dict(p.get("claim") or {})
        row.accepted_values = dict(p.get("accepted_values") or {})
        _apply_common_sync_fields(row, record)
        return "applied", None
    if record.record_type == "viewing_correction":
        row = session.get(ViewingCorrection, record.record_id)
        if row is None:
            row = ViewingCorrection(
                id=record.record_id,
                user_id=user_id,
                entry_id=entry_id,
                target_type=str(p["target_type"]),
                action=str(p["action"]),
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        row.target_id = p.get("target_id")
        row.before_value = dict(p.get("before_value") or {})
        row.after_value = dict(p.get("after_value") or {})
        row.reason = p.get("reason")
        _apply_common_sync_fields(row, record)
        return "applied", None
    if record.record_type == "rating_assessment":
        row = session.get(RatingAssessment, record.record_id)
        if row is None:
            row = RatingAssessment(id=record.record_id, entry_id=entry_id)
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        for field in (
            "mode",
            "rubric_version",
            "state",
            "answers",
            "private_reflection",
            "rubric_score",
            "rubric_coverage",
            "suggested_rating",
            "final_rating_snapshot",
        ):
            if field in p:
                setattr(row, field, p[field])
        row.version = max(record.field_versions.values(), default=1)
        row.created_at = record.created_at
        row.updated_at = record.modified_at
        row.completed_at = _datetime_value(p.get("completed_at"))
        return "applied", None
    if record.record_type == "rating_comparison":
        low = _entry_for_user(session, r.get("entry_low_id", ""), user_id)
        high = _entry_for_user(session, r.get("entry_high_id", ""), user_id)
        if not low or not high:
            return "skipped_dependency", "Compared entry is missing."
        row = session.get(RatingComparison, record.record_id)
        if row is None:
            row = RatingComparison(
                id=record.record_id,
                user_id=user_id,
                entry_low_id=low.id,
                entry_high_id=high.id,
                displayed_left_entry_id=r.get("displayed_left_entry_id", low.id),
                result=str(p["result"]),
                selection_reason=str(p["selection_reason"]),
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        row.dimension = str(p.get("dimension") or "overall_preference")
        row.algorithm_version = str(p.get("algorithm_version") or "platform-sync-v2")
        row.skipped_until = _datetime_value(p.get("skipped_until"))
        row.created_at = record.created_at
        row.updated_at = record.modified_at
        return "applied", None
    if record.record_type == "series_preference":
        row = session.get(SeriesTrackingSubscription, record.record_id)
        if row is None:
            row = SeriesTrackingSubscription(id=record.record_id, entry_id=entry_id)
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        for field in (
            "enabled",
            "notify_new_episode",
            "notify_new_season",
            "include_specials",
            "region",
            "provider_preference",
        ):
            if field in p:
                setattr(row, field, p[field])
        row.created_at = record.created_at
        row.updated_at = record.modified_at
        return "applied", None
    if record.record_type == "list":
        row = session.get(MediaList, record.record_id)
        if row is not None and row.user_id != user_id:
            return "skipped_ownership", "List ID belongs to another user."
        if row is None:
            row = MediaList(
                id=record.record_id,
                user_id=user_id,
                name=str(p["name"]),
                created_at=record.created_at,
            )
            session.add(row)
            session.flush()
            session.add(
                MediaListMembership(
                    list_id=row.id,
                    user_id=user_id,
                    role="owner",
                    invited_by_user_id=user_id,
                )
            )
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        row.name = str(p["name"])
        row.pinned_to_navigation = bool(p.get("pinned_to_navigation"))
        row.deleted_at = record.deleted_at
        row.updated_at = record.modified_at
        row.origin_device_id = record.origin_device_id
        row.origin_event_id = record.origin_event_id
        row.field_versions = record.field_versions
        return "applied", None
    if record.record_type == "list_item":
        media_list = session.get(MediaList, r.get("list_id"))
        catalog = session.get(CatalogItem, r.get("catalog_id"))
        if not media_list or media_list.user_id != user_id or not catalog:
            return "skipped_dependency", "List or catalog record is missing."
        row = session.get(MediaListItem, record.record_id)
        if row is None:
            row = MediaListItem(
                id=record.record_id,
                list_id=media_list.id,
                catalog_item_id=catalog.id,
                added_by_user_id=user_id,
                added_at=record.created_at,
            )
            session.add(row)
        elif not _newer_or_equal(record.modified_at, row.updated_at):
            return "skipped_older", None
        row.position = int(p.get("position") or 0)
        row.shared_note = p.get("shared_note")
        row.updated_at = record.modified_at
        row.deleted_at = record.deleted_at
        row.origin_device_id = record.origin_device_id
        row.origin_event_id = record.origin_event_id
        row.field_versions = record.field_versions
        return "applied", None
    return "skipped_unknown", None


class _DryRunRollback(Exception):
    pass


def import_platform_sync_snapshot(
    session: Session,
    snapshot: PlatformSyncSnapshot | dict[str, Any],
    principal: Principal | None = None,
    *,
    dry_run: bool = False,
) -> PlatformSyncImportReport:
    """Apply a v2 snapshot transactionally and ledger every visible outcome."""

    value = (
        snapshot
        if isinstance(snapshot, PlatformSyncSnapshot)
        else PlatformSyncSnapshot.model_validate(snapshot)
    )
    user_id = current_user_id(session, principal)
    snapshot_hash = value.sha256()
    duplicate = session.scalar(
        select(PlatformSyncImportBatch).where(
            PlatformSyncImportBatch.user_id == user_id,
            PlatformSyncImportBatch.snapshot_hash == snapshot_hash,
        )
    )
    if duplicate:
        return PlatformSyncImportReport(
            batch_id=duplicate.id,
            duplicate_snapshot=True,
            counts={key: int(number) for key, number in duplicate.counts.items()},
        )

    batch = PlatformSyncImportBatch(
        id=new_id(),
        user_id=user_id,
        snapshot_hash=snapshot_hash,
        source_product=value.source.product,
        source_version=value.source.product_version,
        contract_version=value.version,
        state="previewed" if dry_run else "running",
        counts={},
    )
    session.add(batch)
    session.flush()
    counts = {"applied": 0, "skipped": 0, "warnings": 0}
    warnings: list[str] = []
    try:
        with session.begin_nested():
            for record in sorted(
                value.records,
                key=lambda row: (
                    _IMPORT_PRIORITY.get(row.record_type, 999),
                    row.record_type,
                    row.record_id,
                ),
            ):
                outcome, message = _apply_record(session, record, user_id=user_id)
                # Materialize each accepted dependency before the next record.
                # ``Session.get`` does not guarantee that a pending object added by
                # the previous record is queryable through every dependency path.
                if outcome == "applied":
                    session.flush()
                counts["applied" if outcome == "applied" else "skipped"] += 1
                if message:
                    counts["warnings"] += 1
                    warnings.append(f"{record.record_type}/{record.record_id}: {message}")
                session.add(
                    PlatformSyncImportRecord(
                        batch_id=batch.id,
                        record_type=record.record_type,
                        record_id=record.record_id,
                        outcome=outcome,
                        origin_device_id=record.origin_device_id,
                        origin_event_id=record.origin_event_id,
                        safe_message=message,
                    )
                )
            session.flush()
            if dry_run:
                raise _DryRunRollback
        batch.state = "succeeded"
    except _DryRunRollback:
        session.expire_all()
        batch.state = "previewed"
    except (KeyError, TypeError, ValueError, IntegrityError) as exc:
        session.rollback()
        raise ValueError("The platform-sync snapshot could not be applied safely.") from exc
    batch.counts = counts
    batch.completed_at = utcnow()
    session.add(batch)
    session.commit()
    return PlatformSyncImportReport(batch_id=batch.id, counts=counts, warnings=warnings)
