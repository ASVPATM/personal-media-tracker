from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets as secure_random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.authorization import Principal, current_user_id
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
    ExternalIdentity,
    IntegrationConflict,
    IntegrationConnection,
    IntegrationCursor,
    IntegrationEvent,
    IntegrationRun,
    ViewingEvent,
    WatchEntry,
    utcnow,
)
from watchtracker.services.secrets import SecretStore
from watchtracker.taxonomy import normalize_title

RUN_COUNTS = {"created": 0, "updated": 0, "skipped": 0, "conflicts": 0, "errors": 0}
ALLOWED_DIRECTIONS = {"pull", "push", "inbound", "outbound", "test"}
ALLOWED_TRIGGERS = {"manual", "scheduled", "webhook"}
FAILURE_PAUSE_THRESHOLD = 5
NORMALIZED_STATUSES = frozenset(
    {"plan_to_watch", "watching", "paused", "dropped", "watched", "rewatching"}
)
SAFE_CHANGE_FIELDS = frozenset({"personal_rating", "status", "completed", "viewed_on"})


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
        return [
            serialize_connection(connection, state=self._state(connection, active))
            for connection in connections
        ]

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
            self._save_credentials(
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
    ) -> None:
        unknown = set(credentials) - set(allowed_fields)
        if unknown:
            raise IntegrationError("Connection includes an unsupported credential field.")
        saved: list[str] = []
        try:
            for key, value in credentials.items():
                self.secrets.save_named(namespace, key, value, storage=storage)
                saved.append(key)
        except Exception:
            self.secrets.clear_namespace(namespace, saved)
            raise

    def set_enabled(self, connection_id: str, enabled: bool) -> dict[str, Any]:
        connection = self.get(connection_id)
        connection.enabled = enabled
        if enabled:
            connection.paused_reason = None
            connection.failure_count = 0
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
            delay = error.retry_after_seconds or self._backoff_delay(connection.failure_count)
            connection.next_run_at = utcnow() + timedelta(seconds=delay)
            if connection.failure_count >= self.failure_pause_threshold:
                connection.enabled = False
                connection.paused_reason = "Automatically paused after repeated failures. Test the connection, then resume."
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
        del credentials
        with self.session_factory() as session:
            run = session.get(IntegrationRun, run_id)
            assert run is not None
            connection = session.get(IntegrationConnection, run.connection_id)
            assert connection is not None
            coordinator_counts = dict(RUN_COUNTS)
            for item in page.events:
                idempotency_key = self._idempotency_key(connection.id, item)
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
            connection.next_run_at = None
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
            session.commit()
            result = serialize_run(run)
            result["message"] = _bounded_text(page.message)
            return result

    @staticmethod
    def _idempotency_key(connection_id: str, item: IntegrationEventInput) -> str:
        if item.idempotency_key:
            return _safe_hash(f"{connection_id}|{item.idempotency_key}")
        identity = "|".join(f"{key}:{value}" for key, value in sorted(item.identities.items()))
        fallback = "|".join(
            (
                connection_id,
                item.provider_event_id or "",
                identity,
                item.event_kind,
                item.canonical_target or "",
                item.payload_hash,
            )
        )
        return _safe_hash(fallback)

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
                catalog_ids.add(identity.catalog_item_id)
        if not catalog_ids and item.title and item.media_type:
            exact = session.scalars(
                select(CatalogItem).where(
                    CatalogItem.normalized_title == normalize_title(item.title),
                    CatalogItem.release_year == item.year,
                    CatalogItem.media_type == item.media_type,
                )
            ).all()
            catalog_ids = {catalog.id for catalog in exact}
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
        if "viewed_on" in changes and not completed:
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
        if completed:
            session.add(
                ViewingEvent(
                    user_id=entry.user_id,
                    entry=entry,
                    viewed_on=viewed_on,
                    source="integration",
                    source_key=f"{connection.id}:{idempotency_key}",
                )
            )
            entry.view_count += 1
            if viewed_on and (entry.watched_date is None or viewed_on >= entry.watched_date):
                entry.watched_date = viewed_on
            entry.status = "watched"
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
        return "updated"
