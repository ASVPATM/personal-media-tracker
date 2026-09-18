from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from watchtracker.authorization import current_user_id
from watchtracker.db import session_dependency
from watchtracker.metadata.http import ProviderError
from watchtracker.models import MusicAlbum, MusicList, new_id, utcnow
from watchtracker.music.schemas import (
    AlbumInput,
    AlbumUpdate,
    MusicDocument,
    MusicImport,
    MusicListInput,
    normalize_artwork,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(session_dependency)]


def identity_key(data: dict) -> str:
    identity = (
        f"musicbrainz:{data['provider_id']}"
        if data.get("provider_id")
        else "|".join(
            unicodedata.normalize("NFKC", str(data.get(key) or "")).strip().casefold()
            for key in ("title", "artist", "year", "release_type")
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def album_query(session):
    return select(MusicAlbum).where(
        MusicAlbum.user_id == current_user_id(session), MusicAlbum.deleted_at.is_(None)
    )


def get_album(session, identifier):
    row = session.scalar(album_query(session).where(MusicAlbum.id == str(identifier)))
    if row is None:
        raise HTTPException(404, "Music entry not found.")
    return row


def album_out(row, *, detail=True):
    result = {
        key: getattr(row, key)
        for key in AlbumInput.model_fields
        if key not in {"artwork_data", "tracks"}
    }
    result.update(
        id=row.id,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        track_count=len(row.tracks),
        has_local_artwork=bool(row.artwork_data),
    )
    if row.artwork_data:
        result["cover_url"] = f"/api/music/albums/{row.id}/artwork?v={row.version}"
    else:
        result["cover_url"] = row.artwork_url
    if detail:
        result.update(tracks=row.tracks, artwork_data=row.artwork_data)
    return result


@router.get("/api/music/albums")
def albums(
    session: SessionDep,
    q: str = Query(default="", max_length=500),
    status: str = "",
    favorite: bool = False,
    sort: Literal["recent", "title", "artist", "rating"] = "recent",
    direction: Literal["asc", "desc"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    list_id: UUID | None = None,
):
    statement = album_query(session)
    if q.strip():
        term = q.strip().lower()
        statement = statement.where(
            func.lower(MusicAlbum.title).contains(term, autoescape=True)
            | func.lower(MusicAlbum.artist).contains(term, autoescape=True)
        )
    if status == "active":
        statement = statement.where(MusicAlbum.status.in_(["listening", "plan_to_listen"]))
    elif status:
        statement = statement.where(MusicAlbum.status == status)
    if favorite:
        statement = statement.where(MusicAlbum.favorite.is_(True))
    if list_id:
        music_list = get_list(session, list_id)
        statement = statement.where(MusicAlbum.id.in_(music_list.album_ids))
    if sort == "rating":
        statement = statement.where(MusicAlbum.rating.is_not(None))
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    order_column = {
        "recent": MusicAlbum.created_at,
        "title": func.lower(MusicAlbum.title),
        "artist": func.lower(MusicAlbum.artist),
        "rating": MusicAlbum.rating,
    }[sort]
    sort_direction = direction or ("desc" if sort in {"recent", "rating"} else "asc")
    order = order_column.desc() if sort_direction == "desc" else order_column.asc()
    rows = session.scalars(
        statement.order_by(order, MusicAlbum.id).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [album_out(row, detail=False) for row in rows],
        "total": total,
        "page": page,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/api/music/albums", status_code=201)
def create_album(payload: AlbumInput, session: SessionDep):
    data = payload.model_dump(mode="json")
    row = MusicAlbum(user_id=current_user_id(session), identity_key=identity_key(data), **data)
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409,
            "This album is already in your music collection. No duplicate was added.",
        ) from exc
    return album_out(row)


@router.get("/api/music/albums/{identifier}")
def album(identifier: UUID, session: SessionDep):
    return album_out(get_album(session, identifier))


@router.put("/api/music/albums/{identifier}")
def update_album(identifier: UUID, payload: AlbumUpdate, session: SessionDep):
    row = get_album(session, identifier)
    data = payload.model_dump(mode="json", exclude={"version"})
    data["artwork_data"] = payload.artwork_for_update(row.artwork_data)
    if "status" not in payload.model_fields_set:
        data["status"] = row.status
    for field in (
        "subgenres",
        "edition_info",
        "completion_count",
        "genre_additions",
        "genre_removals",
        "subgenre_additions",
        "subgenre_removals",
    ):
        if field not in payload.model_fields_set:
            data[field] = getattr(row, field)
    data.update(
        identity_key=identity_key(data), version=payload.version + 1, updated_at=utcnow()
    )
    try:
        result = session.execute(
            update(MusicAlbum)
            .where(
                MusicAlbum.id == row.id,
                MusicAlbum.user_id == current_user_id(session),
                MusicAlbum.version == payload.version,
            )
            .values(**data)
        )
        if not result.rowcount:
            session.rollback()
            raise HTTPException(
                409, "This music entry changed elsewhere. Reopen it before saving."
            )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409, "Another music entry already uses this album identity."
        ) from exc
    session.expire_all()
    return album_out(get_album(session, identifier))


@router.delete("/api/music/albums/{identifier}", status_code=204)
def delete_album(identifier: UUID, session: SessionDep, version: int = Query(ge=1)):
    row = get_album(session, identifier)
    result = session.execute(
        update(MusicAlbum)
        .where(MusicAlbum.id == row.id, MusicAlbum.version == version)
        .values(
            deleted_at=utcnow(),
            version=version + 1,
            identity_key=hashlib.sha256(
                f"removed:{row.id}:{row.identity_key}".encode()
            ).hexdigest(),
        )
    )
    if not result.rowcount:
        raise HTTPException(
            409, "This music entry changed elsewhere. Reopen it before removing."
        )
    session.commit()


@router.get("/api/music/albums/{identifier}/artwork")
def local_artwork(identifier: UUID, session: SessionDep):
    import base64

    row = get_album(session, identifier)
    if not row.artwork_data:
        raise HTTPException(404, "No local artwork.")
    return Response(
        base64.b64decode(row.artwork_data.split(",", 1)[1]),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/api/music/artwork")
async def artwork(file: UploadFile = File()):
    try:
        return {"artwork_data": normalize_artwork(await file.read(4 * 1024 * 1024 + 1))}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/music/albums/{identifier}/artwork-options")
async def artwork_options(identifier: UUID, request: Request, session: SessionDep):
    row = get_album(session, identifier)
    if not row.provider_id:
        return {
            "options": [],
            "source": "Cover Art Archive",
            "warning": "Link album metadata first, or upload an image.",
        }
    try:
        return await request.app.state.music_provider.artwork_options(
            UUID(row.provider_id), UUID(row.release_group_id) if row.release_group_id else None
        )
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            503, "Artwork options could not be loaded. Your album was not changed."
        ) from exc


@router.get("/api/music/search")
async def search(
    request: Request,
    q: str = Query(min_length=2, max_length=200),
    artist: str = Query(default="", max_length=200),
):
    try:
        return await request.app.state.music_provider.search(q, artist)
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            503, "MusicBrainz is unavailable. You can still add music manually."
        ) from exc


@router.get("/api/music/metadata/{identifier}")
async def metadata(identifier: UUID, request: Request):
    try:
        return await request.app.state.music_provider.detail(identifier)
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            503,
            "Album details could not be loaded. Nothing was changed; try again or enter details manually.",
        ) from exc


