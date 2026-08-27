from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

from watchtracker.authorization import Principal, current_user_id
from watchtracker.metadata import ProviderUnavailable
from watchtracker.models import (
    CatalogItem,
    EpisodeRecord,
    EpisodeViewing,
    ExternalIdentity,
    ReleaseEvent,
    SeasonRecord,
    SeriesTrackingSubscription,
    SyncJob,
    WatchEntry,
    utcnow,
)
from watchtracker.services.entries import serialize_entry

logger = logging.getLogger(__name__)


def _jittered(value: float) -> float:
    """Add bounded jitter so multiple followed titles do not retry in lockstep."""
    return value * random.uniform(0.85, 1.15)


class ReleaseNotFound(LookupError):
    pass


class ReleaseConflict(RuntimeError):
    pass


class ReleaseProviderError(RuntimeError):
    pass


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _serial_subscription(subscription: SeriesTrackingSubscription) -> dict[str, Any]:
    return {
        "id": subscription.id,
        "entry_id": subscription.entry_id,
        "enabled": subscription.enabled,
        "notify_new_episode": subscription.notify_new_episode,
        "notify_new_season": subscription.notify_new_season,
        "include_specials": subscription.include_specials,
        "region": subscription.region,
        "last_attempt_at": subscription.last_attempt_at,
        "last_success_at": subscription.last_success_at,
        "last_error_code": subscription.last_error_code,
        "last_error_message": subscription.last_error_message,
        "next_check_at": subscription.next_check_at,
        "failure_count": subscription.failure_count,
    }


def _stored_watched_episode_ids(session: Session, entry_id: str) -> set[str]:
    return set(
        session.scalars(
            select(EpisodeViewing.episode_id).where(EpisodeViewing.entry_id == entry_id)
        )
    )


def _watched_episode_ids(session: Session, entry: WatchEntry) -> set[str]:
    stored = _stored_watched_episode_ids(session, entry.id)
    if entry.episode_progress_explicit or entry.status != "watched":
        return stored
    return set(
        session.scalars(
            select(EpisodeRecord.id)
            .join(SeasonRecord)
            .where(
                SeasonRecord.catalog_item_id == entry.catalog_item_id,
                SeasonRecord.removed_at.is_(None),
                EpisodeRecord.removed_at.is_(None),
            )
        )
    )


def _materialize_assumed_progress(session: Session, entry: WatchEntry, *, today: date) -> None:
    if entry.episode_progress_explicit:
        return
    existing = _stored_watched_episode_ids(session, entry.id)
    if entry.status == "watched":
        watched_on = entry.finished_date or entry.watched_date or today
        episode_ids = session.scalars(
            select(EpisodeRecord.id)
            .join(SeasonRecord)
            .where(
                SeasonRecord.catalog_item_id == entry.catalog_item_id,
                SeasonRecord.removed_at.is_(None),
                EpisodeRecord.removed_at.is_(None),
            )
        )
        for episode_id in episode_ids:
            if episode_id not in existing:
                session.add(
                    EpisodeViewing(
                        user_id=entry.user_id,
                        episode_id=episode_id,
                        entry_id=entry.id,
                        watched_on=watched_on,
                    )
                )
    entry.episode_progress_explicit = True
    entry.updated_at = utcnow()
    session.flush()


def _episode_payload(episode: EpisodeRecord, watched: set[str]) -> dict[str, Any]:
    return {
        "id": episode.id,
        "provider_episode_id": episode.provider_episode_id,
        "episode_number": episode.episode_number,
        "title": episode.title,
        "overview": episode.overview,
        "air_date": episode.air_date,
        "runtime_minutes": episode.runtime_minutes,
        "production_code": episode.production_code,
        "fetched_at": episode.fetched_at,
        "removed": episode.removed_at is not None,
        "watched": episode.id in watched,
    }


def _season_payload(season: SeasonRecord, watched: set[str]) -> dict[str, Any]:
    episodes = [
        _episode_payload(item, watched) for item in season.episodes if item.removed_at is None
    ]
    return {
        "id": season.id,
        "season_number": season.season_number,
        "title": season.title,
        "overview": season.overview,
        "poster_url": season.poster_url,
        "air_date": season.air_date,
        "episode_count": season.episode_count,
        "status": season.provider_status,
        "fetched_at": season.fetched_at,
        "removed": season.removed_at is not None,
        "watched_count": sum(item["watched"] for item in episodes),
        "episodes": episodes,
    }


