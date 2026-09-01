from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets as secure_random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.authorization import Principal, current_user_id
from watchtracker.catalog_visibility import catalog_visible_to_user
from watchtracker.integrations import (
    IntegrationEventInput,
    IntegrationPage,
    IntegrationProviderError,
    ProviderRegistry,
)
from watchtracker.metadata.http import redact_secrets
from watchtracker.models import (
    AuditEvent,
    CatalogItem,
    EpisodeRecord,
    ExternalIdentity,
    IntegrationConflict,
    IntegrationConnection,
    IntegrationCursor,
    IntegrationEvent,
    IntegrationOAuthGrant,
    IntegrationRun,
    SeasonRecord,
    WatchEntry,
    utcnow,
)
from watchtracker.notifications import NotificationEvent, NotificationService
from watchtracker.services.secrets import SecretStore
from watchtracker.services.viewing_policy import PlaybackObservation, ViewingReducer
from watchtracker.taxonomy import normalize_title

RUN_COUNTS = {"created": 0, "updated": 0, "skipped": 0, "conflicts": 0, "errors": 0}
ALLOWED_DIRECTIONS = {"pull", "push", "inbound", "outbound", "test"}
ALLOWED_TRIGGERS = {"manual", "scheduled", "webhook"}
FAILURE_PAUSE_THRESHOLD = 5
NORMALIZED_STATUSES = frozenset(
    {"plan_to_watch", "watching", "paused", "dropped", "watched", "rewatching"}
)
SAFE_CHANGE_FIELDS = frozenset(
    {
        "personal_rating",
        "status",
        "completed",
        "viewed_on",
        "started_date",
        "finished_date",
        "episode_progress_count",
        "repeat_count",
        "episode_completed",
        "season_number",
        "episode_number",
        "playback_observation",
    }
)
SAFE_SOURCE_FIELDS = frozenset(
    {
        "rating",
        "status",
        "progress",
        "repeat_count",
        "started_date",
        "finished_date",
        "viewed_on",
    }
)


def _integration_catalog_visible(
    session: Session, *, user_id: str, catalog: CatalogItem
) -> bool:
    # A soft-deleted entry is deliberately invisible to generic catalog actions,
    # but integrations must still see that same user's tombstone so a remote pull
    # cannot silently recreate it. Another tenant's tombstone remains invisible.
    return catalog_visible_to_user(session, user_id=user_id, catalog_item=catalog) or bool(
        session.scalar(
            select(WatchEntry.id).where(
                WatchEntry.user_id == user_id,
                WatchEntry.catalog_item_id == catalog.id,
            )
        )
    )


class IntegrationError(RuntimeError):
    pass


class IntegrationNotFound(IntegrationError):
    pass


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.isoformat()