def get_list(session, identifier):
    row = session.scalar(
        select(MusicList).where(
            MusicList.id == str(identifier), MusicList.user_id == current_user_id(session)
        )
    )
    if row is None:
        raise HTTPException(404, "Music list not found.")
    return row


def validate_members(session, values):
    ids = list(dict.fromkeys(str(value) for value in values))
    owned = set(
        session.scalars(
            album_query(session).with_only_columns(MusicAlbum.id).where(MusicAlbum.id.in_(ids))
        )
    )
    if set(ids) != owned:
        raise HTTPException(
            422, "Music lists can contain only active music from your collection."
        )
    return ids


@router.get("/api/music/lists")
def lists(session: SessionDep):
    owned = set(session.scalars(album_query(session).with_only_columns(MusicAlbum.id)))
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "version": row.version,
                "album_ids": [key for key in row.album_ids if key in owned],
            }
            for row in session.scalars(
                select(MusicList)
                .where(MusicList.user_id == current_user_id(session))
                .order_by(MusicList.created_at)
            )
        ]
    }


@router.post("/api/music/lists", status_code=201)
def create_list(payload: MusicListInput, session: SessionDep):
    row = MusicList(
        user_id=current_user_id(session),
        name=payload.name,
        album_ids=validate_members(session, payload.album_ids),
    )
    session.add(row)
    session.commit()
    return {"id": row.id, "name": row.name, "version": row.version, "album_ids": row.album_ids}


