from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import AuditEvent, SyncRequest
from watchtracker.schemas import EntryPatch, MediaListPatch, SyncMutation
from watchtracker.services.entries import (
    EntryConflict,
    EntryNotFound,
    EntryService,
)
from watchtracker.services.lists import MediaListService


class SyncService:
    """Idempotent native-client mutations over PMT's authoritative database."""

    def __init__(
        self,
        session: Session,
        *,
        today,
        principal: Principal | None = None,
    ):
        self.session = session
        self.user_id = current_user_id(session, principal)
        self.today = today

    @staticmethod
    def _hash(device_id: str, mutation: SyncMutation) -> str:
        encoded = json.dumps(
            {"device_id": device_id, **mutation.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def apply(self, device_id: str, mutation: SyncMutation) -> dict[str, Any]:
        request_hash = self._hash(device_id, mutation)
        stored = self.session.scalar(
            select(SyncRequest).where(
                SyncRequest.user_id == self.user_id,
                SyncRequest.request_id == mutation.request_id,
            )
        )
        if stored is not None:
            if stored.request_hash != request_hash:
                return {
                    "request_id": mutation.request_id,
                    "status": "rejected",
                    "error": {
                        "code": "idempotency_key_reused",
                        "message": "This request ID was already used for different content.",
                    },
                }
            return {**stored.result, "duplicate": True}

        entry_service = EntryService(self.session, today=self.today)
        list_service = MediaListService(self.session)
        resource_type = "watch_entry" if mutation.operation == "entry.patch" else "media_list"
        try:
            if mutation.operation == "entry.patch":
                patch = EntryPatch.model_validate(mutation.payload)
                resource = entry_service.patch(
                    mutation.resource_id,
                    patch,
                    source="native_sync",
                    expected_version=mutation.base_version,
                    commit=False,
                )
            elif mutation.operation == "list.patch":
                patch = MediaListPatch.model_validate(mutation.payload)
                resource = list_service.update(
                    mutation.resource_id,
                    pinned=patch.pinned_to_navigation,
                    name=patch.name,
                    expected_version=mutation.base_version,
                    commit=False,
                )
            elif mutation.operation in {"list.item.add", "list.item.remove"}:
                catalog_item_id = str(mutation.payload.get("catalog_item_id") or "")
                if len(catalog_item_id) != 36:
                    raise ValueError("A catalog_item_id is required for this list change.")
                if mutation.operation == "list.item.add":
                    resource = list_service.add_catalog_item(
                        mutation.resource_id,
                        catalog_item_id,
                        shared_note=mutation.payload.get("shared_note"),
                        expected_version=mutation.base_version,
                        commit=False,
                    )
                else:
                    resource = list_service.remove_catalog_item(
                        mutation.resource_id,
                        catalog_item_id,
                        expected_version=mutation.base_version,
                        commit=False,
                    )
            else:  # pragma: no cover - schema rejects unknown operations
                raise ValueError("Unsupported sync operation.")
            result = {
                "request_id": mutation.request_id,
                "status": "applied",
                "resource_type": resource_type,
                "resource_id": mutation.resource_id,
                "version": resource.version,
                "resource": resource.model_dump(mode="json"),
                "duplicate": False,
            }
        except EntryConflict as exc:
            self.session.rollback()
            current = None
            with suppress(EntryNotFound):
                current = (
                    EntryService(self.session, today=self.today).get(mutation.resource_id)
                    if resource_type == "watch_entry"
                    else MediaListService(self.session).get(mutation.resource_id)
                ).model_dump(mode="json")
            result = {
                "request_id": mutation.request_id,
                "status": "conflict",
                "resource_type": resource_type,
                "resource_id": mutation.resource_id,
                "error": {"code": "stale_version", "message": str(exc)},
                "current": current,
                "duplicate": False,
            }
        except EntryNotFound:
            self.session.rollback()
            result = {
                "request_id": mutation.request_id,
                "status": "not_found",
                "resource_type": resource_type,
                "resource_id": mutation.resource_id,
                "duplicate": False,
            }
        except (ValueError, TypeError) as exc:
            self.session.rollback()
            result = {
                "request_id": mutation.request_id,
                "status": "rejected",
                "error": {"code": "invalid_mutation", "message": str(exc)},
                "duplicate": False,
            }

        self.session.add(
            SyncRequest(
                user_id=self.user_id,
                device_id=device_id,
                request_id=mutation.request_id,
                request_hash=request_hash,
                operation=mutation.operation,
                result=result,
            )
        )
        self.session.commit()
        return result

    def pull(self, cursor: str | None, *, limit: int = 200) -> dict[str, Any]:
        statement = select(AuditEvent).where(AuditEvent.user_id == self.user_id)
        if cursor:
            try:
                timestamp_value, event_id = cursor.split("|", 1)
                timestamp = datetime.fromisoformat(timestamp_value)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
            except (ValueError, TypeError) as exc:
                raise ValueError("The sync cursor is invalid.") from exc
            statement = statement.where(
                or_(
                    AuditEvent.created_at > timestamp,
                    and_(
                        AuditEvent.created_at == timestamp,
                        AuditEvent.id > event_id,
                    ),
                )
            )
        rows = list(
            self.session.scalars(
                statement.order_by(AuditEvent.created_at, AuditEvent.id).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = cursor
        if rows:
            last = rows[-1]
            timestamp = last.created_at
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            next_cursor = f"{timestamp.isoformat()}|{last.id}"
        return {
            "changes": [
                {
                    "id": event.id,
                    "resource_type": event.entity_type,
                    "resource_id": event.entity_id,
                    "operation": event.action,
                    "version": (event.after_data or {}).get("version"),
                    "occurred_at": event.created_at,
                }
                for event in rows
            ],
            "cursor": next_cursor,
            "has_more": has_more,
        }