def _supported_entry(session: Session, entry_id: str, user_id: str | None = None) -> WatchEntry:
    filters = [WatchEntry.id == entry_id, WatchEntry.deleted_at.is_(None)]
    if user_id is not None:
        filters.append(WatchEntry.user_id == user_id)
    entry = session.scalar(
        select(WatchEntry)
        .where(*filters)
        .options(
            selectinload(WatchEntry.catalog_item).selectinload(CatalogItem.external_identities)
        )
    )
    if not entry:
        raise ReleaseNotFound("Watch entry not found")
    if entry.catalog_item.media_type not in {"tv", "anime"}:
        raise ReleaseConflict("Release tracking is available only for TV series and anime")
    if not _schedule_identity(entry):
        raise ReleaseConflict(
            "Automatic release tracking requires a verified TVmaze or TMDB TV identity"
        )
    return entry


def _schedule_identity(
    entry: WatchEntry, preferred: str | None = None
) -> tuple[str, str] | None:
    identities = {
        identity.namespace: identity.external_id
        for identity in entry.catalog_item.external_identities
    }
    if entry.catalog_item.provider_source == "tvmaze" and entry.catalog_item.provider_id:
        identities.setdefault("tvmaze", entry.catalog_item.provider_id)
    if entry.catalog_item.tmdb_tv_id:
        identities.setdefault("tmdb_tv", entry.catalog_item.tmdb_tv_id)
    order = [preferred] if preferred else []
    order.extend(provider for provider in ("tvmaze", "tmdb_tv") if provider not in order)
    return next(
        ((provider, identities[provider]) for provider in order if provider in identities),
        None,
    )


