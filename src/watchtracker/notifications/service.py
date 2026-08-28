from __future__ import annotations

import hashlib
import re
import socket
from datetime import UTC, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import (
    CatalogItem,
    NotificationDeliveryAttempt,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationRule,
    ReleaseEvent,
    UserNotification,
    WatchEntry,
    utcnow,
)
from watchtracker.notifications.adapters import (
    NotificationAdapterError,
    NotificationAdapterRegistry,
)
from watchtracker.notifications.contract import NotificationEvent, normalize_event_type
from watchtracker.services.secrets import SecretStore

ENDPOINT_FAILURE_THRESHOLD = 5
DENIED_APPRISE_SCHEMES = frozenset(
    {
        "command",
        "dbus",
        "exec",
        "file",
        "gnome",
        "kodi",
        "macos",
        "shell",
        "syslog",
        "windows",
        "xbmc",
    }
)
EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|\*)){1,2}$")


class NotificationError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def _clean(value: str, limit: int) -> str:
    return " ".join(value.replace("\x00", " ").split())[:limit]


def _matches(pattern: str, event_type: str) -> bool:
    prefix, _, suffix = pattern.partition(".")
    event_prefix, _, event_suffix = event_type.partition(".")
    return prefix == event_prefix and (suffix == "*" or suffix == event_suffix)


def _parse_clock(value: str | None) -> time | None:
    if value is None:
        return None
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise NotificationError("Quiet hours must use HH:MM.") from exc
    if parsed.second or parsed.microsecond:
        raise NotificationError("Quiet hours must use minute precision.")
    return parsed


def _next_allowed(
    value: datetime, *, start: str | None, end: str | None, timezone: str
) -> datetime:
    start_time = _parse_clock(start)
    end_time = _parse_clock(end)
    if start_time is None and end_time is None:
        return value
    if start_time is None or end_time is None:
        raise NotificationError("Quiet hours require both a start and end.")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise NotificationError("Notification timezone is invalid.") from exc
    local = _aware(value).astimezone(zone)
    current = local.timetz().replace(tzinfo=None)
    overnight = start_time >= end_time
    quiet = (
        current >= start_time or current < end_time
        if overnight
        else start_time <= current < end_time
    )
    if not quiet:
        return value
    end_date = local.date()
    if overnight and current >= start_time:
        end_date += timedelta(days=1)
    target = datetime.combine(end_date, end_time, zone)
    return target.astimezone(UTC)


