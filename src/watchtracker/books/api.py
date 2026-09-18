from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from collections import Counter
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from watchtracker.authorization import current_user_id
from watchtracker.books.schemas import (
    BookDocument,
    BookImport,
    BookInput,
    BookListInput,
    BookUpdate,
    EditionId,
    WorkId,
)
from watchtracker.metadata.http import ProviderError
from watchtracker.models import BookList, BookRecord, new_id, utcnow
from watchtracker.music.api import SessionDep, artwork

router = APIRouter()
router.add_api_route("/api/books/artwork", artwork, methods=["POST"])


def identity_key(data):
    value = (
        f"openlibrary:{data['provider_id']}"
        if data.get("provider_id")
        else f"isbn:{data['isbn']}"
        if data.get("isbn")
        else "|".join(
            unicodedata.normalize("NFKC", str(data.get(key) or "")).strip().casefold()
            for key in ("title", "author", "year", "book_format")
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def query(session):
    return select(BookRecord).where(
        BookRecord.user_id == current_user_id(session), BookRecord.deleted_at.is_(None)
    )


def get_book(session, identifier):
    row = session.scalar(query(session).where(BookRecord.id == str(identifier)))
    if row is None:
        raise HTTPException(404, "Book not found.")
    return row


def output(row, detail=True):
    result = {
        key: getattr(row, key)
        for key in BookInput.model_fields
        if detail or key not in {"artwork_data", "chapters", "description", "notes"}
    }
    result.update(
        id=row.id,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        cover_url=f"/api/books/entries/{row.id}/artwork?v={row.version}"
        if row.artwork_data
        else row.artwork_url,
    )
    return result


@router.get("/api/books/entries")
def entries(
    session: SessionDep,
    q: str = Query(default="", max_length=500),
    status: str = "",
    favorite: bool = False,
    sort: Literal["recent", "title", "author", "rating"] = "recent",
    direction: Literal["asc", "desc"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    list_id: UUID | None = None,
):
    statement = query(session)
    if q.strip():
        statement = statement.where(
            func.lower(BookRecord.title).contains(q.strip().lower(), autoescape=True)
            | func.lower(BookRecord.author).contains(q.strip().lower(), autoescape=True)
        )
    if status == "active":
        statement = statement.where(BookRecord.status.in_(["reading", "plan_to_read"]))
    elif status:
        statement = statement.where(BookRecord.status == status)
    if favorite:
        statement = statement.where(BookRecord.favorite.is_(True))
    if list_id:
        statement = statement.where(BookRecord.id.in_(get_list(session, list_id).book_ids))
    if sort == "rating":
        statement = statement.where(BookRecord.rating.is_not(None))
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    order_column = {
        "recent": BookRecord.created_at,
        "title": func.lower(BookRecord.title),
        "author": func.lower(BookRecord.author),
        "rating": BookRecord.rating,
    }[sort]
    sort_direction = direction or ("desc" if sort in {"recent", "rating"} else "asc")
    order = order_column.desc() if sort_direction == "desc" else order_column.asc()
    rows = session.scalars(
        statement.order_by(order, BookRecord.id).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [output(row, False) for row in rows],
        "total": total,
        "page": page,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/api/books/entries", status_code=201)
def create(payload: BookInput, session: SessionDep):
    data = payload.model_dump(mode="json")
    row = BookRecord(user_id=current_user_id(session), identity_key=identity_key(data), **data)
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409,
            "This book is already in your book collection. No duplicate was added.",
        ) from exc
    return output(row)


@router.get("/api/books/entries/{identifier}")
def detail(identifier: UUID, session: SessionDep):
    return output(get_book(session, identifier))


@router.put("/api/books/entries/{identifier}")
def edit(identifier: UUID, payload: BookUpdate, session: SessionDep):
    row = get_book(session, identifier)
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
    try:
        result = session.execute(
            update(BookRecord)
            .where(
                BookRecord.id == row.id,
                BookRecord.user_id == current_user_id(session),
                BookRecord.version == payload.version,
            )
            .values(
                **data,
                identity_key=identity_key(data),
                version=payload.version + 1,
                updated_at=utcnow(),
            )
        )
        if not result.rowcount:
            raise HTTPException(409, "This book changed elsewhere. Reopen it before saving.")
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Another entry already uses this book identity.") from exc
    session.expire_all()
    return output(get_book(session, identifier))


@router.delete("/api/books/entries/{identifier}", status_code=204)
def remove(identifier: UUID, session: SessionDep, version: int = Query(ge=1)):
    row = get_book(session, identifier)
    result = session.execute(
        update(BookRecord)
        .where(BookRecord.id == row.id, BookRecord.version == version)
        .values(
            deleted_at=utcnow(),
            version=version + 1,
            identity_key=hashlib.sha256(
                f"removed:{row.id}:{row.identity_key}".encode()
            ).hexdigest(),
        )
    )
    if not result.rowcount:
        raise HTTPException(409, "This book changed elsewhere. Reopen it before removing.")
    session.commit()


@router.get("/api/books/entries/{identifier}/artwork")
def cover(identifier: UUID, session: SessionDep):
    row = get_book(session, identifier)
    if not row.artwork_data:
        raise HTTPException(404, "No local artwork.")
    return Response(
        base64.b64decode(row.artwork_data.split(",", 1)[1]),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/api/books/search")
async def search(
    request: Request,
    q: str = Query(min_length=2, max_length=200),
    author: str = Query(default="", max_length=200),
    language: Literal["en", "fr", "zh-CN"] = "en",
):
    try:
        return await request.app.state.book_provider.search(q, author, language)
    except (ProviderError, ValueError, TypeError) as exc:
        raise HTTPException(
            503, "Open Library is unavailable. You can still add books manually."
        ) from exc


@router.get("/api/books/metadata/{identifier}/editions")
async def editions(
    identifier: EditionId,
    request: Request,
    title: str = Query(default="", max_length=500),
    language: Literal["en", "fr", "zh-CN"] = "en",
):
    try:
        return await request.app.state.book_provider.editions(identifier, title, language)
    except (ProviderError, ValueError, TypeError) as exc:
        raise HTTPException(
            503, "Edition lookup is unavailable. Your saved book is unchanged."
        ) from exc


@router.get("/api/books/works/{identifier}/editions")
async def work_editions(
    identifier: WorkId,
    request: Request,
    title: str = Query(default="", max_length=500),
    language: Literal["en", "fr", "zh-CN"] = "en",
    preferred: EditionId | None = None,
):
    try:
        return await request.app.state.book_provider.editions(
            identifier, title, language, preferred or ""
        )
    except (ProviderError, ValueError, TypeError) as exc:
        raise HTTPException(
            503, "Edition lookup is unavailable. Your saved book is unchanged."
        ) from exc


@router.get("/api/books/entries/{identifier}/artwork-options")
async def artwork_options(identifier: UUID, request: Request, session: SessionDep):
    row = get_book(session, identifier)
    if not row.provider_id:
        return {
            "options": [],
            "source": "Open Library",
            "warning": "Link book metadata first, or upload an image.",
        }
    try:
        return await request.app.state.book_provider.artwork_options(
            row.provider_id, row.work_id
        )
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            503, "Artwork options could not be loaded. Your book was not changed."
        ) from exc


@router.get("/api/books/metadata/{identifier}")
async def metadata(identifier: EditionId, request: Request):
    try:
        return await request.app.state.book_provider.detail(identifier)
    except (ProviderError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            503,
            "Book details could not be loaded. Nothing was changed; try again or enter details manually.",
        ) from exc


def get_list(session, identifier):
    row = session.scalar(
        select(BookList).where(
            BookList.id == str(identifier), BookList.user_id == current_user_id(session)
        )
    )
    if row is None:
        raise HTTPException(404, "Book list not found.")
    return row


def members(session, values):
    ids = list(dict.fromkeys(str(key) for key in values))
    owned = set(
        session.scalars(
            query(session).with_only_columns(BookRecord.id).where(BookRecord.id.in_(ids))
        )
    )
    if set(ids) != owned:
        raise HTTPException(
            422, "Book lists can contain only active books from your collection."
        )
    return ids


@router.get("/api/books/lists")
def lists(session: SessionDep):
    owned = set(session.scalars(query(session).with_only_columns(BookRecord.id)))
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "version": row.version,
                "book_ids": [key for key in row.book_ids if key in owned],
            }
            for row in session.scalars(
                select(BookList)
                .where(BookList.user_id == current_user_id(session))
                .order_by(BookList.created_at)
            )
        ]
    }


