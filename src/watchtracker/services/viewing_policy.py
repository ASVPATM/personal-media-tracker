from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from watchtracker.models import (
    EpisodeViewing,
    PlaybackBookmark,
    ProviderProgressClaim,
    ViewingCorrection,
    ViewingCycle,
    ViewingEvent,
    WatchEntry,
    utcnow,
)

COMPLETION_THRESHOLD = 0.90
MINIMUM_COMPLETION_THRESHOLD = 0.80
MAXIMUM_COMPLETION_THRESHOLD = 0.95
CROSS_PROVIDER_DUPLICATE_WINDOW = timedelta(hours=6)

PlaybackEvent = Literal["start", "pause", "progress", "stop", "ended", "completed"]
PlaybackDecision = Literal["ignore", "bookmark", "complete", "review"]


@dataclass(frozen=True)
class PlaybackObservation:
    event: PlaybackEvent
    position_seconds: float = 0
    duration_seconds: float = 0
    active_seconds: float | None = None
    strong_completion: bool = False
    observed_at: datetime | None = None


def noise_floor_seconds(duration_seconds: float) -> float:
    return min(120.0, max(30.0, max(duration_seconds, 0.0) * 0.02))


def resume_floor_seconds(duration_seconds: float) -> float:
    return min(120.0, max(30.0, max(duration_seconds, 0.0) * 0.05))


def minimum_active_seconds(duration_seconds: float) -> float:
    return min(600.0, max(duration_seconds, 0.0) * 0.25)


def evaluate_playback_observation(
    observation: PlaybackObservation, *, completion_threshold: float = COMPLETION_THRESHOLD
) -> PlaybackDecision:
    """Return a deterministic decision without mutating user history."""

    threshold = max(
        MINIMUM_COMPLETION_THRESHOLD,
        min(float(completion_threshold), MAXIMUM_COMPLETION_THRESHOLD),
    )
    position = max(float(observation.position_seconds or 0), 0.0)
    duration = max(float(observation.duration_seconds or 0), 0.0)
    active = (
        None
        if observation.active_seconds is None
        else max(float(observation.active_seconds), 0.0)
    )
    if observation.event == "completed" and observation.strong_completion:
        return "complete"
    if position < noise_floor_seconds(duration):
        return "ignore"
    if observation.event in {"start", "pause", "progress"}:
        return "bookmark" if position >= resume_floor_seconds(duration) else "ignore"
    if observation.event not in {"stop", "ended", "completed"}:
        return "ignore"
    if duration <= 0 or position / duration < threshold:
        return "bookmark" if position >= resume_floor_seconds(duration) else "ignore"
    if observation.strong_completion:
        return "complete"
    if active is None or active < minimum_active_seconds(duration):
        return "review"
    return "complete"


