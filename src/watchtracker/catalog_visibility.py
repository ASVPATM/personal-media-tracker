from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from watchtracker.models import (
    CatalogItem,
    MediaList,
    MediaListItem,
    MediaListMembership,
    WatchEntry,
)

PUBLIC_METADATA_PROVIDERS = frozenset(
    {
        "anilist",
        "kitsu",
        "mal",
        "tmdb_movie",
        "tmdb_tv",
        "tvmaze",
        "wikidata",
    }
)


def is_verified_public_catalog(item: CatalogItem) -> bool:
    return bool(
        item.provider_source in PUBLIC_METADATA_PROVIDERS
        and item.provider_id
        and (item.metadata_provenance or {}).get("provider_identity_verified") is True
    )


def catalog_visible_to_user(
    session: Session, *, user_id: str, catalog_item: CatalogItem
) -> bool:
    """Authorize a catalog UUID without revealing another user's manual title."""

    if is_verified_public_catalog(catalog_item):
        return True
    if session.scalar(
        select(WatchEntry.id).where(
            WatchEntry.user_id == user_id,
            WatchEntry.catalog_item_id == catalog_item.id,
            WatchEntry.deleted_at.is_(None),
        )
    ):
        return True
    return bool(
        session.scalar(
            select(MediaListItem.id)
            .join(
                MediaListMembership,
                MediaListMembership.list_id == MediaListItem.list_id,
            )
            .join(MediaList, MediaList.id == MediaListItem.list_id)
            .where(
                MediaListItem.catalog_item_id == catalog_item.id,
                MediaListItem.deleted_at.is_(None),
                MediaListMembership.user_id == user_id,
                MediaList.deleted_at.is_(None),
            )
            .limit(1)
        )
    )