@router.post("/api/books/lists", status_code=201)
def create_list(payload: BookListInput, session: SessionDep):
    row = BookList(
        user_id=current_user_id(session),
        name=payload.name,
        book_ids=members(session, payload.book_ids),
    )
    session.add(row)
    session.commit()
    return {"id": row.id, "name": row.name, "version": row.version, "book_ids": row.book_ids}


@router.put("/api/books/lists/{identifier}")
def edit_list(identifier: UUID, payload: BookListInput, session: SessionDep):
    row = get_list(session, identifier)
    result = session.execute(
        update(BookList)
        .where(BookList.id == row.id, BookList.version == payload.version)
        .values(
            name=payload.name,
            book_ids=members(session, payload.book_ids),
            version=row.version + 1,
        )
    )
    if not result.rowcount:
        raise HTTPException(409, "This book list changed elsewhere. Reopen it before saving.")
    session.commit()
    return {"id": row.id}


@router.delete("/api/books/lists/{identifier}", status_code=204)
def delete_list(identifier: UUID, session: SessionDep, version: int = Query(ge=1)):
    row = get_list(session, identifier)
    if row.version != version:
        raise HTTPException(409, "This book list changed elsewhere. Reopen it before removing.")
    session.delete(row)
    session.commit()


@router.get("/api/books/insights")
def insights(session: SessionDep):
    rows = list(session.scalars(query(session).options(defer(BookRecord.artwork_data))))
    ratings = [row.rating for row in rows if row.rating is not None]
    return {
        "total": len(rows),
        "authors": len({row.author.casefold() for row in rows}),
        "rated": len(ratings),
        "unrated": len(rows) - len(ratings),
        "favorites": sum(row.favorite for row in rows),
        "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "statuses": dict(Counter(row.status for row in rows)),
        "genres": dict(Counter(g for row in rows for g in set(row.genres)).most_common(12)),
        "years": dict(
            sorted(Counter(str(row.year // 10 * 10) for row in rows if row.year).items())
        ),
    }


@router.get("/api/exports/book-collection.json")
def export_books(session: SessionDep):
    rows = list(session.scalars(query(session).order_by(BookRecord.created_at)))
    ids = {row.id for row in rows}
    document = {
        "format": "pmt-book-collection",
        "version": 1,
        "books": [
            {"id": row.id, **{key: getattr(row, key) for key in BookInput.model_fields}}
            for row in rows
        ],
        "lists": [
            {"name": row.name, "book_ids": [key for key in row.book_ids if key in ids]}
            for row in session.scalars(
                select(BookList).where(BookList.user_id == current_user_id(session))
            )
        ],
    }
    return Response(
        json.dumps(document, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="pmt-book-collection.json"',
            "Cache-Control": "no-store",
        },
    )


def summary(document: BookDocument, session):
    data = document.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    keys = set(
        session.scalars(
            select(BookRecord.identity_key).where(
                BookRecord.user_id == current_user_id(session)
            )
        )
    )
    count = 0
    for row in data["books"]:
        key = identity_key(row)
        if key not in keys:
            count += 1
            keys.add(key)
    return {
        "sha256": digest,
        "new_books": count,
        "skipped": len(data["books"]) - count,
        "lists": len(data["lists"]),
    }


@router.post("/api/books/import/preview")
def inspect(payload: BookImport, session: SessionDep):
    return summary(payload.document, session)


@router.post("/api/books/import")
def import_books(payload: BookImport, session: SessionDep):
    result = summary(payload.document, session)
    if payload.sha256 != result["sha256"]:
        raise HTTPException(409, "Inspect this book file before importing it.")
    owner = current_user_id(session)
    existing = {
        row.identity_key: row
        for row in session.scalars(select(BookRecord).where(BookRecord.user_id == owner))
    }
    mapped = {}
    try:
        for source in payload.document.books:
            data = source.model_dump(mode="json", exclude={"id"})
            key = identity_key(data)
            row = existing.get(key)
            if row is None:
                row = BookRecord(id=new_id(), user_id=owner, identity_key=key, **data)
                session.add(row)
                existing[key] = row
            if row.deleted_at is None:
                mapped[str(source.id)] = row.id
        existing_lists = {
            (row.name, tuple(row.book_ids))
            for row in session.scalars(select(BookList).where(BookList.user_id == owner))
        }
        for source in payload.document.lists:
            ids = list(
                dict.fromkeys(mapped[str(key)] for key in source.book_ids if str(key) in mapped)
            )
            signature = (source.name, tuple(ids))
            if signature not in existing_lists:
                session.add(BookList(user_id=owner, name=source.name, book_ids=ids))
                existing_lists.add(signature)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            409, "The book collection changed during import. Inspect the file again."
        ) from exc
    return result