def _aware(value: datetime | None) -> datetime:
    value = value or utcnow()
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ViewingReducer:
    """The only service allowed to convert evidence into viewing history.

    Callers own the surrounding transaction. Methods flush when IDs/projections are
    required but never commit.
    """

    def __init__(self, session: Session, *, user_id: str):
        self.session = session
        self.user_id = user_id

    def _active_cycle(self, entry_id: str, *, kind: str | None = None) -> ViewingCycle | None:
        statement = select(ViewingCycle).where(
            ViewingCycle.user_id == self.user_id,
            ViewingCycle.entry_id == entry_id,
            ViewingCycle.state == "active",
            ViewingCycle.deleted_at.is_(None),
        )
        if kind:
            statement = statement.where(ViewingCycle.kind == kind)
        return self.session.scalar(statement.order_by(ViewingCycle.created_at.desc()))

    def ensure_initial_cycle(self, entry: WatchEntry) -> ViewingCycle:
        cycle = self.session.scalar(
            select(ViewingCycle).where(
                ViewingCycle.user_id == self.user_id,
                ViewingCycle.entry_id == entry.id,
                ViewingCycle.kind == "initial",
                ViewingCycle.deleted_at.is_(None),
            )
        )
        if cycle:
            return cycle
        cycle = ViewingCycle(
            user_id=self.user_id,
            entry_id=entry.id,
            kind="initial",
            scope="title",
            state="active",
            initiated_by="policy",
            target_episode_ids=[],
        )
        self.session.add(cycle)
        self.session.flush()
        return cycle

    def start_rewatch(
        self,
        entry: WatchEntry,
        *,
        scope: Literal["title", "season", "episode_range"] = "title",
        target_episode_ids: list[str] | None = None,
        scope_data: dict[str, object] | None = None,
        initiated_by: str = "manual",
        started_at: datetime | None = None,
    ) -> ViewingCycle:
        active = self._active_cycle(entry.id, kind="rewatch")
        if active:
            active.state = "closed"
            active.ended_at = _aware(started_at)
            active.updated_at = _aware(started_at)
            active.version += 1
        cycle = ViewingCycle(
            user_id=self.user_id,
            entry_id=entry.id,
            kind="rewatch",
            scope=scope,
            scope_data=dict(scope_data or {}),
            target_episode_ids=sorted(set(target_episode_ids or [])),
            state="active",
            initiated_by=initiated_by,
            started_at=_aware(started_at),
        )
        self.session.add(cycle)
        entry.status = "rewatching"
        entry.updated_at = utcnow()
        entry.version = int(entry.version or 0) + 1
        self.session.flush()
        return cycle

    @staticmethod
    def _provider_name(source_event_key: str | None) -> str | None:
        return (
            source_event_key.split(":", 1)[0]
            if source_event_key and ":" in source_event_key
            else None
        )

    def _merge_title_duplicate(
        self,
        entry: WatchEntry,
        *,
        source_event_key: str | None,
        occurred_at: datetime,
    ) -> ViewingEvent | None:
        if not source_event_key:
            return None
        exact = next(
            (
                row
                for row in self.session.scalars(
                    select(ViewingEvent).where(
                        ViewingEvent.user_id == self.user_id,
                        ViewingEvent.entry_id == entry.id,
                        ViewingEvent.deleted_at.is_(None),
                    )
                )
                if source_event_key in (row.source_event_keys or [])
            ),
            None,
        )
        if exact:
            return exact
        provider = self._provider_name(source_event_key)
        if not provider:
            return None
        candidates = self.session.scalars(
            select(ViewingEvent)
            .where(
                ViewingEvent.user_id == self.user_id,
                ViewingEvent.entry_id == entry.id,
                ViewingEvent.source == "integration",
                ViewingEvent.deleted_at.is_(None),
                ViewingEvent.created_at >= occurred_at - CROSS_PROVIDER_DUPLICATE_WINDOW,
                ViewingEvent.created_at <= occurred_at + CROSS_PROVIDER_DUPLICATE_WINDOW,
            )
            .order_by(ViewingEvent.created_at.desc())
        )
        for candidate in candidates:
            existing_providers = {
                self._provider_name(key) for key in candidate.source_event_keys or []
            }
            if provider not in existing_providers:
                candidate.source_event_keys = sorted(
                    set((candidate.source_event_keys or []) + [source_event_key])
                )
                candidate.updated_at = utcnow()
                return candidate
        return None

    def record_title_completion(
        self,
        entry: WatchEntry,
        *,
        viewed_on: date | None,
        source: str,
        source_key: str | None = None,
        source_event_key: str | None = None,
        confidence: float = 1.0,
        explicit_rewatch: bool = False,
        occurred_at: datetime | None = None,
    ) -> tuple[ViewingEvent, Literal["created", "merged", "duplicate"]]:
        if source_key:
            exact = self.session.scalar(
                select(ViewingEvent).where(
                    ViewingEvent.user_id == self.user_id,
                    ViewingEvent.source == source,
                    ViewingEvent.source_key == source_key,
                )
            )
            if exact:
                return exact, "duplicate"
        event_time = _aware(occurred_at)
        merged = self._merge_title_duplicate(
            entry, source_event_key=source_event_key, occurred_at=event_time
        )
        if merged:
            return merged, "merged"

        active_rewatch = self._active_cycle(entry.id, kind="rewatch")
        if explicit_rewatch and entry.view_count > 0 and active_rewatch is None:
            active_rewatch = self.start_rewatch(
                entry, initiated_by=source, started_at=event_time
            )
        if entry.view_count <= 0:
            cycle = self.ensure_initial_cycle(entry)
            occurrence_kind = "completion"
        elif active_rewatch:
            cycle = active_rewatch
            occurrence_kind = "completion"
        else:
            cycle = None
            occurrence_kind = "replay"
        event = ViewingEvent(
            user_id=self.user_id,
            entry=entry,
            cycle_id=cycle.id if cycle else None,
            viewed_on=viewed_on,
            source=source,
            source_key=source_key,
            occurrence_kind=occurrence_kind,
            confidence=max(0.0, min(float(confidence), 1.0)),
            source_event_keys=[source_event_key] if source_event_key else [],
            created_at=event_time,
            updated_at=event_time,
        )
        self.session.add(event)
        entry.view_count = int(entry.view_count or 0) + 1
        if viewed_on and (entry.watched_date is None or viewed_on >= entry.watched_date):
            entry.watched_date = viewed_on
        entry.status = "watched"
        entry.updated_at = utcnow()
        if cycle:
            cycle.state = "completed"
            cycle.ended_at = event_time
            cycle.updated_at = event_time
            cycle.version += 1
        self.session.flush()
        return event, "created"

    def record_episode_completion(
        self,
        entry: WatchEntry,
        *,
        episode_id: str,
        watched_on: date | None,
        source: str,
        source_key: str | None = None,
        source_event_key: str | None = None,
        confidence: float = 1.0,
        occurred_at: datetime | None = None,
    ) -> tuple[EpisodeViewing, Literal["created", "duplicate"]]:
        if source_key:
            exact = self.session.scalar(
                select(EpisodeViewing).where(
                    EpisodeViewing.user_id == self.user_id,
                    EpisodeViewing.source == source,
                    EpisodeViewing.source_key == source_key,
                )
            )
            if exact:
                return exact, "duplicate"
        event_time = _aware(occurred_at)
        provider = self._provider_name(source_event_key)
        if source == "integration" and provider:
            candidates = self.session.scalars(
                select(EpisodeViewing).where(
                    EpisodeViewing.user_id == self.user_id,
                    EpisodeViewing.entry_id == entry.id,
                    EpisodeViewing.episode_id == episode_id,
                    EpisodeViewing.source == "integration",
                    EpisodeViewing.deleted_at.is_(None),
                    EpisodeViewing.created_at >= event_time - CROSS_PROVIDER_DUPLICATE_WINDOW,
                    EpisodeViewing.created_at <= event_time + CROSS_PROVIDER_DUPLICATE_WINDOW,
                )
            )
            for candidate in candidates:
                existing_providers = {
                    self._provider_name(key) for key in candidate.source_event_keys or []
                }
                if source_event_key in (candidate.source_event_keys or []):
                    return candidate, "duplicate"
                if provider not in existing_providers:
                    candidate.source_event_keys = sorted(
                        set((candidate.source_event_keys or []) + [source_event_key])
                    )
                    candidate.updated_at = utcnow()
                    return candidate, "duplicate"
        prior = self.session.scalar(
            select(EpisodeViewing).where(
                EpisodeViewing.user_id == self.user_id,
                EpisodeViewing.entry_id == entry.id,
                EpisodeViewing.episode_id == episode_id,
                EpisodeViewing.deleted_at.is_(None),
            )
        )
        rewatch = self._active_cycle(entry.id, kind="rewatch")
        cycle = rewatch or (None if prior else self.ensure_initial_cycle(entry))
        occurrence_kind = "completion" if not prior or rewatch else "replay"
        event = EpisodeViewing(
            user_id=self.user_id,
            entry_id=entry.id,
            episode_id=episode_id,
            cycle_id=cycle.id if cycle else None,
            watched_on=watched_on,
            source=source,
            source_key=source_key,
            occurrence_kind=occurrence_kind,
            confidence=max(0.0, min(float(confidence), 1.0)),
            source_event_keys=[source_event_key] if source_event_key else [],
            created_at=event_time,
            updated_at=event_time,
        )
        self.session.add(event)
        self.session.flush()
        unique_count = self.session.scalar(
            select(func.count(func.distinct(EpisodeViewing.episode_id))).where(
                EpisodeViewing.user_id == self.user_id,
                EpisodeViewing.entry_id == entry.id,
                EpisodeViewing.deleted_at.is_(None),
            )
        )
        entry.episode_progress_count = int(unique_count or 0)
        entry.episode_progress_explicit = True
        entry.updated_at = utcnow()
        if rewatch and rewatch.target_episode_ids:
            covered = set(
                self.session.scalars(
                    select(EpisodeViewing.episode_id).where(
                        EpisodeViewing.user_id == self.user_id,
                        EpisodeViewing.cycle_id == rewatch.id,
                        EpisodeViewing.deleted_at.is_(None),
                    )
                )
            )
            if set(rewatch.target_episode_ids) <= covered:
                rewatch.state = "completed"
                rewatch.ended_at = event_time
                rewatch.updated_at = event_time
                rewatch.version += 1
                if rewatch.scope != "title":
                    entry.status = "watched"
        return event, "created"

    def record_progress_claim(
        self,
        entry: WatchEntry,
        *,
        provider: str,
        source_key: str,
        claim: dict[str, object],
        accepted_values: dict[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> ProviderProgressClaim:
        existing = self.session.scalar(
            select(ProviderProgressClaim).where(
                ProviderProgressClaim.user_id == self.user_id,
                ProviderProgressClaim.provider == provider,
                ProviderProgressClaim.source_key == source_key,
            )
        )
        if existing:
            return existing
        row = ProviderProgressClaim(
            user_id=self.user_id,
            entry_id=entry.id,
            provider=provider,
            source_key=source_key,
            claim=dict(claim),
            accepted_values=dict(accepted_values or {}),
            observed_at=_aware(observed_at),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def accept_progress_claim(
        self,
        entry: WatchEntry,
        *,
        provider: str,
        source_key: str,
        episode_progress_count: int | None,
        repeat_count: int | None,
        completed_status: bool,
        observed_at: datetime | None = None,
    ) -> tuple[ProviderProgressClaim, dict[str, int]]:
        """Fill blank compatibility projections without inventing occurrences."""

        claim_values: dict[str, int] = {}
        accepted: dict[str, int] = {}
        if episode_progress_count is not None:
            claim_values["episode_progress_count"] = episode_progress_count
            if entry.episode_progress_count is None:
                entry.episode_progress_count = episode_progress_count
                entry.episode_progress_explicit = True
                accepted["episode_progress_count"] = episode_progress_count
        if repeat_count is not None:
            claim_values["repeat_count"] = repeat_count
            expected_views = repeat_count + (1 if completed_status else 0)
            if entry.view_count == 0:
                entry.view_count = expected_views
                accepted["view_count"] = expected_views
        row = self.record_progress_claim(
            entry,
            provider=provider,
            source_key=source_key,
            claim=claim_values,
            accepted_values=accepted,
            observed_at=observed_at,
        )
        if accepted:
            entry.updated_at = utcnow()
        return row, accepted

    def apply_observation(
        self,
        entry: WatchEntry,
        observation: PlaybackObservation,
        *,
        source: str,
        source_key: str,
        source_event_key: str,
        episode_id: str | None = None,
        completion_threshold: float = COMPLETION_THRESHOLD,
    ) -> PlaybackDecision:
        decision = evaluate_playback_observation(
            observation, completion_threshold=completion_threshold
        )
        observed_at = _aware(observation.observed_at)
        if decision == "bookmark":
            bookmark = self.session.scalar(
                select(PlaybackBookmark).where(
                    PlaybackBookmark.user_id == self.user_id,
                    PlaybackBookmark.source == source,
                    PlaybackBookmark.source_key == source_key,
                )
            )
            if bookmark is None:
                bookmark = PlaybackBookmark(
                    user_id=self.user_id,
                    entry_id=entry.id,
                    episode_id=episode_id,
                    source=source,
                    source_key=source_key,
                    position_seconds=observation.position_seconds,
                    duration_seconds=observation.duration_seconds,
                    observed_at=observed_at,
                    expires_at=observed_at + timedelta(days=90),
                )
                self.session.add(bookmark)
            else:
                bookmark.position_seconds = observation.position_seconds
                bookmark.duration_seconds = observation.duration_seconds
                bookmark.observed_at = observed_at
                bookmark.updated_at = utcnow()
                bookmark.deleted_at = None
                bookmark.version += 1
        elif decision == "complete":
            watched_on = observed_at.date() if observation.observed_at else None
            if episode_id:
                self.record_episode_completion(
                    entry,
                    episode_id=episode_id,
                    watched_on=watched_on,
                    source=source,
                    source_key=source_key,
                    source_event_key=source_event_key,
                    confidence=1.0 if observation.strong_completion else 0.9,
                    occurred_at=observed_at,
                )
            else:
                self.record_title_completion(
                    entry,
                    viewed_on=watched_on,
                    source=source,
                    source_key=source_key,
                    source_event_key=source_event_key,
                    confidence=1.0 if observation.strong_completion else 0.9,
                    occurred_at=observed_at,
                )
        self.session.flush()
        return decision

    def tombstone_title_occurrence(
        self, entry: WatchEntry, event: ViewingEvent, *, reason: str = "user_undo"
    ) -> None:
        if event.deleted_at is not None:
            return
        before = {"deleted_at": None, "view_count": entry.view_count}
        event.deleted_at = utcnow()
        event.updated_at = utcnow()
        entry.view_count = max(int(entry.view_count or 0) - 1, 0)
        remaining_dates = list(
            self.session.scalars(
                select(ViewingEvent.viewed_on).where(
                    ViewingEvent.user_id == self.user_id,
                    ViewingEvent.entry_id == entry.id,
                    ViewingEvent.id != event.id,
                    ViewingEvent.deleted_at.is_(None),
                    ViewingEvent.viewed_on.is_not(None),
                )
            )
        )
        entry.watched_date = max(remaining_dates) if remaining_dates else None
        if entry.view_count == 0 and entry.status == "watched":
            entry.status = "plan_to_watch"
        entry.updated_at = utcnow()
        entry.version = int(entry.version or 0) + 1
        self.session.add(
            ViewingCorrection(
                user_id=self.user_id,
                entry_id=entry.id,
                target_type="viewing",
                target_id=event.id,
                action="tombstone",
                before_value=before,
                after_value={
                    "deleted_at": event.deleted_at.isoformat(),
                    "view_count": entry.view_count,
                },
                reason=reason,
            )
        )
        self.session.flush()

    def tombstone_episode_occurrences(
        self, entry: WatchEntry, *, episode_ids: set[str], reason: str = "user_undo"
    ) -> int:
        rows = list(
            self.session.scalars(
                select(EpisodeViewing).where(
                    EpisodeViewing.user_id == self.user_id,
                    EpisodeViewing.entry_id == entry.id,
                    EpisodeViewing.episode_id.in_(episode_ids),
                    EpisodeViewing.deleted_at.is_(None),
                )
            )
        )
        now = utcnow()
        for row in rows:
            row.deleted_at = now
            row.updated_at = now
            self.session.add(
                ViewingCorrection(
                    user_id=self.user_id,
                    entry_id=entry.id,
                    target_type="episode_viewing",
                    target_id=row.id,
                    action="tombstone",
                    before_value={"deleted_at": None, "episode_id": row.episode_id},
                    after_value={"deleted_at": now.isoformat(), "episode_id": row.episode_id},
                    reason=reason,
                )
            )
        remaining = self.session.scalar(
            select(func.count(func.distinct(EpisodeViewing.episode_id))).where(
                EpisodeViewing.user_id == self.user_id,
                EpisodeViewing.entry_id == entry.id,
                EpisodeViewing.deleted_at.is_(None),
                EpisodeViewing.episode_id.not_in(episode_ids),
            )
        )
        entry.episode_progress_explicit = True
        entry.episode_progress_count = int(remaining or 0)
        entry.updated_at = now
        entry.version = int(entry.version or 0) + 1
        self.session.flush()
        return len(rows)
