from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchtracker.db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("provider_source", "provider_id", name="uq_catalog_provider_id"),
        Index("ix_catalog_fallback", "normalized_title", "release_year", "media_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    release_year: Mapped[int | None] = mapped_column(Integer)
    release_date: Mapped[date | None] = mapped_column(Date)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    provider_format: Mapped[str | None] = mapped_column(String(50))
    provider_source: Mapped[str | None] = mapped_column(String(30))
    provider_id: Mapped[str | None] = mapped_column(String(80))
    tmdb_movie_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    tmdb_tv_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    anilist_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    mal_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    poster_url: Mapped[str | None] = mapped_column(Text)
    overview: Mapped[str | None] = mapped_column(Text)
    provider_genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    normalized_genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    inferred_subgenres: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    country: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(30))
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    episode_count: Mapped[int | None] = mapped_column(Integer)
    public_score: Mapped[float | None] = mapped_column(Float)
    taste_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_source: Mapped[str] = mapped_column(String(50), default="manual")
    metadata_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inference_version: Mapped[str] = mapped_column(String(20), default="1.0")
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    entry: Mapped[WatchEntry | None] = relationship(
        back_populates="catalog_item", uselist=False
    )


class WatchEntry(Base):
    __tablename__ = "watch_entries"
    __table_args__ = (
        CheckConstraint("view_count >= 0", name="ck_entry_view_count"),
        CheckConstraint(
            "personal_rating IS NULL OR (personal_rating >= 1 AND personal_rating <= 10)",
            name="ck_entry_rating_range",
        ),
        Index("ix_entry_status_deleted", "status", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="watched", index=True)
    personal_rating: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    user_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_date: Mapped[date | None] = mapped_column(Date)
    finished_date: Mapped[date | None] = mapped_column(Date)
    watched_date: Mapped[date | None] = mapped_column(Date)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    genre_additions: Mapped[list[str]] = mapped_column(JSON, default=list)
    genre_removals: Mapped[list[str]] = mapped_column(JSON, default=list)
    subgenre_additions: Mapped[list[str]] = mapped_column(JSON, default=list)
    subgenre_removals: Mapped[list[str]] = mapped_column(JSON, default=list)
    import_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    catalog_item: Mapped[CatalogItem] = relationship(back_populates="entry")
    viewing_events: Mapped[list[ViewingEvent]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="ViewingEvent.created_at"
    )
    rating_assessments: Mapped[list[RatingAssessment]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    series_subscription: Mapped[SeriesTrackingSubscription | None] = relationship(
        back_populates="entry", cascade="all, delete-orphan", uselist=False
    )
    seasons: Mapped[list[SeasonRecord]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    @property
    def rewatch_count(self) -> int:
        return max(self.view_count - 1, 0)


class ViewingEvent(Base):
    __tablename__ = "viewing_events"
    __table_args__ = (
        UniqueConstraint("source", "source_key", name="uq_viewing_source_key"),
        Index("ix_viewing_entry_date", "entry_id", "viewed_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    viewed_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    source_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entry: Mapped[WatchEntry] = relationship(back_populates="viewing_events")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity_time", "entity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), default="watch_entry")
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="ui")
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportPreviewRecord(Base):
    __tablename__ = "import_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    import_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportHistory(Base):
    __tablename__ = "import_history"
    __table_args__ = (UniqueConstraint("source_hash", name="uq_import_history_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    import_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RatingAssessment(Base):
    __tablename__ = "rating_assessments"
    __table_args__ = (
        CheckConstraint(
            "state IN ('draft', 'completed', 'superseded')",
            name="ck_rating_assessment_state",
        ),
        CheckConstraint("version >= 1", name="ck_rating_assessment_version"),
        Index("ix_rating_assessment_entry_state", "entry_id", "state", "completed_at"),
        Index(
            "uq_rating_assessment_active_draft",
            "entry_id",
            "rubric_version",
            unique=True,
            sqlite_where=sql_text("state = 'draft'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(30), default="guided_v1")
    rubric_version: Mapped[str] = mapped_column(String(40), default="guided-rubric-v1")
    state: Mapped[str] = mapped_column(String(20), default="draft")
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    private_reflection: Mapped[str | None] = mapped_column(Text)
    rubric_score: Mapped[float | None] = mapped_column(Float)
    rubric_coverage: Mapped[float | None] = mapped_column(Float)
    suggested_rating: Mapped[float | None] = mapped_column(Float)
    final_rating_snapshot: Mapped[float | None] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entry: Mapped[WatchEntry] = relationship(back_populates="rating_assessments")


class RatingComparison(Base):
    __tablename__ = "rating_comparisons"
    __table_args__ = (
        CheckConstraint("entry_low_id < entry_high_id", name="ck_rating_pair_order"),
        CheckConstraint(
            "displayed_left_entry_id IN (entry_low_id, entry_high_id)",
            name="ck_rating_pair_left_member",
        ),
        CheckConstraint(
            "result IN ('low', 'high', 'tie', 'skip')",
            name="ck_rating_comparison_result",
        ),
        UniqueConstraint("entry_low_id", "entry_high_id", name="uq_rating_comparison_pair"),
        Index("ix_rating_comparison_updated", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_low_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    entry_high_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    displayed_left_entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(40), default="overall_preference")
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    selection_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), default="advanced-ranking-v1")
    skipped_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RatingRefinementRun(Base):
    __tablename__ = "rating_refinement_runs"
    __table_args__ = (
        CheckConstraint("scope IN ('focused', 'full')", name="ck_rating_refinement_scope"),
        CheckConstraint(
            "state IN ('active', 'completed', 'cancelled')",
            name="ck_rating_refinement_state",
        ),
        CheckConstraint(
            "stage IN ('comparisons', 'assessments', 'complete')",
            name="ck_rating_refinement_stage",
        ),
        CheckConstraint(
            "comparison_target >= 0 AND comparisons_completed >= 0",
            name="ck_rating_refinement_comparison_counts",
        ),
        CheckConstraint(
            "assessment_target >= 0 AND assessments_completed >= 0",
            name="ck_rating_refinement_assessment_counts",
        ),
        Index("ix_rating_refinement_state_updated", "state", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default="comparisons", nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(40), nullable=False)
    ranking_version: Mapped[str] = mapped_column(String(40), nullable=False)
    target_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    completed_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    completed_pair_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    comparison_target: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comparisons_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assessment_target: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assessments_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeriesTrackingSubscription(Base):
    __tablename__ = "series_tracking_subscriptions"
    __table_args__ = (
        CheckConstraint("failure_count >= 0", name="ck_series_tracking_failure_count"),
        Index("ix_series_tracking_due", "enabled", "next_check_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_new_episode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_new_season: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_specials: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    region: Mapped[str | None] = mapped_column(String(10))
    provider_preference: Mapped[str | None] = mapped_column(String(30))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(300))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    entry: Mapped[WatchEntry] = relationship(back_populates="series_subscription")


class SeasonRecord(Base):
    __tablename__ = "season_records"
    __table_args__ = (
        UniqueConstraint(
            "provider_source",
            "provider_series_id",
            "season_number",
            name="uq_season_provider_number",
        ),
        Index("ix_season_entry_number", "entry_id", "season_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    provider_source: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_series_id: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_season_id: Mapped[str | None] = mapped_column(String(80))
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(Text)
    air_date: Mapped[date | None] = mapped_column(Date)
    episode_count: Mapped[int | None] = mapped_column(Integer)
    provider_status: Mapped[str | None] = mapped_column(String(50))
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entry: Mapped[WatchEntry] = relationship(back_populates="seasons")
    episodes: Mapped[list[EpisodeRecord]] = relationship(
        back_populates="season",
        cascade="all, delete-orphan",
        order_by="EpisodeRecord.episode_number",
    )


class EpisodeRecord(Base):
    __tablename__ = "episode_records"
    __table_args__ = (
        UniqueConstraint(
            "provider_source", "provider_episode_id", name="uq_episode_provider_id"
        ),
        Index("ix_episode_season_number", "season_id", "episode_number"),
        Index("ix_episode_air_date", "air_date", "removed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    season_id: Mapped[str] = mapped_column(
        ForeignKey("season_records.id", ondelete="CASCADE"), nullable=False
    )
    provider_source: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_episode_id: Mapped[str] = mapped_column(String(80), nullable=False)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    air_date: Mapped[date | None] = mapped_column(Date)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    production_code: Mapped[str | None] = mapped_column(String(100))
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    season: Mapped[SeasonRecord] = relationship(back_populates="episodes")
    viewings: Mapped[list[EpisodeViewing]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        order_by="EpisodeViewing.created_at",
    )


class EpisodeViewing(Base):
    __tablename__ = "episode_viewings"
    __table_args__ = (
        UniqueConstraint("source", "source_key", name="uq_episode_viewing_source_key"),
        Index("ix_episode_viewing_entry", "entry_id", "episode_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("episode_records.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    watched_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    episode: Mapped[EpisodeRecord] = relationship(back_populates="viewings")


class ReleaseEvent(Base):
    __tablename__ = "release_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('episode_announced', 'episode_released', 'season_announced', 'schedule_changed')",
            name="ck_release_event_type",
        ),
        Index("ix_release_event_unread", "read_at", "dismissed_at", "first_seen_at"),
        Index("ix_release_event_effective", "effective_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    season_id: Mapped[str | None] = mapped_column(
        ForeignKey("season_records.id", ondelete="SET NULL")
    )
    episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("episode_records.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    dedupe_key: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (CheckConstraint("failure_count >= 0", name="ck_sync_job_failure_count"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(30), default="idle", nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(300))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OwnerAccount(Base):
    __tablename__ = "owner_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, default="owner"
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    bootstrap_completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class OwnerSession(Base):
    __tablename__ = "owner_sessions"
    __table_args__ = (
        Index("ix_owner_session_expiry", "expires_at"),
        Index("ix_owner_session_owner", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owner_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    __table_args__ = (
        CheckConstraint("failure_count >= 0", name="ck_login_throttle_failure_count"),
    )

    identity_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CalendarFeedToken(Base):
    __tablename__ = "calendar_feed_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
