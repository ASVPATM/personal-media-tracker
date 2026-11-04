"""Opt-in, resumable metadata fill for imported music and books.

One leased job per entry keeps retries bounded and lets progress survive app
restarts. Matching never uses artwork/popularity as evidence of identity.
"""

import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import load_only

from watchtracker.authorization import bind_principal, current_user_id, principal_for_user
from watchtracker.metadata.collection_identity import collection_title
from watchtracker.metadata.http import ProviderError
from watchtracker.models import BookRecord, MusicAlbum, ScheduledJob, new_id, utcnow
from watchtracker.music.api import SessionDep
from watchtracker.services.catalog_cache import catalog_work
from watchtracker.services.jobs import RetryableJobError

KIND = "collection.metadata"
RESOLUTION = "collection.resolution"
Domain = Literal["music", "books"]
ACTIVE = ("scheduled", "running", "retry")
router = APIRouter()


class FillRequest(BaseModel):
    ids: list[UUID] | None = Field(default=None, max_length=5000)
    language: Literal["en", "fr", "zh-CN"] = "en"
    retry_review: bool = False
    use_wikidata: bool = False
    scope: Literal["all", "identity", "artwork", "optional", "unavailable"] = "all"


def resolution_query(owner, domain, entry_id):
    return select(ScheduledJob).where(
        ScheduledJob.kind == RESOLUTION,
        ScheduledJob.user_id == owner,
        ScheduledJob.scope_type == domain,
        ScheduledJob.scope_id == entry_id,
    )


def record_resolution(session, owner, domain, row, **values):
    record = session.scalar(resolution_query(owner, domain, row.id))
    if record is None:
        record = ScheduledJob(
            kind=RESOLUTION,
            user_id=owner,
            scope_type=domain,
            scope_id=row.id,
            state="completed",
            idempotency_key=f"resolution:{owner}:{domain}:{row.id}",
        )
        session.add(record)
    record.payload = {
        **(record.payload or {}),
        "version": row.version,
        "provider_id": row.provider_id,
        **values,
    }
    record.updated_at = utcnow()
    return record


def configuration(domain):
    # Lazy imports avoid coupling the two collection routers at import time.
    if domain == "music":
        from watchtracker.music.api import collection_index, identity_key
        from watchtracker.music.schemas import AlbumInput

        return MusicAlbum, AlbumInput, collection_index, identity_key, "artist"
    from watchtracker.books.api import collection_index, identity_key
    from watchtracker.books.schemas import BookInput

    return BookRecord, BookInput, collection_index, identity_key, "author"


def confident_candidate(source, results, domain):
    creator = "author" if domain == "books" else "artist"
    exact = [
        row
        for row in results
        if (
            collection_title(row.get("title")) == collection_title(source["title"])
            and collection_title(row.get(creator)) == collection_title(source[creator])
        )
    ]
    if not exact:
        return None
    group = "work_id" if domain == "books" else "release_group_id"
    identities = {row.get(group) or row.get("provider_id") for row in exact}
    if len(identities) > 1:
        # A supplied year can disambiguate different same-name works, but we
        # do not guess an edition's year from the original work's year.
        dated = [
            row for row in exact if source.get("year") and row.get("year") == source["year"]
        ]
        if len({row.get(group) or row.get("provider_id") for row in dated}) != 1:
            return None
        exact = dated
    # Named extended editions must not win over the ordinary album unless
    # requested in the title. Search already ranks useful representatives.
    return next((row for row in exact if not row.get("variant")), exact[0])