class ReleaseTrackingService:
    def __init__(
        self,
        session: Session,
        *,
        today: date,
        principal: Principal | None = None,
        trusted_user_id: str | None = None,
    ):
        self.session = session
        self.today = today
        self.user_id = trusted_user_id or current_user_id(session, principal)

    def follow(
        self,
        entry_id: str,
        *,
        notify_new_episode: bool,
        notify_new_season: bool,
        include_specials: bool,
        region: str,
    ) -> dict[str, Any]:
        entry = _supported_entry(self.session, entry_id, self.user_id)
        subscription = self.session.scalar(
            select(SeriesTrackingSubscription).where(
                SeriesTrackingSubscription.entry_id == entry.id
            )
        )
        if not subscription:
            subscription = SeriesTrackingSubscription(entry_id=entry.id)
            self.session.add(subscription)
        subscription.enabled = True
        subscription.notify_new_episode = notify_new_episode
        subscription.notify_new_season = notify_new_season
        subscription.include_specials = include_specials
        subscription.region = region
        provider, _provider_id = _schedule_identity(entry) or ("tmdb_tv", "")
        subscription.provider_preference = provider
        subscription.next_check_at = utcnow()
        self.session.commit()
        return _serial_subscription(subscription)

    def unfollow(self, entry_id: str) -> None:
        subscription = self.session.scalar(
            select(SeriesTrackingSubscription).where(
                SeriesTrackingSubscription.entry_id == entry_id,
                SeriesTrackingSubscription.entry.has(user_id=self.user_id),
            )
        )
        if not subscription:
            raise ReleaseNotFound("Series subscription not found")
        subscription.enabled = False
        subscription.next_check_at = None
        self.session.commit()

    def detail(self, entry_id: str) -> dict[str, Any]:
        entry = self.session.scalar(
            select(WatchEntry)
            .where(WatchEntry.id == entry_id, WatchEntry.user_id == self.user_id)
            .options(
                selectinload(WatchEntry.catalog_item).selectinload(
                    CatalogItem.external_identities
                ),
                selectinload(WatchEntry.series_subscription),
                selectinload(WatchEntry.catalog_item)
                .selectinload(CatalogItem.seasons)
                .selectinload(SeasonRecord.episodes),
            )
        )
        if not entry:
            raise ReleaseNotFound("Watch entry not found")
        watched = _watched_episode_ids(self.session, entry)
        seasons = [
            _season_payload(item, watched)
            for item in sorted(
                entry.catalog_item.seasons, key=lambda value: value.season_number
            )
            if item.removed_at is None
        ]
        all_episodes = [episode for season in seasons for episode in season["episodes"]]
        released = [
            item
            for item in all_episodes
            if item["air_date"] is not None and item["air_date"] <= self.today
        ]
        next_episode = next(
            (
                item
                for item in released
                if not item["watched"]
                and (
                    entry.series_subscription is None
                    or entry.series_subscription.include_specials
                    or next(
                        season["season_number"]
                        for season in seasons
                        if item in season["episodes"]
                    )
                    != 0
                )
            ),
            None,
        )
        return {
            "entry_id": entry.id,
            "title": entry.catalog_item.canonical_title,
            "supported": bool(
                _schedule_identity(
                    entry,
                    entry.series_subscription.provider_preference
                    if entry.series_subscription
                    else None,
                )
            ),
            "provider_source": (
                _schedule_identity(
                    entry,
                    entry.series_subscription.provider_preference
                    if entry.series_subscription
                    else None,
                )
                or (None, None)
            )[0],
            "subscription": (
                _serial_subscription(entry.series_subscription)
                if entry.series_subscription
                else None
            ),
            "seasons": seasons,
            "progress": {
                "watched": len(watched),
                "released": len(released),
                "total": len(all_episodes),
            },
            "up_next": next_episode,
        }

    def mark_episode(self, episode_id: str, *, watched_on: date | None) -> dict[str, Any]:
        episode = self.session.scalar(
            select(EpisodeRecord)
            .where(EpisodeRecord.id == episode_id, EpisodeRecord.removed_at.is_(None))
            .options(selectinload(EpisodeRecord.season))
        )
        if not episode:
            raise ReleaseNotFound("Episode not found")
        entry = self.session.scalar(
            select(WatchEntry).where(
                WatchEntry.user_id == self.user_id,
                WatchEntry.catalog_item_id == episode.season.catalog_item_id,
                WatchEntry.deleted_at.is_(None),
            )
        )
        if not entry:
            raise ReleaseNotFound("Episode not found")
        _materialize_assumed_progress(self.session, entry, today=self.today)
        existing = self.session.scalar(
            select(EpisodeViewing).where(
                EpisodeViewing.episode_id == episode.id,
                EpisodeViewing.entry_id == entry.id,
                EpisodeViewing.user_id == self.user_id,
            )
        )
        if not existing:
            self.session.add(
                EpisodeViewing(
                    user_id=self.user_id,
                    episode_id=episode.id,
                    entry_id=entry.id,
                    watched_on=watched_on or self.today,
                )
            )
            self.session.commit()
        return self.detail(entry.id)

    def unmark_episode(self, episode_id: str) -> dict[str, Any]:
        episode = self.session.scalar(
            select(EpisodeRecord)
            .where(EpisodeRecord.id == episode_id)
            .options(selectinload(EpisodeRecord.season))
        )
        if not episode:
            raise ReleaseNotFound("Episode not found")
        entry = self.session.scalar(
            select(WatchEntry).where(
                WatchEntry.user_id == self.user_id,
                WatchEntry.catalog_item_id == episode.season.catalog_item_id,
                WatchEntry.deleted_at.is_(None),
            )
        )
        if not entry:
            raise ReleaseNotFound("Episode not found")
        _materialize_assumed_progress(self.session, entry, today=self.today)
        self.session.execute(
            delete(EpisodeViewing).where(
                EpisodeViewing.episode_id == episode.id,
                EpisodeViewing.entry_id == entry.id,
                EpisodeViewing.user_id == self.user_id,
            )
        )
        self.session.commit()
        return self.detail(entry.id)

    def bulk_season(
        self, season_id: str, *, watched: bool, watched_on: date | None
    ) -> dict[str, Any]:
        season = self.session.scalar(
            select(SeasonRecord)
            .where(SeasonRecord.id == season_id)
            .options(selectinload(SeasonRecord.episodes))
        )
        if not season:
            raise ReleaseNotFound("Season not found")
        entry = self.session.scalar(
            select(WatchEntry).where(
                WatchEntry.user_id == self.user_id,
                WatchEntry.catalog_item_id == season.catalog_item_id,
                WatchEntry.deleted_at.is_(None),
            )
        )
        if not entry:
            raise ReleaseNotFound("Season not found")
        _materialize_assumed_progress(self.session, entry, today=self.today)
        episode_ids = [item.id for item in season.episodes if item.removed_at is None]
        if watched:
            existing = set(
                self.session.scalars(
                    select(EpisodeViewing.episode_id).where(
                        EpisodeViewing.entry_id == entry.id,
                        EpisodeViewing.user_id == self.user_id,
                        EpisodeViewing.episode_id.in_(episode_ids),
                    )
                )
            )
            for episode_id in episode_ids:
                if episode_id not in existing:
                    self.session.add(
                        EpisodeViewing(
                            user_id=self.user_id,
                            episode_id=episode_id,
                            entry_id=entry.id,
                            watched_on=watched_on or self.today,
                        )
                    )
        else:
            self.session.execute(
                delete(EpisodeViewing).where(
                    EpisodeViewing.entry_id == entry.id,
                    EpisodeViewing.user_id == self.user_id,
                    EpisodeViewing.episode_id.in_(episode_ids),
                )
            )
        self.session.commit()
        return self.detail(entry.id)

    def currently_watching(self) -> dict[str, Any]:
        entries = list(
            self.session.scalars(
                select(WatchEntry)
                .join(SeriesTrackingSubscription)
                .where(
                    WatchEntry.user_id == self.user_id,
                    WatchEntry.deleted_at.is_(None),
                    WatchEntry.status.in_(("watching", "rewatching")),
                    SeriesTrackingSubscription.enabled.is_(True),
                )
                .options(selectinload(WatchEntry.catalog_item))
            )
        )
        items = [self.detail(entry.id) for entry in entries]
        upcoming = self.upcoming(days=60, limit=12)["items"]
        return {"items": items, "upcoming": upcoming}

    def active_shows(self, *, days: int = 60) -> dict[str, Any]:
        """Return only series with a provider-confirmed upcoming episode.

        TMDB schedule data can establish an announced air date, but it cannot establish
        that an episode is currently available on a streaming service. Keeping this
        predicate date-based avoids presenting an ended or between-seasons title as active.
        """
        end = self.today + timedelta(days=days)
        schedule_rows = list(
            self.session.execute(
                select(
                    WatchEntry.id,
                    func.min(EpisodeRecord.air_date).label("next_air_date"),
                )
                .select_from(SeasonRecord)
                .join(EpisodeRecord, EpisodeRecord.season_id == SeasonRecord.id)
                .join(
                    WatchEntry,
                    WatchEntry.catalog_item_id == SeasonRecord.catalog_item_id,
                )
                .join(
                    SeriesTrackingSubscription,
                    SeriesTrackingSubscription.entry_id == WatchEntry.id,
                )
                .where(
                    WatchEntry.user_id == self.user_id,
                    SeriesTrackingSubscription.enabled.is_(True),
                    SeasonRecord.removed_at.is_(None),
                    EpisodeRecord.removed_at.is_(None),
                    EpisodeRecord.air_date >= self.today,
                    EpisodeRecord.air_date <= end,
                    or_(
                        SeasonRecord.season_number != 0,
                        SeriesTrackingSubscription.include_specials.is_(True),
                    ),
                )
                .group_by(WatchEntry.id)
                .order_by(func.min(EpisodeRecord.air_date), WatchEntry.id)
            )
        )
        if not schedule_rows:
            return {
                "items": [],
                "total": 0,
                "range": {"start": self.today, "end": end},
                "disclaimer": "Provider air dates, not streaming availability.",
            }
        entry_ids = [entry_id for entry_id, _next_air_date in schedule_rows]
        entries = list(
            self.session.scalars(
                select(WatchEntry)
                .where(
                    WatchEntry.id.in_(entry_ids),
                    WatchEntry.user_id == self.user_id,
                    WatchEntry.deleted_at.is_(None),
                )
                .options(
                    selectinload(WatchEntry.catalog_item),
                    selectinload(WatchEntry.viewing_events),
                )
            )
        )
        by_id = {entry.id: entry for entry in entries}
        ordered = [by_id[entry_id] for entry_id in entry_ids if entry_id in by_id]
        return {
            "items": [serialize_entry(entry, include_events=False) for entry in ordered],
            "total": len(ordered),
            "range": {"start": self.today, "end": end},
            "disclaimer": "Provider air dates, not streaming availability.",
        }

    def upcoming(self, *, days: int = 90, limit: int = 500) -> dict[str, Any]:
        end = self.today + timedelta(days=days)
        rows = list(
            self.session.execute(
                select(EpisodeRecord, SeasonRecord, WatchEntry, CatalogItem)
                .join(SeasonRecord, EpisodeRecord.season_id == SeasonRecord.id)
                .join(CatalogItem, SeasonRecord.catalog_item_id == CatalogItem.id)
                .join(WatchEntry, WatchEntry.catalog_item_id == CatalogItem.id)
                .join(
                    SeriesTrackingSubscription,
                    SeriesTrackingSubscription.entry_id == WatchEntry.id,
                )
                .where(
                    WatchEntry.user_id == self.user_id,
                    SeriesTrackingSubscription.enabled.is_(True),
                    EpisodeRecord.removed_at.is_(None),
                    EpisodeRecord.air_date >= self.today,
                    EpisodeRecord.air_date <= end,
                    or_(
                        SeasonRecord.season_number != 0,
                        SeriesTrackingSubscription.include_specials.is_(True),
                    ),
                )
                .order_by(EpisodeRecord.air_date, CatalogItem.normalized_title)
                .limit(limit)
            )
        )
        return {
            "items": [
                {
                    "entry_id": entry.id,
                    "title": catalog.canonical_title,
                    "season_number": season.season_number,
                    "episode_number": episode.episode_number,
                    "episode_title": episode.title,
                    "air_date": episode.air_date,
                    "kind": "air_date",
                }
                for episode, season, entry, catalog in rows
            ],
            "range": {"start": self.today, "end": end},
            "disclaimer": "Air dates are provider schedule metadata, not streaming availability.",
        }

    def notifications(self, *, include_dismissed: bool = False) -> dict[str, Any]:
        statement = (
            select(ReleaseEvent, WatchEntry, CatalogItem)
            .join(WatchEntry, ReleaseEvent.entry_id == WatchEntry.id)
            .join(CatalogItem, WatchEntry.catalog_item_id == CatalogItem.id)
            .where(ReleaseEvent.user_id == self.user_id)
            .order_by(ReleaseEvent.first_seen_at.desc())
        )
        if not include_dismissed:
            statement = statement.where(ReleaseEvent.dismissed_at.is_(None))
        rows = list(self.session.execute(statement.limit(100)))
        items = [
            {
                "id": event.id,
                "entry_id": event.entry_id,
                "title": catalog.canonical_title,
                "event_type": event.event_type,
                "effective_date": event.effective_date,
                "first_seen_at": event.first_seen_at,
                "read": event.read_at is not None,
                "dismissed": event.dismissed_at is not None,
            }
            for event, _entry, catalog in rows
        ]
        return {"items": items, "unread": sum(not item["read"] for item in items)}

    def update_notification(self, event_id: str, action: str) -> dict[str, Any]:
        event = self.session.scalar(
            select(ReleaseEvent).where(
                ReleaseEvent.id == event_id,
                ReleaseEvent.user_id == self.user_id,
            )
        )
        if not event:
            raise ReleaseNotFound("Release notification not found")
        now = utcnow()
        if action == "read":
            event.read_at = now
        elif action == "unread":
            event.read_at = None
        elif action == "dismiss":
            event.dismissed_at = now
            event.read_at = event.read_at or now
        self.session.commit()
        return self.notifications()


