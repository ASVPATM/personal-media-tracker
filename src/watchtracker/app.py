from __future__ import annotations

import asyncio
import logging
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from watchtracker import __version__
from watchtracker.config import Settings, get_settings
from watchtracker.db import (
    make_engine,
    make_session_factory,
    session_dependency,
    upgrade_database,
)
from watchtracker.imports import ImportConflict, ImportError, ImportService
from watchtracker.imports.parsers import ImportLimits
from watchtracker.logging_config import configure_logging
from watchtracker.metadata import MetadataService, ProviderUnavailable
from watchtracker.schemas import (
    EntryMutationResponse,
    EntryOut,
    EntryPatch,
    FromSearchRequest,
    GeneralSettingsUpdate,
    ImportCommitRequest,
    ManualEntryRequest,
    MetadataEnrichmentStart,
    MetadataEnrichmentStatus,
    MetadataReviewOut,
    MetadataSettingsOut,
    MetadataSettingsUpdate,
    PaginatedEntries,
    RatingReviewOut,
    SearchResponse,
    SearchResult,
    ViewingCreate,
)
from watchtracker.security import LocalSecurityMiddleware
from watchtracker.services.backups import BackupError, BackupService
from watchtracker.services.enrichment import MetadataEnrichmentManager
from watchtracker.services.entries import (
    EntryConflict,
    EntryNotFound,
    EntryService,
    refresh_catalog_taxonomy,
)
from watchtracker.services.exports import watch_log_csv
from watchtracker.services.native import NativeActionError, open_local_path
from watchtracker.services.preferences import PreferenceStore
from watchtracker.services.profile import build_profile, profile_markdown
from watchtracker.services.secrets import SecretStore
from watchtracker.services.settings import SettingsWriteError
from watchtracker.services.stats import calculate_stats
from watchtracker.services.updates import UpdateCheckError, UpdateService

STATIC_DIR = Path(__file__).with_name("static")