class CollectionMetadataService:
    def __init__(self, session_factory, music, books):
        self.session_factory = session_factory
        self.providers = {"music": music, "books": books}

    @staticmethod
    def jobs(owner, domain):
        return select(ScheduledJob).where(
            ScheduledJob.kind == KIND,
            ScheduledJob.user_id == owner,
            ScheduledJob.scope_type == domain,
        )

    def schedule(
        self,
        owner,
        domain,
        ids=None,
        language="en",
        retry_review=False,
        use_wikidata=False,
        scope="all",
    ):
        model, _, _, _, _ = configuration(domain)
        with self.session_factory() as session:
            running = session.scalar(
                self.jobs(owner, domain)
                .where(ScheduledJob.state.in_(ACTIVE))
                .order_by(ScheduledJob.created_at.desc())
            )
            if retry_review and running:
                return self.status(owner, domain, running.scope_id)
            if retry_review:
                latest = session.scalar(
                    self.jobs(owner, domain).order_by(ScheduledJob.created_at.desc())
                )
                # Retry only that batch's unresolved entries; do not re-query
                # hundreds of already matched albums with absent provider genres.
                retry_ids = {
                    job.payload.get("entry_id")
                    for job in session.scalars(
                        self.jobs(owner, domain).where(
                            ScheduledJob.scope_id == (latest.scope_id if latest else "")
                        )
                    )
                    if job.state == "paused"
                    or job.payload.get("outcome") in {"review", "changed", "incomplete"}
                }
                ids = list(retry_ids if ids is None else retry_ids.intersection(ids))
            run = running.scope_id if running else new_id()
            statement = (
                select(model)
                .where(model.user_id == owner, model.deleted_at.is_(None))
                .options(
                    load_only(
                        model.id,
                        model.user_id,
                        model.title,
                        model.version,
                        model.provider_id,
                        model.artwork_url,
                        model.year,
                        model.genres,
                        model.created_at,
                    )
                )
            )
            if ids is not None:
                statement = statement.where(model.id.in_(ids))
            existing = {
                job.payload.get("entry_id")
                for job in session.scalars(
                    self.jobs(owner, domain).where(ScheduledJob.scope_id == run)
                )
            }
            resolutions = {
                job.scope_id: job.payload
                for job in session.scalars(
                    select(ScheduledJob).where(
                        ScheduledJob.kind == RESOLUTION,
                        ScheduledJob.user_id == owner,
                        ScheduledJob.scope_type == domain,
                    )
                )
            }
            for row in session.scalars(statement.order_by(model.created_at).limit(5000)):
                decision = resolutions.get(row.id, {})
                if decision.get("version") == row.version:
                    if decision.get("decision") == "manual":
                        continue
                    if (
                        not retry_review
                        and decision.get("checked_at", 0) > time.time() - 7 * 86400
                    ):
                        continue
                if scope == "identity" and row.provider_id:
                    continue
                if scope == "artwork" and row.artwork_url:
                    continue
                if scope == "optional" and (not row.provider_id or (row.year and row.genres)):
                    continue
                if scope == "unavailable" and decision.get("response") != "unavailable":
                    continue
                if row.id in existing or (
                    row.provider_id and row.artwork_url and row.year and row.genres
                ):
                    continue
                session.add(
                    ScheduledJob(
                        kind=KIND,
                        user_id=owner,
                        scope_type=domain,
                        scope_id=run,
                        idempotency_key=f"collection:{run}:{row.id}",
                        max_attempts=2,
                        payload={
                            "owner": owner,
                            "domain": domain,
                            "entry_id": row.id,
                            "run": run,
                            "title": row.title,
                            "language": language,
                            "use_wikidata": bool(use_wikidata and domain == "music"),
                            "retry_review": bool(retry_review),
                        },
                    )
                )
            session.commit()
        return self.status(owner, domain, run)

    def status(self, owner, domain, run=None, review_limit=100, review_offset=0):
        with self.session_factory() as session:
            if not run:
                latest = session.scalar(
                    self.jobs(owner, domain).order_by(ScheduledJob.created_at.desc())
                )
                run = latest.scope_id if latest else None
            model, _, _, _, _ = configuration(domain)
            base = (
                ScheduledJob.kind == KIND,
                ScheduledJob.user_id == owner,
                ScheduledJob.scope_type == domain,
                ScheduledJob.scope_id == (run or ""),
            )

            def count(condition):
                return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

            total, pending, updated, cancelled = session.execute(
                select(
                    func.count(),
                    count(ScheduledJob.state.in_(ACTIVE)),
                    count(ScheduledJob.payload["applied"].as_boolean().is_(True)),
                    count(ScheduledJob.state == "cancelled"),
                ).where(*base)
            ).one()
            from sqlalchemy.orm import aliased

            resolution = aliased(ScheduledJob)
            manual = (
                select(resolution.id)
                .where(
                    resolution.kind == RESOLUTION,
                    resolution.user_id == owner,
                    resolution.scope_type == domain,
                    resolution.scope_id == model.id,
                    resolution.payload["version"].as_integer() == model.version,
                    resolution.payload["decision"].as_string() == "manual",
                )
                .exists()
            )
            outcome = ScheduledJob.payload["outcome"].as_string()
            review_query = (
                select(model.id, model.title, model.version, outcome.label("reason"))
                .join(ScheduledJob, ScheduledJob.payload["entry_id"].as_string() == model.id)
                .where(
                    *base,
                    model.user_id == owner,
                    model.deleted_at.is_(None),
                    ~manual,
                    ~ScheduledJob.state.in_((*ACTIVE, "cancelled")),
                    or_(
                        ScheduledJob.state == "paused",
                        outcome.in_(("review", "duplicate", "changed", "incomplete")),
                    ),
                    ~and_(
                        model.provider_id.is_not(None),
                        or_(model.artwork_url.is_not(None), model.artwork_data.is_not(None)),
                    ),
                )
            )
            review_count = session.scalar(
                select(func.count()).select_from(review_query.subquery())
            )
            # Stable ordering, bounded rows, aggregate counts: no full-batch JSON
            # or full library blobs in each polling response.
            review = [
                dict(row._mapping)
                for row in session.execute(
                    review_query.order_by(ScheduledJob.created_at, ScheduledJob.id)
                    .offset(review_offset)
                    .limit(min(100, review_limit))
                )
            ]
            for row in review:
                row["reason"] = row["reason"] or "unavailable"
            return {
                "run_id": run,
                "total": total,
                "completed": total - pending,
                "pending": pending,
                "updated": updated,
                "review_count": review_count,
                "cancelled": cancelled,
                "review": review,
                "review_offset": review_offset,
                "review_has_more": review_count > review_offset + len(review),
            }

    def cancel(self, owner, domain, run):
        with self.session_factory() as session:
            session.execute(
                update(ScheduledJob)
                .where(
                    ScheduledJob.kind == KIND,
                    ScheduledJob.user_id == owner,
                    ScheduledJob.scope_type == domain,
                    ScheduledJob.scope_id == run,
                    ScheduledJob.state.in_(ACTIVE),
                )
                .values(state="cancelled", updated_at=utcnow())
            )
            session.commit()
        return self.status(owner, domain, run)

    async def execute(self, payload):
        with catalog_work(background=True, retry=bool(payload.get("retry_review"))):
            await self._execute(payload)

    async def _execute(self, payload):
        owner, domain, entry_id = payload["owner"], payload["domain"], payload["entry_id"]
        model, schema, index_factory, identity_key, creator = configuration(domain)
        key = f"collection:{payload['run']}:{entry_id}"
        with self.session_factory() as session:
            principal = principal_for_user(session, owner, authentication_method="system")
            row = session.get(model, entry_id)
            if not principal or not row or row.user_id != owner or row.deleted_at:
                return
            source = {name: getattr(row, name) for name in schema.model_fields}
            version = row.version
        outcome, details, applied = "review", None, False
        provider = self.providers[domain]
        try:
            identifier = source["provider_id"]
            if not identifier:
                if domain == "music" and hasattr(provider, "match_album"):
                    matcher = provider.match_album
                    if payload.get("use_wikidata"):
                        matcher = getattr(provider, "match_album_with_aliases", matcher)
                    candidate = await matcher(source)
                    identifier = candidate.get("provider_id") if candidate else None
                elif domain == "books" and source.get("isbn"):
                    details = await provider.by_isbn(source["isbn"])
                    identifier = details.get("provider_id") if details else None
                else:
                    results = await provider.search(
                        source["title"],
                        source[creator],
                        **(
                            {"language": payload.get("language", "en")}
                            if domain == "books"
                            else {}
                        ),
                    )
                    candidate = confident_candidate(source, results.get("results", []), domain)
                    if (
                        domain == "books"
                        and candidate
                        and hasattr(provider, "preferred_edition")
                    ):
                        candidate = await provider.preferred_edition(
                            candidate, source, payload.get("language", "en")
                        )
                    identifier = candidate.get("provider_id") if candidate else None
            if identifier:
                detail = getattr(provider, "fill_detail", provider.detail)
                details = details or await detail(
                    UUID(identifier) if domain == "music" else identifier
                )
                details = schema.model_validate(details).model_dump(mode="json")
        except ProviderError as exc:
            with self.session_factory() as session:
                row = session.get(model, entry_id)
                if row and row.user_id == owner and row.version == version:
                    record_resolution(session, owner, domain, row, response="unavailable")
                    session.commit()
            raise RetryableJobError(
                "The catalog is temporarily unavailable. Your imported entries are safe.",
                retry_after_seconds=getattr(exc, "retry_after_seconds", None),
            ) from exc
        with self.session_factory() as session:
            principal = principal_for_user(session, owner, authentication_method="system")
            job = session.scalar(
                self.jobs(owner, domain).where(ScheduledJob.idempotency_key == key)
            )
            row = session.get(model, entry_id)
            if (
                not principal
                or not job
                or job.state == "cancelled"
                or not row
                or row.user_id != owner
                or row.deleted_at
            ):
                return
            bind_principal(session, principal)
            if row.version != version:
                outcome = "changed"
            elif details:
                data = dict(source)
                kind = "release_type" if domain == "music" else "book_format"
                if not source["provider_id"] and source.get(kind) in {"album", "book", "other"}:
                    data[kind] = details[kind]
                # Personal data and explicit corrections always win. Fill
                # missing catalog fields, never ratings, status, progress or
                # notes. Existing track/chapter IDs remain untouched.
                names = (
                    (
                        "year",
                        "genres",
                        "subgenres",
                        "artwork_url",
                        "provider_id",
                        "release_group_id",
                        "tracks",
                    )
                    if domain == "music"
                    else (
                        "year",
                        "genres",
                        "subgenres",
                        "artwork_url",
                        "provider_id",
                        "work_id",
                        "description",
                        "publisher",
                        "isbn",
                        "page_count",
                        "chapters",
                    )
                )
                for name in names:
                    if not data.get(name) and details.get(name):
                        if name == "page_count" and details[name] < (
                            source.get("current_page") or 0
                        ):
                            continue
                        data[name] = details[name]
                data["edition_info"] = {
                    **details.get("edition_info", {}),
                    **{
                        name: item
                        for name, item in (source.get("edition_info") or {}).items()
                        if item not in (None, "", [])
                    },
                }
                duplicate = index_factory(session).find(data, row.id)
                if duplicate is not None:
                    outcome = "duplicate"
                    job.payload = {**job.payload, "duplicate_id": duplicate.id}
                else:
                    changes = {
                        name: item for name, item in data.items() if item != source.get(name)
                    }
                    if changes:
                        changes.update(
                            identity_key=identity_key(data),
                            version=version + 1,
                            updated_at=utcnow(),
                        )
                        changed = session.execute(
                            update(model)
                            .where(
                                model.id == row.id,
                                model.user_id == owner,
                                model.version == version,
                                model.deleted_at.is_(None),
                            )
                            .values(**changes)
                        ).rowcount
                        outcome = "updated" if changed else "changed"
                        applied = bool(changed)
                    else:
                        outcome = "unchanged"
                    if outcome in {"updated", "unchanged"} and not (
                        data.get("artwork_url") or data.get("artwork_data")
                    ):
                        outcome = "incomplete"
            job.payload = {**job.payload, "outcome": outcome, "applied": applied}
            if row.version == version or applied:
                session.refresh(row)
                record_resolution(
                    session,
                    owner,
                    domain,
                    row,
                    checked_at=time.time(),
                    response=outcome,
                    absent_fields=[
                        name
                        for name in ("year", "genres", "artwork_url")
                        if details is not None and not details.get(name)
                    ],
                )
            session.commit()


@router.post("/api/collections/{domain}/metadata-fill")
def start_fill(domain: Domain, payload: FillRequest, request: Request, session: SessionDep):
    return request.app.state.collection_metadata.schedule(
        current_user_id(session),
        domain,
        [str(item) for item in payload.ids] if payload.ids is not None else None,
        payload.language,
        payload.retry_review,
        payload.use_wikidata,
        payload.scope,
    )


@router.get("/api/collections/{domain}/metadata-fill")
def fill_status(
    domain: Domain,
    request: Request,
    session: SessionDep,
    review_limit: int = Query(default=100, ge=1, le=5000),
    review_offset: int = Query(default=0, ge=0, le=5000),
):
    return request.app.state.collection_metadata.status(
        current_user_id(session), domain, review_limit=review_limit, review_offset=review_offset
    )


@router.delete("/api/collections/{domain}/metadata-fill/{run}")
def cancel_fill(domain: Domain, run: UUID, request: Request, session: SessionDep):
    return request.app.state.collection_metadata.cancel(
        current_user_id(session), domain, str(run)
    )