class ReleaseSyncService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        metadata: Any,
        *,
        today_factory,
        interval_minutes: int = 360,
    ):
        self.session_factory = session_factory
        self.metadata = metadata
        self.today_factory = today_factory
        self.interval = timedelta(minutes=interval_minutes)
        self._sync_lock = asyncio.Lock()

    async def sync_entry(
        self,
        entry_id: str,
        *,
        refresh: bool = True,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._sync_lock:
            return await self._sync_entry(entry_id, refresh=refresh, user_id=user_id)

    async def _sync_entry(
        self, entry_id: str, *, refresh: bool = True, user_id: str | None = None
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            entry = _supported_entry(session, entry_id, user_id)
            owner_user_id = entry.user_id
            subscription = session.scalar(
                select(SeriesTrackingSubscription).where(
                    SeriesTrackingSubscription.entry_id == entry.id,
                    SeriesTrackingSubscription.enabled.is_(True),
                )
            )
            if not subscription:
                raise ReleaseConflict("Follow this series before syncing releases")
            identity = _schedule_identity(entry, subscription.provider_preference)
            if not identity:
                raise ReleaseConflict("No supported episode provider identity is available")
            provider, provider_id = identity
            subscription.last_attempt_at = utcnow()
            session.commit()
        try:
            payload = await self.metadata.series_schedule(
                provider, provider_id, refresh=refresh
            )
        except ProviderUnavailable as exc:
            with self.session_factory() as session:
                subscription = session.scalar(
                    select(SeriesTrackingSubscription).where(
                        SeriesTrackingSubscription.entry_id == entry_id
                    )
                )
                subscription.failure_count += 1
                subscription.last_error_code = "provider_unavailable"
                subscription.last_error_message = str(exc)[:300]
                delay = _jittered(
                    min(24 * 60, 15 * (2 ** min(subscription.failure_count - 1, 6)))
                )
                subscription.next_check_at = utcnow() + timedelta(minutes=delay)
                session.commit()
            raise ReleaseProviderError(str(exc)) from exc
        return self._apply(entry_id, payload, user_id=owner_user_id)

    def _apply(self, entry_id: str, payload: dict[str, Any], *, user_id: str) -> dict[str, Any]:
        now = utcnow()
        today = self.today_factory()
        seen_seasons: set[int] = set()
        seen_episodes: set[str] = set()
        with self.session_factory() as session:
            subscription = session.scalar(
                select(SeriesTrackingSubscription)
                .join(WatchEntry, SeriesTrackingSubscription.entry_id == WatchEntry.id)
                .where(
                    SeriesTrackingSubscription.entry_id == entry_id,
                    WatchEntry.user_id == user_id,
                )
            )
            if not subscription:
                raise ReleaseConflict("Series subscription no longer exists")
            provider_series_id = str(payload["provider_series_id"])
            provider_source = str(payload["provider_source"])
            entry = session.scalar(
                select(WatchEntry).where(
                    WatchEntry.id == entry_id,
                    WatchEntry.user_id == user_id,
                )
            )
            if not entry:
                raise ReleaseConflict("Series subscription no longer exists")
            catalog_item_id = entry.catalog_item_id
            for season_data in payload.get("seasons", []):
                number = season_data.get("season_number")
                if not isinstance(number, int):
                    continue
                seen_seasons.add(number)
                season = session.scalar(
                    select(SeasonRecord).where(
                        SeasonRecord.provider_source == provider_source,
                        SeasonRecord.provider_series_id == provider_series_id,
                        SeasonRecord.season_number == number,
                    )
                )
                new_season = season is None
                if new_season:
                    season = SeasonRecord(
                        catalog_item_id=catalog_item_id,
                        provider_source=provider_source,
                        provider_series_id=provider_series_id,
                        season_number=number,
                        fetched_at=now,
                    )
                    session.add(season)
                    session.flush()
                old_air_date = season.air_date
                season.provider_season_id = season_data.get("provider_season_id")
                season.title = season_data.get("title")
                season.overview = season_data.get("overview")
                season.poster_url = season_data.get("poster_url")
                season.air_date = _date(season_data.get("air_date"))
                season.episode_count = season_data.get("episode_count")
                season.provider_status = payload.get("status")
                season.fetched_at = now
                season.removed_at = None
                if new_season:
                    self._event_for_catalog_subscribers(
                        session,
                        catalog_item_id=catalog_item_id,
                        season_number=number,
                        season_id=season.id,
                        event_type="season_announced",
                        effective_date=season.air_date,
                        key=f"season:{provider_series_id}:{number}",
                    )
                elif old_air_date != season.air_date and old_air_date is not None:
                    self._event_for_catalog_subscribers(
                        session,
                        catalog_item_id=catalog_item_id,
                        season_number=number,
                        season_id=season.id,
                        event_type="schedule_changed",
                        effective_date=season.air_date,
                        key=f"season-date:{provider_series_id}:{number}:{season.air_date}",
                    )
                for episode_data in season_data.get("episodes", []):
                    provider_episode_id = str(episode_data.get("provider_episode_id") or "")
                    if not provider_episode_id:
                        continue
                    seen_episodes.add(provider_episode_id)
                    episode = session.scalar(
                        select(EpisodeRecord).where(
                            EpisodeRecord.provider_source == provider_source,
                            EpisodeRecord.provider_episode_id == provider_episode_id,
                        )
                    )
                    new_episode = episode is None
                    if new_episode:
                        episode = EpisodeRecord(
                            season_id=season.id,
                            provider_source=provider_source,
                            provider_episode_id=provider_episode_id,
                            fetched_at=now,
                        )
                        session.add(episode)
                        session.flush()
                    old_date = episode.air_date
                    episode.season_id = season.id
                    episode.episode_number = episode_data.get("episode_number")
                    episode.title = episode_data.get("title")
                    episode.overview = episode_data.get("overview")
                    episode.air_date = _date(episode_data.get("air_date"))
                    episode.runtime_minutes = episode_data.get("runtime_minutes")
                    episode.production_code = episode_data.get("production_code")
                    episode.fetched_at = now
                    episode.removed_at = None
                    if episode.air_date is not None and episode.air_date <= today:
                        self._event_for_catalog_subscribers(
                            session,
                            catalog_item_id=catalog_item_id,
                            season_number=number,
                            season_id=season.id,
                            episode_id=episode.id,
                            event_type="episode_released",
                            effective_date=episode.air_date,
                            key=f"episode:{provider_episode_id}:episode_released",
                        )
                    elif new_episode:
                        self._event_for_catalog_subscribers(
                            session,
                            catalog_item_id=catalog_item_id,
                            season_number=number,
                            season_id=season.id,
                            episode_id=episode.id,
                            event_type="episode_announced",
                            effective_date=episode.air_date,
                            key=f"episode:{provider_episode_id}:episode_announced",
                        )
                    elif old_date != episode.air_date and old_date is not None:
                        self._event_for_catalog_subscribers(
                            session,
                            catalog_item_id=catalog_item_id,
                            season_number=number,
                            season_id=season.id,
                            episode_id=episode.id,
                            event_type="schedule_changed",
                            effective_date=episode.air_date,
                            key=f"episode-date:{provider_episode_id}:{episode.air_date}",
                        )
            existing_seasons = list(
                session.scalars(
                    select(SeasonRecord).where(SeasonRecord.catalog_item_id == catalog_item_id)
                )
            )
            for season in existing_seasons:
                if (
                    season.provider_source != provider_source
                    or season.season_number not in seen_seasons
                ):
                    season.removed_at = now
            existing_episodes = list(
                session.scalars(
                    select(EpisodeRecord)
                    .join(SeasonRecord)
                    .where(SeasonRecord.catalog_item_id == catalog_item_id)
                )
            )
            for episode in existing_episodes:
                if (
                    episode.provider_source != provider_source
                    or episode.provider_episode_id not in seen_episodes
                ):
                    episode.removed_at = now
            subscription.last_success_at = now
            subscription.last_attempt_at = now
            subscription.last_error_code = None
            subscription.last_error_message = None
            subscription.failure_count = 0
            subscription.next_check_at = now + self.interval
            subscription.provider_cursor = {
                "provider": provider_source,
                "series_id": provider_series_id,
            }
            session.commit()
            return ReleaseTrackingService(session, today=today, trusted_user_id=user_id).detail(
                entry_id
            )

    @classmethod
    def _event_for_catalog_subscribers(
        cls,
        session: Session,
        *,
        catalog_item_id: str,
        season_number: int,
        event_type: str,
        effective_date: date | None,
        key: str,
        season_id: str | None = None,
        episode_id: str | None = None,
    ) -> None:
        """Fan a shared schedule change out to established private subscriptions."""
        subscriptions = session.scalars(
            select(SeriesTrackingSubscription)
            .join(WatchEntry, SeriesTrackingSubscription.entry_id == WatchEntry.id)
            .where(
                WatchEntry.catalog_item_id == catalog_item_id,
                WatchEntry.deleted_at.is_(None),
                SeriesTrackingSubscription.enabled.is_(True),
                SeriesTrackingSubscription.last_success_at.is_not(None),
            )
        )
        for target in subscriptions:
            if season_number == 0 and not target.include_specials:
                continue
            cls._event(
                session,
                target,
                entry_id=target.entry_id,
                event_type=event_type,
                effective_date=effective_date,
                key=key,
                season_id=season_id,
                episode_id=episode_id,
            )

    @staticmethod
    def _event(
        session: Session,
        subscription: SeriesTrackingSubscription,
        *,
        entry_id: str,
        event_type: str,
        effective_date: date | None,
        key: str,
        season_id: str | None = None,
        episode_id: str | None = None,
    ) -> None:
        if event_type.startswith("episode") and not subscription.notify_new_episode:
            return
        if event_type == "season_announced" and not subscription.notify_new_season:
            return
        entry = session.scalar(select(WatchEntry).where(WatchEntry.id == entry_id))
        if not entry:
            return
        existing = session.scalar(
            select(ReleaseEvent).where(
                ReleaseEvent.user_id == entry.user_id,
                ReleaseEvent.dedupe_key == key,
            )
        )
        if existing:
            existing.updated_at = utcnow()
            existing.effective_date = effective_date
            return
        session.add(
            ReleaseEvent(
                user_id=entry.user_id,
                entry_id=entry_id,
                season_id=season_id,
                episode_id=episode_id,
                event_type=event_type,
                effective_date=effective_date,
                dedupe_key=key,
            )
        )

    async def sync_due(
        self,
        *,
        limit: int | None = 20,
        force: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        with self.session_factory() as session:
            # Choosing a library release check opts verified TV/anime entries into the
            # local schedule cache. An explicitly disabled subscription remains disabled.
            candidate_statement = (
                select(WatchEntry)
                .join(CatalogItem, WatchEntry.catalog_item_id == CatalogItem.id)
                .outerjoin(
                    SeriesTrackingSubscription,
                    SeriesTrackingSubscription.entry_id == WatchEntry.id,
                )
                .where(
                    WatchEntry.deleted_at.is_(None),
                    CatalogItem.media_type.in_(("tv", "anime")),
                    or_(
                        CatalogItem.tmdb_tv_id.is_not(None),
                        CatalogItem.external_identities.any(
                            ExternalIdentity.namespace == "tvmaze"
                        ),
                    ),
                    SeriesTrackingSubscription.id.is_(None),
                )
                .order_by(WatchEntry.updated_at.desc(), WatchEntry.id)
            )
            if user_id is not None:
                candidate_statement = candidate_statement.where(WatchEntry.user_id == user_id)
            candidates = list(session.scalars(candidate_statement))
            for entry in candidates:
                session.add(
                    SeriesTrackingSubscription(
                        entry_id=entry.id,
                        enabled=True,
                        notify_new_episode=False,
                        notify_new_season=False,
                        include_specials=False,
                        provider_preference=(_schedule_identity(entry) or ("tmdb_tv", ""))[0],
                        next_check_at=now,
                    )
                )
            if candidates:
                session.commit()
            statement = (
                select(SeriesTrackingSubscription.entry_id)
                .join(WatchEntry, SeriesTrackingSubscription.entry_id == WatchEntry.id)
                .where(SeriesTrackingSubscription.enabled.is_(True))
            )
            if user_id is not None:
                statement = statement.where(WatchEntry.user_id == user_id)
            if not force:
                statement = statement.where(
                    or_(
                        SeriesTrackingSubscription.next_check_at.is_(None),
                        SeriesTrackingSubscription.next_check_at <= now,
                    )
                )
            statement = statement.order_by(
                SeriesTrackingSubscription.last_success_at.is_not(None),
                SeriesTrackingSubscription.next_check_at,
                SeriesTrackingSubscription.entry_id,
            )
            if limit is not None:
                statement = statement.limit(limit)
            ids = list(session.scalars(statement))
        result = {"total": len(ids), "synced": 0, "failed": 0}
        for entry_id in ids:
            try:
                await self.sync_entry(entry_id, refresh=True, user_id=user_id)
                result["synced"] += 1
            except (ReleaseConflict, ReleaseProviderError):
                result["failed"] += 1
        return result


class ReleaseScheduler:
    JOB_NAME = "release-sync"

    def __init__(
        self,
        sync_service: ReleaseSyncService,
        session_factory: sessionmaker[Session],
        *,
        interval_minutes: int,
        batch_size: int,
    ):
        self.sync_service = sync_service
        self.session_factory = session_factory
        self.interval_seconds = max(60, interval_minutes * 60)
        self.batch_size = batch_size
        self.owner_id = str(uuid4())
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            # Recreate loop-bound state when an embedded app is restarted.
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def _acquire(self) -> bool:
        now = utcnow()
        lease = now + timedelta(minutes=10)
        with self.session_factory() as session:
            job = session.scalar(select(SyncJob).where(SyncJob.name == self.JOB_NAME))
            if not job:
                job = SyncJob(
                    name=self.JOB_NAME,
                    state="idle",
                    next_run_at=now,
                    updated_at=now,
                )
                session.add(job)
                session.commit()
            updated = session.execute(
                update(SyncJob)
                .where(
                    SyncJob.id == job.id,
                    or_(SyncJob.lease_until.is_(None), SyncJob.lease_until < now),
                )
                .values(
                    state="running",
                    owner_id=self.owner_id,
                    lease_until=lease,
                    last_attempt_at=now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()
            return bool(updated.rowcount)

    def _finish(self, *, error: Exception | None = None) -> None:
        now = utcnow()
        with self.session_factory() as session:
            job = session.scalar(
                select(SyncJob).where(
                    SyncJob.name == self.JOB_NAME, SyncJob.owner_id == self.owner_id
                )
            )
            if not job:
                return
            job.state = "failed" if error else "idle"
            job.lease_until = None
            job.owner_id = None
            job.updated_at = now
            if error:
                job.failure_count += 1
                job.last_error_code = type(error).__name__
                job.last_error_message = "Scheduled release sync failed safely."
                delay = _jittered(
                    min(self.interval_seconds, 60 * (2 ** min(job.failure_count, 6)))
                )
                job.next_run_at = now + timedelta(seconds=delay)
            else:
                job.failure_count = 0
                job.last_success_at = now
                job.last_error_code = None
                job.last_error_message = None
                job.next_run_at = now + timedelta(seconds=self.interval_seconds)
            session.commit()

    async def run_once(
        self, *, force: bool = False, user_id: str | None = None
    ) -> dict[str, Any]:
        if not self._acquire():
            return {"status": "already_running", "total": 0, "synced": 0, "failed": 0}
        try:
            # A user-triggered "Check library now" must cover the whole eligible
            # library. Background runs retain the configured batch cap so routine
            # checks remain gentle on provider APIs.
            result = await self.sync_service.sync_due(
                limit=None if force else self.batch_size,
                force=force,
                user_id=user_id,
            )
        except Exception as exc:
            self._finish(error=exc)
            raise
        self._finish()
        return {"status": "completed", **result}

    async def _run(self) -> None:
        try:
            await self.run_once()
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
                except TimeoutError:
                    await self.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Release scheduler stopped after a safe failure")

    def status(self) -> dict[str, Any]:
        scheduler_running = self._task is not None and not self._task.done()
        with self.session_factory() as session:
            job = session.scalar(select(SyncJob).where(SyncJob.name == self.JOB_NAME))
            if not job:
                return {
                    "state": "idle",
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "next_run_at": None,
                    "last_error_code": None,
                    "last_error_message": None,
                    "scheduler_running": scheduler_running,
                }
            return {
                "state": job.state,
                "last_attempt_at": job.last_attempt_at,
                "last_success_at": job.last_success_at,
                "next_run_at": job.next_run_at,
                "last_error_code": job.last_error_code,
                "last_error_message": job.last_error_message,
                "scheduler_running": scheduler_running,
            }


def ical_snapshot(items: list[dict[str, Any]], *, generated_at: datetime | None = None) -> str:
    generated = (generated_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")

    def clean(value: Any) -> str:
        return (
            str(value or "")
            .replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace(",", "\\,")
            .replace(";", "\\;")
        )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Personal Media Tracker//Release Schedule//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Personal Media Tracker — Upcoming",
    ]
    for item in items:
        air_date = item.get("air_date")
        if not air_date:
            continue
        day = air_date.isoformat().replace("-", "")
        summary = f"{item['title']} — S{item['season_number']:02d}E{int(item.get('episode_number') or 0):02d}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:pmt-{clean(item['entry_id'])}-{day}-{item.get('season_number')}-{item.get('episode_number')}@local",
                f"DTSTAMP:{generated}",
                f"DTSTART;VALUE=DATE:{day}",
                f"SUMMARY:{clean(summary)}",
                "DESCRIPTION:Provider air date. This does not claim streaming availability.",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
