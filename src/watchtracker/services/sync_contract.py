from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import (
    CatalogItem,
    EpisodeRecord,
    EpisodeViewing,
    ExternalIdentity,
    MediaList,
    MediaListItem,
    RatingAssessment,
    RatingComparison,
    SeriesTrackingSubscription,
    ViewingEvent,
    WatchEntry,
)

SyncRecordType = Literal[
    "catalog",
    "entry",
    "viewing",
    "episode_viewing",
    "rating_assessment",
    "rating_comparison",
    "series_preference",
    "list",
    "list_item",
]


class PlatformSyncRecord(BaseModel):
    """Provider-agnostic logical record suitable for a future mobile store."""

    record_type: SyncRecordType
    record_id: str
    modified_at: datetime
    deleted_at: datetime | None = None
    relationships: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class PlatformSyncSnapshot(BaseModel):
    """Versioned boundary contract; this does not enable network or CloudKit sync."""

    contract: Literal["pmt.platform-sync"] = "pmt.platform-sync"
    version: Literal[1] = 1
    generated_at: datetime
    records: list[PlatformSyncRecord]
    excluded_domains: list[str] = Field(
        default_factory=lambda: [
            "credentials",
            "provider_raw_payloads",
            "provider_response_cache",
            "release_schedule_cache",
            "integration_runtime_state",
            "private_developer_tools",
        ]
    )


def _timestamp(value: datetime | None, fallback: datetime) -> datetime:
    return value or fallback


def build_platform_sync_snapshot(
    session: Session, principal: Principal | None = None
) -> PlatformSyncSnapshot:
    """Build a side-effect-free snapshot of user-owned, cross-platform state.

    The contract intentionally excludes credentials and replaceable provider/runtime
    caches. It is an architectural seam for a future iOS/CloudKit adapter, not a
    public synchronization feature.
    """

    generated_at = datetime.now(UTC)
    user_id = current_user_id(session, principal)
    records: list[PlatformSyncRecord] = []
    catalog_ids = set(
        session.scalars(select(WatchEntry.catalog_item_id).where(WatchEntry.user_id == user_id))
    )
    identities: dict[str, dict[str, str]] = {}
    for identity in session.scalars(
        select(ExternalIdentity).where(ExternalIdentity.catalog_item_id.in_(catalog_ids))
    ):
        identities.setdefault(identity.catalog_item_id, {})[identity.namespace] = (
            identity.external_id
        )

    for catalog in session.scalars(
        select(CatalogItem).where(CatalogItem.id.in_(catalog_ids)).order_by(CatalogItem.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="catalog",
                record_id=catalog.id,
                modified_at=_timestamp(catalog.updated_at, catalog.created_at),
                payload={
                    "canonical_title": catalog.canonical_title,
                    "original_title": catalog.original_title,
                    "release_year": catalog.release_year,
                    "release_date": catalog.release_date,
                    "media_type": catalog.media_type,
                    "provider_format": catalog.provider_format,
                    "external_ids": identities.get(catalog.id, {}),
                    "metadata_source": catalog.metadata_source,
                },
            )
        )

    for entry in session.scalars(
        select(WatchEntry).where(WatchEntry.user_id == user_id).order_by(WatchEntry.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="entry",
                record_id=entry.id,
                modified_at=_timestamp(entry.updated_at, entry.created_at),
                deleted_at=entry.deleted_at,
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
                    "genre_additions": entry.genre_additions or [],
                    "genre_removals": entry.genre_removals or [],
                    "subgenre_additions": entry.subgenre_additions or [],
                    "subgenre_removals": entry.subgenre_removals or [],
                },
            )
        )

    for viewing in session.scalars(
        select(ViewingEvent).where(ViewingEvent.user_id == user_id).order_by(ViewingEvent.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="viewing",
                record_id=viewing.id,
                modified_at=viewing.created_at,
                relationships={"entry_id": viewing.entry_id},
                payload={"viewed_on": viewing.viewed_on, "source": viewing.source},
            )
        )

    episode_rows = {
        episode.id: episode
        for episode in session.scalars(select(EpisodeRecord).order_by(EpisodeRecord.id))
    }
    for viewing in session.scalars(
        select(EpisodeViewing)
        .where(EpisodeViewing.user_id == user_id)
        .order_by(EpisodeViewing.id)
    ):
        episode = episode_rows.get(viewing.episode_id)
        records.append(
            PlatformSyncRecord(
                record_type="episode_viewing",
                record_id=viewing.id,
                modified_at=viewing.created_at,
                relationships={"entry_id": viewing.entry_id},
                payload={
                    "watched_on": viewing.watched_on,
                    "source": viewing.source,
                    "provider": episode.provider_source if episode else None,
                    "provider_episode_id": episode.provider_episode_id if episode else None,
                    "episode_number": episode.episode_number if episode else None,
                },
            )
        )

    for assessment in session.scalars(
        select(RatingAssessment)
        .join(WatchEntry, RatingAssessment.entry_id == WatchEntry.id)
        .where(WatchEntry.user_id == user_id)
        .order_by(RatingAssessment.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="rating_assessment",
                record_id=assessment.id,
                modified_at=_timestamp(assessment.updated_at, assessment.created_at),
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
                    "version": assessment.version,
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
            PlatformSyncRecord(
                record_type="rating_comparison",
                record_id=comparison.id,
                modified_at=_timestamp(comparison.updated_at, comparison.created_at),
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

    for subscription in session.scalars(
        select(SeriesTrackingSubscription)
        .join(WatchEntry, SeriesTrackingSubscription.entry_id == WatchEntry.id)
        .where(WatchEntry.user_id == user_id)
        .order_by(SeriesTrackingSubscription.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="series_preference",
                record_id=subscription.id,
                modified_at=_timestamp(subscription.updated_at, subscription.created_at),
                relationships={"entry_id": subscription.entry_id},
                payload={
                    "enabled": subscription.enabled,
                    "notify_new_episode": subscription.notify_new_episode,
                    "notify_new_season": subscription.notify_new_season,
                    "include_specials": subscription.include_specials,
                    "region": subscription.region,
                    "provider_preference": subscription.provider_preference,
                },
            )
        )

    for media_list in session.scalars(
        select(MediaList).where(MediaList.user_id == user_id).order_by(MediaList.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="list",
                record_id=media_list.id,
                modified_at=_timestamp(media_list.updated_at, media_list.created_at),
                payload={
                    "name": media_list.name,
                    "pinned_to_navigation": media_list.pinned_to_navigation,
                },
            )
        )
    for item in session.scalars(
        select(MediaListItem)
        .join(MediaList, MediaListItem.list_id == MediaList.id)
        .where(MediaList.user_id == user_id)
        .order_by(MediaListItem.id)
    ):
        records.append(
            PlatformSyncRecord(
                record_type="list_item",
                record_id=item.id,
                modified_at=item.added_at,
                relationships={
                    "list_id": item.list_id,
                    "catalog_id": item.catalog_item_id,
                },
                payload={
                    "position": item.position,
                    "shared_note": item.shared_note,
                },
            )
        )

    records.sort(key=lambda record: (record.record_type, record.record_id))
    return PlatformSyncSnapshot(generated_at=generated_at, records=records)
