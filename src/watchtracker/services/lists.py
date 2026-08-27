from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import (
    AuditEvent,
    CatalogItem,
    MediaList,
    MediaListActivity,
    MediaListItem,
    MediaListMembership,
    UserAccount,
    UserNotification,
    WatchEntry,
)
from watchtracker.schemas import (
    CatalogOut,
    MediaListActivityOut,
    MediaListItemOut,
    MediaListMembershipOut,
    MediaListOut,
)
from watchtracker.services.entries import EntryConflict, EntryNotFound, serialize_entry


def _now() -> datetime:
    return datetime.now(UTC)


class MediaListService:
    """Catalog-based lists with explicit owner/editor/viewer authorization."""

    def __init__(self, session: Session, principal: Principal | None = None):
        self.session = session
        self.user_id = current_user_id(session, principal)

    def _membership(self, list_id: str) -> MediaListMembership:
        membership = self.session.scalar(
            select(MediaListMembership).where(
                MediaListMembership.list_id == list_id,
                MediaListMembership.user_id == self.user_id,
            )
        )
        if membership is None:
            raise EntryNotFound("List not found")
        return membership

    def _loaded(
        self,
        list_id: str,
        *,
        permission: Literal["view", "edit", "manage"] = "view",
    ) -> tuple[MediaList, MediaListMembership]:
        membership = self._membership(list_id)
        if permission == "edit" and membership.role not in {"owner", "editor"}:
            raise EntryConflict("You have view-only access to this list.")
        if permission == "manage" and membership.role != "owner":
            raise EntryConflict("Only the list owner can manage sharing.")
        media_list = self.session.scalar(
            select(MediaList)
            .where(MediaList.id == list_id)
            .execution_options(populate_existing=True)
            .options(
                selectinload(MediaList.items)
                .selectinload(MediaListItem.catalog_item)
                .selectinload(CatalogItem.external_identities),
                selectinload(MediaList.memberships),
            )
        )
        if media_list is None:
            raise EntryNotFound("List not found")
        return media_list, membership

    @staticmethod
    def _catalog_out(catalog: CatalogItem) -> CatalogOut:
        return CatalogOut.model_validate(catalog).model_copy(
            update={
                "poster_override_url": None,
                "external_ids": {
                    identity.namespace: identity.external_id
                    for identity in catalog.external_identities
                },
            }
        )

    def _serialize(
        self, media_list: MediaList, membership: MediaListMembership
    ) -> MediaListOut:
        catalog_ids = [item.catalog_item_id for item in media_list.items]
        entries: dict[str, WatchEntry] = {}
        if catalog_ids:
            rows = self.session.scalars(
                select(WatchEntry)
                .where(
                    WatchEntry.user_id == self.user_id,
                    WatchEntry.catalog_item_id.in_(catalog_ids),
                    WatchEntry.deleted_at.is_(None),
                )
                .options(
                    selectinload(WatchEntry.catalog_item).selectinload(
                        CatalogItem.external_identities
                    ),
                    selectinload(WatchEntry.viewing_events),
                )
            )
            entries = {entry.catalog_item_id: entry for entry in rows}
        user_ids = [row.user_id for row in media_list.memberships]
        users = {
            user.id: user
            for user in self.session.scalars(
                select(UserAccount).where(UserAccount.id.in_(user_ids))
            )
        }
        member_rows = []
        for row in sorted(
            media_list.memberships,
            key=lambda value: (
                value.role != "owner",
                users[value.user_id].display_name.casefold(),
            ),
        ):
            user = users[row.user_id]
            member_rows.append(
                MediaListMembershipOut(
                    id=row.id,
                    user_id=row.user_id,
                    username=user.username,
                    display_name=user.display_name,
                    role=row.role,
                    accepted_at=row.accepted_at,
                )
            )
        items = []
        for item in media_list.items:
            entry = entries.get(item.catalog_item_id)
            items.append(
                MediaListItemOut(
                    id=item.id,
                    catalog_item=self._catalog_out(item.catalog_item),
                    entry=serialize_entry(entry, include_events=False) if entry else None,
                    tracked_by_viewer=entry is not None,
                    added_by_user_id=item.added_by_user_id,
                    position=item.position,
                    shared_note=item.shared_note,
                    added_at=item.added_at,
                )
            )
        return MediaListOut(
            id=media_list.id,
            version=media_list.version,
            name=media_list.name,
            pinned_to_navigation=(
                media_list.pinned_to_navigation if membership.role == "owner" else False
            ),
            visibility=media_list.visibility,
            current_user_role=membership.role,
            can_edit=membership.role in {"owner", "editor"},
            can_manage_members=membership.role == "owner",
            owner_user_id=media_list.user_id,
            members=member_rows,
            items=items,
            created_at=media_list.created_at,
            updated_at=media_list.updated_at,
        )

    def _activity(
        self, media_list: MediaList, action: str, payload: dict | None = None
    ) -> None:
        self.session.add(
            MediaListActivity(
                list_id=media_list.id,
                actor_user_id=self.user_id,
                action=action,
                safe_payload=payload or {},
            )
        )

    def _notify_members(
        self,
        media_list: MediaList,
        event_type: str,
        message: str,
        *,
        exclude_actor: bool = True,
    ) -> None:
        for membership in media_list.memberships:
            if exclude_actor and membership.user_id == self.user_id:
                continue
            self.session.add(
                UserNotification(
                    user_id=membership.user_id,
                    event_type=event_type,
                    title=media_list.name,
                    safe_message=message[:300],
                    resource_type="media_list",
                    resource_id=media_list.id,
                )
            )

    def _audit_members(self, media_list: MediaList, action: str) -> None:
        snapshot = {"id": media_list.id, "version": media_list.version}
        for membership in media_list.memberships:
            self.session.add(
                AuditEvent(
                    user_id=membership.user_id,
                    action=action,
                    entity_type="media_list",
                    entity_id=media_list.id,
                    source="ui",
                    after_data=snapshot,
                )
            )

    def _touch(self, media_list: MediaList, action: str) -> None:
        media_list.version = int(media_list.version or 0) + 1
        media_list.updated_at = _now()
        self._audit_members(media_list, action)

    def list_all(
        self, *, sort: str = "created_at", direction: str = "asc"
    ) -> list[MediaListOut]:
        columns = {
            "name": func.lower(MediaList.name),
            "created_at": MediaList.created_at,
            "updated_at": MediaList.updated_at,
        }
        column = columns.get(sort, MediaList.created_at)
        ordering = column.desc() if direction == "desc" else column.asc()
        rows = self.session.execute(
            select(MediaList, MediaListMembership)
            .join(MediaListMembership, MediaListMembership.list_id == MediaList.id)
            .where(MediaListMembership.user_id == self.user_id)
            .order_by(ordering, MediaList.id)
            .options(
                selectinload(MediaList.items)
                .selectinload(MediaListItem.catalog_item)
                .selectinload(CatalogItem.external_identities),
                selectinload(MediaList.memberships),
            )
        ).all()
        return [self._serialize(media_list, membership) for media_list, membership in rows]

    def get(self, list_id: str) -> MediaListOut:
        return self._serialize(*self._loaded(list_id))

    def create(self, name: str) -> MediaListOut:
        clean_name = " ".join(name.split())
        duplicate = self.session.scalar(
            select(MediaList).where(
                MediaList.user_id == self.user_id,
                func.lower(MediaList.name) == clean_name.casefold(),
            )
        )
        if duplicate:
            raise EntryConflict("A list with that name already exists")
        media_list = MediaList(user_id=self.user_id, name=clean_name)
        membership = MediaListMembership(
            media_list=media_list,
            user_id=self.user_id,
            role="owner",
            invited_by_user_id=self.user_id,
        )
        self.session.add_all([media_list, membership])
        self.session.flush()
        self._activity(media_list, "list_created", {"name": clean_name})
        self._audit_members(media_list, "list_created")
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise EntryConflict("A list with that name already exists") from exc
        return self.get(media_list.id)

    def delete(self, list_id: str) -> None:
        media_list, _membership = self._loaded(list_id, permission="manage")
        self._notify_members(media_list, "list_deleted", "The shared list was deleted.")
        self.session.delete(media_list)
        self.session.commit()

    def update(
        self,
        list_id: str,
        *,
        pinned: bool | None = None,
        name: str | None = None,
        expected_version: int | None = None,
        commit: bool = True,
    ) -> MediaListOut:
        media_list, membership = self._loaded(list_id)
        if expected_version is not None and media_list.version != expected_version:
            raise EntryConflict("This list changed on another device. Reload and try again.")
        if pinned is not None:
            if membership.role != "owner":
                raise EntryConflict("Only the owner can pin this shared list.")
            if pinned and not media_list.pinned_to_navigation:
                pinned_count = self.session.scalar(
                    select(func.count(MediaList.id)).where(
                        MediaList.user_id == self.user_id,
                        MediaList.pinned_to_navigation.is_(True),
                    )
                )
                if int(pinned_count or 0) >= 5:
                    raise EntryConflict("You can add up to five custom lists to navigation")
            media_list.pinned_to_navigation = pinned
        if name is not None:
            if membership.role != "owner":
                raise EntryConflict("Only the owner can rename this list.")
            clean_name = " ".join(name.split())
            duplicate = self.session.scalar(
                select(MediaList).where(
                    MediaList.user_id == self.user_id,
                    MediaList.id != list_id,
                    func.lower(MediaList.name) == clean_name.casefold(),
                )
            )
            if duplicate:
                raise EntryConflict("A list with that name already exists")
            media_list.name = clean_name
        self._touch(media_list, "list_updated")
        self._activity(media_list, "list_updated")
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return self.get(list_id)

    def set_navigation_pin(
        self, list_id: str, pinned: bool, *, expected_version: int | None = None
    ) -> MediaListOut:
        return self.update(list_id, pinned=pinned, expected_version=expected_version)

    def add_entry(self, list_id: str, entry_id: str) -> MediaListOut:
        entry = self.session.scalar(
            select(WatchEntry).where(
                WatchEntry.id == entry_id,
                WatchEntry.user_id == self.user_id,
                WatchEntry.deleted_at.is_(None),
            )
        )
        if not entry:
            raise EntryNotFound("Watch entry not found")
        return self.add_catalog_item(list_id, entry.catalog_item_id)

    def add_catalog_item(
        self,
        list_id: str,
        catalog_item_id: str,
        *,
        shared_note: str | None = None,
        expected_version: int | None = None,
        commit: bool = True,
    ) -> MediaListOut:
        media_list, _membership = self._loaded(list_id, permission="edit")
        if expected_version is not None and media_list.version != expected_version:
            raise EntryConflict("This list changed on another device. Reload and try again.")
        catalog = self.session.get(CatalogItem, catalog_item_id)
        if catalog is None:
            raise EntryNotFound("Catalog title not found")
        existing = next(
            (item for item in media_list.items if item.catalog_item_id == catalog_item_id),
            None,
        )
        if existing:
            return self._serialize(media_list, self._membership(list_id))
        position = max((item.position for item in media_list.items), default=-1) + 1
        self.session.add(
            MediaListItem(
                media_list=media_list,
                catalog_item=catalog,
                added_by_user_id=self.user_id,
                position=position,
                shared_note=" ".join(shared_note.split())[:500] if shared_note else None,
            )
        )
        self._touch(media_list, "list_item_added")
        self._activity(
            media_list,
            "item_added",
            {"catalog_item_id": catalog.id, "title": catalog.canonical_title},
        )
        self._notify_members(
            media_list,
            "list_item_added",
            f"{catalog.canonical_title} was added to this shared list.",
        )
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return self.get(list_id)

    def remove_entry(self, list_id: str, entry_id: str) -> MediaListOut:
        entry = self.session.scalar(
            select(WatchEntry).where(
                WatchEntry.id == entry_id,
                WatchEntry.user_id == self.user_id,
            )
        )
        if entry is None:
            raise EntryNotFound("Watch entry not found")
        return self.remove_catalog_item(list_id, entry.catalog_item_id)

    def remove_catalog_item(
        self,
        list_id: str,
        catalog_item_id: str,
        *,
        expected_version: int | None = None,
        commit: bool = True,
    ) -> MediaListOut:
        media_list, _membership = self._loaded(list_id, permission="edit")
        if expected_version is not None and media_list.version != expected_version:
            raise EntryConflict("This list changed on another device. Reload and try again.")
        item = next(
            (item for item in media_list.items if item.catalog_item_id == catalog_item_id),
            None,
        )
        if item is None:
            raise EntryNotFound("Title is not in this list")
        title = item.catalog_item.canonical_title
        self.session.delete(item)
        self._touch(media_list, "list_item_removed")
        self._activity(
            media_list,
            "item_removed",
            {"catalog_item_id": catalog_item_id, "title": title},
        )
        self._notify_members(
            media_list,
            "list_item_removed",
            f"{title} was removed from this shared list.",
        )
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return self.get(list_id)

    def add_member(self, list_id: str, username: str, role: str) -> MediaListOut:
        media_list, _membership = self._loaded(list_id, permission="manage")
        normalized = " ".join(username.split()).casefold()
        user = self.session.scalar(
            select(UserAccount).where(
                UserAccount.normalized_username == normalized,
                UserAccount.state == "active",
            )
        )
        if user is None:
            raise EntryNotFound("No active account has that exact username.")
        if user.id == media_list.user_id:
            raise EntryConflict("The list owner is already a member.")
        existing = self.session.scalar(
            select(MediaListMembership).where(
                MediaListMembership.list_id == list_id,
                MediaListMembership.user_id == user.id,
            )
        )
        if existing:
            existing.role = role
        else:
            self.session.add(
                MediaListMembership(
                    media_list=media_list,
                    user_id=user.id,
                    role=role,
                    invited_by_user_id=self.user_id,
                )
            )
            self.session.flush()
        media_list.visibility = "shared"
        self._touch(media_list, "list_member_added")
        self._activity(
            media_list,
            "member_added",
            {"user_id": user.id, "display_name": user.display_name, "role": role},
        )
        self.session.add(
            UserNotification(
                user_id=user.id,
                event_type="list_shared",
                title=media_list.name,
                safe_message=f"A list was shared with you as {role}.",
                resource_type="media_list",
                resource_id=media_list.id,
            )
        )
        self.session.commit()
        return self.get(list_id)

    def update_member(self, list_id: str, member_user_id: str, role: str) -> MediaListOut:
        media_list, _membership = self._loaded(list_id, permission="manage")
        target = self.session.scalar(
            select(MediaListMembership).where(
                MediaListMembership.list_id == list_id,
                MediaListMembership.user_id == member_user_id,
            )
        )
        if target is None or target.role == "owner":
            raise EntryNotFound("Shared-list member not found")
        target.role = role
        self._touch(media_list, "list_member_updated")
        self._activity(media_list, "member_updated", {"user_id": member_user_id, "role": role})
        self.session.add(
            UserNotification(
                user_id=member_user_id,
                event_type="list_role_changed",
                title=media_list.name,
                safe_message=f"Your shared-list role changed to {role}.",
                resource_type="media_list",
                resource_id=media_list.id,
            )
        )
        self.session.commit()
        return self.get(list_id)

    def remove_member(self, list_id: str, member_user_id: str) -> MediaListOut:
        media_list, _membership = self._loaded(list_id, permission="manage")
        target = self.session.scalar(
            select(MediaListMembership).where(
                MediaListMembership.list_id == list_id,
                MediaListMembership.user_id == member_user_id,
            )
        )
        if target is None or target.role == "owner":
            raise EntryNotFound("Shared-list member not found")
        self.session.delete(target)
        self._touch(media_list, "list_member_removed")
        self._activity(media_list, "member_removed", {"user_id": member_user_id})
        self.session.add(
            UserNotification(
                user_id=member_user_id,
                event_type="list_unshared",
                title=media_list.name,
                safe_message="This list is no longer shared with you.",
                resource_type="media_list",
                resource_id=media_list.id,
            )
        )
        remaining = [row for row in media_list.memberships if row.id != target.id]
        if len(remaining) == 1:
            media_list.visibility = "private"
        self.session.commit()
        return self.get(list_id)

    def activity(self, list_id: str, *, limit: int = 50) -> list[MediaListActivityOut]:
        self._loaded(list_id)
        rows = list(
            self.session.scalars(
                select(MediaListActivity)
                .where(MediaListActivity.list_id == list_id)
                .order_by(MediaListActivity.created_at.desc(), MediaListActivity.id.desc())
                .limit(limit)
            )
        )
        actor_ids = {row.actor_user_id for row in rows if row.actor_user_id}
        users = (
            {
                user.id: user.display_name
                for user in self.session.scalars(
                    select(UserAccount).where(UserAccount.id.in_(actor_ids))
                )
            }
            if actor_ids
            else {}
        )
        return [
            MediaListActivityOut(
                id=row.id,
                action=row.action,
                actor_user_id=row.actor_user_id,
                actor_display_name=users.get(row.actor_user_id),
                safe_payload=row.safe_payload,
                created_at=row.created_at,
            )
            for row in rows
        ]

    def notifications(self, *, unread_only: bool = False, limit: int = 100) -> list[dict]:
        statement = select(UserNotification).where(
            UserNotification.user_id == self.user_id,
            UserNotification.dismissed_at.is_(None),
        )
        if unread_only:
            statement = statement.where(UserNotification.read_at.is_(None))
        rows = self.session.scalars(
            statement.order_by(UserNotification.created_at.desc()).limit(limit)
        )
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "title": row.title,
                "message": row.safe_message,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "read_at": row.read_at,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def update_notification(self, notification_id: str, action: str) -> bool:
        row = self.session.scalar(
            select(UserNotification).where(
                UserNotification.id == notification_id,
                UserNotification.user_id == self.user_id,
            )
        )
        if row is None:
            return False
        if action == "read":
            row.read_at = _now()
        elif action == "unread":
            row.read_at = None
        elif action == "dismiss":
            row.dismissed_at = _now()
        else:
            raise ValueError("Unknown notification action.")
        self.session.commit()
        return True
