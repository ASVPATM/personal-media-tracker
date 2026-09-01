from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import secrets as secure_tokens
import socket
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

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
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from watchtracker import __version__
from watchtracker.authorization import (
    Principal,
    current_principal,
    request_principal,
    require_admin,
)
from watchtracker.build_manifest import BUILD_MANIFEST
from watchtracker.config import Settings, get_settings
from watchtracker.db import (
    make_engine,
    make_session_factory,
    migration_head,
    session_dependency,
    upgrade_database,
)
from watchtracker.icons import DEFAULT_ICON_BACKGROUND, DEFAULT_ICON_TEXT
from watchtracker.imports import ImportConflict, ImportError, ImportNotFound, ImportService
from watchtracker.imports.parsers import ImportLimits
from watchtracker.integrations import ProviderRegistry, default_registry
from watchtracker.logging_config import configure_logging
from watchtracker.metadata import MetadataService, ProviderUnavailable
from watchtracker.models import (
    IntegrationConnection,
    OwnerSession,
    ScheduledJob,
    ServerState,
    UserAccount,
    WatchEntry,
    utcnow,
)
from watchtracker.notifications import (
    NotificationDeliveryService,
    NotificationError,
    NotificationService,
    default_notification_adapters,
)
from watchtracker.recommendations import RecommendationService
from watchtracker.recommendations.service import (
    RecommendationConflict,
    RecommendationNotFound,
)
from watchtracker.remote_client import (
    RemoteClientError,
    RemoteDeviceClient,
    RemoteProfileStore,
)
from watchtracker.schemas import (
    AdminUserUpdate,
    ArtworkOption,
    ArtworkOptionsOut,
    ArtworkSelection,
    BrowserSessionAdopt,
    CatalogLibraryAdd,
    EntryMutationResponse,
    EntryOut,
    EntryPatch,
    EpisodeViewingCreate,
    FromSearchRequest,
    GeneralSettingsUpdate,
    ImportCommitRequest,
    IntegrationConnectionCreate,
    IntegrationConnectionState,
    IntegrationOAuthStart,
    IntegrationRunCreate,
    IntegrationUserBindingCreate,
    InvitationCreate,
    InvitationRedeem,
    LocalServerRecovery,
    ManualEntryRequest,
    MediaListCreate,
    MediaListMemberAdd,
    MediaListMemberUpdate,
    MediaListOut,
    MediaListPatch,
    MetadataEnrichmentStart,
    MetadataEnrichmentStatus,
    MetadataReviewOut,
    MetadataSettingsOut,
    MetadataSettingsUpdate,
    NativeLogin,
    NativeRefresh,
    NotificationEndpointCreate,
    NotificationEndpointUpdate,
    NotificationSettingsUpdate,
    OwnerBootstrap,
    OwnerLogin,
    OwnerPasswordChange,
    PaginatedEntries,
    PortableListDocument,
    PortableListImportOut,
    RatingAssessmentComplete,
    RatingAssessmentCreate,
    RatingAssessmentPatch,
    RatingComparisonUpdate,
    RatingRefinementEntryUpdate,
    RatingRefinementStart,
    RatingReviewOut,
    RecommendationDataDelete,
    RecommendationDataDeleteOut,
    RecommendationFeedbackCreate,
    RecommendationFeedbackOut,
    RecommendationPreferencesOut,
    RecommendationPreferencesUpdate,
    RecommendationReadinessOut,
    RecommendationResultsOut,
    RecommendationRunCreate,
    RecommendationRunOut,
    ReleaseEventUpdate,
    RemoteConflictResolution,
    RemoteOfflineMutation,
    RemoteServerConnect,
    RemoteServerConnectionState,
    RemoteServerDiscover,
    RemoteServerEnroll,
    SearchResponse,
    SearchResult,
    SeasonBulkUpdate,
    SeriesFollowUpdate,
    ServerActivationRequest,
    ServerBootstrap,
    SyncPushRequest,
    ViewingCreate,
)
from watchtracker.security import LocalSecurityMiddleware
from watchtracker.services.auth import CSRF_COOKIE, SESSION_COOKIE, AuthService
from watchtracker.services.backgrounds import (
    BackgroundImageError,
    BackgroundImageStore,
)
from watchtracker.services.backups import BackupError, BackupService, ScheduledBackupService
from watchtracker.services.enrichment import MetadataEnrichmentManager
from watchtracker.services.entries import (
    EntryConflict,
    EntryNotFound,
    EntryService,
    refresh_catalog_taxonomy,
)
from watchtracker.services.exports import obsidian_vault_zip, watch_log_csv
from watchtracker.services.insights import (
    InsightFilters,
    calculate_insights,
    insight_titles,
)
from watchtracker.services.integration_auth import (
    IntegrationAuthorizationError,
    IntegrationAuthorizationService,
)
from watchtracker.services.integrations import (
    IntegrationCoordinator,
    IntegrationError,
    IntegrationNotFound,
    IntegrationService,
)
from watchtracker.services.jobs import (
    DurableJobRunner,
    DurableJobService,
    JobCapabilityUnavailable,
    RetryableJobError,
)
from watchtracker.services.lists import MediaListService
from watchtracker.services.native import NativeActionError, open_local_path
from watchtracker.services.playback_integrations import (
    PlaybackIntegrationService,
    authenticate_webhook,
    ingest_playback,
)
from watchtracker.services.preferences import PreferenceStore
from watchtracker.services.profile import build_profile, profile_markdown
from watchtracker.services.ratings import (
    RUBRIC_VERSION,
    AdvancedRankingService,
    RatingAssessmentService,
    RatingComparisonService,
    RatingConflict,
    RatingFeatureDisabled,
    RatingNotFound,
    RatingRefinementService,
    advanced_rating_export,
    rubric_contract,
)
from watchtracker.services.releases import (
    ReleaseConflict,
    ReleaseNotFound,
    ReleaseProviderError,
    ReleaseScheduler,
    ReleaseSyncService,
    ReleaseTrackingService,
    ical_snapshot,
)
from watchtracker.services.secrets import SecretStore
from watchtracker.services.settings import SettingsWriteError, persist_env_values
from watchtracker.services.stats import calculate_stats
from watchtracker.services.sync import SyncService
from watchtracker.services.updates import UpdateCheckError, UpdateDownloadError, UpdateService
from watchtracker.tailscale_access import (
    TailscaleAccessError,
    TailscaleAccessManager,
    supports_managed_tailscale,
)

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
    integration_registry: ProviderRegistry | None = None,
    migrate: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    settings.require_safe_access_configuration()
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
    preferences.bind_session_factory(session_factory)
    auth = AuthService(session_factory, settings)
    metadata = metadata_service or MetadataService(settings)
    enrichment = MetadataEnrichmentManager(
        session_factory,
        metadata,
        today_factory=lambda: _today(settings),
    )
    backups = BackupService(settings, engine, session_factory)
    scheduled_backups = ScheduledBackupService(
        backups,
        session_factory,
        interval_hours=settings.server_backup_interval_hours,
        retention=settings.server_backup_retention,
    )
    updates = update_service or UpdateService(
        settings.repository_url,
        __version__,
        cache_dir=settings.resolved_cache_dir,
        packaged=settings.packaged,
    )
    integrations = integration_registry or default_registry(
        allow_anilist_account_sync=settings.anilist_account_sync_authorized
    )
    backgrounds = BackgroundImageStore(settings.resolved_config_dir)
    integration_coordinator = IntegrationCoordinator(session_factory, integrations, secrets)
    notification_adapters = default_notification_adapters()
    notification_delivery = NotificationDeliveryService(
        session_factory, secrets, notification_adapters
    )
    release_sync = ReleaseSyncService(
        session_factory,
        metadata,
        today_factory=lambda: _today(settings),
        interval_minutes=settings.release_check_interval_minutes,
    )
    release_scheduler = ReleaseScheduler(
        release_sync,
        session_factory,
        interval_minutes=settings.release_check_interval_minutes,
        batch_size=settings.release_sync_batch_size,
    )
    durable_jobs = DurableJobService(session_factory)
    recommendations = RecommendationService(
        session_factory,
        metadata_service=metadata,
        build_manifest=BUILD_MANIFEST,
        job_service=durable_jobs,
    )

    async def scheduled_server_backup(_payload: dict) -> None:
        result = await asyncio.to_thread(backups.create_server_snapshot)
        await asyncio.to_thread(backups.verify_recovery_archive, result.path)
        await asyncio.to_thread(scheduled_backups._prune)

    async def scheduled_release_sync(payload: dict) -> None:
        result = await release_sync.sync_due(
            limit=settings.release_sync_batch_size,
            force=False,
            user_id=payload.get("user_id"),
        )
        if result.get("failed") and not result.get("synced"):
            raise RetryableJobError("Release providers were temporarily unavailable.")

    async def scheduled_integration_sync(payload: dict) -> None:
        for _page in range(10):
            result = await integration_coordinator.run(
                payload["connection_id"],
                capability=payload["capability"],
                direction=payload.get("direction", "pull"),
                trigger="scheduled",
                user_id=payload["user_id"],
            )
            if result.get("state") == "failed":
                raise RetryableJobError(
                    result.get("error_message") or "The integration provider is unavailable.",
                    retry_after_seconds=result.get("retry_after_seconds"),
                )
            if not result.get("has_more"):
                break

    async def scheduled_notification_delivery(_payload: dict) -> None:
        await notification_delivery.deliver_due(limit=20)

    async def scheduled_recommendation_generate(payload: dict) -> None:
        compatibility = recommendations.run_compatibility(payload["user_id"], payload["run_id"])
        if compatibility == "missing":
            return
        if compatibility == "unsupported":
            raise JobCapabilityUnavailable(
                "This recommendation job requires a different PMT distribution capability."
            )
        if payload.get("_recovered_lease"):
            try:
                recovered = recommendations.recover_run(payload["run_id"], payload["user_id"])
            except RecommendationNotFound:
                return
            if not recovered:
                return
        try:
            recommendations.run(payload["user_id"], payload["run_id"])
        except RecommendationNotFound:
            return
        await recommendations.generate(payload["run_id"], payload["user_id"])
        try:
            status = recommendations.run(payload["user_id"], payload["run_id"])
        except RecommendationNotFound:
            return
        if status["state"] == "failed" and status["retryable"]:
            raise RetryableJobError(
                status.get("safe_failure_detail") or "Recommendation generation failed."
            )

    job_runner = DurableJobRunner(
        durable_jobs,
        {
            "server_backup": scheduled_server_backup,
            "release_sync": scheduled_release_sync,
            "integration_sync": scheduled_integration_sync,
            "notifications.deliver": scheduled_notification_delivery,
            "recommendation.generate": scheduled_recommendation_generate,
        },
        concurrency=settings.job_worker_concurrency,
        poll_seconds=settings.job_poll_seconds,
    )

    def prepare_recurring_jobs() -> None:
        compatible_recoverable_ids = recommendations.compatible_recoverable_run_ids()
        capability_resumed_ids = durable_jobs.resume_capability_scopes(
            kind="recommendation.generate",
            scope_type="recommendation_run",
            scope_ids=compatible_recoverable_ids,
        )
        compatible_pending_ids = recommendations.compatible_pending_run_ids()
        recovered_scopes = durable_jobs.recover_interrupted_scopes(
            kinds={"recommendation.generate"},
            scope_ids=compatible_pending_ids,
        )
        durable_jobs.enqueue(
            "notifications.deliver",
            idempotency_key="recurring:notifications-deliver",
            payload={"_repeat_seconds": 30},
        )
        recovered_run_ids = {
            scope_id
            for kind, scope_type, scope_id in recovered_scopes
            if kind == "recommendation.generate"
            and scope_type == "recommendation_run"
            and scope_id
        }
        for run_id, user_id in recommendations.recover_pending(
            recoverable_running_ids=recovered_run_ids,
            capability_resumed_ids=capability_resumed_ids,
        ):
            durable_jobs.enqueue(
                "recommendation.generate",
                idempotency_key=f"recommendation:{run_id}",
                user_id=user_id,
                scope_type="recommendation_run",
                scope_id=run_id,
                payload={"run_id": run_id, "user_id": user_id},
                max_attempts=3,
            )
        if settings.access_mode == "server":
            durable_jobs.enqueue(
                "server_backup",
                idempotency_key="recurring:server-backup",
                payload={"_repeat_seconds": settings.server_backup_interval_hours * 3600},
            )
        if preferences.load().get("release_check_mode") == "automatic":
            durable_jobs.enqueue(
                "release_sync",
                idempotency_key="recurring:release-sync",
                payload={"_repeat_seconds": settings.release_check_interval_minutes * 60},
            )
        with session_factory() as session:
            connections = list(
                session.scalars(
                    select(IntegrationConnection).where(
                        IntegrationConnection.enabled.is_(True),
                        IntegrationConnection.paused_reason.is_(None),
                    )
                )
            )
        for connection in connections:
            interval = int((connection.schedule or {}).get("interval_minutes") or 0)
            capabilities = [
                name
                for name, enabled in (connection.capabilities or {}).items()
                if enabled not in {False, "off"} and name.startswith("pull_")
            ]
            if interval <= 0 or not capabilities:
                continue
            for capability in capabilities:
                durable_jobs.enqueue(
                    "integration_sync",
                    idempotency_key=f"recurring:integration:{connection.id}:{capability}",
                    due_at=connection.next_run_at,
                    user_id=connection.user_id,
                    scope_type="integration_connection",
                    scope_id=connection.id,
                    payload={
                        "connection_id": connection.id,
                        "capability": capability,
                        "direction": "pull",
                        "user_id": connection.user_id,
                        "_repeat_seconds": interval * 60,
                    },
                )

    remote_client = (
        RemoteDeviceClient(RemoteProfileStore(settings.remote_client_path))
        if settings.access_mode == "local"
        else None
    )

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

    def individual_tmdb_credential(principal: Principal) -> tuple[str | None, str]:
        return secrets.get_named("metadata.tmdb.user", principal.user_id)

    def effective_metadata(
        principal: Principal, coordinator: MetadataService | Any | None = None
    ) -> MetadataService | Any:
        if settings.access_mode != "server" or principal.is_admin:
            token, _source = secrets.get()
        else:
            token, _source = individual_tmdb_credential(principal)
            if not token and preferences.load(principal.user_id).get(
                "use_server_metadata_token"
            ):
                token, _source = secrets.get()
        coordinator = coordinator or metadata
        scoped = getattr(coordinator, "with_tmdb_token", None)
        return scoped(token) if scoped else coordinator

    def metadata_settings_payload(principal: Principal) -> MetadataSettingsOut:
        server_token, server_source = secrets.get()
        if settings.access_mode != "server":
            token, source = server_token, server_source
            scope = "local"
            individual_configured = bool(token)
            use_server_token = False
        elif principal.is_admin:
            token, source = server_token, server_source
            scope = "server_shared"
            individual_configured = False
            use_server_token = False
        else:
            individual_token, source = individual_tmdb_credential(principal)
            use_server_token = bool(
                preferences.load(principal.user_id).get("use_server_metadata_token")
            )
            token = individual_token
            if not token and use_server_token:
                token, source = server_token, server_source
            scope = "individual" if individual_token or not token else "server_shared"
            individual_configured = bool(individual_token)
        return MetadataSettingsOut(
            tmdb_configured=bool(token),
            anilist_enabled=bool(settings.anilist_enabled),
            storage=source,
            legacy_token_available=bool(
                secrets.legacy_token()
                if settings.access_mode != "server" or principal.is_admin
                else False
            ),
            preferred_storage=(
                preferred_credential_storage()
                if settings.access_mode != "server" or principal.is_admin
                else "local_secret_file"
            ),
            keychain_available=bool(
                secrets.keyring_available
                and (settings.access_mode != "server" or principal.is_admin)
            ),
            credential_scope=scope,
            individual_token_configured=individual_configured,
            server_token_available=bool(server_token)
            if settings.access_mode == "server"
            else False,
            use_server_token=use_server_token,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_runtime_directories()
        configure_logging(settings)
        logger = logging.getLogger(__name__)
        logger.info(
            "Starting Personal Media Tracker %s [%s]",
            __version__,
            BUILD_MANIFEST.distribution_flavor,
        )
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
            preferences.migrate_legacy_user_preferences()
            auth.require_server_owner()
            with session_factory() as session:
                refresh_catalog_taxonomy(session)
            enrichment.start_verified_if_needed()
            if (
                settings.release_scheduler_enabled
                and preferences.load().get("release_check_mode") == "automatic"
                and settings.access_mode == "local"
            ):
                release_scheduler.start()
            prepare_recurring_jobs()
            job_runner.start()
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
            await job_runner.close()
            await scheduled_backups.close()
            await release_scheduler.close()
            await enrichment.close()
            await updates.close()
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
    app.state.scheduled_backups = scheduled_backups
    app.state.updates = updates
    app.state.integrations = integrations
    app.state.backgrounds = backgrounds
    app.state.integration_coordinator = integration_coordinator
    app.state.notification_adapters = notification_adapters
    app.state.notification_delivery = notification_delivery
    app.state.release_sync = release_sync
    app.state.release_scheduler = release_scheduler
    app.state.durable_jobs = durable_jobs
    app.state.recommendations = recommendations
    app.state.job_runner = job_runner
    app.state.auth = auth
    app.state.remote_client = remote_client

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

    @app.exception_handler(IntegrationNotFound)
    async def integration_not_found(_request: Request, exc: IntegrationNotFound):
        return _error(404, "integration_not_found", str(exc))

    @app.exception_handler(IntegrationError)
    async def integration_error(_request: Request, exc: IntegrationError):
        return _error(409, "integration_error", str(exc))

    @app.exception_handler(IntegrationAuthorizationError)
    async def integration_authorization_error(
        _request: Request, exc: IntegrationAuthorizationError
    ):
        return _error(400, "integration_authorization_error", str(exc))

    @app.exception_handler(NotificationError)
    async def notification_error(_request: Request, exc: NotificationError):
        return _error(400, "notification_error", str(exc))

    @app.exception_handler(EntryConflict)
    async def entry_conflict(_request: Request, exc: EntryConflict):
        return _error(409, "conflict", str(exc))

    @app.exception_handler(ImportConflict)
    async def import_conflict(_request: Request, exc: ImportConflict):
        return _error(409, "import_conflict", str(exc))

    @app.exception_handler(ImportNotFound)
    async def import_not_found(_request: Request, exc: ImportNotFound):
        return _error(404, "not_found", str(exc))

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

    @app.exception_handler(TailscaleAccessError)
    async def tailscale_access_error(_request: Request, exc: TailscaleAccessError):
        return _error(409, "tailscale_unavailable", str(exc))

    @app.exception_handler(BackupError)
    async def backup_error(_request: Request, exc: BackupError):
        return _error(400, "backup_error", str(exc))

    @app.exception_handler(UpdateCheckError)
    async def update_error(_request: Request, exc: UpdateCheckError):
        return _error(503, "update_check_failed", str(exc))

    @app.exception_handler(UpdateDownloadError)
    async def update_download_error(_request: Request, exc: UpdateDownloadError):
        return _error(409, "update_download_failed", str(exc))

    @app.exception_handler(NativeActionError)
    async def native_action_error(_request: Request, exc: NativeActionError):
        return _error(500, "native_action_failed", str(exc))

    @app.exception_handler(RemoteClientError)
    async def remote_client_error(_request: Request, exc: RemoteClientError):
        return _error(409, "remote_client_error", str(exc))

    @app.exception_handler(RatingFeatureDisabled)
    async def rating_feature_disabled(_request: Request, exc: RatingFeatureDisabled):
        return _error(409, "advanced_ratings_disabled", str(exc))

    @app.exception_handler(RatingNotFound)
    async def rating_not_found(_request: Request, exc: RatingNotFound):
        return _error(404, "rating_not_found", str(exc))

    @app.exception_handler(RatingConflict)
    async def rating_conflict(_request: Request, exc: RatingConflict):
        return _error(409, "rating_conflict", str(exc))

    @app.exception_handler(RecommendationNotFound)
    async def recommendation_not_found(_request: Request, exc: RecommendationNotFound):
        return _error(404, "recommendation_not_found", str(exc))

    @app.exception_handler(RecommendationConflict)
    async def recommendation_conflict(_request: Request, exc: RecommendationConflict):
        return _error(409, "recommendation_conflict", str(exc))

    @app.exception_handler(ReleaseNotFound)
    async def release_not_found(_request: Request, exc: ReleaseNotFound):
        return _error(404, "release_not_found", str(exc))

    @app.exception_handler(ReleaseConflict)
    async def release_conflict(_request: Request, exc: ReleaseConflict):
        return _error(409, "release_conflict", str(exc))

    @app.exception_handler(ReleaseProviderError)
    async def release_provider_error(_request: Request, exc: ReleaseProviderError):
        return _error(503, "release_provider_unavailable", str(exc))

    def advanced_ratings_enabled(session: Session) -> bool:
        principal = current_principal(session)
        return preferences.load(principal.user_id).get("advanced_ratings_enabled") is True

    @app.get("/health")
    def health(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "version": __version__,
            "distribution_flavor": BUILD_MANIFEST.distribution_flavor,
            "recommendation_capabilities": list(BUILD_MANIFEST.recommendation_capabilities),
            "database": "ready",
            "mode": settings.access_mode,
        }

    @app.get("/ready")
    def ready(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {
            "status": "setup_required"
            if settings.access_mode == "server" and not auth.owner_exists()
            else "ready"
        }

    @app.get("/api/v1/server/capabilities")
    def server_capabilities(session: Session = Depends(session_dependency)):
        state = session.get(ServerState, 1)
        return {
            "product": "personal-media-tracker",
            "server_version": __version__,
            "api_version": state.api_version if state else "1",
            "minimum_client_api_version": "1",
            "schema_revision": migration_head(settings),
            "instance_id": state.instance_id if state else None,
            "mode": settings.access_mode,
            "library_authority": "pmt_server"
            if settings.access_mode == "server"
            else "embedded_local",
            "setup_required": settings.access_mode == "server" and not auth.owner_exists(),
            "build_manifest": BUILD_MANIFEST.as_dict(base_version=__version__),
            "features": {
                "multi_user": True,
                "invitations": True,
                "device_sessions": True,
                "optimistic_concurrency": True,
                "idempotent_sync": True,
                "icloud_library": False,
                "recommendations": True,
                "recommendation_capabilities": list(BUILD_MANIFEST.recommendation_capabilities),
            },
        }

    @app.get(
        "/api/v1/recommendations/readiness",
        response_model=RecommendationReadinessOut,
    )
    def recommendation_readiness(
        principal: Principal = Depends(request_principal),
    ):
        return recommendations.readiness(principal.user_id)

    @app.get(
        "/api/v1/recommendations/preferences",
        response_model=RecommendationPreferencesOut,
    )
    def recommendation_preferences(
        principal: Principal = Depends(request_principal),
    ):
        return recommendations.preferences(principal.user_id)

    @app.put(
        "/api/v1/recommendations/preferences",
        response_model=RecommendationPreferencesOut,
    )
    def update_recommendation_preferences(
        payload: RecommendationPreferencesUpdate,
        principal: Principal = Depends(request_principal),
    ):
        return recommendations.update_preferences(
            principal.user_id,
            payload.model_dump(exclude_none=True),
        )

    @app.post(
        "/api/v1/recommendation-runs",
        response_model=RecommendationRunOut,
        status_code=202,
    )
    def start_recommendation_run(
        payload: RecommendationRunCreate = Body(default=RecommendationRunCreate()),
        principal: Principal = Depends(request_principal),
    ):
        run, _created = recommendations.start_run(
            principal.user_id,
            idempotency_key=payload.idempotency_key,
            result_limit=payload.result_limit,
        )
        if run["state"] == "queued":
            durable_jobs.enqueue(
                "recommendation.generate",
                idempotency_key=f"recommendation:{run['id']}",
                user_id=principal.user_id,
                scope_type="recommendation_run",
                scope_id=run["id"],
                payload={"run_id": run["id"], "user_id": principal.user_id},
                max_attempts=3,
            )
        return run

    @app.get(
        "/api/v1/recommendation-runs/{run_id}",
        response_model=RecommendationRunOut,
    )
    def recommendation_run(
        run_id: str,
        principal: Principal = Depends(request_principal),
    ):
        return recommendations.run(principal.user_id, run_id)

    @app.get(
        "/api/v1/recommendation-runs/{run_id}/results",
        response_model=RecommendationResultsOut,
    )
    def recommendation_results(
        run_id: str,
        principal: Principal = Depends(request_principal),
    ):
        return recommendations.results(principal.user_id, run_id)

    @app.post(
        "/api/v1/recommendation-results/{result_id}/feedback",
        response_model=RecommendationFeedbackOut,
    )
    def recommendation_feedback(
        result_id: str,
        payload: RecommendationFeedbackCreate,
        principal: Principal = Depends(request_principal),
    ):
        return recommendations.feedback(
            principal.user_id,
            result_id,
            payload.feedback,
        )

    @app.delete(
        "/api/v1/me/recommendation-data",
        response_model=RecommendationDataDeleteOut,
    )
    def delete_recommendation_data(
        payload: RecommendationDataDelete,
        principal: Principal = Depends(request_principal),
    ):
        del payload
        return {"deleted": recommendations.delete_user_data(principal.user_id)}

    def native_host_authorized(request: Request) -> bool:
        expected = settings.native_host_token
        supplied = request.headers.get("x-pmt-native-host", "")
        return bool(
            expected
            and getattr(request.state, "native_desktop_loopback", False)
            and secure_tokens.compare_digest(supplied, expected)
        )

    def browser_cookie_secure(request: Request) -> bool:
        return not getattr(request.state, "native_desktop_loopback", False)

    def set_auth_cookies(response: Response, issued, request: Request) -> None:
        max_age = settings.session_ttl_hours * 3600
        secure = browser_cookie_secure(request)
        response.set_cookie(
            SESSION_COOKIE,
            issued.session_token,
            max_age=max_age,
            secure=secure,
            httponly=True,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            issued.csrf_token,
            max_age=max_age,
            secure=secure,
            httponly=False,
            samesite="strict",
            path="/",
        )

    def clear_auth_cookies(response: Response, request: Request) -> None:
        secure = browser_cookie_secure(request)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True)
        response.delete_cookie(CSRF_COOKIE, path="/", secure=secure)

    @app.get("/api/auth/status")
    def auth_status(request: Request, response: Response):
        record = auth.authenticate(request.cookies.get(SESSION_COOKIE), kind="browser")
        trusted_native_host = native_host_authorized(request)
        host_identity = auth.server_account_identity() if trusted_native_host else None
        trusted_local_profile = False
        if settings.access_mode == "server" and record is None and trusted_native_host:
            issued = auth.login_trusted_legacy_host()
            if issued is not None:
                set_auth_cookies(response, issued, request)
                record = auth.authenticate(issued.session_token, kind="browser")
                trusted_local_profile = record is not None
        return {
            "mode": settings.access_mode,
            "authenticated": settings.access_mode == "local" or record is not None,
            "owner_configured": auth.owner_exists(),
            "setup_required": settings.access_mode == "server" and not auth.owner_exists(),
            "native_server_host": host_identity is not None,
            "server_account_hint": host_identity,
            "trusted_local_profile": trusted_local_profile,
            "server_console_available": bool(
                settings.access_mode == "server" and not trusted_native_host
            ),
        }

    @app.get("/api/v1/setup/status")
    def setup_status():
        return {
            "mode": settings.access_mode,
            "setup_required": settings.access_mode == "server" and not auth.owner_exists(),
            "bootstrap_available": bool(
                settings.access_mode == "server"
                and settings.server_bootstrap_token
                and not auth.owner_exists()
            ),
        }

    @app.post("/api/v1/setup/bootstrap", status_code=201)
    def bootstrap_server(payload: ServerBootstrap):
        if auth.owner_exists():
            raise HTTPException(409, "Server setup is already complete.")
        try:
            account = auth.bootstrap_server(
                payload.setup_token,
                payload.password,
                username=payload.username,
                display_name=payload.display_name,
            )
        except ValueError as exc:
            # Do not distinguish a missing setup secret from a wrong one.
            raise HTTPException(409, str(exc)) from exc
        return {
            "setup_required": False,
            "administrator": {
                "id": account.id,
                "username": account.username,
                "display_name": account.display_name,
            },
            "next": "Sign in with the new server account.",
        }

    @app.post("/api/auth/bootstrap", status_code=201)
    def bootstrap_owner(payload: OwnerBootstrap):
        try:
            auth.bootstrap(payload.password)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"owner_configured": True, "bootstrap_locked": True}

    @app.post("/api/auth/login")
    def login_owner(payload: OwnerLogin, request: Request, response: Response):
        if settings.access_mode != "server":
            raise HTTPException(409, "Sign-in is not used in local-only mode.")
        identity = request.client.host if request.client else "unknown"
        issued = auth.login(
            payload.username,
            payload.password,
            identity,
            device_label=request.headers.get("user-agent", "Web browser")[:120],
        )
        if issued is None:
            # Intentionally generic: do not reveal owner existence or throttle state.
            raise HTTPException(401, "The username or password is incorrect.")
        set_auth_cookies(response, issued, request)
        return {"authenticated": True, "expires_at": issued.expires_at}

    @app.post("/api/v1/setup/local-host-recovery")
    def recover_local_server_account(
        payload: LocalServerRecovery,
        request: Request,
        response: Response,
    ):
        if settings.access_mode != "server" or not native_host_authorized(request):
            raise HTTPException(404, "Local server-account recovery is unavailable.")
        try:
            account = auth.recover_server_account_password(payload.new_password)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        identity = request.client.host if request.client else "native-host"
        issued = auth.login(
            account["username"],
            payload.new_password,
            identity,
            device_label="PMT app on server host",
        )
        if issued is None:
            raise HTTPException(500, "The recovered server account could not be signed in.")
        set_auth_cookies(response, issued, request)
        return {
            "authenticated": True,
            "username": account["username"],
            "sessions_revoked": True,
        }

    @app.get("/api/auth/session")
    def auth_session(request: Request, principal: Principal = Depends(request_principal)):
        record = request.state.user_session
        return {
            "authenticated": True,
            "expires_at": record.expires_at,
            "user_id": principal.user_id,
            "role": principal.role,
        }

    @app.get("/api/v1/me")
    def current_account(
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        account = session.get(UserAccount, principal.user_id)
        if account is None:
            raise HTTPException(404, "User account not found.")
        # Versions before dedicated server accounts assigned the existing personal
        # library to the only administrator. Keep that migrated library reachable
        # without changing ownership or weakening the dedicated-account model for
        # new server installations.
        legacy_personal_library = bool(
            account.role == "admin"
            and session.scalar(
                select(WatchEntry.id)
                .where(
                    WatchEntry.user_id == account.id,
                    WatchEntry.deleted_at.is_(None),
                )
                .limit(1)
            )
        )
        return {
            "id": account.id,
            "username": account.username,
            "display_name": account.display_name,
            "email": account.email,
            "role": account.role,
            "state": account.state,
            "locale": account.locale,
            "timezone": account.timezone,
            "legacy_personal_library": legacy_personal_library,
        }

    @app.get("/api/v1/auth/sessions")
    def user_sessions(principal: Principal = Depends(request_principal)):
        return {"items": auth.list_sessions(principal.user_id)}

    @app.delete("/api/v1/auth/sessions/{session_id}", status_code=204)
    def revoke_user_session(session_id: str, principal: Principal = Depends(request_principal)):
        if not auth.revoke_session(principal.user_id, session_id):
            raise HTTPException(404, "Session not found.")
        return Response(status_code=204)

    @app.post("/api/v1/auth/device/login")
    def native_login(payload: NativeLogin, request: Request):
        if settings.access_mode != "server" or not auth.owner_exists():
            raise HTTPException(409, "PMT Server setup is not complete.")
        identity = request.client.host if request.client else "unknown"
        issued = auth.login_native(
            payload.username,
            payload.password,
            identity,
            device_id=payload.device_id,
            device_label=payload.device_label,
        )
        if issued is None:
            raise HTTPException(401, "The username or password is incorrect.")
        return {
            "token_type": "Bearer",
            "access_token": issued.session_token,
            "access_expires_at": issued.expires_at,
            "refresh_token": issued.refresh_token,
            "refresh_expires_at": issued.refresh_expires_at,
            "session_id": issued.session_id,
        }

    @app.post("/api/v1/auth/device/refresh")
    def native_refresh(payload: NativeRefresh):
        issued = auth.refresh_native(payload.refresh_token)
        if issued is None:
            raise HTTPException(401, "The device session is invalid or expired.")
        return {
            "token_type": "Bearer",
            "access_token": issued.session_token,
            "access_expires_at": issued.expires_at,
            "refresh_token": issued.refresh_token,
            "refresh_expires_at": issued.refresh_expires_at,
            "session_id": issued.session_id,
        }

    @app.post("/api/v1/auth/device/browser-session")
    def create_native_browser_session(
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        record = request.state.user_session
        if record.session_kind != "native":
            raise HTTPException(409, "A native device session is required.")
        try:
            issued = auth.issue_browser_handoff(
                principal.user_id,
                device_id=record.device_id or record.id,
                device_label=record.device_label or "Personal Media Tracker app",
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "handoff_token": issued.session_token,
            "expires_at": issued.expires_at,
        }

    @app.post("/api/v1/auth/browser/adopt")
    def adopt_native_browser_session(
        payload: BrowserSessionAdopt,
        request: Request,
        response: Response,
    ):
        issued = auth.adopt_browser_handoff(
            payload.handoff_token,
            device_label=f"PMT installed app · {request.headers.get('user-agent', 'device')}",
        )
        if issued is None:
            raise HTTPException(401, "This saved app session is invalid or expired.")
        set_auth_cookies(response, issued, request)
        return {"authenticated": True, "expires_at": issued.expires_at}

    @app.post("/api/v1/auth/device/logout", status_code=204)
    def native_logout(request: Request, principal: Principal = Depends(request_principal)):
        record = request.state.user_session
        if record.session_kind != "native":
            raise HTTPException(409, "This endpoint revokes native device sessions only.")
        auth.revoke_session(principal.user_id, record.id)
        return Response(status_code=204)

    @app.post("/api/v1/auth/invitations/redeem", status_code=201)
    def redeem_invitation(payload: InvitationRedeem):
        if settings.access_mode != "server" or not auth.owner_exists():
            raise HTTPException(409, "PMT Server setup is not complete.")
        try:
            account = auth.redeem_invitation(
                payload.token,
                payload.password,
                username=payload.username,
                display_name=payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "created": True,
            "account": {
                "id": account.id,
                "username": account.username,
                "display_name": account.display_name,
            },
            "next": "Sign in with this account.",
        }

    @app.get("/api/v1/admin/users")
    def admin_users(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        return {"items": auth.list_users()}

    @app.patch("/api/v1/admin/users/{user_id}")
    def update_admin_user(
        user_id: str,
        payload: AdminUserUpdate,
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        try:
            return auth.update_user(
                principal.user_id,
                user_id,
                state=payload.state,
                role=payload.role,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/admin/invitations")
    def admin_invitations(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        return {"items": auth.list_invitations()}

    @app.post("/api/v1/admin/invitations", status_code=201)
    def create_admin_invitation(
        payload: InvitationCreate,
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        issued = auth.create_invitation(
            principal.user_id,
            role=payload.role,
            email=payload.email,
            expires_hours=payload.expires_hours,
        )
        return {
            "id": issued.invitation_id,
            "kind": issued.kind,
            "token": issued.token,
            "expires_at": issued.expires_at,
            "shown_once": True,
            "redeem_url": (
                f"{settings.public_base_url.rstrip('/')}/?invite={issued.token}"
                if settings.public_base_url
                else None
            ),
        }

    @app.post("/api/v1/admin/users/{user_id}/recovery-invitation", status_code=201)
    def create_recovery_invitation(
        user_id: str, principal: Principal = Depends(request_principal)
    ):
        require_admin(principal)
        try:
            issued = auth.create_invitation(
                principal.user_id,
                expires_hours=24,
                recovery_for_user_id=user_id,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {
            "id": issued.invitation_id,
            "kind": issued.kind,
            "token": issued.token,
            "expires_at": issued.expires_at,
            "shown_once": True,
            "redeem_url": (
                f"{settings.public_base_url.rstrip('/')}/?invite={issued.token}"
                if settings.public_base_url
                else None
            ),
        }

    @app.delete("/api/v1/admin/invitations/{invitation_id}", status_code=204)
    def revoke_admin_invitation(
        invitation_id: str, principal: Principal = Depends(request_principal)
    ):
        require_admin(principal)
        if not auth.revoke_invitation(principal.user_id, invitation_id):
            raise HTTPException(404, "Invitation not found.")
        return Response(status_code=204)

    @app.get("/api/v1/jobs")
    def scheduled_job_status(principal: Principal = Depends(request_principal)):
        return {
            "worker": "running" if job_runner.running else "stopped",
            "items": durable_jobs.list_safe(
                user_id=principal.user_id, admin=principal.is_admin
            ),
        }

    @app.post("/api/v1/admin/jobs/refresh", status_code=202)
    def refresh_scheduled_jobs(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        prepare_recurring_jobs()
        return {"scheduled": True}

    @app.post("/api/v1/admin/jobs/{job_id}/resume", status_code=202)
    def resume_scheduled_job(job_id: str, principal: Principal = Depends(request_principal)):
        require_admin(principal)
        if not durable_jobs.resume(job_id):
            raise HTTPException(409, "Only a paused job can be resumed.")
        return {"state": "scheduled"}

    @app.delete("/api/v1/admin/jobs/{job_id}", status_code=204)
    def cancel_scheduled_job(job_id: str, principal: Principal = Depends(request_principal)):
        require_admin(principal)
        if not durable_jobs.cancel(job_id):
            raise HTTPException(409, "A running task cannot be cancelled.")
        return Response(status_code=204)

    @app.post("/api/auth/logout", status_code=204)
    def logout_owner(request: Request, response: Response):
        auth.logout(request.cookies.get(SESSION_COOKIE))
        clear_auth_cookies(response, request)

    @app.post("/api/auth/password")
    def change_owner_password(
        payload: OwnerPasswordChange,
        request: Request,
        response: Response,
        principal: Principal = Depends(request_principal),
    ):
        if not auth.change_password(
            payload.current_password, payload.new_password, user_id=principal.user_id
        ):
            raise HTTPException(400, "The current password is incorrect.")
        clear_auth_cookies(response, request)
        return {"changed": True, "sessions_revoked": True}

    @app.post("/api/auth/sessions/revoke")
    def revoke_owner_sessions(
        request: Request,
        response: Response,
        principal: Principal = Depends(request_principal),
    ):
        count = auth.revoke_all(principal.user_id)
        clear_auth_cookies(response, request)
        return {"revoked": count}

    def readiness_report() -> dict:
        prospective = settings.model_copy(update={"access_mode": "server"})
        configuration_errors = prospective.access_configuration_errors()
        backup_files = sorted(
            settings.resolved_backups_dir.glob("*.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        with session_factory() as session:
            active_user_count = int(
                session.scalar(
                    select(func.count(UserAccount.id)).where(UserAccount.state == "active")
                )
                or 0
            )
            last_connection_at = session.scalar(select(func.max(OwnerSession.last_seen_at)))
            backup_job = session.scalar(
                select(ScheduledJob).where(
                    ScheduledJob.idempotency_key == "recurring:server-backup"
                )
            )
        checks = [
            {
                "key": "backup",
                "label": "Current safety backup",
                "ok": bool(backup_files),
                "remediation": "Create a backup before activating shared access.",
            },
            {
                "key": "database",
                "label": "Single local SQLite database",
                "ok": settings.database_url.startswith("sqlite:///")
                and settings.resolved_database_path.is_absolute(),
                "remediation": "Keep SQLite on storage local to the one server process.",
            },
            {
                "key": "owner",
                "label": "Server account",
                "ok": auth.owner_exists(),
                "remediation": "Complete the one-time server-account setup.",
            },
            {
                "key": "https",
                "label": "HTTPS public URL and trusted hosts",
                "ok": not configuration_errors,
                "remediation": configuration_errors[0] if configuration_errors else "Ready.",
            },
        ]
        return {
            "mode": settings.access_mode,
            "ready": all(item["ok"] for item in checks),
            "checks": checks,
            "access_url": settings.public_base_url
            if settings.access_mode == "server"
            else None,
            "last_connection_at": last_connection_at,
            "last_backup_at": backup_job.completed_at if backup_job else None,
            "backup_status": backup_job.state if backup_job else "not_started",
            "active_user_count": active_user_count,
            "local_only_blocked_reason": (
                "This server has multiple active accounts. Stopping the service leaves "
                "every account and library stored on the standalone server; it cannot "
                "be converted into one local library."
                if active_user_count > 1
                else None
            ),
            "restart_required": False,
        }

    @app.get("/api/server/readiness")
    def server_readiness(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        return readiness_report()

    @app.get("/api/v1/server/readiness")
    def versioned_server_readiness(
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        return readiness_report()

    @app.post("/api/server/activate")
    def activate_server(
        payload: ServerActivationRequest,
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        if settings.packaged:
            raise HTTPException(
                409,
                "The regular desktop package cannot become PMT Server. Install the "
                "separate PMT Server Setup Beta package.",
            )
        if settings.access_mode != "local":
            raise HTTPException(409, "Shared access is already active.")
        if not Settings.is_loopback_host(payload.bind_host):
            raise HTTPException(
                400,
                "The initial server release binds behind a local HTTPS proxy; use a loopback bind host.",
            )
        try:
            for value in payload.trusted_proxy_ips:
                ipaddress.ip_address(value)
            if (payload.bind_host, payload.port) != (settings.host, settings.port):
                with socket.socket(
                    socket.AF_INET6 if ":" in payload.bind_host else socket.AF_INET
                ) as probe:
                    probe.bind((payload.bind_host, payload.port))
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409, "The proposed bind address or port is unavailable."
            ) from exc
        if auth.owner_exists():
            if not auth.verify_owner_password(payload.owner_password):
                raise HTTPException(400, "The owner password is incorrect.")
        else:
            auth.bootstrap(payload.owner_password)
        backup = backups.create(prefix="personal-media-tracker-pre-server")
        from urllib.parse import urlsplit

        public_host = urlsplit(payload.public_base_url).hostname
        secret = secure_tokens.token_urlsafe(64)
        persist_env_values(
            settings.resolved_env_path,
            {
                "WATCHTRACKER_ACCESS_MODE": "server",
                "WATCHTRACKER_HOST": payload.bind_host,
                "WATCHTRACKER_PORT": str(payload.port),
                "WATCHTRACKER_PUBLIC_BASE_URL": payload.public_base_url,
                "WATCHTRACKER_APPLICATION_SECRET": secret,
                "WATCHTRACKER_TRUSTED_HOSTS": public_host,
                "WATCHTRACKER_TRUSTED_PROXY_IPS": ",".join(payload.trusted_proxy_ips),
            },
        )
        return {
            "activated": True,
            "restart_required": True,
            "access_url": payload.public_base_url,
            "backup": backup.path.name,
        }

    @app.post("/api/server/local-only")
    def return_to_local_only(
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        require_admin(principal)
        active_users = session.scalar(
            select(func.count(UserAccount.id)).where(UserAccount.state == "active")
        )
        if int(active_users or 0) > 1:
            raise HTTPException(
                409,
                "Shared Server has multiple active users. It cannot choose one private library for local-only mode.",
            )
        persist_env_values(
            settings.resolved_env_path,
            {
                "WATCHTRACKER_ACCESS_MODE": "local",
                "WATCHTRACKER_HOST": "127.0.0.1",
                "WATCHTRACKER_PUBLIC_BASE_URL": None,
                "WATCHTRACKER_APPLICATION_SECRET": None,
                "WATCHTRACKER_TRUSTED_HOSTS": None,
                "WATCHTRACKER_TRUSTED_PROXY_IPS": None,
            },
        )
        auth.revoke_all()
        return {"local_only": True, "restart_required": True}

    @app.get("/api/search", response_model=SearchResponse)
    async def search(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=200)],
        media_type: Literal["movie", "tv", "anime"] | None = None,
        principal: Principal = Depends(request_principal),
    ):
        return await effective_metadata(principal).search(q, media_type)

    @app.get("/api/settings/metadata", response_model=MetadataSettingsOut)
    def metadata_settings_status(
        principal: Principal = Depends(request_principal),
    ):
        return metadata_settings_payload(principal)

    @app.put("/api/settings/metadata", response_model=MetadataSettingsOut)
    def update_metadata_settings(
        payload: MetadataSettingsUpdate,
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        global_credential = settings.access_mode != "server" or principal.is_admin
        try:
            if global_credential:
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
            else:
                if payload.import_existing_keychain:
                    raise ValueError(
                        "System-vault migration is available only to the server account."
                    )
                if payload.clear_tmdb_token:
                    secrets.clear_named("metadata.tmdb.user", principal.user_id)
                elif payload.tmdb_token:
                    secrets.save_named(
                        "metadata.tmdb.user",
                        principal.user_id,
                        payload.tmdb_token,
                        storage="local_secret_file",
                    )
                if payload.use_server_token is not None:
                    preferences.update(
                        user_id=principal.user_id,
                        use_server_metadata_token=payload.use_server_token,
                    )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if global_credential:
            token, _source = secrets.get()
            settings.tmdb_token = token
            configure = getattr(request.app.state.metadata, "configure_tmdb", None)
            if configure:
                configure(token)
        return metadata_settings_payload(principal)

    @app.post("/api/settings/metadata/migrate-legacy", response_model=MetadataSettingsOut)
    def migrate_legacy_metadata_settings(
        request: Request, principal: Principal = Depends(request_principal)
    ):
        require_admin(principal)
        try:
            secrets.migrate_legacy(storage="local_secret_file")
            preferences.update(
                credential_storage="local_secret_file",
                credential_vault_opt_in=False,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        token, _source = secrets.get()
        settings.tmdb_token = token
        configure = getattr(request.app.state.metadata, "configure_tmdb", None)
        if configure:
            configure(token)
        return metadata_settings_payload(principal)

    @app.get("/api/settings/general")
    def general_settings(
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        stored = preferences.load(principal.user_id)
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
            "timezone": stored.get("timezone", settings.timezone),
            "language": stored.get("language", settings.language),
            "region": stored.get("region", settings.region),
            "theme": stored.get("theme", "system"),
            "accent": stored.get("accent", "forest"),
            "accent_color": stored.get("accent_color"),
            "background_color": stored.get("background_color"),
            "background_strength": stored.get("background_strength", 16),
            "background_mode": stored.get("background_mode", "adaptive"),
            "background_image_enabled": bool(
                stored.get("background_image_enabled", False) and backgrounds.available
            ),
            "background_image_available": backgrounds.available,
            "background_image_version": backgrounds.version,
            "background_image_opacity": stored.get("background_image_opacity", 24),
            "background_image_tint": bool(stored.get("background_image_tint", True)),
            "media_artwork_tint": bool(stored.get("media_artwork_tint", False)),
            "media_artwork_full_color": bool(stored.get("media_artwork_full_color", False)),
            "show_episode_progress": bool(stored.get("show_episode_progress", True)),
            "icon_background_color": stored.get(
                "icon_background_color", DEFAULT_ICON_BACKGROUND
            ),
            "icon_text_color": stored.get("icon_text_color", DEFAULT_ICON_TEXT),
            "icon_follow_accent": bool(stored.get("icon_follow_accent", False)),
            "interface_language": stored.get("interface_language", "en"),
            "advanced_ratings_enabled": bool(stored.get("advanced_ratings_enabled", False)),
            "release_check_mode": stored.get("release_check_mode"),
            "sidebar_mode": stored.get("sidebar_mode", "expanded"),
            "navigation_order": stored.get("navigation_order", "standard"),
            "settings_privacy_reminder_dismissed": bool(
                stored.get("settings_privacy_reminder_dismissed", False)
            ),
            "keyboard_shortcuts": stored.get("keyboard_shortcuts") or {},
            "effective_timezone": str(getattr(settings.tzinfo, "key", settings.tzinfo)),
            "data_location": (
                str(settings.resolved_data_dir)
                if principal.is_admin
                else "Managed by PMT Server"
            ),
            "database_size": (
                database_path.stat().st_size
                if principal.is_admin and database_path.exists()
                else 0
            ),
            "last_backup_at": (
                datetime.fromtimestamp(
                    backup_files[0].stat().st_mtime, settings.tzinfo
                ).isoformat()
                if principal.is_admin and backup_files
                else None
            ),
            "version": __version__,
            "repository_url": settings.repository_url,
            "native_actions": settings.native_actions
            and principal.is_admin
            and (
                (
                    settings.access_mode == "local"
                    and getattr(request.state, "native_desktop_loopback", False)
                )
                or (settings.access_mode == "server" and native_host_authorized(request))
            ),
            "release_mode": settings.release_mode,
        }

    @app.put("/api/settings/general")
    async def update_general_settings(
        payload: GeneralSettingsUpdate,
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        changes = payload.model_dump(exclude_unset=True)
        stored = preferences.update(user_id=principal.user_id, **changes)
        if (
            settings.access_mode == "local"
            and "timezone" in changes
            and "WATCHTRACKER_TIMEZONE" not in os.environ
        ):
            settings.timezone = changes["timezone"]
        if (
            settings.access_mode == "local"
            and changes.get("language")
            and "WATCHTRACKER_LANGUAGE" not in os.environ
        ):
            settings.language = changes["language"]
        if (
            settings.access_mode == "local"
            and changes.get("region")
            and "WATCHTRACKER_REGION" not in os.environ
        ):
            settings.region = changes["region"]
        if {"language", "region"} & changes.keys():
            configure = getattr(request.app.state.metadata, "configure_tmdb", None)
            if configure:
                configure(settings.tmdb_token)
        if "release_check_mode" in changes:
            if (
                changes["release_check_mode"] == "automatic"
                and settings.release_scheduler_enabled
            ):
                request.app.state.release_scheduler.start()
            else:
                await request.app.state.release_scheduler.close()
        return {"status": "saved", **stored}

    @app.get("/api/settings/background-image")
    def background_image(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        if not backgrounds.available:
            raise HTTPException(404, "No workspace background image has been imported.")
        return FileResponse(
            backgrounds.path,
            media_type="image/webp",
            filename="workspace-background.webp",
            headers={"Content-Disposition": "inline"},
        )

    @app.put("/api/settings/background-image")
    async def upload_background_image(
        file: UploadFile = File(...),
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        limit = settings.upload_limit_mb * 1024 * 1024
        content = await file.read(limit + 1)
        if len(content) > limit:
            return _error(
                413, "payload_too_large", "Image exceeds the configured upload limit."
            )
        try:
            status = await asyncio.to_thread(backgrounds.save, content)
        except BackgroundImageError as exc:
            raise HTTPException(422, str(exc)) from exc
        preferences.update(user_id=principal.user_id, background_image_enabled=True)
        return status

    @app.delete("/api/settings/background-image", status_code=204)
    def delete_background_image(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        backgrounds.delete()
        preferences.update(user_id=principal.user_id, background_image_enabled=False)
        return Response(status_code=204)

    @app.post("/api/backups")
    def create_backup(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        result = backups.create(user_id=principal.user_id)
        logging.getLogger(__name__).info("Backup created: %s", result.path.name)
        return {
            "status": "created",
            "filename": result.path.name,
            "size": result.size,
            "created_at": result.created_at,
            "location": str(settings.resolved_backups_dir),
        }

    @app.post("/api/v1/admin/backups", status_code=201)
    def create_server_backup(principal: Principal = Depends(request_principal)):
        require_admin(principal)
        if settings.access_mode != "server":
            raise HTTPException(409, "Server disaster backups are available in server mode.")
        result = backups.create_server_snapshot()
        verification = backups.verify_recovery_archive(result.path)
        return {
            "status": "created",
            "filename": result.path.name,
            "size": result.size,
            "created_at": result.created_at,
            "verification": verification,
        }

    @app.post("/api/v1/admin/backups/{filename}/verify")
    def verify_server_backup(filename: str, principal: Principal = Depends(request_principal)):
        require_admin(principal)
        if filename != Path(filename).name or not filename.endswith(".zip"):
            raise HTTPException(404, "Backup not found.")
        return backups.verify_recovery_archive(settings.resolved_backups_dir / filename)

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
        if settings.access_mode == "server":
            raise HTTPException(
                409,
                "Restore is available only in local-only mode. This prevents replacing the active server's authentication boundary mid-session.",
            )
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
    async def restore_backup(
        file: UploadFile = File(...),
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        return await _restore_upload(file, import_existing=False)

    @app.post("/api/data/import-database")
    async def import_existing_database(
        file: UploadFile = File(...),
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
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
        file: UploadFile = File(...),
        archive_sha256: str = Form(...),
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        return await _restore_upload(
            file,
            import_existing=True,
            expected_sha256=archive_sha256,
        )

    @app.post("/api/system/open-folder")
    def open_folder(
        kind: Literal["data", "backups", "logs"],
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        if not settings.native_actions or not (
            (
                settings.access_mode == "local"
                and getattr(request.state, "native_desktop_loopback", False)
            )
            or (settings.access_mode == "server" and native_host_authorized(request))
        ):
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

    @app.post("/api/updates/download", status_code=202)
    async def download_update(
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        return await updates.start_download()

    @app.get("/api/updates/status")
    def update_download_status():
        return updates.status()

    @app.get("/api/integrations/catalog")
    def integration_catalog(session: Session = Depends(session_dependency)):
        return {"providers": IntegrationService(session, integrations, secrets).catalog()}

    @app.get("/api/v1/integrations/catalog")
    def integration_catalog_v1(session: Session = Depends(session_dependency)):
        return {"providers": IntegrationService(session, integrations, secrets).catalog()}

    @app.get("/api/integrations/connections")
    def integration_connections(session: Session = Depends(session_dependency)):
        return {
            "connections": IntegrationService(
                session, integrations, secrets
            ).list_connections(),
            "access_mode": settings.access_mode,
            "public_base_url": settings.public_base_url,
        }

    @app.get("/api/v1/integrations/connections")
    def integration_connections_v1(session: Session = Depends(session_dependency)):
        return integration_connections(session)

    @app.post("/api/integrations/connections", status_code=201)
    def create_integration_connection(
        payload: IntegrationConnectionCreate,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        if settings.access_mode == "server" and payload.provider_slug in {
            "jellyfin",
            "plex",
            "emby",
        }:
            require_admin(principal)
        return IntegrationService(session, integrations, secrets).create(**payload.model_dump())

    @app.post("/api/v1/integrations/connections", status_code=201)
    def create_integration_connection_v1(
        payload: IntegrationConnectionCreate,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        return create_integration_connection(payload, principal, session)

    @app.patch("/api/integrations/connections/{connection_id}")
    def set_integration_connection_state(
        connection_id: str,
        payload: IntegrationConnectionState,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        result = IntegrationService(session, integrations, secrets).set_enabled(
            connection_id, payload.enabled
        )
        if not payload.enabled:
            durable_jobs.cancel_scope(
                kind="integration_sync",
                scope_type="integration_connection",
                scope_id=connection_id,
            )
            return result
        interval = int((result.get("schedule") or {}).get("interval_minutes") or 0)
        capabilities = [
            name
            for name, enabled in (result.get("capabilities") or {}).items()
            if enabled not in {False, "off"} and name.startswith("pull_")
        ]
        if interval > 0:
            for capability in capabilities:
                job = durable_jobs.enqueue(
                    "integration_sync",
                    idempotency_key=f"recurring:integration:{connection_id}:{capability}",
                    due_at=utcnow(),
                    user_id=principal.user_id,
                    scope_type="integration_connection",
                    scope_id=connection_id,
                    payload={
                        "connection_id": connection_id,
                        "capability": capability,
                        "direction": "pull",
                        "user_id": principal.user_id,
                        "_repeat_seconds": interval * 60,
                    },
                )
                if job.state == "paused":
                    durable_jobs.resume(job.id)
        return result

    @app.delete("/api/integrations/connections/{connection_id}", status_code=204)
    def disconnect_integration(
        connection_id: str, session: Session = Depends(session_dependency)
    ):
        durable_jobs.cancel_scope(
            kind="integration_sync",
            scope_type="integration_connection",
            scope_id=connection_id,
        )
        IntegrationService(session, integrations, secrets).disconnect(connection_id)
        return Response(status_code=204)

    @app.post("/api/integrations/connections/{connection_id}/runs", status_code=202)
    async def run_integration(
        connection_id: str,
        payload: IntegrationRunCreate,
        principal: Principal = Depends(request_principal),
    ):
        return await integration_coordinator.run(
            connection_id,
            capability=payload.capability,
            direction=payload.direction,
            dry_run=payload.dry_run,
            user_id=principal.user_id,
        )

    @app.get("/api/integrations/connections/{connection_id}/runs")
    def integration_runs(
        connection_id: str,
        limit: int = Query(default=25, ge=1, le=100),
        session: Session = Depends(session_dependency),
    ):
        return {
            "runs": IntegrationService(session, integrations, secrets).runs(
                connection_id, limit
            )
        }

    @app.get("/api/integrations/connections/{connection_id}/events")
    def integration_events(
        connection_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(session_dependency),
    ):
        return {
            "events": IntegrationService(session, integrations, secrets).events(
                connection_id, limit
            )
        }

    @app.get("/api/v1/integrations/connections/{connection_id}/conflicts")
    def integration_conflicts(
        connection_id: str,
        limit: int = Query(default=50, ge=1, le=100),
        session: Session = Depends(session_dependency),
    ):
        return {
            "conflicts": IntegrationService(session, integrations, secrets).conflicts(
                connection_id, limit
            )
        }

    @app.post("/api/v1/integrations/connections/{connection_id}/oauth/start")
    def start_integration_oauth(
        connection_id: str,
        _payload: IntegrationOAuthStart,
        request: Request,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        base_url = settings.public_base_url or str(request.base_url).rstrip("/")
        provider = (
            IntegrationService(session, integrations, secrets, principal)
            .get(connection_id)
            .provider_slug
        )
        callback = f"{base_url}/api/v1/integrations/oauth/{provider}/callback"
        return IntegrationAuthorizationService(session, integrations, secrets, principal).start(
            connection_id, redirect_uri=callback
        )

    @app.get("/api/v1/integrations/oauth/{provider}/callback")
    async def complete_integration_oauth(
        provider: str,
        state: str = Query(min_length=20, max_length=500),
        code: str = Query(min_length=1, max_length=4_000),
        session: Session = Depends(session_dependency),
    ):
        result = await IntegrationAuthorizationService(session, integrations, secrets).callback(
            provider, state=state, code=code
        )
        return {
            **result,
            "message": "Provider authorization completed. You can return to PMT.",
        }

    @app.get("/api/v1/integrations/connections/{connection_id}/authorization")
    def integration_authorization_status(
        connection_id: str,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        return IntegrationAuthorizationService(
            session, integrations, secrets, principal
        ).status(connection_id)

    @app.get("/api/v1/integrations/connections/{connection_id}/bindings")
    def integration_bindings(
        connection_id: str,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        return {
            "bindings": PlaybackIntegrationService(session, principal).bindings(connection_id)
        }

    @app.post("/api/v1/integrations/connections/{connection_id}/bindings", status_code=201)
    def create_integration_binding(
        connection_id: str,
        payload: IntegrationUserBindingCreate,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        return PlaybackIntegrationService(session, principal).bind(
            connection_id, **payload.model_dump()
        )

    @app.post("/api/v1/integrations/connections/{connection_id}/webhook-credential")
    def create_integration_webhook(
        connection_id: str,
        request: Request,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        base_url = settings.public_base_url or str(request.base_url).rstrip("/")
        return PlaybackIntegrationService(session, principal).issue_webhook(
            connection_id, base_url=base_url
        )

    @app.post("/api/v1/webhooks/{provider}/{public_id}")
    async def receive_playback_webhook(
        provider: Literal["jellyfin", "plex", "emby"],
        public_id: str,
        request: Request,
        session: Session = Depends(session_dependency),
    ):
        token = request.headers.get("x-pmt-webhook-token", "")
        if provider in {"plex", "emby"} and not token:
            token = request.query_params.get("token", "")
        authenticated = authenticate_webhook(
            session, provider=provider, public_id=public_id, token=token
        )
        if authenticated is None:
            raise HTTPException(401, "Webhook credential is invalid or revoked.")
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > 1_048_576:
            raise HTTPException(413, "Webhook payload is too large.")
        _credential, connection = authenticated
        if provider == "plex" and "multipart/form-data" in request.headers.get(
            "content-type", ""
        ):
            form = await request.form()
            raw_payload = form.get("payload")
            if not isinstance(raw_payload, str):
                raise HTTPException(422, "Plex webhook payload is missing.")
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, "Plex webhook payload is invalid.") from exc
        else:
            try:
                payload = await request.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(422, "Webhook payload is invalid.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(422, "Webhook payload must be an object.")
        return ingest_playback(session, integration_coordinator, connection, payload)

    @app.get("/api/metadata/enrichment", response_model=MetadataEnrichmentStatus)
    def metadata_enrichment_status(
        request: Request, principal: Principal = Depends(request_principal)
    ):
        return request.app.state.enrichment.status(principal.user_id)

    @app.get("/api/metadata/providers")
    def metadata_provider_catalog(
        principal: Principal = Depends(request_principal),
    ):
        """Expose capabilities without leaking credentials or provider cache data."""
        return {"providers": effective_metadata(principal).provider_catalog()}

    @app.post(
        "/api/metadata/enrichment",
        response_model=MetadataEnrichmentStatus,
        status_code=202,
    )
    async def start_metadata_enrichment(
        payload: MetadataEnrichmentStart,
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        return request.app.state.enrichment.start(
            payload.limit,
            user_id=principal.user_id,
            metadata=effective_metadata(principal, request.app.state.enrichment.metadata),
        )

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

    @app.get("/api/ratings/rubric")
    def rating_rubric(
        version: str | None = Query(default=None, max_length=40),
        session: Session = Depends(session_dependency),
    ):
        return {
            **rubric_contract(version or RUBRIC_VERSION),
            "advanced_ratings_enabled": advanced_ratings_enabled(session),
        }

    @app.post("/api/ratings/assessments", status_code=201)
    def create_rating_assessment(
        payload: RatingAssessmentCreate,
        session: Session = Depends(session_dependency),
    ):
        return RatingAssessmentService(
            session, enabled=advanced_ratings_enabled(session)
        ).create(payload)

    @app.get("/api/ratings/assessments/{assessment_id}")
    def get_rating_assessment(
        assessment_id: str, session: Session = Depends(session_dependency)
    ):
        # Read access remains available while the feature is off so drafts/history can
        # be retained, inspected and exported without enabling mutations.
        return RatingAssessmentService(session, enabled=True).get(assessment_id)

    @app.patch("/api/ratings/assessments/{assessment_id}")
    def patch_rating_assessment(
        assessment_id: str,
        payload: RatingAssessmentPatch,
        session: Session = Depends(session_dependency),
    ):
        return RatingAssessmentService(
            session, enabled=advanced_ratings_enabled(session)
        ).patch(assessment_id, payload)

    @app.post("/api/ratings/assessments/{assessment_id}/complete")
    def complete_rating_assessment(
        assessment_id: str,
        payload: RatingAssessmentComplete,
        session: Session = Depends(session_dependency),
    ):
        return RatingAssessmentService(
            session, enabled=advanced_ratings_enabled(session)
        ).complete(assessment_id, payload)

    @app.delete("/api/ratings/assessments/{assessment_id}", status_code=204)
    def discard_rating_assessment(
        assessment_id: str, session: Session = Depends(session_dependency)
    ):
        RatingAssessmentService(session, enabled=advanced_ratings_enabled(session)).discard(
            assessment_id
        )

    @app.get("/api/ratings/comparisons/next")
    def next_rating_comparison(
        cross_media: bool = False,
        session_size: Annotated[int, Query(ge=1, le=10)] = 5,
        refinement_run_id: Annotated[str | None, Query(min_length=36, max_length=36)] = None,
        session: Session = Depends(session_dependency),
    ):
        return RatingComparisonService(session, enabled=advanced_ratings_enabled(session)).next(
            cross_media=cross_media,
            session_size=session_size,
            refinement_run_id=refinement_run_id,
        )

    @app.put("/api/ratings/comparisons/{pair_key}")
    def update_rating_comparison(
        pair_key: str,
        payload: RatingComparisonUpdate,
        session: Session = Depends(session_dependency),
    ):
        return RatingComparisonService(session, enabled=advanced_ratings_enabled(session)).put(
            pair_key, payload
        )

    @app.delete("/api/ratings/comparisons/{pair_key}", status_code=204)
    def undo_rating_comparison(pair_key: str, session: Session = Depends(session_dependency)):
        RatingComparisonService(session, enabled=advanced_ratings_enabled(session)).delete(
            pair_key
        )

    @app.get("/api/ratings/refinement-runs/active")
    def active_rating_refinement(session: Session = Depends(session_dependency)):
        return {
            "run": RatingRefinementService(
                session, enabled=advanced_ratings_enabled(session)
            ).active()
        }

    @app.post("/api/ratings/refinement-runs", status_code=201)
    def start_rating_refinement(
        payload: RatingRefinementStart,
        session: Session = Depends(session_dependency),
    ):
        return RatingRefinementService(
            session, enabled=advanced_ratings_enabled(session)
        ).start(payload.scope, entry_id=payload.entry_id)

    @app.get("/api/ratings/refinement-runs/{run_id}")
    def get_rating_refinement(run_id: str, session: Session = Depends(session_dependency)):
        return RatingRefinementService(session, enabled=True).get(run_id)

    @app.post("/api/ratings/refinement-runs/{run_id}/finish-comparisons")
    def finish_refinement_comparisons(
        run_id: str, session: Session = Depends(session_dependency)
    ):
        return RatingRefinementService(
            session, enabled=advanced_ratings_enabled(session)
        ).finish_comparisons_early(run_id)

    @app.post("/api/ratings/refinement-runs/{run_id}/finish-early")
    def finish_rating_refinement_early(
        run_id: str,
        session: Session = Depends(session_dependency),
    ):
        return RatingRefinementService(
            session, enabled=advanced_ratings_enabled(session)
        ).finish_early(run_id)

    @app.post("/api/ratings/refinement-runs/{run_id}/undo-comparison")
    def undo_refinement_comparison(run_id: str, session: Session = Depends(session_dependency)):
        return RatingRefinementService(
            session, enabled=advanced_ratings_enabled(session)
        ).undo_last_comparison(run_id)

    @app.post("/api/ratings/refinement-runs/{run_id}/skip-entry")
    def skip_refinement_entry(
        run_id: str,
        payload: RatingRefinementEntryUpdate,
        session: Session = Depends(session_dependency),
    ):
        return RatingRefinementService(
            session, enabled=advanced_ratings_enabled(session)
        ).skip_assessment(run_id, payload.entry_id)

    @app.delete("/api/ratings/refinement-runs/{run_id}")
    def cancel_rating_refinement(run_id: str, session: Session = Depends(session_dependency)):
        return RatingRefinementService(
            session, enabled=advanced_ratings_enabled(session)
        ).cancel(run_id)

    @app.get("/api/rankings")
    def rankings(
        mode: Literal["personal", "technical"] | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 48,
        show_all: bool = False,
        media_type: Literal["movie", "tv", "anime"] | None = None,
        status: Literal["watched", "watching", "plan_to_watch", "dropped", "rewatching"]
        | None = None,
        genre: Annotated[str | None, Query(max_length=100)] = None,
        year_min: Annotated[int | None, Query(ge=1878, le=2200)] = None,
        year_max: Annotated[int | None, Query(ge=1878, le=2200)] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        session: Session = Depends(session_dependency),
    ):
        enabled = advanced_ratings_enabled(session)
        advanced = enabled and mode != "personal"
        if mode == "technical" and not enabled:
            raise RatingFeatureDisabled(
                "Technical rankings require Advanced ratings in Settings."
            )
        return AdvancedRankingService(session).rankings(
            advanced=advanced,
            page=page,
            page_size=page_size,
            show_all=show_all,
            media_type=media_type,
            status=status,
            genre=genre,
            year_min=year_min,
            year_max=year_max,
            q=q,
        )

    @app.put("/api/series/{entry_id}/subscription")
    def follow_series(
        entry_id: str,
        payload: SeriesFollowUpdate,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).follow(
            entry_id,
            notify_new_episode=payload.notify_new_episode,
            notify_new_season=payload.notify_new_season,
            include_specials=payload.include_specials,
            region=settings.region,
        )

    @app.delete("/api/series/{entry_id}/subscription", status_code=204)
    def unfollow_series(entry_id: str, session: Session = Depends(session_dependency)):
        ReleaseTrackingService(session, today=_today(settings)).unfollow(entry_id)

    @app.get("/api/series/{entry_id}")
    def series_detail(entry_id: str, session: Session = Depends(session_dependency)):
        return ReleaseTrackingService(session, today=_today(settings)).detail(entry_id)

    @app.post("/api/series/{entry_id}/sync")
    async def sync_series(
        entry_id: str,
        request: Request,
        principal: Principal = Depends(request_principal),
    ):
        return await request.app.state.release_sync.sync_entry(
            entry_id, refresh=True, user_id=principal.user_id
        )

    @app.put("/api/episodes/{episode_id}/viewing")
    def mark_episode_watched(
        episode_id: str,
        payload: EpisodeViewingCreate,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).mark_episode(
            episode_id, watched_on=payload.watched_on
        )

    @app.delete("/api/episodes/{episode_id}/viewing")
    def mark_episode_unwatched(episode_id: str, session: Session = Depends(session_dependency)):
        return ReleaseTrackingService(session, today=_today(settings)).unmark_episode(
            episode_id
        )

    @app.put("/api/seasons/{season_id}/viewing")
    def bulk_season_viewing(
        season_id: str,
        payload: SeasonBulkUpdate,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).bulk_season(
            season_id, watched=payload.watched, watched_on=payload.watched_on
        )

    @app.get("/api/releases/currently-watching")
    def release_currently_watching(session: Session = Depends(session_dependency)):
        return ReleaseTrackingService(session, today=_today(settings)).currently_watching()

    @app.get("/api/releases/active-shows")
    def active_release_shows(
        days: Annotated[int, Query(ge=1, le=180)] = 60,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).active_shows(days=days)

    @app.get("/api/releases/upcoming")
    def upcoming_releases(
        days: Annotated[int, Query(ge=1, le=366)] = 90,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).upcoming(days=days)

    @app.get("/api/releases/notifications")
    def release_notifications(
        include_dismissed: bool = False,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).notifications(
            include_dismissed=include_dismissed
        )

    @app.patch("/api/releases/notifications/{event_id}")
    def update_release_notification(
        event_id: str,
        payload: ReleaseEventUpdate,
        session: Session = Depends(session_dependency),
    ):
        return ReleaseTrackingService(session, today=_today(settings)).update_notification(
            event_id, payload.action
        )

    @app.get("/api/releases/sync")
    def release_sync_status(
        request: Request, principal: Principal = Depends(request_principal)
    ):
        return {
            **request.app.state.release_scheduler.status(),
            "mode": preferences.load(principal.user_id).get("release_check_mode"),
        }

    @app.post("/api/releases/sync")
    async def sync_all_releases(
        request: Request, principal: Principal = Depends(request_principal)
    ):
        return await request.app.state.release_scheduler.run_once(
            full_library=True, user_id=principal.user_id
        )

    @app.get("/api/exports/upcoming-releases.ics")
    def upcoming_icalendar(session: Session = Depends(session_dependency)):
        items = ReleaseTrackingService(session, today=_today(settings)).upcoming(days=366)[
            "items"
        ]
        filename = f"personal-media-tracker-upcoming-{_today(settings).isoformat()}.ics"
        return PlainTextResponse(
            ical_snapshot(items),
            media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/exports/upcoming-releases/feed", status_code=201)
    def create_upcoming_feed(
        principal: Principal = Depends(request_principal),
    ):
        if settings.access_mode != "server" or not settings.public_base_url:
            raise HTTPException(
                409, "A subscription feed is available only in authenticated server mode."
            )
        token = auth.issue_calendar_feed(principal.user_id)
        return {
            "feed_url": f"{settings.public_base_url.rstrip('/')}/feeds/upcoming.ics?token={token}",
            "shown_once": True,
            "contains": "followed-series titles and provider air dates only",
        }

    @app.delete("/api/exports/upcoming-releases/feed")
    def revoke_upcoming_feeds(
        principal: Principal = Depends(request_principal),
    ):
        return {"revoked": auth.revoke_calendar_feeds(principal.user_id)}

    @app.get("/feeds/upcoming.ics", include_in_schema=False)
    def public_upcoming_feed(
        token: Annotated[str | None, Query(min_length=32, max_length=200)] = None,
        session: Session = Depends(session_dependency),
    ):
        user_id = auth.validate_calendar_feed(token)
        if settings.access_mode != "server" or not user_id:
            raise HTTPException(404, "Calendar feed not found.")
        items = ReleaseTrackingService(
            session, today=_today(settings), trusted_user_id=user_id
        ).upcoming(days=366)["items"]
        return PlainTextResponse(
            ical_snapshot(items),
            media_type="text/calendar; charset=utf-8",
            headers={"Cache-Control": "private, no-cache", "X-Robots-Tag": "noindex"},
        )

    @app.post("/api/entries/from-search", response_model=EntryMutationResponse)
    async def add_from_search(
        payload: FromSearchRequest,
        request: Request,
        session: Session = Depends(session_dependency),
        principal: Principal = Depends(request_principal),
    ):
        catalog = await effective_metadata(principal).detail(payload.result)
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
            trusted_metadata=True,
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
        status: Literal[
            "watched",
            "watching",
            "plan_to_watch",
            "dropped",
            "rewatching",
            "active",
        ]
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

    @app.get("/api/v1/entries/{entry_id}", response_model=EntryOut)
    def versioned_get_entry(entry_id: str, session: Session = Depends(session_dependency)):
        return EntryService(session, today=_today(settings)).get(entry_id)

    @app.get("/api/v1/sync/snapshot", response_model=PaginatedEntries)
    def sync_snapshot(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 100,
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).list(
            page=page,
            page_size=page_size,
            sort="recently_added",
            direction="asc",
            media_type=None,
            status=None,
            genre=None,
            year_min=None,
            year_max=None,
            rating_min=None,
            rating_max=None,
            rated="all",
            q=None,
            include_deleted=True,
        )

    @app.post("/api/v1/sync/push")
    def sync_push(
        payload: SyncPushRequest,
        request: Request,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        authenticated_session = getattr(request.state, "user_session", None)
        if (
            authenticated_session is not None
            and authenticated_session.session_kind == "native"
            and authenticated_session.device_id != payload.device_id
        ):
            raise HTTPException(409, "The sync device ID does not match this session.")
        service = SyncService(session, today=_today(settings), principal=principal)
        results = [service.apply(payload.device_id, item) for item in payload.mutations]
        return {
            "results": results,
            "applied": sum(item["status"] == "applied" for item in results),
            "conflicts": sum(item["status"] == "conflict" for item in results),
        }

    @app.get("/api/v1/sync/pull")
    def sync_pull(
        cursor: Annotated[str | None, Query(max_length=200)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        principal: Principal = Depends(request_principal),
        session: Session = Depends(session_dependency),
    ):
        try:
            return SyncService(session, today=_today(settings), principal=principal).pull(
                cursor, limit=limit
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def local_remote_client() -> RemoteDeviceClient:
        if settings.access_mode != "local" or remote_client is None:
            raise HTTPException(
                409,
                "Server connections are managed on a PMT desktop or mobile device, not by the server itself.",
            )
        return remote_client

    def remote_profile_summary(client: RemoteDeviceClient, profile) -> dict:
        rows = client.store.outbox(profile.id)
        return {
            "id": profile.id,
            "label": profile.label,
            "base_url": profile.base_url,
            "instance_id": profile.instance_id,
            "api_version": profile.api_version,
            "server_version": profile.server_version,
            "account_username": profile.account_username,
            "enabled": bool(profile.enabled),
            "device_id": profile.device_id,
            "created_at": profile.created_at,
            "last_synced_at": profile.last_synced_at,
            "pending_count": sum(row["state"] in {"pending", "failed"} for row in rows),
            "conflict_count": sum(row["state"] == "conflict" for row in rows),
            "cached_entry_count": len(client.store.cached(profile.id, "watch_entry")),
        }

    @app.get("/api/device/server-connections")
    def device_server_connections():
        client = local_remote_client()
        return {
            "authority": "embedded_local",
            "token_storage": "operating_system_keychain",
            "items": [
                remote_profile_summary(client, profile) for profile in client.store.profiles()
            ],
        }

    @app.post("/api/device/server-connections/discover")
    def discover_device_server(payload: RemoteServerDiscover):
        return local_remote_client().discover(payload.server_url)

    @app.post("/api/device/server-connections", status_code=201)
    def connect_device_server(payload: RemoteServerConnect):
        client = local_remote_client()
        profile = client.connect(
            value=payload.server_url,
            username=payload.username,
            password=payload.password,
            label=payload.label,
            device_label=payload.device_label,
        )
        return remote_profile_summary(client, profile)

    @app.post("/api/device/server-connections/enroll", status_code=201)
    def enroll_device_server(payload: RemoteServerEnroll):
        client = local_remote_client()
        profile = client.enroll(
            value=payload.server_url,
            invitation_token=payload.invitation_token,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            label=payload.label,
            device_label=payload.device_label,
        )
        return remote_profile_summary(client, profile)

    def require_native_local_request(request: Request) -> None:
        if settings.access_mode != "local":
            raise HTTPException(
                409,
                "Personal Tailscale access belongs to a local library, not PMT Server.",
            )
        if not settings.native_actions or not getattr(
            request.state, "native_desktop_loopback", False
        ):
            raise HTTPException(
                409,
                "Set up personal Tailscale access from the installed PMT application.",
            )

    def personal_tailscale_payload(*, port: int) -> dict[str, Any]:
        snapshot = TailscaleAccessManager().snapshot(port=port)
        return {
            "supported": supports_managed_tailscale(),
            "installed": snapshot.installed,
            "connected": snapshot.connected,
            "enabled": settings.personal_tailscale_enabled,
            "access_url": settings.personal_tailscale_url or snapshot.access_url,
            "route_active": snapshot.route_active,
            "route_conflict": snapshot.route_conflict,
            "account_required": False,
            "scope": "one_private_local_library",
        }

    @app.get("/api/device/personal-tailscale")
    def personal_tailscale_status(request: Request):
        if settings.access_mode != "local":
            return {
                "supported": False,
                "installed": False,
                "connected": False,
                "enabled": False,
                "access_url": None,
                "route_active": False,
                "route_conflict": False,
                "account_required": False,
                "scope": "standalone_server",
            }
        current_port = request.url.port or settings.port or 8000
        return {
            **personal_tailscale_payload(port=current_port),
            "manageable": bool(
                settings.native_actions
                and getattr(request.state, "native_desktop_loopback", False)
            ),
        }

    @app.post("/api/device/personal-tailscale/enable")
    def enable_personal_tailscale(request: Request):
        require_native_local_request(request)
        current_port = request.url.port or settings.port or 8000
        manager = TailscaleAccessManager()
        snapshot = manager.ensure_route(port=current_port)
        if not snapshot.access_url:
            raise HTTPException(409, "Tailscale did not provide a private HTTPS address.")
        persist_env_values(
            settings.resolved_env_path,
            {
                "WATCHTRACKER_PERSONAL_TAILSCALE_ENABLED": "true",
                "WATCHTRACKER_PERSONAL_TAILSCALE_URL": snapshot.access_url,
                "WATCHTRACKER_PERSONAL_TAILSCALE_TARGET_PORT": str(current_port),
                # Future launches stay on a stable proxy target. The current launch
                # is already routed to its actual bound port above.
                "WATCHTRACKER_PORT": "8000",
            },
        )
        settings.personal_tailscale_enabled = True
        settings.personal_tailscale_url = snapshot.access_url
        settings.personal_tailscale_target_port = current_port
        return {
            **personal_tailscale_payload(port=current_port),
            "manageable": True,
            "restart_required": current_port != 8000,
        }

    @app.post("/api/device/personal-tailscale/disable")
    def disable_personal_tailscale(request: Request):
        require_native_local_request(request)
        current_port = request.url.port or settings.port or 8000
        TailscaleAccessManager().remove_managed_route(port=current_port)
        persist_env_values(
            settings.resolved_env_path,
            {
                "WATCHTRACKER_PERSONAL_TAILSCALE_ENABLED": None,
                "WATCHTRACKER_PERSONAL_TAILSCALE_URL": None,
                "WATCHTRACKER_PERSONAL_TAILSCALE_TARGET_PORT": None,
            },
        )
        settings.personal_tailscale_enabled = False
        settings.personal_tailscale_url = None
        settings.personal_tailscale_target_port = None
        return {"enabled": False, "route_active": False, "restart_required": False}

    @app.post("/api/device/server-connections/sync-enabled")
    def sync_enabled_device_server():
        client = local_remote_client()
        results = []
        for profile in client.store.enabled_profiles():
            try:
                results.append({"ok": True, **client.sync(profile.id)})
            except RemoteClientError as exc:
                results.append({"ok": False, "profile_id": profile.id, "message": str(exc)})
        return {"items": results}

    @app.patch("/api/device/server-connections/{profile_id}")
    def set_device_server_state(profile_id: str, payload: RemoteServerConnectionState):
        client = local_remote_client()
        profile = client.store.set_enabled(profile_id, payload.enabled)
        return remote_profile_summary(client, profile)

    @app.get("/api/device/server-connections/{profile_id}/cache")
    def device_server_cache(profile_id: str):
        client = local_remote_client()
        client.store.get_profile(profile_id)
        return {
            "items": client.store.cached(profile_id, "watch_entry"),
            "offline": True,
            "read_only": True,
        }

    @app.get("/api/device/server-connections/{profile_id}/outbox")
    def device_server_outbox(profile_id: str):
        client = local_remote_client()
        client.store.get_profile(profile_id)
        return {"items": client.store.outbox(profile_id)}

    @app.post("/api/device/server-connections/{profile_id}/outbox", status_code=202)
    def queue_device_server_edit(profile_id: str, payload: RemoteOfflineMutation):
        client = local_remote_client()
        client.store.get_profile(profile_id)
        request_id = client.store.enqueue(
            profile_id,
            operation=payload.operation,
            resource_type=(
                "watch_entry" if payload.operation == "entry.patch" else "media_list"
            ),
            resource_id=payload.resource_id,
            base_version=payload.base_version,
            payload=payload.payload,
        )
        return {"request_id": request_id, "state": "pending", "safe_offline": True}

    @app.post("/api/device/server-connections/{profile_id}/sync")
    def sync_device_server(profile_id: str):
        return local_remote_client().sync(profile_id)

    @app.post("/api/device/server-connections/{profile_id}/browser-session")
    def open_device_server_account(profile_id: str):
        profile, handoff = local_remote_client().browser_handoff(profile_id)
        return {
            "server_url": profile.base_url,
            "handoff_token": handoff,
        }

    @app.post("/api/device/server-connections/{profile_id}/conflicts/{request_id}")
    def resolve_device_server_conflict(
        profile_id: str,
        request_id: str,
        payload: RemoteConflictResolution,
    ):
        store = local_remote_client().store
        store.get_profile(profile_id)
        if payload.action == "discard":
            store.discard(profile_id, request_id)
            return {"state": "discarded"}
        replacement_id = store.rebase(profile_id, request_id)
        return {"state": "pending", "request_id": replacement_id}

    @app.delete("/api/device/server-connections/{profile_id}", status_code=204)
    def disconnect_device_server(profile_id: str):
        local_remote_client().disconnect(profile_id)
        return Response(status_code=204)

    @app.get("/api/entries/{entry_id}/artwork", response_model=ArtworkOptionsOut)
    async def entry_artwork_options(
        entry_id: str,
        request: Request,
        session: Session = Depends(session_dependency),
        principal: Principal = Depends(request_principal),
    ):
        entry = EntryService(session, today=_today(settings)).get(entry_id)
        catalog = entry.catalog_item
        scoped_metadata = effective_metadata(principal)
        identity = scoped_metadata.preferred_identity(
            catalog.external_ids,
            capability="artwork",
            primary=(catalog.provider_source, catalog.provider_id),
        )
        provider, provider_id = identity or (None, None)

        options: list[ArtworkOption] = []
        seen: set[str] = set()
        if catalog.poster_url:
            options.append(ArtworkOption(poster_url=catalog.poster_url, is_default=True))
            seen.add(catalog.poster_url)
        supported = bool(provider and provider_id)
        warning = None
        if supported:
            try:
                rows = await scoped_metadata.artwork_options(provider, provider_id)
                for row in rows:
                    option = ArtworkOption.model_validate(row)
                    if option.poster_url not in seen:
                        options.append(option)
                        seen.add(option.poster_url)
            except ProviderUnavailable as exc:
                warning = f"Alternative images could not be refreshed. {exc}"
        return ArtworkOptionsOut(
            supported=supported,
            provider=provider,
            default_url=catalog.poster_url,
            selected_url=catalog.poster_override_url or catalog.poster_url,
            options=options,
            warning=warning,
        )

    @app.put("/api/entries/{entry_id}/artwork", response_model=EntryOut)
    async def select_entry_artwork(
        entry_id: str,
        payload: ArtworkSelection,
        request: Request,
        session: Session = Depends(session_dependency),
        principal: Principal = Depends(request_principal),
    ):
        service = EntryService(session, today=_today(settings))
        entry = service.get(entry_id)
        if payload.poster_url is None:
            return service.set_poster_override(entry_id, None)

        catalog = entry.catalog_item
        allowed = {catalog.poster_url} if catalog.poster_url else set()
        scoped_metadata = effective_metadata(principal)
        identity = scoped_metadata.preferred_identity(
            catalog.external_ids,
            capability="artwork",
            primary=(catalog.provider_source, catalog.provider_id),
        )
        provider, provider_id = identity or (None, None)
        if payload.poster_url not in allowed and provider and provider_id:
            rows = await scoped_metadata.artwork_options(provider, provider_id)
            allowed.update(row.get("poster_url") for row in rows)
        if payload.poster_url not in allowed:
            raise HTTPException(422, "Select an image supplied for this title.")
        return service.set_poster_override(entry_id, payload.poster_url)

    @app.get("/api/lists", response_model=list[MediaListOut])
    def media_lists(
        sort: Literal["name", "created_at", "updated_at"] = "created_at",
        direction: Literal["asc", "desc"] = "asc",
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).list_all(sort=sort, direction=direction)

    @app.get("/api/v1/lists", response_model=list[MediaListOut])
    def versioned_media_lists(
        sort: Literal["name", "created_at", "updated_at"] = "created_at",
        direction: Literal["asc", "desc"] = "asc",
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).list_all(sort=sort, direction=direction)

    @app.post("/api/lists", response_model=MediaListOut, status_code=201)
    def create_media_list(
        payload: MediaListCreate, session: Session = Depends(session_dependency)
    ):
        return MediaListService(session).create(payload.name)

    @app.post(
        "/api/lists/import",
        response_model=PortableListImportOut,
        status_code=201,
    )
    async def import_portable_list(
        file: UploadFile = File(...),
        session: Session = Depends(session_dependency),
    ):
        limit = min(settings.upload_limit_mb * 1024 * 1024, 4 * 1024 * 1024)
        content = await file.read(limit + 1)
        if len(content) > limit:
            return _error(413, "payload_too_large", "Shared-list file exceeds 4 MB.")
        if not content:
            raise HTTPException(422, "The shared-list file is empty.")
        try:
            document = PortableListDocument.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                422,
                "This is not a supported PMT shared-list file.",
            ) from exc
        return MediaListService(session).import_portable(document)

    @app.get("/api/lists/{list_id}", response_model=MediaListOut)
    def media_list_detail(list_id: str, session: Session = Depends(session_dependency)):
        return MediaListService(session).get(list_id)

    @app.get("/api/exports/lists/{list_id}.pmt-list.json")
    def export_portable_list(
        list_id: str,
        session: Session = Depends(session_dependency),
    ):
        document = MediaListService(session).export_portable(list_id)
        filename = f"pmt-shared-list-{_today(settings).isoformat()}.json"
        content = json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/lists/{list_id}", response_model=MediaListOut)
    def versioned_media_list_detail(
        list_id: str, session: Session = Depends(session_dependency)
    ):
        return MediaListService(session).get(list_id)

    @app.patch("/api/lists/{list_id}", response_model=MediaListOut)
    def update_media_list(
        list_id: str,
        payload: MediaListPatch,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).update(
            list_id,
            pinned=payload.pinned_to_navigation,
            name=payload.name,
        )

    @app.delete("/api/lists/{list_id}", status_code=204)
    def delete_media_list(list_id: str, session: Session = Depends(session_dependency)):
        MediaListService(session).delete(list_id)
        return Response(status_code=204)

    @app.post("/api/lists/{list_id}/entries/{entry_id}", response_model=MediaListOut)
    def add_media_list_entry(
        list_id: str,
        entry_id: str,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).add_entry(list_id, entry_id)

    @app.delete("/api/lists/{list_id}/entries/{entry_id}", response_model=MediaListOut)
    def remove_media_list_entry(
        list_id: str,
        entry_id: str,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).remove_entry(list_id, entry_id)

    @app.post(
        "/api/v1/lists/{list_id}/items/{catalog_item_id}",
        response_model=MediaListOut,
    )
    def add_shared_list_item(
        list_id: str,
        catalog_item_id: str,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).add_catalog_item(list_id, catalog_item_id)

    @app.post(
        "/api/v1/catalog/{catalog_item_id}/library",
        response_model=EntryMutationResponse,
        status_code=201,
    )
    def add_shared_catalog_title_to_library(
        catalog_item_id: str,
        payload: CatalogLibraryAdd = Body(default_factory=CatalogLibraryAdd),
        session: Session = Depends(session_dependency),
    ):
        return EntryService(session, today=_today(settings)).add_existing_catalog(
            catalog_item_id,
            options=payload,
            if_existing=payload.if_existing,
        )

    @app.delete(
        "/api/v1/lists/{list_id}/items/{catalog_item_id}",
        response_model=MediaListOut,
    )
    def remove_shared_list_item(
        list_id: str,
        catalog_item_id: str,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).remove_catalog_item(list_id, catalog_item_id)

    @app.post("/api/v1/lists/{list_id}/members", response_model=MediaListOut)
    def add_shared_list_member(
        list_id: str,
        payload: MediaListMemberAdd,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).add_member(list_id, payload.username, payload.role)

    @app.patch(
        "/api/v1/lists/{list_id}/members/{member_user_id}",
        response_model=MediaListOut,
    )
    def update_shared_list_member(
        list_id: str,
        member_user_id: str,
        payload: MediaListMemberUpdate,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).update_member(list_id, member_user_id, payload.role)

    @app.delete(
        "/api/v1/lists/{list_id}/members/{member_user_id}",
        response_model=MediaListOut,
    )
    def remove_shared_list_member(
        list_id: str,
        member_user_id: str,
        session: Session = Depends(session_dependency),
    ):
        return MediaListService(session).remove_member(list_id, member_user_id)

    @app.get("/api/v1/lists/{list_id}/activity")
    def shared_list_activity(
        list_id: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        session: Session = Depends(session_dependency),
    ):
        return {"items": MediaListService(session).activity(list_id, limit=limit)}

    @app.get("/api/v1/notifications")
    def user_notifications(
        unread_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        session: Session = Depends(session_dependency),
    ):
        return NotificationService(session, secrets, adapters=notification_adapters).inbox(
            unread_only=unread_only, limit=limit
        )

    @app.patch("/api/v1/notifications/{source_kind}/{notification_id}")
    def update_unified_notification(
        source_kind: Literal["inbox", "release"],
        notification_id: str,
        action: Literal["read", "unread", "dismiss"] = Body(embed=True),
        session: Session = Depends(session_dependency),
    ):
        return NotificationService(
            session, secrets, adapters=notification_adapters
        ).update_inbox(source_kind, notification_id, action)

    @app.patch("/api/v1/notifications/{notification_id}")
    def update_user_notification(
        notification_id: str,
        action: Literal["read", "unread", "dismiss"] = Body(embed=True),
        session: Session = Depends(session_dependency),
    ):
        return NotificationService(
            session, secrets, adapters=notification_adapters
        ).update_inbox("inbox", notification_id, action)

    @app.get("/api/v1/notification-settings")
    def notification_settings(session: Session = Depends(session_dependency)):
        result = NotificationService(
            session, secrets, adapters=notification_adapters
        ).settings()
        result["managed_apprise_api_available"] = settings.managed_apprise_api_available
        return result

    @app.put("/api/v1/notification-settings")
    def update_notification_settings(
        payload: NotificationSettingsUpdate,
        session: Session = Depends(session_dependency),
    ):
        service = NotificationService(session, secrets, adapters=notification_adapters)
        return {"rules": service.replace_rules([row.model_dump() for row in payload.rules])}

    @app.post("/api/v1/notification-endpoints", status_code=201)
    def create_notification_endpoint(
        payload: NotificationEndpointCreate,
        session: Session = Depends(session_dependency),
    ):
        return NotificationService(
            session, secrets, adapters=notification_adapters
        ).create_endpoint(
            label=payload.label,
            adapter=payload.adapter,
            destination=payload.destination,
            storage=payload.credential_storage,
        )

    @app.post("/api/v1/notification-endpoints/managed-apprise", status_code=201)
    def create_managed_apprise_endpoint(session: Session = Depends(session_dependency)):
        if not settings.managed_apprise_api_available:
            raise NotificationError("A managed Apprise API is not available in this setup.")
        return NotificationService(
            session, secrets, adapters=notification_adapters
        ).create_managed_apprise_endpoint(settings.managed_apprise_api_url or "")

    @app.patch("/api/v1/notification-endpoints/{endpoint_id}")
    def update_notification_endpoint(
        endpoint_id: str,
        payload: NotificationEndpointUpdate,
        session: Session = Depends(session_dependency),
    ):
        return NotificationService(
            session, secrets, adapters=notification_adapters
        ).update_endpoint(
            endpoint_id,
            enabled=payload.enabled,
            expected_version=payload.expected_version,
        )

    @app.delete("/api/v1/notification-endpoints/{endpoint_id}", status_code=204)
    def delete_notification_endpoint(
        endpoint_id: str,
        session: Session = Depends(session_dependency),
    ):
        NotificationService(session, secrets, adapters=notification_adapters).delete_endpoint(
            endpoint_id
        )
        return Response(status_code=204)

    @app.post("/api/v1/notification-endpoints/{endpoint_id}/test")
    async def test_notification_endpoint(
        endpoint_id: str,
        session: Session = Depends(session_dependency),
    ):
        return await NotificationService(
            session, secrets, adapters=notification_adapters
        ).test_endpoint(endpoint_id)

    @app.get("/api/v1/notification-deliveries")
    def notification_deliveries(
        state: Literal["pending", "leased", "retry", "delivered", "failed", "cancelled"]
        | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        session: Session = Depends(session_dependency),
    ):
        return {
            "items": NotificationService(
                session, secrets, adapters=notification_adapters
            ).deliveries(state=state, limit=limit)
        }

    @app.post("/api/entries/{entry_id}/metadata", response_model=EntryOut)
    async def apply_entry_metadata(
        entry_id: str,
        result: SearchResult,
        request: Request,
        session: Session = Depends(session_dependency),
        principal: Principal = Depends(request_principal),
    ):
        detail = await effective_metadata(principal).detail(result)
        return EntryService(session, today=_today(settings)).apply_metadata(
            entry_id, detail, trusted_metadata=True
        )

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

    def _insight_filters(
        *,
        period: Literal["all", "year", "90d", "30d", "custom"],
        date_from: date | None,
        date_to: date | None,
        media_type: str | None,
        genre: str | None,
        status: str | None,
        watch_kind: Literal["all", "first", "rewatch"],
        aggregation: Literal["auto", "week", "month", "year"],
    ) -> InsightFilters:
        return InsightFilters(
            period=period,
            date_from=date_from,
            date_to=date_to,
            media_type=media_type,
            genre=genre.strip() if genre and genre.strip() else None,
            status=status,
            watch_kind=watch_kind,
            aggregation=aggregation,
        )

    @app.get("/api/insights")
    def insights(
        period: Literal["all", "year", "90d", "30d", "custom"] = "year",
        date_from: date | None = None,
        date_to: date | None = None,
        media_type: Literal["movie", "tv", "anime"] | None = None,
        genre: Annotated[str | None, Query(max_length=100)] = None,
        status: Literal["watched", "watching", "plan_to_watch", "dropped", "rewatching"]
        | None = None,
        watch_kind: Literal["all", "first", "rewatch"] = "all",
        aggregation: Literal["auto", "week", "month", "year"] = "auto",
        session: Session = Depends(session_dependency),
    ):
        filters = _insight_filters(
            period=period,
            date_from=date_from,
            date_to=date_to,
            media_type=media_type,
            genre=genre,
            status=status,
            watch_kind=watch_kind,
            aggregation=aggregation,
        )
        try:
            return calculate_insights(session, today=_today(settings), filters=filters)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/insights/titles")
    def insights_titles(
        period: Literal["all", "year", "90d", "30d", "custom"] = "year",
        date_from: date | None = None,
        date_to: date | None = None,
        media_type: Literal["movie", "tv", "anime"] | None = None,
        genre: Annotated[str | None, Query(max_length=100)] = None,
        status: Literal["watched", "watching", "plan_to_watch", "dropped", "rewatching"]
        | None = None,
        watch_kind: Literal["all", "first", "rewatch"] = "all",
        rating_bucket: Annotated[float | None, Query(ge=1, le=10)] = None,
        rating_state: Literal["rated", "unrated"] | None = None,
        activity_only: bool = False,
        release_year_from: Annotated[int | None, Query(ge=1878, le=2200)] = None,
        release_year_to: Annotated[int | None, Query(ge=1878, le=2200)] = None,
        release_year_unknown: bool = False,
        session: Session = Depends(session_dependency),
    ):
        if (
            release_year_from is not None
            and release_year_to is not None
            and release_year_from > release_year_to
        ):
            raise HTTPException(422, "release_year_from cannot exceed release_year_to")
        filters = _insight_filters(
            period=period,
            date_from=date_from,
            date_to=date_to,
            media_type=media_type,
            genre=genre,
            status=status,
            watch_kind=watch_kind,
            aggregation="auto",
        )
        try:
            return insight_titles(
                session,
                today=_today(settings),
                filters=filters,
                rating_bucket=rating_bucket,
                rating_state=rating_state,
                activity_only=activity_only,
                release_year_from=release_year_from,
                release_year_to=release_year_to,
                release_year_unknown=release_year_unknown,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/imports/preview")
    async def import_preview(
        file: UploadFile = File(...),
        import_kind: Literal[
            "auto", "csv", "manual", "canonical", "letterboxd", "obsidian"
        ] = Form("auto"),
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

    @app.get("/api/exports/obsidian-vault.zip")
    def export_obsidian_vault(session: Session = Depends(session_dependency)):
        filename = f"personal-media-tracker-obsidian-{_today(settings).isoformat()}.zip"
        return Response(
            content=obsidian_vault_zip(session, generated_on=_today(settings)),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/exports/portable-library.zip")
    def export_portable_library(
        principal: Principal = Depends(request_principal),
    ):
        require_admin(principal)
        if settings.access_mode == "server":
            raise HTTPException(
                409,
                "A server-wide disaster backup is not a personal export. Use an "
                "server-owner backup workflow instead.",
            )
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

    @app.get("/api/exports/advanced-ratings.json")
    def export_advanced_ratings(session: Session = Depends(session_dependency)):
        filename = f"advanced-ratings-private-{_today(settings).isoformat()}.json"
        return JSONResponse(
            jsonable_encoder(advanced_rating_export(session)),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/exports/recommendations.json")
    def export_recommendations(
        principal: Principal = Depends(request_principal),
    ):
        filename = f"recommendations-private-{_today(settings).isoformat()}.json"
        return JSONResponse(
            jsonable_encoder(recommendations.export(principal.user_id)),
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
