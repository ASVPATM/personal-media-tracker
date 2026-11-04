"""Explicit, version-checked review decisions; never auto-merge owned records."""

import hashlib
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from watchtracker.authorization import current_principal, current_user_id
from watchtracker.metadata.http import ProviderError
from watchtracker.models import ScheduledJob
from watchtracker.music.api import SessionDep
from watchtracker.services.catalog_cache import catalog_work
from watchtracker.services.collection_metadata import (
    Domain,
    configuration,
    record_resolution,
    resolution_query,
)

router = APIRouter()


@router.get("/api/collections/{domain}/metadata-coverage")
async def coverage(domain: Domain, request: Request, session: SessionDep):
    """Separate identity, fields and locally cached images; no guessed percentage."""
    from watchtracker.services.collection_artwork import STALE_SECONDS

    model, _, _, _, creator = configuration(domain)
    rows = list(
        session.execute(
            select(
                model.id,
                model.provider_id,
                model.year,
                model.genres,
                getattr(model, creator).label("creator"),
                model.artwork_url,
                model.artwork_data.is_not(None).label("uploaded"),
                (model.release_group_id if domain == "music" else model.work_id).label("work"),
            ).where(model.user_id == current_user_id(session), model.deleted_at.is_(None))
        )
    )
    session.rollback()
    import asyncio

    inventory = await asyncio.to_thread(request.app.state.collection_artwork.inventory)
    cached = {
        path.stem for path, info in inventory if info.st_mtime > time.time() - STALE_SECONDS
    }
    local_images = 0
    for row in rows:
        urls = [row.artwork_url]
        if domain == "music" and row.work:
            urls.append(f"https://coverartarchive.org/release-group/{row.work}/front-500")
        if domain == "books" and row.provider_id:
            urls.append(
                f"https://covers.openlibrary.org/b/olid/{row.provider_id}-M.jpg?default=false"
            )
        local_images += bool(
            row.uploaded
            or any(hashlib.sha256(url.encode()).hexdigest() in cached for url in urls if url)
        )
    return {
        "total": len(rows),
        "linked": sum(bool(row.provider_id) for row in rows),
        "fields": {
            "year": sum(bool(row.year) for row in rows),
            "creator": sum(bool(row.creator) for row in rows),
            "genres": sum(bool(row.genres) for row in rows),
            "artwork_reference": sum(bool(row.uploaded or row.artwork_url) for row in rows),
        },
        "local_images": local_images,
        "uncached_images_not_verified": True,
    }


@router.get("/api/collections/cache")
async def cache_info(request: Request, session: SessionDep):
    principal = current_principal(session)
    if not (principal.is_local_mode or principal.is_admin):
        return {"can_clear": False}
    return {**await request.app.state.collection_artwork.diagnostics(), "can_clear": True}


@router.delete("/api/collections/cache")
async def clear_cache(request: Request, session: SessionDep):
    principal = current_principal(session)
    if not (principal.is_local_mode or principal.is_admin):
        raise HTTPException(403, "Only the server account can clear the shared cover cache.")
    return await request.app.state.collection_artwork.clear()


class Decision(BaseModel):
    version: int = Field(ge=1)
    action: Literal["manual", "later", "spelling", "apply"]
    title: str | None = Field(default=None, min_length=1, max_length=500)
    creator: str | None = Field(default=None, min_length=1, max_length=500)
    provider_id: str | None = Field(default=None, max_length=50)


def owned(session, domain, identifier):
    model, _, _, _, _ = configuration(domain)
    row = session.get(model, str(identifier))
    if not row or row.user_id != current_user_id(session) or row.deleted_at:
        raise HTTPException(404, "Collection entry not found.")
    return row


def output(row, domain):
    if domain == "music":
        from watchtracker.music.api import album_out

        return album_out(row)
    from watchtracker.books.api import output as book_output

    return book_output(row)


@router.get("/api/collections/{domain}/review/{identifier}")
def review_entry(domain: Domain, identifier: UUID, session: SessionDep):
    row = owned(session, domain, identifier)
    owner = current_user_id(session)
    record = session.scalar(resolution_query(owner, domain, row.id))
    # Duplicate review is informative only: neither entry is merged/deleted.
    job = session.scalar(
        select(ScheduledJob)
        .where(
            ScheduledJob.kind == "collection.metadata",
            ScheduledJob.user_id == owner,
            ScheduledJob.scope_type == domain,
            ScheduledJob.payload["entry_id"].as_string() == row.id,
        )
        .order_by(ScheduledJob.created_at.desc())
    )
    duplicate = None
    if job and job.payload.get("duplicate_id"):
        model, _, _, _, _ = configuration(domain)
        other = session.get(model, job.payload["duplicate_id"])
        if other and other.user_id == owner and not other.deleted_at:
            duplicate = output(other, domain)
    return {
        "entry": output(row, domain),
        "duplicate": duplicate,
        "resolution": record.payload
        if record and record.payload.get("version") == row.version
        else None,
    }