def _bounded_text(value: str, limit: int = 300) -> str:
    return " ".join(value.split())[:limit]


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_source_values(values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key not in SAFE_SOURCE_FIELDS or isinstance(value, (dict, list)):
            continue
        if (
            value is None
            or isinstance(value, (bool, int))
            or isinstance(value, float)
            and math.isfinite(value)
        ):
            result[key] = value
        elif isinstance(value, str):
            result[key] = _bounded_text(value, 120)
    return result


def serialize_connection(connection: IntegrationConnection, *, state: str) -> dict[str, Any]:
    return {
        "id": connection.id,
        "provider_slug": connection.provider_slug,
        "label": connection.label,
        "enabled": connection.enabled,
        "configuration": connection.configuration,
        "remote_profile": connection.remote_profile,
        "capabilities": connection.capabilities,
        "schedule": connection.schedule,
        "has_credentials": bool(connection.secret_reference),
        "credential_storage": connection.credential_storage,
        "failure_count": connection.failure_count,
        "paused_reason": connection.paused_reason,
        "last_attempt_at": _iso(connection.last_attempt_at),
        "last_success_at": _iso(connection.last_success_at),
        "next_run_at": _iso(connection.next_run_at),
        "created_at": _iso(connection.created_at),
        "updated_at": _iso(connection.updated_at),
        "state": state,
    }


def serialize_run(run: IntegrationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "connection_id": run.connection_id,
        "trigger": run.trigger,
        "direction": run.direction,
        "capability": run.capability,
        "state": run.state,
        "dry_run": run.dry_run,
        "counts": {**RUN_COUNTS, **(run.counts or {})},
        "error_code": run.error_code,
        "error_message": run.error_message,
        "retry_after_seconds": run.retry_after_seconds,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
    }


class IntegrationService:
    def __init__(
        self,
        session: Session,
        registry: ProviderRegistry,
        secrets: SecretStore,
        principal: Principal | None = None,
    ):
        self.session = session
        self.registry = registry
        self.secrets = secrets
        self.user_id = current_user_id(session, principal)

    def catalog(self) -> list[dict[str, Any]]:
        connected = {
            slug: count
            for slug, count in self.session.execute(
                select(IntegrationConnection.provider_slug, IntegrationConnection.id)
                .where(IntegrationConnection.user_id == self.user_id)
                .order_by(IntegrationConnection.provider_slug)
            ).all()
        }
        result = self.registry.catalog()
        for provider in result:
            provider["configured"] = provider["slug"] in connected
        return result

    def list_connections(self) -> list[dict[str, Any]]:
        active = set(
            self.session.scalars(
                select(IntegrationRun.connection_id)
                .join(
                    IntegrationConnection,
                    IntegrationRun.connection_id == IntegrationConnection.id,
                )
                .where(
                    IntegrationConnection.user_id == self.user_id,
                    IntegrationRun.state == "running",
                )
            )
        )
        connections = self.session.scalars(
            select(IntegrationConnection)
            .where(IntegrationConnection.user_id == self.user_id)
            .order_by(IntegrationConnection.provider_slug, IntegrationConnection.created_at)
        ).all()
        values: list[dict[str, Any]] = []
        for connection in connections:
            value = serialize_connection(connection, state=self._state(connection, active))
            grant = self.session.scalar(
                select(IntegrationOAuthGrant).where(
                    IntegrationOAuthGrant.connection_id == connection.id
                )
            )
            value["authorization"] = {
                "authorized": bool(grant and not grant.reconnect_reason),
                "expires_at": _iso(grant.expires_at) if grant else None,
                "reconnect_reason": grant.reconnect_reason if grant else None,
            }
            value["open_conflicts"] = int(
                self.session.scalar(
                    select(func.count(IntegrationConflict.id)).where(
                        IntegrationConflict.connection_id == connection.id,
                        IntegrationConflict.resolved_at.is_(None),
                    )
                )
                or 0
            )
            values.append(value)
        return values

    @staticmethod
    def _state(connection: IntegrationConnection, active: set[str]) -> str:
        if connection.id in active:
            return "syncing"
        if connection.paused_reason:
            return "paused"
        if connection.failure_count:
            return "needs_attention"
        if connection.enabled:
            return "connected"
        return "not_configured"

    def get(self, connection_id: str) -> IntegrationConnection:
        connection = self.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.user_id == self.user_id,
            )
        )
        if not connection:
            raise IntegrationNotFound("Integration connection not found.")
        return connection

    def create(
        self,
        *,
        provider_slug: str,
        label: str,
        configuration: dict[str, Any] | None = None,
        capabilities: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
        credentials: dict[str, str] | None = None,
        credential_storage: str | None = None,
    ) -> dict[str, Any]:
        try:
            definition = self.registry.definition(provider_slug)
        except KeyError as exc:
            raise IntegrationError("Unknown integration provider.") from exc
        if not self.registry.adapter(provider_slug):
            raise IntegrationError(
                definition.availability_reason
                or "This integration is not available in the current release."
            )
        clean_label = _bounded_text(label, 120)
        if not clean_label:
            raise IntegrationError("Connection label is required.")
        self._validate_capabilities(definition.capabilities, capabilities or {})
        secret_reference = None
        connection = IntegrationConnection(
            user_id=self.user_id,
            provider_slug=provider_slug,
            label=clean_label,
            enabled=False,
            configuration=self._safe_configuration(configuration or {}),
            capabilities=capabilities or {},
            schedule=schedule or {},
        )
        self.session.add(connection)
        self.session.flush()
        if credentials:
            secret_reference = f"integration.{connection.id}"
            connection.credential_storage = self._save_credentials(
                definition.secret_fields,
                secret_reference,
                credentials,
                credential_storage,
            )
            connection.secret_reference = secret_reference
        self.session.commit()
        return serialize_connection(connection, state="not_configured")

    @staticmethod
    def _safe_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
        forbidden = re.compile(r"(?i)(token|secret|password|authorization|api.?key|auth.?code)")
        if any(forbidden.search(str(key)) for key in configuration):
            raise IntegrationError("Credentials must use the protected credential fields.")
        encoded = json.dumps(configuration)
        if len(encoded) > 20_000:
            raise IntegrationError("Integration configuration is too large.")
        return configuration

    @staticmethod
    def _validate_capabilities(allowed: tuple[str, ...], selected: dict[str, Any]) -> None:
        if set(selected) - set(allowed):
            raise IntegrationError("Connection includes an unsupported capability.")
        if any(
            value not in {True, False, "pull", "push", "both", "off"}
            for value in selected.values()
        ):
            raise IntegrationError("Capability direction is invalid.")

    def _save_credentials(
        self,
        allowed_fields: tuple[str, ...],
        namespace: str,
        credentials: dict[str, str],
        storage: str | None,
    ) -> str:
        unknown = set(credentials) - set(allowed_fields)
        if unknown:
            raise IntegrationError("Connection includes an unsupported credential field.")
        return self.secrets.save_many_named(namespace, credentials, storage=storage)

    def set_enabled(self, connection_id: str, enabled: bool) -> dict[str, Any]:
        connection = self.get(connection_id)
        connection.enabled = enabled
        if enabled:
            connection.paused_reason = None
            connection.failure_count = 0
            interval_minutes = int((connection.schedule or {}).get("interval_minutes") or 0)
            connection.next_run_at = utcnow() if interval_minutes > 0 else None
        else:
            connection.next_run_at = None
        self.session.commit()
        return serialize_connection(
            connection, state="connected" if enabled else "not_configured"
        )

    def disconnect(self, connection_id: str) -> None:
        connection = self.get(connection_id)
        definition = self.registry.definition(connection.provider_slug)
        if connection.secret_reference:
            self.secrets.clear_namespace(
                connection.secret_reference, list(definition.secret_fields)
            )
        self.session.delete(connection)
        self.session.commit()

    def runs(self, connection_id: str, limit: int = 25) -> list[dict[str, Any]]:
        self.get(connection_id)
        return [
            serialize_run(run)
            for run in self.session.scalars(
                select(IntegrationRun)
                .where(IntegrationRun.connection_id == connection_id)
                .order_by(IntegrationRun.started_at.desc())
                .limit(min(max(limit, 1), 100))
            )
        ]

    def events(self, connection_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.get(connection_id)
        events = self.session.scalars(
            select(IntegrationEvent)
            .where(IntegrationEvent.connection_id == connection_id)
            .order_by(IntegrationEvent.created_at.desc())
            .limit(min(max(limit, 1), 200))
        ).all()
        return [
            {
                "id": event.id,
                "run_id": event.run_id,
                "event_kind": event.event_kind,
                "canonical_target": event.canonical_target,
                "outcome": event.outcome,
                "safe_summary": event.safe_summary,
                "created_at": _iso(event.created_at),
            }
            for event in events
        ]

    def conflicts(self, connection_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.get(connection_id)
        rows = self.session.scalars(
            select(IntegrationConflict)
            .where(
                IntegrationConflict.connection_id == connection_id,
                IntegrationConflict.resolved_at.is_(None),
            )
            .order_by(IntegrationConflict.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )
        return [
            {
                "id": row.id,
                "run_id": row.run_id,
                "catalog_item_id": row.catalog_item_id,
                "conflict_kind": row.conflict_kind,
                "safe_summary": row.safe_summary,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]


class IntegrationCoordinator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        registry: ProviderRegistry,
        secrets: SecretStore,
        *,
        failure_pause_threshold: int = FAILURE_PAUSE_THRESHOLD,
    ):
        self.session_factory = session_factory
        self.registry = registry
        self.secrets = secrets
        self.failure_pause_threshold = max(1, failure_pause_threshold)
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    async def run(
        self,
        connection_id: str,
        *,
        capability: str,
        direction: str,
        trigger: str = "manual",
        dry_run: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if direction not in ALLOWED_DIRECTIONS:
            raise IntegrationError("Integration direction is invalid.")
        if trigger not in ALLOWED_TRIGGERS:
            raise IntegrationError("Integration trigger is invalid.")
        if user_id is None:
            with self.session_factory() as session:
                user_id = current_user_id(session)
        lock = self._locks.setdefault((connection_id, capability, direction), asyncio.Lock())
        if lock.locked():
            with self.session_factory() as session:
                active = session.scalar(
                    select(IntegrationRun)
                    .join(
                        IntegrationConnection,
                        IntegrationRun.connection_id == IntegrationConnection.id,
                    )
                    .where(
                        IntegrationConnection.user_id == user_id,
                        IntegrationRun.connection_id == connection_id,
                        IntegrationRun.capability == capability,
                        IntegrationRun.direction == direction,
                        IntegrationRun.state == "running",
                    )
                    .order_by(IntegrationRun.started_at.desc())
                )
                if active:
                    value = serialize_run(active)
                    value["coalesced"] = True
                    return value
        async with lock:
            return await self._execute(
                connection_id,
                capability=capability,
                direction=direction,
                trigger=trigger,
                dry_run=dry_run,
                user_id=user_id,
            )

    def ingest(
        self,
        connection_id: str,
        event: IntegrationEventInput,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        """Commit one already-authenticated inbound provider event."""
        with self.session_factory() as session:
            connection = session.scalar(
                select(IntegrationConnection).where(
                    IntegrationConnection.id == connection_id,
                    IntegrationConnection.provider_slug.in_(("jellyfin", "plex", "emby")),
                )
            )
            if connection is None:
                raise IntegrationNotFound("Integration connection not found.")
            run = IntegrationRun(
                connection_id=connection.id,
                trigger="webhook",
                direction="inbound",
                capability="receive_playback_event",
                state="running",
                dry_run=False,
                counts=dict(RUN_COUNTS),
            )
            session.add(run)
            session.commit()
            run_id = run.id
        return self._commit_page(
            run_id,
            IntegrationPage(
                events=(event,),
                provider_version="playback-webhook-v1",
                message="Playback event accepted.",
            ),
            {},
            {},
        )

    async def _execute(
        self,
        connection_id: str,
        *,
        capability: str,
        direction: str,
        trigger: str,
        dry_run: bool,
        user_id: str,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            connection = session.scalar(
                select(IntegrationConnection).where(
                    IntegrationConnection.id == connection_id,
                    IntegrationConnection.user_id == user_id,
                )
            )
            if not connection:
                raise IntegrationNotFound("Integration connection not found.")
            definition = self.registry.definition(connection.provider_slug)
            adapter = self.registry.adapter(connection.provider_slug)
            if adapter is None:
                raise IntegrationError("This provider adapter is unavailable.")
            if capability not in definition.capabilities:
                raise IntegrationError("This provider does not support that capability.")
            if connection.paused_reason and capability != "test_connection":
                raise IntegrationError("Resume this connection before running it again.")
            if not connection.enabled and capability != "test_connection" and not dry_run:
                raise IntegrationError("Test and enable this connection before syncing.")
            cursor_record = session.scalar(
                select(IntegrationCursor).where(
                    IntegrationCursor.connection_id == connection_id,
                    IntegrationCursor.capability == capability,
                    IntegrationCursor.direction == direction,
                )
            )
            cursor = dict(cursor_record.checkpoint) if cursor_record else {}
            safe_connection = {
                "id": connection.id,
                "provider_slug": connection.provider_slug,
                "label": connection.label,
                "configuration": dict(connection.configuration),
                "remote_profile": dict(connection.remote_profile),
            }
            credentials: dict[str, str] = {}
            if connection.secret_reference:
                for key in definition.secret_fields:
                    value, _source = self.secrets.get_named(connection.secret_reference, key)
                    if value:
                        credentials[key] = value
            run = IntegrationRun(
                connection_id=connection_id,
                trigger=trigger,
                direction=direction,
                capability=capability,
                state="running",
                dry_run=dry_run,
                counts=dict(RUN_COUNTS),
            )
            connection.last_attempt_at = utcnow()
            if cursor_record:
                cursor_record.last_attempt_at = utcnow()
            session.add(run)
            session.commit()
            run_id = run.id

        try:
            page = await adapter.run(
                capability=capability,
                direction=direction,
                connection=safe_connection,
                credentials=credentials,
                cursor=cursor,
                dry_run=dry_run,
            )
            if not isinstance(page, IntegrationPage):
                raise IntegrationProviderError(
                    "invalid_adapter_result", "The provider returned an invalid sync result."
                )
        except IntegrationProviderError as exc:
            return self._fail_run(run_id, exc, credentials)
        except Exception as exc:
            wrapped = IntegrationProviderError(
                "provider_error", "The integration request failed safely.", retryable=True
            )
            return self._fail_run(run_id, wrapped, credentials, internal=exc)
        return self._commit_page(run_id, page, cursor, credentials)

    def _fail_run(
        self,
        run_id: str,
        error: IntegrationProviderError,
        credentials: dict[str, str],
        *,
        internal: Exception | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            run = session.get(IntegrationRun, run_id)
            assert run is not None
            connection = session.get(IntegrationConnection, run.connection_id)
            assert connection is not None
            redacted = redact_secrets(error.safe_message, list(credentials.values()))
            if internal is not None:
                # The type is useful in local logs/tests; its potentially sensitive text is not.
                redacted = f"{redacted} ({type(internal).__name__})"
            run.state = "failed"
            run.error_code = _bounded_text(error.code, 80)
            run.error_message = _bounded_text(redacted)
            run.retry_after_seconds = error.retry_after_seconds
            run.completed_at = utcnow()
            run.counts = {**RUN_COUNTS, "errors": 1}
            connection.failure_count += 1
            if connection.secret_reference and credentials:
                definition = self.registry.definition(connection.provider_slug)
                refreshed = {
                    key: value
                    for key, value in credentials.items()
                    if key in definition.secret_fields and value
                }
                if refreshed:
                    self.secrets.save_many_named(
                        connection.secret_reference,
                        refreshed,
                        storage=connection.credential_storage,
                    )
            delay = error.retry_after_seconds or self._backoff_delay(connection.failure_count)
            connection.next_run_at = utcnow() + timedelta(seconds=delay)
            if connection.failure_count >= self.failure_pause_threshold:
                connection.enabled = False
                connection.paused_reason = "Automatically paused after repeated failures. Test the connection, then resume."
                NotificationService.emit(
                    session,
                    NotificationEvent(
                        user_id=connection.user_id,
                        event_type="integration.paused",
                        title=connection.label,
                        safe_message="This integration paused after repeated failures.",
                        source_kind="integration_connection",
                        source_key=f"{connection.id}:paused:{connection.failure_count}",
                        resource_type="integration_connection",
                        resource_id=connection.id,
                    ),
                )
            session.commit()
            return serialize_run(run)

    @staticmethod
    def _backoff_delay(failure_count: int) -> int:
        base = min(3600, 30 * 2 ** max(failure_count - 1, 0))
        spread = max(1, base // 5)
        return min(3600, base - spread + secure_random.randbelow(spread * 2 + 1))

    def _commit_page(
        self,
        run_id: str,
        page: IntegrationPage,
        previous_cursor: dict[str, Any],
        credentials: dict[str, str],
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            run = session.get(IntegrationRun, run_id)
            assert run is not None
            connection = session.get(IntegrationConnection, run.connection_id)
            assert connection is not None
            coordinator_counts = dict(RUN_COUNTS)
            for item in page.events:
                idempotency_key = self._idempotency_key(
                    connection.id, item, dry_run=run.dry_run
                )
                existing = session.scalar(
                    select(IntegrationEvent).where(
                        IntegrationEvent.connection_id == connection.id,
                        IntegrationEvent.idempotency_key == idempotency_key,
                    )
                )
                if existing:
                    coordinator_counts["skipped"] += 1
                    continue
                outcome, target, entry = self._resolve_event(
                    session, run, connection.user_id, item
                )
                resolution_outcome = outcome
                if entry is not None and outcome not in {
                    "needs_review",
                    "tombstone_skipped",
                }:
                    outcome = self._apply_normalized_changes(
                        session,
                        run,
                        connection,
                        entry,
                        item,
                        idempotency_key,
                    )
                    if resolution_outcome == "created" and outcome in {
                        "updated",
                        "skipped",
                    }:
                        outcome = "created"
                payload_hash = (
                    item.payload_hash.lower()
                    if re.fullmatch(r"[0-9a-fA-F]{64}", item.payload_hash)
                    else _safe_hash(item.payload_hash)
                )
                session.add(
                    IntegrationEvent(
                        run_id=run.id,
                        connection_id=connection.id,
                        provider_event_id=item.provider_event_id,
                        idempotency_key=idempotency_key,
                        canonical_target=target,
                        event_kind=_bounded_text(item.event_kind, 60),
                        outcome=outcome,
                        safe_summary=_bounded_text(item.safe_summary),
                        payload_hash=payload_hash,
                        source_values=_safe_source_values(item.source_values),
                    )
                )
                if outcome == "needs_review":
                    coordinator_counts["conflicts"] += 1
                elif outcome in {
                    "skipped",
                    "rejected",
                    "status_unmapped",
                    "tombstone_skipped",
                }:
                    coordinator_counts["skipped"] += 1
                elif outcome in {"updated", "would_update"}:
                    coordinator_counts["updated"] += 1
                else:
                    coordinator_counts["created"] += 1
            counts = coordinator_counts if page.events else page.counts
            counts["errors"] += page.errors
            run.counts = counts
            run.state = "previewed" if run.dry_run else "succeeded"
            run.completed_at = utcnow()
            run.retry_after_seconds = page.retry_after_seconds
            connection.failure_count = 0
            connection.paused_reason = None
            connection.last_success_at = utcnow()
            interval_minutes = int((connection.schedule or {}).get("interval_minutes") or 0)
            connection.next_run_at = (
                utcnow() + timedelta(minutes=interval_minutes)
                if connection.enabled and interval_minutes > 0
                else None
            )
            if page.remote_profile:
                connection.remote_profile = {
                    key: value
                    for key, value in page.remote_profile.items()
                    if key not in {"token", "access_token", "refresh_token", "secret"}
                }
            if page.credential_updates:
                if not connection.secret_reference:
                    connection.secret_reference = f"integration.{connection.id}"
                definition = self.registry.definition(connection.provider_slug)
                allowed = set(definition.secret_fields)
                updates = {
                    key: value
                    for key, value in page.credential_updates.items()
                    if key in allowed and value
                }
                if updates:
                    self.secrets.save_many_named(
                        connection.secret_reference,
                        updates,
                        storage=connection.credential_storage,
                    )
                grant = session.scalar(
                    select(IntegrationOAuthGrant).where(
                        IntegrationOAuthGrant.connection_id == connection.id
                    )
                )
                if grant:
                    grant.refresh_generation += 1
                    grant.last_refresh_at = utcnow()
                    grant.reconnect_reason = None
            if not run.dry_run:
                cursor_record = session.scalar(
                    select(IntegrationCursor).where(
                        IntegrationCursor.connection_id == connection.id,
                        IntegrationCursor.capability == run.capability,
                        IntegrationCursor.direction == run.direction,
                    )
                )
                if not cursor_record:
                    cursor_record = IntegrationCursor(
                        connection_id=connection.id,
                        capability=run.capability,
                        direction=run.direction,
                        checkpoint=previous_cursor,
                    )
                    session.add(cursor_record)
                if page.next_cursor is not None:
                    cursor_record.checkpoint = page.next_cursor
                cursor_record.provider_version = page.provider_version
                cursor_record.last_attempt_at = run.started_at
                cursor_record.last_success_at = utcnow()
            if counts["conflicts"]:
                NotificationService.emit(
                    session,
                    NotificationEvent(
                        user_id=connection.user_id,
                        event_type="integration.completed_with_conflicts",
                        title=connection.label,
                        safe_message=f"Import completed with {counts['conflicts']} item(s) to review.",
                        source_kind="integration_run",
                        source_key=f"{run.id}:conflicts",
                        resource_type="integration_connection",
                        resource_id=connection.id,
                    ),
                )
            session.commit()
            result = serialize_run(run)
            result["message"] = _bounded_text(page.message)
            result["has_more"] = page.has_more
            return result

    @staticmethod
    def _idempotency_key(
        connection_id: str, item: IntegrationEventInput, *, dry_run: bool = False
    ) -> str:
        if item.idempotency_key:
            material = f"{connection_id}|{item.idempotency_key}"
        else:
            identity = "|".join(
                f"{key}:{value}" for key, value in sorted(item.identities.items())
            )
            material = "|".join(
                (
                    connection_id,
                    item.provider_event_id or "",
                    identity,
                    item.event_kind,
                    item.canonical_target or "",
                    item.payload_hash,
                )
            )
        return _safe_hash(f"preview|{material}" if dry_run else material)

    @staticmethod
    def _resolve_event(
        session: Session,
        run: IntegrationRun,
        user_id: str,
        item: IntegrationEventInput,
    ) -> tuple[str, str | None, WatchEntry | None]:
        catalog_ids: set[str] = set()
        for namespace, external_id in item.identities.items():
            identity = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.namespace == namespace,
                    ExternalIdentity.external_id == str(external_id),
                )
            )
            if identity:
                catalog = session.get(CatalogItem, identity.catalog_item_id)
                if catalog is not None and _integration_catalog_visible(
                    session, user_id=user_id, catalog=catalog
                ):
                    catalog_ids.add(identity.catalog_item_id)
        if not catalog_ids and item.title and item.media_type:
            exact = session.scalars(
                select(CatalogItem).where(
                    CatalogItem.normalized_title == normalize_title(item.title),
                    CatalogItem.release_year == item.year,
                    CatalogItem.media_type == item.media_type,
                )
            ).all()
            catalog_ids = {
                catalog.id
                for catalog in exact
                if _integration_catalog_visible(session, user_id=user_id, catalog=catalog)
            }
        if not catalog_ids and item.identities and item.title and item.media_type:
            if run.dry_run:
                return "would_create", item.canonical_target, None
            catalog = CatalogItem(
                canonical_title=_bounded_text(item.title, 500),
                normalized_title=normalize_title(item.title),
                release_year=item.year,
                media_type=item.media_type,
                metadata_source="integration",
                metadata_provenance={"source": "account_import"},
            )
            session.add(catalog)
            session.flush()
            for namespace, external_id in item.identities.items():
                existing_identity = session.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.namespace == _bounded_text(namespace, 80),
                        ExternalIdentity.external_id == _bounded_text(str(external_id), 200),
                    )
                )
                if existing_identity is not None:
                    continue
                session.add(
                    ExternalIdentity(
                        catalog_item_id=catalog.id,
                        namespace=_bounded_text(namespace, 80),
                        external_id=_bounded_text(str(external_id), 200),
                        provenance="integration_import",
                        confidence=1.0,
                        verified_at=utcnow(),
                    )
                )
            catalog_ids = {catalog.id}
        if len(catalog_ids) == 1:
            catalog_id = next(iter(catalog_ids))
            entry = session.scalar(
                select(WatchEntry).where(
                    WatchEntry.user_id == user_id,
                    WatchEntry.catalog_item_id == catalog_id,
                )
            )
            if entry and entry.deleted_at is not None:
                return "tombstone_skipped", catalog_id, entry
            if entry is None:
                if run.dry_run:
                    return "would_create", catalog_id, None
                status = str(item.changes.get("status") or "plan_to_watch")
                if status not in NORMALIZED_STATUSES:
                    status = "plan_to_watch"
                entry = WatchEntry(
                    user_id=user_id,
                    catalog_item_id=catalog_id,
                    status=status,
                    view_count=0,
                    import_context={"source": "integration", "run_id": run.id},
                )
                session.add(entry)
                session.flush()
                return "created", catalog_id, entry
            return item.outcome, catalog_id, entry
        conflict_kind = (
            "identity_contradiction" if len(catalog_ids) > 1 else "identity_unmatched"
        )
        session.add(
            IntegrationConflict(
                connection_id=run.connection_id,
                run_id=run.id,
                conflict_kind=conflict_kind,
                local_value={"catalog_item_ids": sorted(catalog_ids)},
                remote_value={
                    "identities": item.identities,
                    "title": item.title,
                    "year": item.year,
                    "media_type": item.media_type,
                },
                safe_summary=(
                    "Provider identities point to different PMT titles."
                    if catalog_ids
                    else "No verified or exact PMT identity matched this provider item."
                ),
            )
        )
        return "needs_review", item.canonical_target, None

    @staticmethod
    def _record_conflict(
        session: Session,
        run: IntegrationRun,
        entry: WatchEntry,
        *,
        kind: str,
        local_value: dict[str, Any],
        remote_value: dict[str, Any],
        summary: str,
    ) -> None:
        session.add(
            IntegrationConflict(
                connection_id=run.connection_id,
                run_id=run.id,
                catalog_item_id=entry.catalog_item_id,
                conflict_kind=kind,
                local_value=local_value,
                remote_value=remote_value,
                safe_summary=summary,
            )
        )

    @staticmethod
    def _parse_viewed_on(value: Any) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
                except ValueError:
                    return None
        return None

    def _apply_normalized_changes(
        self,
        session: Session,
        run: IntegrationRun,
        connection: IntegrationConnection,
        entry: WatchEntry,
        item: IntegrationEventInput,
        idempotency_key: str,
    ) -> str:
        changes = item.changes
        if not changes:
            return item.outcome

        unsupported = sorted(set(changes) - SAFE_CHANGE_FIELDS)
        if unsupported:
            self._record_conflict(
                session,
                run,
                entry,
                kind="unsupported_remote_fields",
                local_value={},
                remote_value={"field_names": unsupported},
                summary="The provider requested fields that integrations are not allowed to change.",
            )
            return "needs_review"

        completed = changes.get("completed", False)
        if not isinstance(completed, bool):
            return "rejected"

        viewed_on = self._parse_viewed_on(changes.get("viewed_on"))
        raw_viewed_on = changes.get("viewed_on")
        if raw_viewed_on is not None and raw_viewed_on != "" and viewed_on is None:
            return "rejected"
        episode_completed = changes.get("episode_completed", False)
        if not isinstance(episode_completed, bool):
            return "rejected"
        playback_raw = changes.get("playback_observation")
        playback: PlaybackObservation | None = None
        playback_threshold = 0.9
        if playback_raw is not None:
            if not isinstance(playback_raw, dict):
                return "rejected"
            try:
                observed_at_raw = playback_raw.get("observed_at")
                observed_at = (
                    datetime.fromisoformat(str(observed_at_raw).replace("Z", "+00:00"))
                    if observed_at_raw
                    else None
                )
                playback_threshold = float(playback_raw.get("completion_threshold") or 0.9)
                playback = PlaybackObservation(
                    event=str(playback_raw.get("event")),  # type: ignore[arg-type]
                    position_seconds=float(playback_raw.get("position_seconds") or 0),
                    duration_seconds=float(playback_raw.get("duration_seconds") or 0),
                    active_seconds=(
                        float(playback_raw["active_seconds"])
                        if playback_raw.get("active_seconds") is not None
                        else None
                    ),
                    strong_completion=bool(playback_raw.get("strong_completion")),
                    observed_at=observed_at,
                )
            except (TypeError, ValueError):
                return "rejected"
            if playback.event not in {
                "start",
                "pause",
                "progress",
                "stop",
                "ended",
                "completed",
            }:
                return "rejected"
        if "viewed_on" in changes and not (completed or episode_completed):
            return "rejected"

        parsed_dates: dict[str, date | None] = {}
        for field in ("started_date", "finished_date"):
            if field in changes:
                parsed = self._parse_viewed_on(changes.get(field))
                if changes.get(field) not in {None, ""} and parsed is None:
                    return "rejected"
                parsed_dates[field] = parsed

        progress = changes.get("episode_progress_count")
        repeats = changes.get("repeat_count")
        if progress is not None and (isinstance(progress, bool) or not str(progress).isdigit()):
            return "rejected"
        if repeats is not None and (isinstance(repeats, bool) or not str(repeats).isdigit()):
            return "rejected"
        progress_value = int(progress) if progress is not None else None
        repeat_value = int(repeats) if repeats is not None else None
        if progress_value is not None and not 0 <= progress_value <= 100_000:
            return "rejected"
        if repeat_value is not None and not 0 <= repeat_value <= 10_000:
            return "rejected"

        rating: float | None = None
        if "personal_rating" in changes:
            value = changes["personal_rating"]
            if isinstance(value, bool):
                return "rejected"
            try:
                rating = float(value)
            except (TypeError, ValueError):
                return "rejected"
            if not 1 <= rating <= 10:
                return "rejected"
            if entry.personal_rating is not None and abs(entry.personal_rating - rating) > 1e-9:
                self._record_conflict(
                    session,
                    run,
                    entry,
                    kind="personal_rating_diverged",
                    local_value={"personal_rating": entry.personal_rating},
                    remote_value={"personal_rating": rating},
                    summary="The local and provider personal ratings differ; PMT kept the local rating.",
                )
                return "needs_review"

        remote_status = changes.get("status")
        if remote_status is not None:
            if not isinstance(remote_status, str) or remote_status not in NORMALIZED_STATUSES:
                return "status_unmapped"
            allowed_promotion = (
                remote_status == entry.status
                or (entry.status, remote_status)
                in {
                    ("plan_to_watch", "watching"),
                    ("plan_to_watch", "watched"),
                    ("watching", "watched"),
                }
                or (completed and remote_status == "watched")
            )
            if not allowed_promotion:
                self._record_conflict(
                    session,
                    run,
                    entry,
                    kind="status_diverged",
                    local_value={"status": entry.status},
                    remote_value={"status": remote_status},
                    summary="The local and provider statuses differ; PMT kept the local status.",
                )
                return "needs_review"

        would_change = (
            (rating is not None and entry.personal_rating is None)
            or (remote_status is not None and remote_status != entry.status)
            or completed
            or episode_completed
            or playback is not None
            or any(
                value is not None and getattr(entry, field) is None
                for field, value in parsed_dates.items()
            )
            or (progress_value is not None and entry.episode_progress_count is None)
            or (repeat_value is not None and entry.view_count == 0)
        )
        if not would_change:
            return "skipped"
        if run.dry_run:
            return "would_update"

        before = {
            "status": entry.status,
            "personal_rating": entry.personal_rating,
            "view_count": entry.view_count,
            "watched_date": entry.watched_date.isoformat() if entry.watched_date else None,
        }
        if rating is not None and entry.personal_rating is None:
            entry.personal_rating = rating
        if remote_status is not None:
            entry.status = remote_status
        conflict_recorded = False
        for field, value in parsed_dates.items():
            local = getattr(entry, field)
            if local is None:
                setattr(entry, field, value)
            elif value is not None and local != value:
                self._record_conflict(
                    session,
                    run,
                    entry,
                    kind=f"{field}_diverged",
                    local_value={field: local.isoformat()},
                    remote_value={field: value.isoformat()},
                    summary="The local and provider dates differ; PMT kept the local date.",
                )
                conflict_recorded = True
        reducer = ViewingReducer(session, user_id=entry.user_id)
        if (
            progress_value is not None
            and entry.episode_progress_count is not None
            and entry.episode_progress_count != progress_value
        ):
            self._record_conflict(
                session,
                run,
                entry,
                kind="episode_progress_diverged",
                local_value={"episode_progress_count": entry.episode_progress_count},
                remote_value={"episode_progress_count": progress_value},
                summary="Episode progress differs; PMT kept the local value.",
            )
            conflict_recorded = True
        if repeat_value is not None and entry.view_count != 0:
            expected_views = repeat_value + (1 if entry.status == "watched" else 0)
            if entry.view_count != expected_views:
                self._record_conflict(
                    session,
                    run,
                    entry,
                    kind="repeat_count_diverged",
                    local_value={"view_count": entry.view_count},
                    remote_value={"repeat_count": repeat_value},
                    summary="Repeat count differs; PMT kept the local viewing count.",
                )
                conflict_recorded = True
        episode = None
        if episode_completed or playback is not None:
            season_number = changes.get("season_number")
            episode_number = changes.get("episode_number")
            if season_number is not None and episode_number is not None:
                episode = session.scalar(
                    select(EpisodeRecord)
                    .join(SeasonRecord, EpisodeRecord.season_id == SeasonRecord.id)
                    .where(
                        SeasonRecord.catalog_item_id == entry.catalog_item_id,
                        SeasonRecord.season_number == int(season_number),
                        EpisodeRecord.episode_number == int(episode_number),
                    )
                )
        if episode_completed:
            if episode:
                reducer.record_episode_completion(
                    entry,
                    episode_id=episode.id,
                    watched_on=viewed_on,
                    source="integration",
                    source_key=f"{connection.id}:{idempotency_key}",
                    source_event_key=(
                        f"{connection.provider_slug}:{item.provider_event_id or idempotency_key}"
                    ),
                )
            else:
                current = entry.episode_progress_count or 0
                reducer.accept_progress_claim(
                    entry,
                    provider=connection.provider_slug,
                    source_key=f"unmatched-episode:{connection.id}:{idempotency_key}",
                    episode_progress_count=max(current, progress_value or current + 1),
                    repeat_count=None,
                    completed_status=False,
                )
        playback_decision = None
        if playback is not None:
            playback_decision = reducer.apply_observation(
                entry,
                playback,
                source="integration",
                source_key=f"{connection.id}:{idempotency_key}",
                source_event_key=(
                    f"{connection.provider_slug}:{item.provider_event_id or idempotency_key}"
                ),
                episode_id=episode.id if episode else None,
                completion_threshold=playback_threshold,
            )
            if playback_decision == "review":
                self._record_conflict(
                    session,
                    run,
                    entry,
                    kind="playback_completion_ambiguous",
                    local_value={"view_count": entry.view_count},
                    remote_value={
                        "event": playback.event,
                        "position_seconds": playback.position_seconds,
                        "duration_seconds": playback.duration_seconds,
                    },
                    summary="Playback reached the end without enough active time; PMT did not mark it watched.",
                )
                conflict_recorded = True
        if completed:
            reducer.record_title_completion(
                entry,
                viewed_on=viewed_on,
                source="integration",
                source_key=f"{connection.id}:{idempotency_key}",
                source_event_key=(
                    f"{connection.provider_slug}:{item.provider_event_id or idempotency_key}"
                ),
            )
        # Apply aggregate provider claims after any concrete completion. This
        # prevents a provider response containing both ``completed`` and
        # ``repeat_count`` from projecting a count and then incrementing it a
        # second time for the same real-world completion.
        if progress_value is not None or repeat_value is not None:
            reducer.accept_progress_claim(
                entry,
                provider=connection.provider_slug,
                source_key=f"{connection.id}:{idempotency_key}",
                episode_progress_count=progress_value,
                repeat_count=repeat_value,
                completed_status=(remote_status or entry.status) == "watched",
            )
        entry.updated_at = utcnow()
        after = {
            "status": entry.status,
            "personal_rating": entry.personal_rating,
            "view_count": entry.view_count,
            "watched_date": entry.watched_date.isoformat() if entry.watched_date else None,
        }
        session.add(
            AuditEvent(
                user_id=entry.user_id,
                action="integration_sync",
                entity_type="watch_entry",
                entity_id=entry.id,
                source="integration",
                before_data=before,
                after_data=after,
            )
        )
        if conflict_recorded:
            return "needs_review"
        if playback_decision == "ignore" and len(changes) == 1:
            return "skipped"
        return "updated"
