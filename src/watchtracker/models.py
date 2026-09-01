from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
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


class UserAccount(Base):
    """A PMT data owner.

    Account-management UI and general multi-user sign-in arrive in the next roadmap
    slice.  This table lands first so every private record and request can already be
    scoped to an immutable subject identifier.
    """

    __tablename__ = "user_accounts"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')", name="ck_user_account_role"),
        CheckConstraint(
            "state IN ('invited', 'active', 'disabled')", name="ck_user_account_state"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    normalized_email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


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
    # Cached from schedule providers. Unlike episode_count, this excludes
    # future and undated/TBA episodes so card progress reflects episodes that
    # are actually available to watch.
    released_episode_count: Mapped[int | None] = mapped_column(Integer)
    public_score: Mapped[float | None] = mapped_column(Float)
    taste_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_source: Mapped[str] = mapped_column(String(50), default="manual")
    metadata_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_field_sources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    inference_version: Mapped[str] = mapped_column(String(20), default="1.0")
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    entries: Mapped[list[WatchEntry]] = relationship(back_populates="catalog_item")
    seasons: Mapped[list[SeasonRecord]] = relationship(
        back_populates="catalog_item", cascade="all, delete-orphan"
    )
    external_identities: Mapped[list[ExternalIdentity]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    metadata_sources: Mapped[list[CatalogMetadataSource]] = relationship(
        back_populates="catalog_item", cascade="all, delete-orphan", lazy="selectin"
    )
    list_items: Mapped[list[MediaListItem]] = relationship(back_populates="catalog_item")


class WatchEntry(Base):
    __tablename__ = "watch_entries"
    __table_args__ = (
        CheckConstraint("view_count >= 0", name="ck_entry_view_count"),
        CheckConstraint(
            "personal_rating IS NULL OR (personal_rating >= 1 AND personal_rating <= 10)",
            name="ck_entry_rating_range",
        ),
        UniqueConstraint("user_id", "catalog_item_id", name="uq_watch_entry_user_catalog"),
        Index("ix_watch_entry_user_deleted", "user_id", "deleted_at"),
        Index("ix_entry_status_deleted", "status", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="watched", index=True)
    personal_rating: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    user_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_date: Mapped[date | None] = mapped_column(Date)
    finished_date: Mapped[date | None] = mapped_column(Date)
    watched_date: Mapped[date | None] = mapped_column(Date)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    poster_override_url: Mapped[str | None] = mapped_column(Text)
    episode_progress_explicit: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # A compact count is retained even when a provider has not supplied individual
    # episode rows. Detailed EpisodeViewing records remain the richer source whenever
    # they exist; this value keeps card-level progress useful for every episodic title.
    episode_progress_count: Mapped[int | None] = mapped_column(Integer)
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

    catalog_item: Mapped[CatalogItem] = relationship(back_populates="entries")
    viewing_events: Mapped[list[ViewingEvent]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="ViewingEvent.created_at"
    )
    viewing_cycles: Mapped[list[ViewingCycle]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="ViewingCycle.created_at"
    )
    rating_assessments: Mapped[list[RatingAssessment]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    series_subscription: Mapped[SeriesTrackingSubscription | None] = relationship(
        back_populates="entry", cascade="all, delete-orphan", uselist=False
    )

    @property
    def rewatch_count(self) -> int:
        return max(self.view_count - 1, 0)


class MediaList(Base):
    __tablename__ = "media_lists"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_media_list_user_name"),
        Index("ix_media_list_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    pinned_to_navigation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private", nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), default="owned", nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(160))
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    items: Mapped[list[MediaListItem]] = relationship(
        back_populates="media_list",
        cascade="all, delete-orphan",
        order_by="(MediaListItem.position, MediaListItem.added_at)",
    )
    memberships: Mapped[list[MediaListMembership]] = relationship(
        back_populates="media_list", cascade="all, delete-orphan"
    )
    activity: Mapped[list[MediaListActivity]] = relationship(
        back_populates="media_list", cascade="all, delete-orphan"
    )


class MediaListItem(Base):
    __tablename__ = "media_list_items"
    __table_args__ = (
        UniqueConstraint("list_id", "catalog_item_id", name="uq_media_list_catalog"),
        Index("ix_media_list_item_list", "list_id", "position", "added_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_id: Mapped[str] = mapped_column(
        ForeignKey("media_lists.id", ondelete="CASCADE"), nullable=False
    )
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    added_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shared_note: Mapped[str | None] = mapped_column(String(500))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    media_list: Mapped[MediaList] = relationship(back_populates="items")
    catalog_item: Mapped[CatalogItem] = relationship(back_populates="list_items")


class MediaListMembership(Base):
    __tablename__ = "media_list_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_list_member_role"),
        UniqueConstraint("list_id", "user_id", name="uq_list_membership_user"),
        Index("ix_list_membership_user", "user_id", "accepted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_id: Mapped[str] = mapped_column(
        ForeignKey("media_lists.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    invited_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    media_list: Mapped[MediaList] = relationship(back_populates="memberships")


class MediaListActivity(Base):
    __tablename__ = "media_list_activity"
    __table_args__ = (Index("ix_list_activity_list_created", "list_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_id: Mapped[str] = mapped_column(
        ForeignKey("media_lists.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    safe_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    media_list: Mapped[MediaList] = relationship(back_populates="activity")


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        Index("ix_user_notification_inbox", "user_id", "read_at", "created_at"),
        UniqueConstraint(
            "user_id", "source_kind", "source_key", name="uq_user_notification_source"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_kind: Mapped[str | None] = mapped_column(String(30))
    source_key: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(300), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class NotificationEndpoint(Base):
    __tablename__ = "notification_endpoints"
    __table_args__ = (
        CheckConstraint(
            "adapter IN ('apprise', 'apprise_api')",
            name="ck_notification_endpoint_adapter",
        ),
        CheckConstraint("version >= 1", name="ck_notification_endpoint_version"),
        Index("ix_notification_endpoint_user", "user_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter: Mapped[str] = mapped_column(String(30), nullable=False)
    secret_reference: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    redacted_hint: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class NotificationRule(Base):
    __tablename__ = "notification_rules"
    __table_args__ = (
        CheckConstraint("lead_time_hours >= 0", name="ck_notification_rule_lead_time"),
        CheckConstraint("version >= 1", name="ck_notification_rule_version"),
        UniqueConstraint(
            "user_id",
            "event_pattern",
            "endpoint_id",
            "lead_time_hours",
            name="uq_notification_rule_route",
        ),
        Index("ix_notification_rule_user", "user_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    event_pattern: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lead_time_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quiet_start: Mapped[str | None] = mapped_column(String(5))
    quiet_end: Mapped[str | None] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    endpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_endpoints.id", ondelete="CASCADE")
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    external_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'leased', 'retry', 'delivered', 'failed', 'cancelled')",
            name="ck_notification_outbox_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_notification_outbox_attempts"),
        UniqueConstraint("dedupe_key", name="uq_notification_outbox_dedupe"),
        Index("ix_notification_outbox_due", "state", "due_at"),
        Index("ix_notification_outbox_user", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[str] = mapped_column(
        ForeignKey("notification_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    safe_message: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class NotificationDeliveryAttempt(Base):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="ck_notification_attempt_number"),
        UniqueConstraint("outbox_id", "attempt_number", name="uq_notification_attempt"),
        Index("ix_notification_attempt_outbox", "outbox_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    outbox_id: Mapped[str] = mapped_column(
        ForeignKey("notification_outbox.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_category: Mapped[str] = mapped_column(String(30), nullable=False)
    receipt_hash: Mapped[str | None] = mapped_column(String(64))
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ViewingCycle(Base):
    """An initial watch or an explicitly initiated rewatch.

    This is additive to the legacy counters.  New code treats cycle/occurrence rows as
    authoritative while ``WatchEntry`` keeps compatibility projections for older
    exports and clients.
    """

    __tablename__ = "viewing_cycles"
    __table_args__ = (
        CheckConstraint("kind IN ('initial', 'rewatch')", name="ck_viewing_cycle_kind"),
        CheckConstraint(
            "scope IN ('title', 'season', 'episode_range')",
            name="ck_viewing_cycle_scope",
        ),
        CheckConstraint(
            "state IN ('active', 'closed', 'completed', 'abandoned')",
            name="ck_viewing_cycle_state",
        ),
        Index("ix_viewing_cycle_entry_state", "entry_id", "state", "deleted_at"),
        Index("ix_viewing_cycle_user_modified", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), default="title", nullable=False)
    scope_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    target_episode_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    entry: Mapped[WatchEntry] = relationship(back_populates="viewing_cycles")


class ViewingEvent(Base):
    __tablename__ = "viewing_events"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_key", name="uq_viewing_user_source_key"),
        Index("ix_viewing_entry_date", "entry_id", "viewed_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    cycle_id: Mapped[str | None] = mapped_column(
        ForeignKey("viewing_cycles.id", ondelete="SET NULL"), index=True
    )
    viewed_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    source_key: Mapped[str | None] = mapped_column(String(200))
    occurrence_kind: Mapped[str] = mapped_column(
        String(20), default="completion", nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_event_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    entry: Mapped[WatchEntry] = relationship(back_populates="viewing_events")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity_time", "entity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    import_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportHistory(Base):
    __tablename__ = "import_history"
    __table_args__ = (
        UniqueConstraint("user_id", "source_hash", name="uq_import_history_user_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    question_order: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
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
        UniqueConstraint(
            "user_id", "entry_low_id", "entry_high_id", name="uq_rating_user_pair"
        ),
        Index("ix_rating_comparison_updated", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default="comparisons", nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(40), nullable=False)
    ranking_version: Mapped[str] = mapped_column(String(40), nullable=False)
    session_policy_version: Mapped[str] = mapped_column(
        String(40), default="direct-first-v2", nullable=False
    )
    target_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    completed_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    skipped_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
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
        Index("ix_season_catalog_number", "catalog_item_id", "season_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
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

    catalog_item: Mapped[CatalogItem] = relationship(back_populates="seasons")
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
        UniqueConstraint(
            "user_id", "source", "source_key", name="uq_episode_viewing_user_source_key"
        ),
        Index("ix_episode_viewing_entry", "entry_id", "episode_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("episode_records.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    cycle_id: Mapped[str | None] = mapped_column(
        ForeignKey("viewing_cycles.id", ondelete="SET NULL"), index=True
    )
    watched_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(200))
    occurrence_kind: Mapped[str] = mapped_column(
        String(20), default="completion", nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_event_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    episode: Mapped[EpisodeRecord] = relationship(back_populates="viewings")


class PlaybackBookmark(Base):
    __tablename__ = "playback_bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_key", name="uq_bookmark_source_key"),
        Index("ix_bookmark_entry_modified", "entry_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[str | None] = mapped_column(
        ForeignKey("episode_records.id", ondelete="CASCADE")
    )
    position_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ProviderProgressClaim(Base):
    """A tracker/provider assertion, not invented viewing history."""

    __tablename__ = "provider_progress_claims"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "source_key", name="uq_progress_claim_key"),
        Index("ix_progress_claim_entry_observed", "entry_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    claim: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    accepted_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ViewingCorrection(Base):
    __tablename__ = "viewing_corrections"
    __table_args__ = (Index("ix_viewing_correction_entry", "entry_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("watch_entries.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    before_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    after_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class PlatformSyncImportBatch(Base):
    __tablename__ = "platform_sync_import_batches"
    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_hash", name="uq_platform_import_snapshot"),
        Index("ix_platform_import_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_product: Mapped[str] = mapped_column(String(80), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(40))
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformSyncImportRecord(Base):
    __tablename__ = "platform_sync_import_records"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "record_type", "record_id", name="uq_platform_import_record"
        ),
        Index("ix_platform_import_record_origin", "origin_device_id", "origin_event_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("platform_sync_import_batches.id", ondelete="CASCADE"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(60), nullable=False)
    record_id: Mapped[str] = mapped_column(String(200), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    origin_device_id: Mapped[str | None] = mapped_column(String(100))
    origin_event_id: Mapped[str | None] = mapped_column(String(200))
    safe_message: Mapped[str | None] = mapped_column(String(300))
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ReleaseEvent(Base):
    __tablename__ = "release_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('episode_announced', 'episode_released', 'season_announced', 'schedule_changed')",
            name="ck_release_event_type",
        ),
        UniqueConstraint("user_id", "dedupe_key", name="uq_release_event_user_dedupe"),
        Index("ix_release_event_unread", "read_at", "dismissed_at", "first_seen_at"),
        Index("ix_release_event_effective", "effective_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("namespace", "external_id", name="uq_external_identity_value"),
        UniqueConstraint(
            "catalog_item_id", "namespace", name="uq_catalog_external_identity_namespace"
        ),
        Index("ix_external_identity_catalog", "catalog_item_id", "namespace"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    namespace: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provenance: Mapped[str] = mapped_column(String(80), default="migration", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CatalogMetadataSource(Base):
    """A normalized provider snapshot; personal fields never belong here."""

    __tablename__ = "catalog_metadata_sources"
    __table_args__ = (
        UniqueConstraint(
            "catalog_item_id", "provider", "provider_id", name="uq_catalog_metadata_source"
        ),
        Index("ix_catalog_metadata_source_catalog", "catalog_item_id", "provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    external_ids: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    catalog_item: Mapped[CatalogItem] = relationship(back_populates="metadata_sources")


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint("failure_count >= 0", name="ck_integration_failure_count"),
        Index("ix_integration_connection_user", "user_id", "provider_slug"),
        Index("ix_integration_connection_provider", "provider_slug", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider_slug: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    remote_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    secret_reference: Mapped[str | None] = mapped_column(String(160), unique=True)
    credential_storage: Mapped[str | None] = mapped_column(String(30))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paused_reason: Mapped[str | None] = mapped_column(String(300))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IntegrationOAuthState(Base):
    __tablename__ = "integration_oauth_states"
    __table_args__ = (Index("ix_integration_oauth_state_expiry", "expires_at", "used_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider_slug: Mapped[str] = mapped_column(String(60), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    verifier_reference: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(800), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationOAuthGrant(Base):
    __tablename__ = "integration_oauth_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    token_type: Mapped[str] = mapped_column(String(30), default="Bearer", nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remote_subject: Mapped[str | None] = mapped_column(String(200))
    reconnect_reason: Mapped[str | None] = mapped_column(String(160))
    authorized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IntegrationUserBinding(Base):
    __tablename__ = "integration_user_bindings"
    __table_args__ = (
        UniqueConstraint("connection_id", "remote_user_id", name="uq_binding_remote_user"),
        UniqueConstraint("connection_id", "pmt_user_id", name="uq_binding_pmt_user"),
        Index("ix_integration_binding_user", "pmt_user_id", "connection_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    remote_user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    remote_user_label: Mapped[str | None] = mapped_column(String(120))
    pmt_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IntegrationCursor(Base):
    __tablename__ = "integration_cursors"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "capability", "direction", name="uq_integration_cursor"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(60), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(60))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IntegrationRun(Base):
    __tablename__ = "integration_runs"
    __table_args__ = (
        Index("ix_integration_run_connection_time", "connection_id", "started_at"),
        Index("ix_integration_run_state", "state", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    capability: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationEvent(Base):
    __tablename__ = "integration_events"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "idempotency_key", name="uq_integration_event_delivery"
        ),
        Index("ix_integration_event_run", "run_id", "created_at"),
        Index("ix_integration_event_target", "canonical_target", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="SET NULL")
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    provider_event_id: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_target: Mapped[str | None] = mapped_column(String(200))
    event_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    safe_summary: Mapped[str] = mapped_column(String(300), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IntegrationConflict(Base):
    __tablename__ = "integration_conflicts"
    __table_args__ = (
        Index("ix_integration_conflict_open", "connection_id", "resolved_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="SET NULL")
    )
    catalog_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="SET NULL")
    )
    conflict_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    local_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    remote_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    safe_summary: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(30))


class WebhookCredential(Base):
    __tablename__ = "webhook_credentials"
    __table_args__ = (Index("ix_webhook_credential_public", "public_id", "revoked_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class ScheduledJob(Base):
    """Database-leased work item shared by backups, releases, and integrations."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('scheduled', 'running', 'retry', 'paused', 'completed', 'cancelled')",
            name="ck_scheduled_job_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_scheduled_job_attempts"),
        UniqueConstraint("idempotency_key", name="uq_scheduled_job_idempotency"),
        Index("ix_scheduled_job_due", "state", "due_at"),
        Index("ix_scheduled_job_owner", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE")
    )
    scope_type: Mapped[str | None] = mapped_column(String(40))
    scope_id: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(300))
    paused_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("session_kind IN ('browser', 'native')", name="ck_user_session_kind"),
        Index("ix_user_session_expiry", "expires_at"),
        Index("ix_user_session_user", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    session_kind: Mapped[str] = mapped_column(String(20), default="browser", nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(80))
    device_label: Mapped[str | None] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str | None] = mapped_column(String(64))
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Source compatibility for internal extensions that imported the old single-owner name.
OwnerSession = UserSession


class AccountInvitation(Base):
    __tablename__ = "account_invitations"
    __table_args__ = (
        CheckConstraint("kind IN ('signup', 'recovery')", name="ck_invitation_kind"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_invitation_role"),
        Index("ix_invitation_expiry", "expires_at", "consumed_at", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    recovery_for_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20), default="signup", nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServerAuditEvent(Base):
    __tablename__ = "server_audit_events"
    __table_args__ = (Index("ix_server_audit_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    safe_summary: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ServerState(Base):
    __tablename__ = "server_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    instance_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    api_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class SyncRequest(Base):
    __tablename__ = "sync_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_sync_request_user_request"),
        Index("ix_sync_request_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


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


class UserRecommendationPreference(Base):
    __tablename__ = "user_recommendation_preferences"
    __table_args__ = (
        CheckConstraint(
            "engine IN ('scalar', 'advanced_hybrid')", name="ck_recommendation_engine"
        ),
        CheckConstraint("version >= 1", name="ck_recommendation_preference_version"),
        CheckConstraint(
            "retention_days >= 30 AND retention_days <= 3650",
            name="ck_recommendation_retention_days",
        ),
        CheckConstraint("consent_revision >= 1", name="ck_recommendation_consent_revision"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    engine: Mapped[str] = mapped_column(String(30), default="scalar", nullable=False)
    use_ratings: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_favorites: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_refinement: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_rewatches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    use_live_discovery: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    local_llm_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    excluded_media_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    excluded_genres: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    consent_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class RecommendationSignalSnapshot(Base):
    __tablename__ = "recommendation_signal_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "source_hash", name="uq_recommendation_signal_hash"),
        CheckConstraint("source_revision >= 1", name="ck_recommendation_signal_revision"),
        Index("ix_recommendation_signal_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    source_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_contract_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    evidence_anchors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    evidence_sufficient: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RecommendationCatalogCandidate(Base):
    __tablename__ = "recommendation_catalog_candidates"
    __table_args__ = (
        UniqueConstraint("catalog_item_id", name="uq_recommendation_candidate_catalog"),
        CheckConstraint(
            "source_score >= 0 AND source_score <= 1",
            name="ck_recommendation_candidate_score",
        ),
        Index("ix_recommendation_candidate_freshness", "source", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    source_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    region: Mapped[str | None] = mapped_column(String(30))
    language: Mapped[str | None] = mapped_column(String(30))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    catalog_item: Mapped[CatalogItem] = relationship(lazy="selectin")


class RecommendationCandidateSnapshot(Base):
    __tablename__ = "recommendation_candidate_snapshots"
    __table_args__ = (
        CheckConstraint(
            "preference_revision >= 1", name="ck_recommendation_snapshot_preference_revision"
        ),
        Index("ix_recommendation_candidate_snapshot_user", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    preference_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_signal_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warning_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list[RecommendationCandidateSnapshotItem]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", lazy="selectin"
    )


class RecommendationCandidateSnapshotItem(Base):
    __tablename__ = "recommendation_candidate_snapshot_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "candidate_id", name="uq_recommendation_snapshot_item"),
        UniqueConstraint("snapshot_id", "position", name="uq_recommendation_snapshot_position"),
        CheckConstraint("position >= 1", name="ck_recommendation_snapshot_position"),
        CheckConstraint(
            "identity_quality >= 0 AND identity_quality <= 1",
            name="ck_recommendation_identity_quality",
        ),
        CheckConstraint(
            "metadata_quality >= 0 AND metadata_quality <= 1",
            name="ck_recommendation_metadata_quality",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_candidate_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_catalog_candidates.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    identity_quality: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    metadata_quality: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    artwork_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    scoring_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provenance_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    snapshot: Mapped[RecommendationCandidateSnapshot] = relationship(back_populates="items")
    candidate: Mapped[RecommendationCatalogCandidate] = relationship(lazy="selectin")


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_recommendation_run_state",
        ),
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_recommendation_run_idempotency"
        ),
        CheckConstraint("input_revision >= 1", name="ck_recommendation_run_revision"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_recommendation_run_progress",
        ),
        Index(
            "uq_recommendation_run_active_user",
            "user_id",
            unique=True,
            sqlite_where=sql_text("state IN ('queued', 'running')"),
            postgresql_where=sql_text("state IN ('queued', 'running')"),
        ),
        Index("ix_recommendation_run_user_state", "user_id", "state", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    distribution_flavor: Mapped[str] = mapped_column(String(40), nullable=False)
    engine: Mapped[str] = mapped_column(String(30), default="scalar", nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    signal_contract_version: Mapped[str] = mapped_column(String(40), nullable=False)
    score_scale_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signal_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("recommendation_signal_snapshots.id", ondelete="SET NULL")
    )
    candidate_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("recommendation_candidate_snapshots.id", ondelete="SET NULL")
    )
    input_revision: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    deterministic_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    phase: Mapped[str] = mapped_column(String(40), default="checking_readiness", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_indeterminate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_units: Mapped[int | None] = mapped_column(Integer)
    total_units: Mapped[int | None] = mapped_column(Integer)
    message_key: Mapped[str] = mapped_column(
        String(100), default="recommendations.progress.checking_readiness", nullable=False
    )
    warning_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safe_failure_detail: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class RecommendationResult(Base):
    __tablename__ = "recommendation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "rank", name="uq_recommendation_result_rank"),
        UniqueConstraint("run_id", "catalog_item_id", name="uq_recommendation_result_catalog"),
        CheckConstraint("rank >= 1", name="ck_recommendation_result_rank"),
        CheckConstraint(
            "final_match >= 0 AND final_match <= 1",
            name="ck_recommendation_result_match",
        ),
        CheckConstraint(
            "display_match >= 0 AND display_match <= 100",
            name="ck_recommendation_result_display",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_recommendation_result_confidence",
        ),
        CheckConstraint(
            "baseline_contribution >= 0 AND baseline_contribution <= 1",
            name="ck_recommendation_result_baseline",
        ),
        CheckConstraint(
            "tower_contribution IS NULL OR (tower_contribution >= 0 AND tower_contribution <= 1)",
            name="ck_recommendation_result_tower",
        ),
        CheckConstraint(
            "llm_contribution IS NULL OR (llm_contribution >= 0 AND llm_contribution <= 1)",
            name="ck_recommendation_result_llm",
        ),
        Index("ix_recommendation_result_run", "run_id", "rank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_runs.id", ondelete="CASCADE"), nullable=False
    )
    catalog_item_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_catalog_candidates.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    final_match: Mapped[float] = mapped_column(Float, nullable=False)
    display_match: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_contribution: Mapped[float] = mapped_column(Float, nullable=False)
    tower_contribution: Mapped[float | None] = mapped_column(Float)
    llm_contribution: Mapped[float | None] = mapped_column(Float)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risk_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    anchor_catalog_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    eligibility_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    catalog_item: Mapped[CatalogItem] = relationship(lazy="selectin")


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        CheckConstraint(
            "feedback IN ('useful', 'not_interested', 'already_seen', 'wrong_mood')",
            name="ck_recommendation_feedback_value",
        ),
        UniqueConstraint("user_id", "result_id", name="uq_recommendation_feedback_result"),
        Index("ix_recommendation_feedback_user", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    result_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_results.id", ondelete="CASCADE"), nullable=False
    )
    feedback: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RecommendationPreferenceClaim(Base):
    __tablename__ = "recommendation_preference_claims"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_recommendation_claim_confidence"
        ),
        CheckConstraint("source_revision >= 1", name="ck_recommendation_claim_revision"),
        Index("ix_recommendation_claim_user_active", "user_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(160))
    source_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RecommendationModelQualification(Base):
    __tablename__ = "recommendation_model_qualifications"
    __table_args__ = (Index("ix_recommendation_qualification_user", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    adapter_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    qualification_version: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    capability_results: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    safe_timings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    stability_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CalendarFeedToken(Base):
    __tablename__ = "calendar_feed_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