class NotificationService:
    def __init__(
        self,
        session: Session,
        secrets: SecretStore,
        principal: Principal | None = None,
        adapters: NotificationAdapterRegistry | None = None,
    ):
        self.session = session
        self.secrets = secrets
        self.user_id = current_user_id(session, principal)
        self.adapters = adapters

    @staticmethod
    def emit(
        session: Session,
        event: NotificationEvent,
        *,
        create_in_app: bool = True,
    ) -> UserNotification | None:
        row = None
        if create_in_app:
            row = session.scalar(
                select(UserNotification).where(
                    UserNotification.user_id == event.user_id,
                    UserNotification.source_kind == event.source_kind,
                    UserNotification.source_key == event.source_key,
                )
            )
            if row is None:
                row = UserNotification(
                    user_id=event.user_id,
                    event_type=event.event_type,
                    source_kind=event.source_kind,
                    source_key=_clean(event.source_key, 160),
                    title=_clean(event.title, 160),
                    safe_message=_clean(event.safe_message, 300),
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    created_at=event.created_at or utcnow(),
                )
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    row = session.scalar(
                        select(UserNotification).where(
                            UserNotification.user_id == event.user_id,
                            UserNotification.source_kind == event.source_kind,
                            UserNotification.source_key == event.source_key,
                        )
                    )
        NotificationService.route_existing(session, event)
        return row

    @staticmethod
    def route_existing(session: Session, event: NotificationEvent) -> int:
        event_type = normalize_event_type(event.event_type)
        rules = list(
            session.scalars(
                select(NotificationRule).where(
                    NotificationRule.user_id == event.user_id,
                    NotificationRule.enabled.is_(True),
                    NotificationRule.external_enabled.is_(True),
                    NotificationRule.endpoint_id.is_not(None),
                )
            )
        )
        created = 0
        now = utcnow()
        for rule in rules:
            if not _matches(rule.event_pattern, event_type):
                continue
            endpoint = session.scalar(
                select(NotificationEndpoint).where(
                    NotificationEndpoint.id == rule.endpoint_id,
                    NotificationEndpoint.user_id == event.user_id,
                    NotificationEndpoint.enabled.is_(True),
                )
            )
            if endpoint is None:
                continue
            due = now
            routed_type = event_type
            if rule.lead_time_hours and event.effective_date:
                due = datetime.combine(event.effective_date, time.min, UTC) - timedelta(
                    hours=rule.lead_time_hours
                )
                routed_type = "release.upcoming"
            due = _next_allowed(
                max(due, now),
                start=rule.quiet_start,
                end=rule.quiet_end,
                timezone=rule.timezone,
            )
            dedupe = hashlib.sha256(
                f"{event.user_id}|{endpoint.id}|{event.source_kind}|{event.source_key}|"
                f"{rule.id}|{rule.lead_time_hours}".encode()
            ).hexdigest()
            exists = session.scalar(
                select(NotificationOutbox.id).where(NotificationOutbox.dedupe_key == dedupe)
            )
            if exists:
                continue
            try:
                with session.begin_nested():
                    session.add(
                        NotificationOutbox(
                            user_id=event.user_id,
                            endpoint_id=endpoint.id,
                            source_kind=event.source_kind,
                            source_key=_clean(event.source_key, 160),
                            event_type=routed_type,
                            title=_clean(event.title, 160),
                            safe_message=_clean(event.safe_message, 500),
                            resource_type=event.resource_type,
                            resource_id=event.resource_id,
                            dedupe_key=dedupe,
                            due_at=due,
                        )
                    )
                    # Make the unique route visible to subsequent producer calls in this
                    # transaction, not only after the outer event transaction commits.
                    session.flush()
            except IntegrityError:
                continue
            created += 1
        return created

    def inbox(self, *, unread_only: bool = False, limit: int = 100) -> dict[str, Any]:
        generic_statement = select(UserNotification).where(
            UserNotification.user_id == self.user_id,
            UserNotification.dismissed_at.is_(None),
        )
        release_statement = (
            select(ReleaseEvent, CatalogItem)
            .join(WatchEntry, ReleaseEvent.entry_id == WatchEntry.id)
            .join(CatalogItem, WatchEntry.catalog_item_id == CatalogItem.id)
            .where(
                ReleaseEvent.user_id == self.user_id,
                ReleaseEvent.dismissed_at.is_(None),
            )
        )
        if unread_only:
            generic_statement = generic_statement.where(UserNotification.read_at.is_(None))
            release_statement = release_statement.where(ReleaseEvent.read_at.is_(None))
        generic = list(self.session.scalars(generic_statement))
        releases = list(self.session.execute(release_statement))
        items = [
            {
                "id": row.id,
                "source_kind": "inbox",
                "event_type": normalize_event_type(row.event_type),
                "title": row.title,
                "message": row.safe_message,
                "effective_date": None,
                "created_at": _iso(row.created_at),
                "read": row.read_at is not None,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
            }
            for row in generic
        ]
        items.extend(
            {
                "id": event.id,
                "source_kind": "release",
                "event_type": normalize_event_type(event.event_type),
                "title": catalog.canonical_title,
                "message": event.event_type.replace("_", " ").title(),
                "effective_date": event.effective_date.isoformat()
                if event.effective_date
                else None,
                "created_at": _iso(event.first_seen_at),
                "read": event.read_at is not None,
                "resource_type": "watch_entry",
                "resource_id": event.entry_id,
            }
            for event, catalog in releases
        )
        items.sort(key=lambda item: item["created_at"] or "", reverse=True)
        items = items[: min(max(limit, 1), 200)]
        generic_unread = self.session.scalar(
            select(func.count(UserNotification.id)).where(
                UserNotification.user_id == self.user_id,
                UserNotification.dismissed_at.is_(None),
                UserNotification.read_at.is_(None),
            )
        )
        release_unread = self.session.scalar(
            select(func.count(ReleaseEvent.id)).where(
                ReleaseEvent.user_id == self.user_id,
                ReleaseEvent.dismissed_at.is_(None),
                ReleaseEvent.read_at.is_(None),
            )
        )
        return {"items": items, "unread": int(generic_unread or 0) + int(release_unread or 0)}

    def update_inbox(self, source_kind: str, item_id: str, action: str) -> dict[str, Any]:
        model = ReleaseEvent if source_kind == "release" else UserNotification
        row = self.session.scalar(
            select(model).where(model.id == item_id, model.user_id == self.user_id)
        )
        if row is None:
            raise NotificationError("Notification not found.")
        now = utcnow()
        if action == "read":
            row.read_at = now
        elif action == "unread":
            row.read_at = None
        elif action == "dismiss":
            row.dismissed_at = now
            row.read_at = row.read_at or now
        else:
            raise NotificationError("Notification action is invalid.")
        self.session.commit()
        return self.inbox()

    def settings(self) -> dict[str, Any]:
        endpoints = list(
            self.session.scalars(
                select(NotificationEndpoint)
                .where(NotificationEndpoint.user_id == self.user_id)
                .order_by(NotificationEndpoint.created_at)
            )
        )
        rules = list(
            self.session.scalars(
                select(NotificationRule)
                .where(NotificationRule.user_id == self.user_id)
                .order_by(NotificationRule.created_at)
            )
        )
        return {
            "endpoints": [self._endpoint_out(row) for row in endpoints],
            "rules": [self._rule_out(row) for row in rules],
            "capabilities": self.adapters.capabilities() if self.adapters else [],
        }

    @staticmethod
    def _endpoint_out(row: NotificationEndpoint) -> dict[str, Any]:
        return {
            "id": row.id,
            "label": row.label,
            "adapter": row.adapter,
            "redacted_hint": row.redacted_hint,
            "enabled": row.enabled,
            "verified_at": _iso(row.verified_at),
            "last_test_at": _iso(row.last_test_at),
            "last_success_at": _iso(row.last_success_at),
            "last_failure_code": row.last_failure_code,
            "failure_count": row.failure_count,
            "version": row.version,
        }

    @staticmethod
    def _rule_out(row: NotificationRule) -> dict[str, Any]:
        return {
            "id": row.id,
            "event_pattern": row.event_pattern,
            "enabled": row.enabled,
            "lead_time_hours": row.lead_time_hours,
            "quiet_start": row.quiet_start,
            "quiet_end": row.quiet_end,
            "timezone": row.timezone,
            "endpoint_id": row.endpoint_id,
            "in_app_enabled": row.in_app_enabled,
            "external_enabled": row.external_enabled,
            "version": row.version,
        }

    def create_endpoint(
        self,
        *,
        label: str,
        adapter: str,
        destination: str,
        storage: str | None,
        trusted_managed_api: bool = False,
    ) -> dict[str, Any]:
        label = _clean(label, 120)
        destination = destination.strip()
        if not label:
            raise NotificationError("Endpoint label is required.")
        if trusted_managed_api:
            parsed = urlsplit(destination)
            if (
                adapter != "apprise_api"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or not parsed.path.startswith("/notify/")
                or parsed.query
                or parsed.fragment
                or len(destination) > 2_000
            ):
                raise NotificationError("The managed Apprise API endpoint is invalid.")
        else:
            self._validate_destination(adapter, destination)
        registered = self.adapters.get(adapter) if self.adapters else None
        available = getattr(registered, "available", lambda: True)() if registered else False
        if not available:
            raise NotificationError("This notification adapter is unavailable.")
        validator = getattr(registered, "validate_destination", None)
        if validator and not validator(destination):
            raise NotificationError("This notification destination is not supported.")
        endpoint = NotificationEndpoint(
            user_id=self.user_id,
            label=label,
            adapter=adapter,
            secret_reference="pending",
            redacted_hint=f"{adapter.replace('_', ' ').title()} · {label}",
        )
        self.session.add(endpoint)
        self.session.flush()
        namespace = f"notification.{endpoint.id}"
        try:
            self.secrets.save_named(namespace, "destination", destination, storage=storage)
            endpoint.secret_reference = namespace
            self.session.commit()
        except Exception:
            self.session.rollback()
            self.secrets.clear_namespace(namespace, ["destination"])
            raise
        return self._endpoint_out(endpoint)

    def create_managed_apprise_endpoint(self, destination: str) -> dict[str, Any]:
        existing = self.session.scalar(
            select(NotificationEndpoint).where(
                NotificationEndpoint.user_id == self.user_id,
                NotificationEndpoint.adapter == "apprise_api",
                NotificationEndpoint.label == "Docker Apprise API",
            )
        )
        if existing is not None:
            return self._endpoint_out(existing)
        return self.create_endpoint(
            label="Docker Apprise API",
            adapter="apprise_api",
            destination=destination,
            storage="local_secret_file",
            trusted_managed_api=True,
        )

    @staticmethod
    def _validate_destination(adapter: str, destination: str) -> None:
        parsed = urlsplit(destination)
        scheme = parsed.scheme.casefold()
        if adapter == "apprise":
            if not scheme or scheme in DENIED_APPRISE_SCHEMES or len(destination) > 8_000:
                raise NotificationError("This Apprise destination scheme is not allowed.")
        elif adapter == "apprise_api":
            loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
            if not parsed.hostname or (parsed.scheme != "https" and not loopback):
                raise NotificationError("Apprise API destinations require HTTPS or loopback.")
            if parsed.username or parsed.password or len(destination) > 2_000:
                raise NotificationError("Apprise API destination is invalid.")
        else:
            raise NotificationError("Unknown notification adapter.")

    def update_endpoint(
        self, endpoint_id: str, *, enabled: bool, expected_version: int | None = None
    ) -> dict[str, Any]:
        endpoint = self._endpoint(endpoint_id)
        if expected_version is not None and endpoint.version != expected_version:
            raise NotificationError("Notification endpoint changed; reload and try again.")
        endpoint.enabled = enabled
        if enabled:
            endpoint.failure_count = 0
            endpoint.last_failure_code = None
        endpoint.version += 1
        self.session.commit()
        return self._endpoint_out(endpoint)

    def _endpoint(self, endpoint_id: str) -> NotificationEndpoint:
        endpoint = self.session.scalar(
            select(NotificationEndpoint).where(
                NotificationEndpoint.id == endpoint_id,
                NotificationEndpoint.user_id == self.user_id,
            )
        )
        if endpoint is None:
            raise NotificationError("Notification endpoint not found.")
        return endpoint

    def delete_endpoint(self, endpoint_id: str) -> None:
        endpoint = self._endpoint(endpoint_id)
        reference = endpoint.secret_reference
        self.session.delete(endpoint)
        self.session.commit()
        self.secrets.clear_namespace(reference, ["destination"])

    async def test_endpoint(self, endpoint_id: str) -> dict[str, Any]:
        endpoint = self._endpoint(endpoint_id)
        now = utcnow()
        if endpoint.last_test_at and now - _aware(endpoint.last_test_at) < timedelta(
            seconds=30
        ):
            raise NotificationError("Wait 30 seconds before sending another test.")
        endpoint.last_test_at = now
        self.session.commit()
        destination, _storage = self.secrets.get_named(
            endpoint.secret_reference, "destination", refresh=True
        )
        adapter = self.adapters.get(endpoint.adapter) if self.adapters else None
        if not destination or adapter is None:
            raise NotificationError("Notification endpoint is unavailable.")
        try:
            await adapter.send(
                destination,
                title="PMT notification test",
                body="Your Personal Media Tracker notification connection is working.",
                dedupe_key=f"test:{endpoint.id}:{int(now.timestamp())}",
            )
        except NotificationAdapterError as exc:
            endpoint.failure_count += 1
            endpoint.last_failure_code = exc.code
            self.session.commit()
            raise NotificationError(exc.safe_message) from exc
        endpoint.verified_at = now
        endpoint.last_success_at = now
        endpoint.failure_count = 0
        endpoint.last_failure_code = None
        self.session.commit()
        return self._endpoint_out(endpoint)

    def replace_rules(self, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(values) > 50:
            raise NotificationError("Too many notification rules.")
        existing = list(
            self.session.scalars(
                select(NotificationRule).where(NotificationRule.user_id == self.user_id)
            )
        )
        for row in existing:
            self.session.delete(row)
        self.session.flush()
        created: list[NotificationRule] = []
        for value in values:
            pattern = str(value.get("event_pattern") or "")
            if not EVENT_PATTERN.fullmatch(pattern):
                raise NotificationError("Notification event pattern is invalid.")
            endpoint_id = value.get("endpoint_id")
            external = bool(value.get("external_enabled"))
            if external:
                if not endpoint_id:
                    raise NotificationError("External rules require an endpoint.")
                self._endpoint(str(endpoint_id))
            timezone = str(value.get("timezone") or "UTC")
            try:
                ZoneInfo(timezone)
            except ZoneInfoNotFoundError as exc:
                raise NotificationError("Notification timezone is invalid.") from exc
            _next_allowed(
                utcnow(),
                start=value.get("quiet_start"),
                end=value.get("quiet_end"),
                timezone=timezone,
            )
            lead = int(value.get("lead_time_hours") or 0)
            if lead not in {0, 24, 168}:
                raise NotificationError("Release lead time must be day-of, 1 day, or 7 days.")
            row = NotificationRule(
                user_id=self.user_id,
                event_pattern=pattern,
                enabled=bool(value.get("enabled", True)),
                lead_time_hours=lead,
                quiet_start=value.get("quiet_start"),
                quiet_end=value.get("quiet_end"),
                timezone=timezone,
                endpoint_id=str(endpoint_id) if endpoint_id else None,
                in_app_enabled=bool(value.get("in_app_enabled", True)),
                external_enabled=external,
            )
            self.session.add(row)
            created.append(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise NotificationError("Duplicate notification rule.") from exc
        return [self._rule_out(row) for row in created]

    def deliveries(self, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        statement = select(NotificationOutbox).where(NotificationOutbox.user_id == self.user_id)
        if state:
            statement = statement.where(NotificationOutbox.state == state)
        rows = self.session.scalars(
            statement.order_by(NotificationOutbox.created_at.desc()).limit(limit)
        )
        return [
            {
                "id": row.id,
                "endpoint_id": row.endpoint_id,
                "event_type": row.event_type,
                "title": row.title,
                "state": row.state,
                "attempt_count": row.attempt_count,
                "due_at": _iso(row.due_at),
                "delivered_at": _iso(row.delivered_at),
            }
            for row in rows
        ]


class NotificationDeliveryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        secrets: SecretStore,
        adapters: NotificationAdapterRegistry,
        *,
        worker_id: str | None = None,
    ):
        self.session_factory = session_factory
        self.secrets = secrets
        self.adapters = adapters
        self.worker_id = worker_id or f"{socket.gethostname()}:{uuid4().hex[:10]}"

    def _claim(self, limit: int) -> list[str]:
        now = utcnow()
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.due_at <= now,
                        or_(
                            NotificationOutbox.state.in_(("pending", "retry")),
                            (
                                (NotificationOutbox.state == "leased")
                                & (NotificationOutbox.lease_expires_at < now)
                            ),
                        ),
                    )
                    .order_by(NotificationOutbox.due_at, NotificationOutbox.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            claimed: list[str] = []
            for row in rows:
                row.state = "leased"
                row.lease_owner = self.worker_id
                row.lease_expires_at = now + timedelta(minutes=2)
                row.attempt_count += 1
                claimed.append(row.id)
            session.commit()
            return claimed

    async def deliver_due(self, *, limit: int = 20) -> dict[str, int]:
        counts = {"delivered": 0, "retry": 0, "failed": 0, "skipped": 0}
        for outbox_id in self._claim(max(1, min(limit, 50))):
            outcome = await self._deliver(outbox_id)
            counts[outcome] += 1
        return counts

    async def _deliver(self, outbox_id: str) -> str:
        with self.session_factory() as session:
            row = session.scalar(
                select(NotificationOutbox).where(
                    NotificationOutbox.id == outbox_id,
                    NotificationOutbox.state == "leased",
                    NotificationOutbox.lease_owner == self.worker_id,
                )
            )
            if row is None:
                return "skipped"
            endpoint = session.scalar(
                select(NotificationEndpoint).where(
                    NotificationEndpoint.id == row.endpoint_id,
                    NotificationEndpoint.user_id == row.user_id,
                )
            )
            if endpoint is None or not endpoint.enabled:
                row.state = "cancelled"
                row.cancelled_at = utcnow()
                session.commit()
                return "skipped"
            destination, _storage = self.secrets.get_named(
                endpoint.secret_reference, "destination", refresh=True
            )
            adapter = self.adapters.get(endpoint.adapter)
            if not destination or adapter is None:
                error = NotificationAdapterError(
                    "adapter_unavailable", "The notification adapter is unavailable."
                )
            else:
                error = None
            title, body, dedupe = row.title, row.safe_message, row.dedupe_key
            attempt = row.attempt_count
        started = utcnow()
        try:
            if error:
                raise error
            result = await adapter.send(destination, title=title, body=body, dedupe_key=dedupe)
        except NotificationAdapterError as exc:
            with self.session_factory() as session:
                row = session.get(NotificationOutbox, outbox_id)
                endpoint = session.get(NotificationEndpoint, row.endpoint_id) if row else None
                if row is None or endpoint is None:
                    return "skipped"
                row.lease_owner = None
                row.lease_expires_at = None
                endpoint.failure_count += 1
                endpoint.last_failure_code = exc.code
                permanent = not exc.retryable or row.attempt_count >= row.max_attempts
                if permanent:
                    row.state = "failed"
                else:
                    row.state = "retry"
                    delay = exc.retry_after_seconds
                    if delay is None:
                        base_delay = min(21_600, 30 * 2 ** (row.attempt_count - 1))
                        jitter_window = max(1, base_delay // 5)
                        jitter = (
                            int(
                                hashlib.sha256(
                                    f"{row.id}:{row.attempt_count}".encode()
                                ).hexdigest()[:8],
                                16,
                            )
                            % jitter_window
                        )
                        delay = base_delay + jitter
                    row.due_at = utcnow() + timedelta(seconds=delay)
                if endpoint.failure_count >= ENDPOINT_FAILURE_THRESHOLD:
                    endpoint.enabled = False
                    if endpoint.failure_count == ENDPOINT_FAILURE_THRESHOLD:
                        NotificationService.emit(
                            session,
                            NotificationEvent(
                                user_id=endpoint.user_id,
                                event_type="notifications.endpoint_paused",
                                title=endpoint.label,
                                safe_message=(
                                    "This notification destination paused after repeated "
                                    "delivery failures."
                                ),
                                source_kind="notification_endpoint",
                                source_key=f"{endpoint.id}:paused",
                                resource_type="notification_endpoint",
                                resource_id=endpoint.id,
                            ),
                        )
                session.add(
                    NotificationDeliveryAttempt(
                        outbox_id=row.id,
                        attempt_number=attempt,
                        result_category="permanent_failure"
                        if permanent
                        else "retryable_failure",
                        safe_error_code=_clean(exc.code, 80),
                        safe_error_message=_clean(exc.safe_message, 300),
                        started_at=started,
                        completed_at=utcnow(),
                    )
                )
                session.commit()
                return "failed" if permanent else "retry"
        with self.session_factory() as session:
            row = session.get(NotificationOutbox, outbox_id)
            endpoint = session.get(NotificationEndpoint, row.endpoint_id) if row else None
            if row is None or endpoint is None:
                return "skipped"
            row.state = "delivered"
            row.delivered_at = utcnow()
            row.lease_owner = None
            row.lease_expires_at = None
            endpoint.failure_count = 0
            endpoint.last_failure_code = None
            endpoint.last_success_at = utcnow()
            session.add(
                NotificationDeliveryAttempt(
                    outbox_id=row.id,
                    attempt_number=attempt,
                    result_category="delivered",
                    receipt_hash=result.receipt_hash,
                    started_at=started,
                    completed_at=utcnow(),
                )
            )
            session.commit()
        return "delivered"
