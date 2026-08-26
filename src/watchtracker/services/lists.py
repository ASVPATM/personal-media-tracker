from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from watchtracker.models import MediaList, MediaListItem, WatchEntry
from watchtracker.schemas import MediaListItemOut, MediaListOut
from watchtracker.services.entries import EntryConflict, EntryNotFound, serialize_entry


class MediaListService:
    """Small, local list organizer; entries remain owned by the main library."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _serialize(media_list: MediaList) -> MediaListOut:
        return MediaListOut(
            id=media_list.id,
            name=media_list.name,
            pinned_to_navigation=media_list.pinned_to_navigation,
            items=[
                MediaListItemOut(
                    id=item.id,
                    entry=serialize_entry(item.entry, include_events=False),
                    added_at=item.added_at,
                )
                for item in media_list.items
                if item.entry.deleted_at is None
            ],
            created_at=media_list.created_at,
            updated_at=media_list.updated_at,
        )

    def _loaded(self, list_id: str) -> MediaList:
        media_list = self.session.scalar(
            select(MediaList)
            .where(MediaList.id == list_id)
            .execution_options(populate_existing=True)
            .options(
                selectinload(MediaList.items)
                .selectinload(MediaListItem.entry)
                .selectinload(WatchEntry.catalog_item),
                selectinload(MediaList.items)
                .selectinload(MediaListItem.entry)
                .selectinload(WatchEntry.viewing_events),
            )
        )
        if not media_list:
            raise EntryNotFound("List not found")
        return media_list

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
        lists = self.session.scalars(
            select(MediaList)
            .order_by(ordering, MediaList.id)
            .options(
                selectinload(MediaList.items)
                .selectinload(MediaListItem.entry)
                .selectinload(WatchEntry.catalog_item),
                selectinload(MediaList.items)
                .selectinload(MediaListItem.entry)
                .selectinload(WatchEntry.viewing_events),
            )
        )
        return [self._serialize(media_list) for media_list in lists]

    def get(self, list_id: str) -> MediaListOut:
        return self._serialize(self._loaded(list_id))

    def create(self, name: str) -> MediaListOut:
        clean_name = " ".join(name.split())
        duplicate = self.session.scalar(
            select(MediaList).where(func.lower(MediaList.name) == clean_name.casefold())
        )
        if duplicate:
            raise EntryConflict("A list with that name already exists")
        media_list = MediaList(name=clean_name)
        self.session.add(media_list)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise EntryConflict("A list with that name already exists") from exc
        return self._serialize(self._loaded(media_list.id))

    def delete(self, list_id: str) -> None:
        media_list = self._loaded(list_id)
        self.session.delete(media_list)
        self.session.commit()

    def set_navigation_pin(self, list_id: str, pinned: bool) -> MediaListOut:
        media_list = self._loaded(list_id)
        if pinned and not media_list.pinned_to_navigation:
            pinned_count = self.session.scalar(
                select(func.count(MediaList.id)).where(MediaList.pinned_to_navigation.is_(True))
            )
            if int(pinned_count or 0) >= 5:
                raise EntryConflict("You can add up to five custom lists to navigation")
        media_list.pinned_to_navigation = pinned
        self.session.commit()
        return self._serialize(self._loaded(list_id))

    def add_entry(self, list_id: str, entry_id: str) -> MediaListOut:
        media_list = self._loaded(list_id)
        entry = self.session.scalar(
            select(WatchEntry).where(WatchEntry.id == entry_id, WatchEntry.deleted_at.is_(None))
        )
        if not entry:
            raise EntryNotFound("Watch entry not found")
        if any(item.entry_id == entry_id for item in media_list.items):
            return self._serialize(media_list)
        self.session.add(MediaListItem(media_list=media_list, entry=entry))
        self.session.commit()
        return self._serialize(self._loaded(list_id))

    def remove_entry(self, list_id: str, entry_id: str) -> MediaListOut:
        media_list = self._loaded(list_id)
        item = next((item for item in media_list.items if item.entry_id == entry_id), None)
        if not item:
            raise EntryNotFound("Title is not in this list")
        self.session.delete(item)
        self.session.commit()
        return self._serialize(self._loaded(list_id))