@router.put("/api/music/lists/{identifier}")
def update_list(identifier: UUID, payload: MusicListInput, session: SessionDep):
    row = get_list(session, identifier)
    result = session.execute(
        update(MusicList)
        .where(MusicList.id == row.id, MusicList.version == payload.version)
        .values(
            name=payload.name,
            album_ids=validate_members(session, payload.album_ids),
            version=row.version + 1,
        )
    )
    if not result.rowcount:
        raise HTTPException(409, "This music list changed elsewhere. Reopen it before saving.")
    session.commit()
    return {"id": row.id}


@router.delete("/api/music/lists/{identifier}", status_code=204)
def delete_list(identifier: UUID, session: SessionDep, version: int = Query(ge=1)):
    row = get_list(session, identifier)
    if row.version != version:
        raise HTTPException(
            409, "This music list changed elsewhere. Reopen it before removing."
        )
    session.delete(row)
    session.commit()


@router.get("/api/music/insights")
def insights(session: SessionDep):
    rows = list(session.scalars(album_query(session).options(defer(MusicAlbum.artwork_data))))
    ratings = [row.rating for row in rows if row.rating is not None]
    return {
        "total": len(rows),
        "artists": len({row.artist.casefold() for row in rows}),
        "rated": len(ratings),
        "unrated": len(rows) - len(ratings),
        "favorites": sum(row.favorite for row in rows),
        "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "statuses": dict(Counter(row.status for row in rows)),
        "genres": dict(
            Counter(genre for row in rows for genre in set(row.genres)).most_common(12)
        ),
        "years": dict(
            sorted(Counter(str(row.year // 10 * 10) for row in rows if row.year).items())
        ),
    }


@router.get("/api/exports/music-collection.json")
def export_music(session: SessionDep):
    rows = list(session.scalars(album_query(session).order_by(MusicAlbum.created_at)))
    ids = {row.id for row in rows}
    document = {
        "format": "pmt-music-collection",
        "version": 1,
        "albums": [
            {"id": row.id, **{key: getattr(row, key) for key in AlbumInput.model_fields}}
            for row in rows
        ],
        "lists": [
            {"name": row.name, "album_ids": [key for key in row.album_ids if key in ids]}
            for row in session.scalars(
                select(MusicList).where(MusicList.user_id == current_user_id(session))
            )
        ],
    }
    return Response(
        json.dumps(document, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="pmt-music-collection.json"',
            "Cache-Control": "no-store",
        },
    )


def import_summary(document: MusicDocument, session):
    data = document.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    keys = set(
        session.scalars(
            select(MusicAlbum.identity_key).where(
                MusicAlbum.user_id == current_user_id(session)
            )
        )
    )
    added = 0
    for row in data["albums"]:
        key = identity_key(row)
        if key not in keys:
            added += 1
            keys.add(key)
    return {
        "sha256": digest,
        "new_albums": added,
        "skipped": len(data["albums"]) - added,
        "lists": len(data["lists"]),
    }


@router.post("/api/music/import/preview")
def inspect_music(payload: MusicImport, session: SessionDep):
    return import_summary(payload.document, session)


@router.post("/api/music/import")
def import_music(payload: MusicImport, session: SessionDep):
    summary = import_summary(payload.document, session)
    if payload.sha256 != summary["sha256"]:
        raise HTTPException(409, "Inspect this music file before importing it.")
    owner = current_user_id(session)
    existing = {
        row.identity_key: row
        for row in session.scalars(select(MusicAlbum).where(MusicAlbum.user_id == owner))
    }
    mapped = {}
    try:
        for source in payload.document.albums:
            data = source.model_dump(mode="json", exclude={"id"})
            key = identity_key(data)
            row = existing.get(key)
            if row is None:
                row = MusicAlbum(id=new_id(), user_id=owner, identity_key=key, **data)
                session.add(row)
                existing[key] = row
            if row.deleted_at is None:
                mapped[str(source.id)] = row.id
        existing_lists = {
            (row.name, tuple(row.album_ids))
            for row in session.scalars(select(MusicList).where(MusicList.user_id == owner))
        }
        for source in payload.document.lists:
            ids = list(
                dict.fromkeys(
                    mapped[str(key)] for key in source.album_ids if str(key) in mapped
                )
            )
            signature = (source.name, tuple(ids))
            if signature not in existing_lists:
                session.add(MusicList(user_id=owner, name=source.name, album_ids=ids))
                existing_lists.add(signature)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409, "The music collection changed during import. Inspect the file again."
        ) from exc
    return summary
