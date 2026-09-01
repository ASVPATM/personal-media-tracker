from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from watchtracker.authorization import Principal, current_user_id
from watchtracker.catalog_visibility import catalog_visible_to_user
from watchtracker.imports.parsers import (
    ImportLimits,
    import_breakdown,
    parse_letterboxd_zip,
    parse_manual_csv,
    parse_obsidian_vault_zip,
)
from watchtracker.models import (
    AuditEvent,
    CatalogItem,
    ImportHistory,
    ImportPreviewRecord,
    ViewingEvent,
    WatchEntry,
)
from watchtracker.schemas import CatalogData, EntryOptions
from watchtracker.services.entries import EntryService
from watchtracker.taxonomy import normalize_title

PARSER_VERSION = "2.1"


class ImportError(ValueError):
    pass


class ImportNotFound(ImportError):
    """An import resource is absent or belongs to a different principal."""


class ImportConflict(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _catalog(row: dict[str, Any]) -> CatalogData:
    return CatalogData(
        canonical_title=row["title"],
        original_title=row.get("original_title"),
        release_year=row.get("release_year"),
        media_type=row["media_type"],
        provider_format=row.get("provider_format"),
        provider_source=row.get("provider_source"),
        provider_id=row.get("provider_id"),
        tmdb_movie_id=row.get("tmdb_movie_id"),
        tmdb_tv_id=row.get("tmdb_tv_id"),
        anilist_id=row.get("anilist_id"),
        mal_id=row.get("mal_id"),
        provider_genres=row.get("genres") or [],
        keywords=row.get("subgenres") or [],
    )


def _parse_iso(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class ImportService:
    def __init__(
        self,
        session: Session,
        *,
        today: date,
        limits: ImportLimits | None = None,
        principal: Principal | None = None,
    ):
        self.session = session
        self.today = today
        self.limits = limits or ImportLimits()
        self.principal = principal
        self.user_id = current_user_id(session, principal)

    def _find_import_catalog(
        self, service: EntryService, data: CatalogData
    ) -> tuple[CatalogItem | None, bool]:
        catalog = service.find_catalog(data)
        if catalog:
            return catalog, False
        # Older importer versions interpreted values such as "show" as movie. A
        # unique unresolved title is safe to reclassify when the new file carries
        # an explicit media type; provider-resolved records are never guessed here.
        statement = select(CatalogItem).where(
            CatalogItem.normalized_title == normalize_title(data.canonical_title),
            CatalogItem.provider_source.is_(None),
            CatalogItem.provider_id.is_(None),
            CatalogItem.tmdb_movie_id.is_(None),
            CatalogItem.tmdb_tv_id.is_(None),
            CatalogItem.anilist_id.is_(None),
            CatalogItem.mal_id.is_(None),
        )
        if data.release_year is not None:
            statement = statement.where(
                or_(
                    CatalogItem.release_year == data.release_year,
                    CatalogItem.release_year.is_(None),
                )
            )
        candidates = [
            candidate
            for candidate in self.session.scalars(statement.limit(100))
            if catalog_visible_to_user(
                self.session, user_id=self.user_id, catalog_item=candidate
            )
        ]
        if len(candidates) == 1:
            return candidates[0], candidates[0].media_type != data.media_type
        return None, False

    def preview(
        self, filename: str, content: bytes, import_kind: str = "auto"
    ) -> dict[str, Any]:
        source_hash = hashlib.sha256(PARSER_VERSION.encode() + b"\0" + content).hexdigest()
        filename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255] or "import"
        kind = import_kind
        if kind == "auto":
            if filename.casefold().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(content)) as archive:
                        kind = (
                            "obsidian"
                            if "Personal Media Tracker/Media Library.md" in archive.namelist()
                            else "letterboxd"
                        )
                except zipfile.BadZipFile:
                    kind = "letterboxd"
            else:
                kind = "csv"
        try:
            if kind == "letterboxd":
                rows, invalid, warnings = parse_letterboxd_zip(content, limits=self.limits)
            elif kind == "obsidian":
                rows, invalid, warnings = parse_obsidian_vault_zip(content, limits=self.limits)
            elif kind in {"csv", "manual", "canonical"}:
                rows, invalid, warnings = parse_manual_csv(content, limits=self.limits)
                kind = "csv"
            else:
                raise ImportError("Unsupported import type")
        except ValueError as exc:
            raise ImportError(str(exc)) from exc

        entry_service = EntryService(self.session, today=self.today, principal=self.principal)
        counts = {
            "parsed_rows": len(rows),
            "new_entries": 0,
            "updates": 0,
            "duplicates": 0,
            "conflicts": 0,
            "invalid_rows": len(invalid),
            "media_type_corrections": 0,
        }
        conflicts: list[dict[str, Any]] = []
        for row in rows:
            catalog, media_correction = self._find_import_catalog(entry_service, _catalog(row))
            existing = None
            if catalog:
                existing = self.session.scalar(
                    select(WatchEntry)
                    .where(
                        WatchEntry.catalog_item_id == catalog.id,
                        WatchEntry.user_id == self.user_id,
                    )
                    .options(
                        selectinload(WatchEntry.catalog_item),
                        selectinload(WatchEntry.viewing_events),
                    )
                )
            if not existing:
                counts["new_entries"] += 1
                row["proposed_action"] = "create"
                continue
            row["existing_entry_id"] = existing.id
            if media_correction:
                counts["media_type_corrections"] += 1
                row["media_type_correction"] = {
                    "from": existing.catalog_item.media_type,
                    "to": row["media_type"],
                }
            row_conflicts = []
            for field in ("personal_rating", "notes"):
                incoming = row.get(field)
                current = getattr(existing, field)
                if (
                    incoming not in (None, "")
                    and current not in (None, "")
                    and incoming != current
                ):
                    row_conflicts.append(
                        {"field": field, "existing": current, "incoming": incoming}
                    )
            if row_conflicts:
                counts["conflicts"] += 1
                conflicts.append(
                    {
                        "row_number": row["row_number"],
                        "title": row["title"],
                        "fields": row_conflicts,
                    }
                )
                row["proposed_action"] = "conflict"
            elif any(
                (
                    row.get("personal_rating") is not None and existing.personal_rating is None,
                    row.get("notes") and not existing.notes,
                    row.get("view_count", 0) > existing.view_count,
                    bool(row.get("viewing_events")),
                    set(row.get("tags") or []) - set(existing.user_tags or []),
                    media_correction,
                    row.get("status") != existing.status,
                    {
                        **(existing.import_context or {}),
                        **(row.get("import_context") or {}),
                    }
                    != (existing.import_context or {}),
                )
            ):
                counts["updates"] += 1
                row["proposed_action"] = "update"
            else:
                counts["duplicates"] += 1
                row["proposed_action"] = "duplicate"

        mappings = list(
            {
                json.dumps(row["status_mapping"], sort_keys=True): row["status_mapping"]
                for row in rows
                if row.get("status_mapping")
            }.values()
        )
        normalizations = [
            row["normalization_note"] for row in rows if row.get("normalization_note")
        ]
        already = self.session.scalar(
            select(ImportHistory).where(
                ImportHistory.user_id == self.user_id,
                ImportHistory.source_hash == source_hash,
            )
        )
        if already:
            warnings.append(
                "This exact file was already imported; committing again is a no-op."
            )
        payload = {
            "source_hash": source_hash,
            "kind": kind,
            "parser_version": PARSER_VERSION,
            "rows": rows,
            "invalid": invalid,
            "conflicts": conflicts,
            "counts": counts,
            "warnings": list(dict.fromkeys(warnings)),
            "status_mappings": mappings,
            "normalizations": list(dict.fromkeys(normalizations)),
            "media_type_breakdown": import_breakdown(rows, "media_type"),
            "status_breakdown": import_breakdown(rows, "status"),
            "already_imported": bool(already),
        }
        record = ImportPreviewRecord(
            user_id=self.user_id,
            source_hash=source_hash,
            filename=filename,
            import_kind=kind,
            payload=payload,
            expires_at=_now() + timedelta(hours=24),
        )
        self.session.add(record)
        self.session.commit()
        return {
            "preview_id": record.id,
            **{key: value for key, value in payload.items() if key != "rows"},
        }

    def commit(
        self,
        preview_id: str,
        *,
        conflict_policy: str | None,
        allow_invalid: bool,
    ) -> dict[str, Any]:
        record = self.session.scalar(
            select(ImportPreviewRecord).where(
                ImportPreviewRecord.id == preview_id,
                ImportPreviewRecord.user_id == self.user_id,
            )
        )
        if not record:
            raise ImportNotFound("Import preview not found")
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < _now():
            raise ImportError("Import preview has expired")
        if record.committed_at:
            history = self.session.scalar(
                select(ImportHistory).where(
                    ImportHistory.user_id == self.user_id,
                    ImportHistory.source_hash == record.source_hash,
                )
            )
            return {"status": "already_imported", **(history.summary if history else {})}
        payload = record.payload
        if payload["invalid"] and not allow_invalid:
            raise ImportConflict(
                "Preview contains invalid rows; review them or explicitly allow valid rows only"
            )
        if payload["conflicts"] and conflict_policy not in {"preserve_existing", "overwrite"}:
            raise ImportConflict("Personal data conflicts require an explicit conflict policy")
        existing_history = self.session.scalar(
            select(ImportHistory).where(
                ImportHistory.user_id == self.user_id,
                ImportHistory.source_hash == record.source_hash,
            )
        )
        if existing_history:
            record.committed_at = _now()
            self.session.commit()
            return {"status": "already_imported", **existing_history.summary}

        summary = {
            "created": 0,
            "updated": 0,
            "duplicates": 0,
            "viewing_events_added": 0,
            "invalid_skipped": len(payload["invalid"]),
        }
        service = EntryService(self.session, today=self.today, principal=self.principal)
        source = f"import:{record.import_kind}"
        try:
            for row in payload["rows"]:
                catalog_data = _catalog(row)
                catalog, media_correction = self._find_import_catalog(service, catalog_data)
                entry = None
                if catalog:
                    entry = self.session.scalar(
                        select(WatchEntry)
                        .where(
                            WatchEntry.catalog_item_id == catalog.id,
                            WatchEntry.user_id == self.user_id,
                        )
                        .options(
                            selectinload(WatchEntry.catalog_item),
                            selectinload(WatchEntry.viewing_events),
                        )
                    )
                is_new = entry is None
                events = row.get("viewing_events") or []
                if is_new:
                    creation_status = "plan_to_watch" if events else row["status"]
                    creation_count = 0 if events else row["view_count"]
                    options = EntryOptions(
                        status=creation_status,
                        personal_rating=row.get("personal_rating"),
                        notes=row.get("notes"),
                        user_tags=row.get("tags") or [],
                        started_date=_parse_iso(row.get("started_date")),
                        finished_date=_parse_iso(row.get("finished_date")),
                        watched_date=None if events else _parse_iso(row.get("watched_date")),
                        view_count=creation_count,
                    )
                    mutation = service.create_or_handle_duplicate(
                        catalog_data,
                        options,
                        source=source,
                        default_watched_date=False,
                        commit=False,
                    )
                    entry = service._loaded_entry(mutation.entry.id)
                    summary["created"] += 1
                else:
                    if media_correction and not (
                        entry.catalog_item.metadata_provenance or {}
                    ).get("provider_identity_verified"):
                        entry.catalog_item.media_type = row["media_type"]
                    service._merge_catalog(entry.catalog_item, catalog_data)

                before = {
                    "status": entry.status,
                    "personal_rating": entry.personal_rating,
                    "view_count": entry.view_count,
                }
                changed = is_new or media_correction
                incoming_rating = row.get("personal_rating")
                if (
                    incoming_rating is not None
                    and (entry.personal_rating is None or conflict_policy == "overwrite")
                    and entry.personal_rating != incoming_rating
                ):
                    entry.personal_rating = incoming_rating
                    changed = True
                incoming_notes = row.get("notes")
                if (
                    incoming_notes
                    and (not entry.notes or conflict_policy == "overwrite")
                    and entry.notes != incoming_notes
                ):
                    entry.notes = incoming_notes
                    changed = True
                merged_tags = sorted(
                    set(entry.user_tags or []) | set(row.get("tags") or []), key=str.casefold
                )
                if merged_tags != (entry.user_tags or []):
                    entry.user_tags = merged_tags
                    changed = True
                incoming_context = row.get("import_context") or {}
                merged_context = {**(entry.import_context or {}), **incoming_context}
                if merged_context != (entry.import_context or {}):
                    entry.import_context = merged_context
                    changed = True
                for field in ("started_date", "finished_date", "watched_date"):
                    incoming = _parse_iso(row.get(field))
                    if incoming and getattr(entry, field) is None:
                        setattr(entry, field, incoming)
                        changed = True
                original_view_count = entry.view_count
                for event_index, event_data in enumerate(events):
                    source_key = f"{record.source_hash[:32]}:{row['row_key']}:{event_data.get('event_key') or event_index}"
                    exists = self.session.scalar(
                        select(ViewingEvent.id).where(
                            ViewingEvent.user_id == self.user_id,
                            ViewingEvent.source == source,
                            ViewingEvent.source_key == source_key,
                        )
                    )
                    if not exists:
                        event = ViewingEvent(
                            user_id=self.user_id,
                            entry=entry,
                            viewed_on=_parse_iso(event_data.get("viewed_on")),
                            source=source,
                            source_key=source_key,
                        )
                        self.session.add(event)
                        summary["viewing_events_added"] += 1
                        changed = True
                self.session.flush()
                stored_event_count = (
                    self.session.query(ViewingEvent)
                    .filter(ViewingEvent.entry_id == entry.id)
                    .count()
                )
                entry.view_count = max(
                    original_view_count, row["view_count"], stored_event_count
                )
                if entry.view_count != original_view_count:
                    changed = True
                if (
                    not (entry.view_count > 0 and row["status"] == "plan_to_watch")
                    and entry.status != row["status"]
                ):
                    entry.status = row["status"]
                    changed = True
                dated = [event.viewed_on for event in entry.viewing_events if event.viewed_on]
                incoming_watched = _parse_iso(row.get("watched_date"))
                latest = max(
                    [*dated, *([incoming_watched] if incoming_watched else [])], default=None
                )
                if latest and (entry.watched_date is None or latest > entry.watched_date):
                    entry.watched_date = latest
                    changed = True
                if entry.deleted_at:
                    entry.deleted_at = None
                    changed = True
                if not is_new:
                    if changed:
                        summary["updated"] += 1
                    else:
                        summary["duplicates"] += 1
                if changed:
                    self.session.add(
                        AuditEvent(
                            user_id=self.user_id,
                            action="import",
                            entity_id=entry.id,
                            source=source,
                            before_data=before,
                            after_data={
                                "status": entry.status,
                                "personal_rating": entry.personal_rating,
                                "view_count": entry.view_count,
                            },
                        )
                    )
            history = ImportHistory(
                user_id=self.user_id,
                source_hash=record.source_hash,
                filename=record.filename,
                import_kind=record.import_kind,
                summary=summary,
            )
            self.session.add(history)
            record.committed_at = _now()
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {"status": "committed", **summary}