@router.get("/api/collections/{domain}/review/{identifier}/candidates")
async def candidates(
    domain: Domain,
    identifier: UUID,
    request: Request,
    session: SessionDep,
    q: str = Query(max_length=500),
    creator: str = Query(default="", max_length=500),
    language: Literal["en", "fr", "zh-CN"] = "en",
):
    row = owned(session, domain, identifier)
    version = row.version
    session.rollback()  # No transaction or lock while waiting on a catalog.
    provider = request.app.state.collection_metadata.providers[domain]
    try:
        with catalog_work(retry=True):
            result = await provider.search(
                q, creator, **({"language": language} if domain == "books" else {})
            )
    except ProviderError as exc:
        raise HTTPException(503, "Catalog unavailable; try again") from exc
    return {"version": version, "results": result.get("results", [])[:6]}


@router.post("/api/collections/{domain}/review/{identifier}")
async def decide(
    domain: Domain, identifier: UUID, payload: Decision, request: Request, session: SessionDep
):
    row = owned(session, domain, identifier)
    owner = current_user_id(session)
    if row.version != payload.version:
        raise HTTPException(
            409, "This entry changed. Reopen review before applying a decision."
        )
    _, schema, index_factory, _, creator = configuration(domain)
    original = {name: getattr(row, name) for name in schema.model_fields}
    if payload.action in {"manual", "later"}:
        record_resolution(session, owner, domain, row, decision=payload.action)
        if payload.action == "manual":
            session.execute(
                update(ScheduledJob)
                .where(
                    ScheduledJob.kind == "collection.metadata",
                    ScheduledJob.user_id == owner,
                    ScheduledJob.scope_type == domain,
                    ScheduledJob.payload["entry_id"].as_string() == row.id,
                    ScheduledJob.state.in_(("scheduled", "retry", "running")),
                )
                .values(state="cancelled")
            )
        session.commit()
        return {"entry": output(row, domain), "decision": payload.action}
    data = dict(original)
    if payload.action == "spelling":
        if not payload.title or not payload.creator:
            raise HTTPException(422, "Enter the complete title and creator.")
        data.update(title=payload.title.strip(), **{creator: payload.creator.strip()})
    else:
        if not payload.provider_id:
            raise HTTPException(422, "Choose an edition first.")
        try:
            from pydantic import TypeAdapter

            from watchtracker.books.schemas import EditionId

            identifier_value = (
                UUID(payload.provider_id)
                if domain == "music"
                else TypeAdapter(EditionId).validate_python(payload.provider_id)
            )
        except ValueError as exc:
            raise HTTPException(422, "Invalid edition identifier.") from exc
        session.rollback()
        provider = request.app.state.collection_metadata.providers[domain]
        try:
            with catalog_work(retry=True):
                detail = schema.model_validate(
                    await provider.detail(identifier_value)
                ).model_dump(mode="json")
        except ProviderError as exc:
            raise HTTPException(503, "Catalog unavailable; try again") from exc
        row = owned(session, domain, identifier)
        if row.version != payload.version:
            raise HTTPException(
                409, "This entry changed. Reopen review before applying a decision."
            )
        catalog_fields = (
            "title",
            creator,
            "year",
            "genres",
            "subgenres",
            "artwork_url",
            "provider_id",
            "edition_info",
        )
        catalog_fields += (
            ("release_type", "release_group_id")
            if domain == "music"
            else ("book_format", "work_id", "publisher", "isbn", "description", "page_count")
        )
        for name in catalog_fields:
            if detail.get(name) not in (None, "", [], {}):
                data[name] = detail[name]
        contents = "tracks" if domain == "music" else "chapters"
        if not data[contents]:
            data[contents] = detail[contents]
        if domain == "books" and (data.get("current_page") or 0) > (
            data.get("page_count") or 0
        ):
            data["page_count"] = original["page_count"]
        if index_factory(session).find(data, row.id) is not None:
            raise HTTPException(
                409,
                "This edition is already in your collection. Review both entries; nothing was merged.",
            )
    if domain == "music":
        from watchtracker.music.api import update_album
        from watchtracker.music.schemas import AlbumUpdate

        result = update_album(identifier, AlbumUpdate(**data, version=payload.version), session)
    else:
        from watchtracker.books.api import edit
        from watchtracker.books.schemas import BookUpdate

        result = edit(identifier, BookUpdate(**data, version=payload.version), session)
    row = owned(session, domain, identifier)
    record_resolution(
        session,
        owner,
        domain,
        row,
        decision=payload.action,
        previous_provider_id=original["provider_id"],
        checked_at=0,
        response="changed" if payload.action == "spelling" else "updated",
        absent_fields=[],
    )
    session.commit()
    return {"entry": result, "decision": payload.action}
