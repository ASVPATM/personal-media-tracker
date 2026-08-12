from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
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