def _today(settings: Settings):
    return datetime.now(settings.tzinfo).date()


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def create_app(
    settings: Settings | None = None,
    *,
    metadata_service: MetadataService | None = None,
    secret_store: SecretStore | None = None,
    update_service: UpdateService | None = None,
    migrate: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    preferences = PreferenceStore(settings)
    stored_preferences = preferences.apply_runtime_values()
    secrets = secret_store or SecretStore(
        settings,
        keyring_enabled=(
            stored_preferences.get("credential_storage") == "keychain"
            and stored_preferences.get("credential_vault_opt_in") is True
        ),
    )
    token, _token_source = secrets.get()
    settings.tmdb_token = token
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    metadata = metadata_service or MetadataService(settings)
    enrichment = MetadataEnrichmentManager(
        session_factory,
        metadata,
        today_factory=lambda: _today(settings),
    )
    backups = BackupService(settings, engine, session_factory)
    updates = update_service or UpdateService(settings.repository_url, __version__)

    def preferred_credential_storage() -> Literal["keychain", "local_secret_file"]:
        stored = preferences.load()
        return (
            "keychain"
            if (
                stored.get("credential_storage") == "keychain"
                and stored.get("credential_vault_opt_in") is True
            )
            else "local_secret_file"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_runtime_directories()
        configure_logging(settings)
        logger = logging.getLogger(__name__)
        logger.info("Starting Personal Media Tracker %s", __version__)
        try:
            if migrate:
                result = upgrade_database(settings)
                if result.changed:
                    logger.info(
                        "Database migrated from %s to %s; backup=%s",
                        result.previous_revision or "empty",
                        result.current_revision,
                        result.backup_path.name if result.backup_path else "not required",
                    )
            app.state.engine = engine
            app.state.session_factory = session_factory
            app.state.settings = settings
            app.state.metadata = metadata
            app.state.enrichment = enrichment
            with session_factory() as session:
                refresh_catalog_taxonomy(session)
            enrichment.start_verified_if_needed()
            yield
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            locations = " > ".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in frames[-8:]
            )
            logger.error(
                "Application startup or lifespan failed: type=%s locations=%s",
                type(exc).__name__,
                locations or "unavailable",
            )
            raise
        finally:
            await enrichment.close()
            close = getattr(metadata, "close", None)
            if close:
                await close()
            engine.dispose()
            logger.info("Personal Media Tracker stopped")

    app = FastAPI(
        title="Personal Media Tracker",
        version=__version__,
        description="Local-first watch diary API. Public provider ratings are never used as personal ratings.",
        lifespan=lifespan,
        docs_url=None if settings.release_mode else "/docs",
        redoc_url=None if settings.release_mode else "/redoc",
    )
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = settings
    app.state.metadata = metadata
    app.state.enrichment = enrichment
    app.state.preferences = preferences
    app.state.secrets = secrets
    app.state.backups = backups
    app.state.updates = updates

    @app.middleware("http")
    async def bound_request_size(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length and content_length.isdigit():
                backup_paths = {
                    "/api/backups/restore",
                    "/api/data/import-database",
                    "/api/data/portable/inspect",
                    "/api/data/portable/import",
                }
                limit_mb = (
                    settings.backup_upload_limit_mb
                    if request.url.path in backup_paths
                    else settings.upload_limit_mb
                )
                limit = limit_mb * 1024 * 1024 + 1024 * 1024
                if int(content_length) > limit:
                    return _error(
                        413, "payload_too_large", "Request exceeds the configured upload limit."
                    )
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            # The desktop WebView may otherwise reuse a stale first-page response.
            # That made a populated library appear empty until a page-size change
            # produced a different URL.
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        reference = uuid.uuid4().hex[:10]
        frames = traceback.extract_tb(exc.__traceback__)
        locations = " > ".join(
            f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames[-8:]
        )
        logging.getLogger(__name__).error(
            "Unexpected error reference=%s type=%s locations=%s",
            reference,
            type(exc).__name__,
            locations or "unavailable",
        )
        return _error(
            500,
            "internal_error",
            f"The local application could not complete that request. Reference: {reference}",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        details = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return _error(422, "validation_error", "The request contains invalid data.", details)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        message = (
            str(exc.detail)
            if isinstance(exc.detail, str)
            else "The request could not be completed."
        )
        return _error(exc.status_code, "http_error", message)

    @app.exception_handler(EntryNotFound)
    async def not_found(_request: Request, exc: EntryNotFound):
        return _error(404, "not_found", str(exc))

    @app.exception_handler(EntryConflict)
    async def entry_conflict(_request: Request, exc: EntryConflict):
        return _error(409, "conflict", str(exc))

    @app.exception_handler(ImportConflict)
    async def import_conflict(_request: Request, exc: ImportConflict):
        return _error(409, "import_conflict", str(exc))

    @app.exception_handler(ImportError)
    async def import_error(_request: Request, exc: ImportError):
        return _error(400, "invalid_import", str(exc))

    @app.exception_handler(ProviderUnavailable)
    async def provider_error(_request: Request, exc: ProviderUnavailable):
        return _error(503, "provider_unavailable", str(exc))

    @app.exception_handler(SettingsWriteError)
    async def settings_write_error(_request: Request, _exc: SettingsWriteError):
        return _error(
            500, "settings_write_failed", "The local settings file could not be saved."
        )

    @app.exception_handler(BackupError)
    async def backup_error(_request: Request, exc: BackupError):
        return _error(400, "backup_error", str(exc))

    @app.exception_handler(UpdateCheckError)
    async def update_error(_request: Request, exc: UpdateCheckError):
        return _error(503, "update_check_failed", str(exc))

    @app.exception_handler(NativeActionError)
    async def native_action_error(_request: Request, exc: NativeActionError):
        return _error(500, "native_action_failed", str(exc))

    @app.get("/health")
    def health(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "version": __version__,
            "database": "ready",
            "mode": "release" if settings.release_mode else "development",
        }

    @app.get("/api/search", response_model=SearchResponse)
    async def search(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=200)],
        media_type: Literal["movie", "tv", "anime"] | None = None,
    ):
        return await request.app.state.metadata.search(q, media_type)

    @app.get("/api/settings/metadata", response_model=MetadataSettingsOut)
    def metadata_settings_status():
        active_token, source = secrets.get()
        return MetadataSettingsOut(
            tmdb_configured=bool(active_token),
            anilist_enabled=bool(settings.anilist_enabled),
            storage=source,
            legacy_token_available=bool(secrets.legacy_token()),
            preferred_storage=preferred_credential_storage(),
            keychain_available=secrets.keyring_available,
        )

    @app.put("/api/settings/metadata", response_model=MetadataSettingsOut)
    def update_metadata_settings(payload: MetadataSettingsUpdate, request: Request):
        try:
            if payload.clear_tmdb_token:
                secrets.clear()
                preferences.update(
                    credential_storage="local_secret_file",
                    credential_vault_opt_in=False,
                )
            elif payload.import_existing_keychain:
                secrets.copy_existing_keyring_to_local()
                preferences.update(
                    credential_storage="local_secret_file",
                    credential_vault_opt_in=False,
                )
            elif payload.tmdb_token:
                secrets.save(payload.tmdb_token, storage=payload.credential_storage)
                preferences.update(
                    credential_storage=payload.credential_storage,
                    credential_vault_opt_in=payload.credential_storage == "keychain",
                )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        token, source = secrets.get()
        settings.tmdb_token = token
        configure = getattr(request.app.state.metadata, "configure_tmdb", None)
        if configure:
            configure(token)
        return MetadataSettingsOut(
            tmdb_configured=bool(token),
            anilist_enabled=bool(settings.anilist_enabled),
            storage=source,
            legacy_token_available=bool(secrets.legacy_token()),
            preferred_storage=preferred_credential_storage(),
            keychain_available=secrets.keyring_available,
        )

    @app.post("/api/settings/metadata/migrate-legacy", response_model=MetadataSettingsOut)
    def migrate_legacy_metadata_settings(request: Request):
        try:
            secrets.migrate_legacy(storage="local_secret_file")
            preferences.update(
                credential_storage="local_secret_file",
                credential_vault_opt_in=False,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        token, source = secrets.get()
        settings.tmdb_token = token
        configure = getattr(request.app.state.metadata, "configure_tmdb", None)
        if configure:
            configure(token)
        return MetadataSettingsOut(
            tmdb_configured=bool(token),
            anilist_enabled=bool(settings.anilist_enabled),
            storage=source,
            legacy_token_available=bool(secrets.legacy_token()),
            preferred_storage=preferred_credential_storage(),
            keychain_available=secrets.keyring_available,
        )

    @app.get("/api/settings/general")
    def general_settings():
        stored = preferences.load()
        database_path = settings.resolved_database_path
        backup_files = sorted(
            [
                *settings.resolved_backups_dir.glob("personal-media-tracker-*.zip"),
                *settings.resolved_backups_dir.glob("personal-watch-tracker-*.zip"),
            ],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return {
            "onboarding_complete": bool(stored.get("onboarding_complete")),
            "timezone": settings.timezone,
            "language": settings.language,
            "region": settings.region,
            "theme": stored.get("theme", "system"),
            "accent": stored.get("accent", "forest"),
            "accent_color": stored.get("accent_color"),
            "background_color": stored.get("background_color"),
            "background_strength": stored.get("background_strength", 16),
            "background_mode": stored.get("background_mode", "adaptive"),
            "media_artwork_tint": bool(stored.get("media_artwork_tint", False)),
            "interface_language": stored.get("interface_language", "en"),
            "effective_timezone": str(getattr(settings.tzinfo, "key", settings.tzinfo)),
            "data_location": str(settings.resolved_data_dir),
            "database_size": database_path.stat().st_size if database_path.exists() else 0,
            "last_backup_at": (
                datetime.fromtimestamp(
                    backup_files[0].stat().st_mtime, settings.tzinfo
                ).isoformat()
                if backup_files
                else None
            ),
            "version": __version__,
            "repository_url": settings.repository_url,
            "native_actions": settings.native_actions,
            "release_mode": settings.release_mode,
        }

    @app.put("/api/settings/general")
    def update_general_settings(payload: GeneralSettingsUpdate, request: Request):
        changes = payload.model_dump(exclude_unset=True)
        stored = preferences.update(**changes)
        if "timezone" in changes and "WATCHTRACKER_TIMEZONE" not in os.environ:
            settings.timezone = changes["timezone"]
        if changes.get("language") and "WATCHTRACKER_LANGUAGE" not in os.environ:
            settings.language = changes["language"]
        if changes.get("region") and "WATCHTRACKER_REGION" not in os.environ:
            settings.region = changes["region"]
        if {"language", "region"} & changes.keys():
            configure = getattr(request.app.state.metadata, "configure_tmdb", None)
            if configure:
                configure(settings.tmdb_token)
        return {"status": "saved", **stored}

    @app.post("/api/backups")
    def create_backup():
        result = backups.create()
        logging.getLogger(__name__).info("Backup created: %s", result.path.name)
        return {
            "status": "created",
            "filename": result.path.name,
            "size": result.size,
            "created_at": result.created_at,
            "location": str(settings.resolved_backups_dir),
        }

    async def _prepare_backup_upload(file: UploadFile):
        limit = settings.backup_upload_limit_mb * 1024 * 1024
        size = file.size
        if size is None:
            file.file.seek(0, 2)
            size = file.file.tell()
        if size > limit:
            return _error(413, "payload_too_large", "Backup exceeds the configured limit.")
        await file.seek(0)
        return file.file

    async def _restore_upload(
        file: UploadFile,
        *,
        import_existing: bool,
        expected_sha256: str | None = None,
    ):
        nonlocal enrichment
        upload = await _prepare_backup_upload(file)
        if isinstance(upload, JSONResponse):
            return upload
        await enrichment.close()
        try:
            result = await asyncio.to_thread(
                backups.restore_file,
                file.filename or "database.sqlite3",
                upload,
                import_existing=import_existing,
                expected_sha256=expected_sha256,
            )
            with session_factory() as session:
                refresh_catalog_taxonomy(session)
        finally:
            # Restore disposes the shared engine before atomically replacing SQLite.
            # A fresh manager then reconnects through the same session factory, keeping
            # enrichment usable without requiring an application restart.
            enrichment = MetadataEnrichmentManager(
                session_factory,
                metadata,
                today_factory=lambda: _today(settings),
            )
            app.state.enrichment = enrichment
            try:
                enrichment.start_verified_if_needed()
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Metadata enrichment restart skipped after restore: type=%s",
                    type(exc).__name__,
                )
        logging.getLogger(__name__).info(
            "%s completed; safety backup=%s",
            "Database import" if import_existing else "Restore",
            result["safety_backup"],
        )
        return result

    @app.post("/api/backups/restore")
    async def restore_backup(file: UploadFile = File(...)):
        return await _restore_upload(file, import_existing=False)

    @app.post("/api/data/import-database")
    async def import_existing_database(file: UploadFile = File(...)):
        return await _restore_upload(file, import_existing=True)

    @app.post("/api/data/portable/inspect")
    async def inspect_portable_data(file: UploadFile = File(...)):
        upload = await _prepare_backup_upload(file)
        if isinstance(upload, JSONResponse):
            return upload
        return await asyncio.to_thread(
            backups.inspect_file,
            file.filename or "watchtracker-migration",
            upload,
        )

    @app.post("/api/data/portable/import")
    async def import_portable_data(
        file: UploadFile = File(...), archive_sha256: str = Form(...)
    ):
        return await _restore_upload(
            file,
            import_existing=True,
            expected_sha256=archive_sha256,
        )

    @app.post("/api/system/open-folder")
    def open_folder(kind: Literal["data", "backups", "logs"]):
        if not settings.native_actions:
            raise HTTPException(
                409,
                "Opening folders is available in the packaged desktop application.",
            )
        paths = {
            "data": settings.resolved_data_dir,
            "backups": settings.resolved_backups_dir,
            "logs": settings.resolved_log_dir,
        }
        open_local_path(paths[kind])
        return {"status": "opened", "kind": kind}

    @app.post("/api/updates/check")
    async def check_for_updates():
        return await updates.check()

    @app.get("/api/metadata/enrichment", response_model=MetadataEnrichmentStatus)
    def metadata_enrichment_status(request: Request):
        return request.app.state.enrichment.status()

    @app.post(
        "/api/metadata/enrichment",
        response_model=MetadataEnrichmentStatus,
        status_code=202,
    )
    async def start_metadata_enrichment(payload: MetadataEnrichmentStart, request: Request):
        return request.app.state.enrichment.start(payload.limit)

    @app.get("/api/metadata/review", response_model=MetadataReviewOut)
    def metadata_review(
        after_entry_id: str | None = None,
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).metadata_review(
            after_entry_id=after_entry_id
        )

    @app.get("/api/ratings/review", response_model=RatingReviewOut)
    def rating_review(
        after_entry_id: str | None = None,
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).rating_review(
            after_entry_id=after_entry_id
        )

    @app.post("/api/entries/from-search", response_model=EntryMutationResponse)
    async def add_from_search(
        payload: FromSearchRequest,
        request: Request,
        session: Session = Depends(session_dependency),
    ):
        catalog = await request.app.state.metadata.detail(payload.result)
        options = payload.model_dump(
            include={
                "status",
                "personal_rating",
                "notes",
                "user_tags",
                "started_date",
                "finished_date",
                "watched_date",
                "view_count",
            }
        )
        return EntryService(session, today=_today(settings)).create_or_handle_duplicate(
            catalog,
            __import__("watchtracker.schemas", fromlist=["EntryOptions"]).EntryOptions(
                **options
            ),
            if_existing=payload.if_existing,
        )

    @app.post("/api/entries/manual", response_model=EntryMutationResponse, status_code=201)
    def add_manual(
        payload: ManualEntryRequest,
        session: Session = Depends(session_dependency),
    ):
        catalog_fields = set(
            __import__(
                "watchtracker.schemas", fromlist=["CatalogData"]
            ).CatalogData.model_fields
        )
        option_fields = set(
            __import__(
                "watchtracker.schemas", fromlist=["EntryOptions"]
            ).EntryOptions.model_fields
        )
        from watchtracker.schemas import CatalogData, EntryOptions

        catalog = CatalogData(**payload.model_dump(include=catalog_fields))
        options = EntryOptions(**payload.model_dump(include=option_fields))
        return EntryService(session, today=_today(settings)).create_or_handle_duplicate(
            catalog, options
        )

    @app.get("/api/entries", response_model=PaginatedEntries)
    def list_entries(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 24,
        sort: Literal[
            "recently_watched",
            "recently_added",
            "personal_rating",
            "title",
            "release_year",
            "media_type",
        ] = "recently_watched",
        direction: Literal["asc", "desc"] = "desc",
        media_type: Literal["movie", "tv", "anime"] | None = None,
        status: Literal["watched", "watching", "plan_to_watch", "dropped", "rewatching"]
        | None = None,
        genre: Annotated[str | None, Query(max_length=100)] = None,
        year_min: Annotated[int | None, Query(ge=1878, le=2200)] = None,
        year_max: Annotated[int | None, Query(ge=1878, le=2200)] = None,
        rating_min: Annotated[float | None, Query(ge=1, le=10)] = None,
        rating_max: Annotated[float | None, Query(ge=1, le=10)] = None,
        rated: Literal["all", "rated", "unrated"] = "all",
        q: Annotated[str | None, Query(max_length=200)] = None,
        include_deleted: bool = False,
        session: Session = Depends(session_dependency),
    ):
        if year_min and year_max and year_min > year_max:
            raise HTTPException(422, "year_min cannot exceed year_max")
        if rating_min and rating_max and rating_min > rating_max:
            raise HTTPException(422, "rating_min cannot exceed rating_max")
        return EntryService(session, today=_today(settings)).list(
            page=page,
            page_size=page_size,
            sort=sort,
            direction=direction,
            media_type=media_type,
            status=status,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            rating_min=rating_min,
            rating_max=rating_max,
            rated=rated,
            q=q,
            include_deleted=include_deleted,
        )

    @app.get("/api/entries/{entry_id}", response_model=EntryOut)
    def get_entry(entry_id: str, session: Session = Depends(session_dependency)):
        return EntryService(session, today=_today(settings)).get(entry_id)

    @app.patch("/api/entries/{entry_id}", response_model=EntryOut)
    def patch_entry(
        entry_id: str,
        payload: EntryPatch,
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).patch(entry_id, payload)

    @app.post("/api/entries/{entry_id}/metadata", response_model=EntryOut)
    async def apply_entry_metadata(
        entry_id: str,
        result: SearchResult,
        request: Request,
        session: Session = Depends(session_dependency),
    ):
        detail = await request.app.state.metadata.detail(result)
        return EntryService(session, today=_today(settings)).apply_metadata(entry_id, detail)

    @app.delete("/api/entries/{entry_id}", status_code=204)
    def delete_entry(entry_id: str, session: Session = Depends(session_dependency)):
        EntryService(session, today=_today(settings)).soft_delete(entry_id)
        return Response(status_code=204)

    @app.post("/api/entries/{entry_id}/restore", response_model=EntryOut)
    def restore_entry(entry_id: str, session: Session = Depends(session_dependency)):
        return EntryService(session, today=_today(settings)).restore(entry_id)

    @app.post("/api/entries/{entry_id}/viewings", response_model=EntryOut)
    def add_viewing(
        entry_id: str,
        payload: ViewingCreate = Body(default_factory=ViewingCreate),
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).add_viewing(
            entry_id, payload.viewed_on
        )

    @app.delete("/api/entries/{entry_id}/viewings/{event_id}", response_model=EntryOut)
    def delete_viewing(
        entry_id: str,
        event_id: str,
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).delete_viewing(entry_id, event_id)

    @app.get("/api/stats")
    def stats(session: Session = Depends(session_dependency)):
        return calculate_stats(session, today=_today(settings))

    @app.post("/api/imports/preview")
    async def import_preview(
        file: UploadFile = File(...),
        import_kind: Literal["auto", "csv", "manual", "canonical", "letterboxd"] = Form("auto"),
        session: Session = Depends(session_dependency),
    ):
        limit = settings.upload_limit_mb * 1024 * 1024
        content = await file.read(limit + 1)
        if len(content) > limit:
            return _error(413, "payload_too_large", "Upload exceeds the configured limit.")
        if not content:
            raise ImportError("Uploaded file is empty")
        limits = ImportLimits(
            max_members=settings.import_max_members,
            max_rows=settings.import_max_rows,
            max_cell_chars=settings.import_max_cell_chars,
            max_decompressed_bytes=settings.import_max_decompressed_mb * 1024 * 1024,
            max_member_bytes=min(
                settings.import_max_decompressed_mb * 1024 * 1024,
                settings.upload_limit_mb * 4 * 1024 * 1024,
            ),
        )
        return ImportService(session, today=_today(settings), limits=limits).preview(
            file.filename or "import", content, import_kind
        )

    @app.post("/api/imports/{preview_id}/commit")
    def import_commit(
        preview_id: str,
        payload: ImportCommitRequest,
        session: Session = Depends(session_dependency),
    ):
        result = ImportService(session, today=_today(settings)).commit(
            preview_id,
            conflict_policy=payload.conflict_policy,
            allow_invalid=payload.allow_invalid,
        )
        logging.getLogger(__name__).info(
            "Import committed: status=%s created=%s updated=%s events=%s",
            result.get("status"),
            result.get("created", 0),
            result.get("updated", 0),
            result.get("viewing_events_added", 0),
        )
        return result

    @app.get("/api/exports/watch-log.csv")
    def export_csv(session: Session = Depends(session_dependency)):
        value = watch_log_csv(session)
        filename = f"watch-log-{_today(settings).isoformat()}.csv"
        return PlainTextResponse(
            value,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/exports/portable-library.zip")
    def export_portable_library():
        result = backups.create(prefix="personal-media-tracker-everything")
        filename = f"personal-media-tracker-everything-{_today(settings).isoformat()}.zip"
        logging.getLogger(__name__).info("Portable library exported: %s", result.path.name)
        return FileResponse(
            result.path,
            media_type="application/zip",
            filename=filename,
        )

    @app.get("/api/exports/preference-profile.json")
    def export_profile_json(session: Session = Depends(session_dependency)):
        filename = f"preference-profile-{_today(settings).isoformat()}.json"
        return JSONResponse(
            build_profile(session, today=_today(settings)),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/exports/preference-profile.md")
    def export_profile_markdown(session: Session = Depends(session_dependency)):
        profile = build_profile(session, today=_today(settings))
        filename = f"preference-profile-{_today(settings).isoformat()}.md"
        return PlainTextResponse(
            profile_markdown(profile),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def run() -> None:
    from watchtracker.launcher import LauncherError, main, show_launcher_error
    from watchtracker.runtime import is_packaged

    try:
        raise SystemExit(main())
    except LauncherError as exc:
        if is_packaged():
            show_launcher_error(str(exc))
        print(f"Personal Media Tracker: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2) from None
