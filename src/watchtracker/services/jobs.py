from __future__ import annotations

import asyncio
import inspect
import logging
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.models import ScheduledJob, UserAccount, UserNotification

logger = logging.getLogger(__name__)
JobHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class RetryableJobError(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class DurableJobService:
    """Database compare-and-swap leases with bounded retry and pause behavior."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        lease_seconds: int = 600,
        worker_id: str | None = None,
        now_factory: Callable[[], datetime] = _now,
    ):
        self.session_factory = session_factory
        self.lease_seconds = max(30, lease_seconds)
        self.worker_id = worker_id or f"{socket.gethostname()}:{uuid4()}"
        self.now_factory = now_factory

    def enqueue(
        self,
        kind: str,
        *,
        idempotency_key: str,
        due_at: datetime | None = None,
        user_id: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        payload: dict[str, Any] | None = None,
        priority: int = 100,
        max_attempts: int = 5,
    ) -> ScheduledJob:
        now = self.now_factory()
        with self.session_factory() as session:
            existing = session.scalar(
                select(ScheduledJob).where(ScheduledJob.idempotency_key == idempotency_key)
            )
            if existing is not None:
                existing.kind = kind[:80]
                existing.user_id = user_id
                existing.scope_type = scope_type
                existing.scope_id = scope_id
                existing.payload = payload or {}
                existing.priority = priority
                existing.max_attempts = max(1, max_attempts)
                if existing.state in {"completed", "cancelled"}:
                    existing.state = "scheduled"
                    existing.completed_at = None
                    existing.attempts = 0
                    existing.last_error_code = None
                    existing.last_error_message = None
                if due_at is not None and _aware(existing.due_at) > _aware(due_at):
                    existing.due_at = due_at
                session.commit()
                return existing
            job = ScheduledJob(
                kind=kind[:80],
                user_id=user_id,
                scope_type=scope_type,
                scope_id=scope_id,
                payload=payload or {},
                state="scheduled",
                due_at=due_at or now,
                priority=priority,
                attempts=0,
                max_attempts=max(1, max_attempts),
                idempotency_key=idempotency_key[:160],
            )
            session.add(job)
            session.commit()
            return job

    def claim(self, *, kinds: set[str] | None = None) -> ScheduledJob | None:
        now = self.now_factory()
        with self.session_factory() as session:
            statement = (
                select(ScheduledJob.id)
                .where(
                    ScheduledJob.state.in_(("scheduled", "retry")),
                    ScheduledJob.due_at <= now,
                    or_(
                        ScheduledJob.lease_expires_at.is_(None),
                        ScheduledJob.lease_expires_at < now,
                    ),
                )
                .order_by(
                    ScheduledJob.priority,
                    ScheduledJob.due_at,
                    ScheduledJob.created_at,
                )
                .limit(20)
            )
            if kinds:
                statement = statement.where(ScheduledJob.kind.in_(kinds))
            candidates = list(session.scalars(statement))
            for job_id in candidates:
                claimed = session.execute(
                    update(ScheduledJob)
                    .where(
                        ScheduledJob.id == job_id,
                        ScheduledJob.state.in_(("scheduled", "retry")),
                        ScheduledJob.due_at <= now,
                        or_(
                            ScheduledJob.lease_expires_at.is_(None),
                            ScheduledJob.lease_expires_at < now,
                        ),
                    )
                    .values(
                        state="running",
                        lease_owner=self.worker_id,
                        lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                        attempts=ScheduledJob.attempts + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                session.commit()
                if claimed.rowcount:
                    return session.get(ScheduledJob, job_id)
        return None

    def complete(self, job_id: str) -> None:
        now = self.now_factory()
        with self.session_factory() as session:
            job = session.scalar(
                select(ScheduledJob).where(
                    ScheduledJob.id == job_id,
                    ScheduledJob.lease_owner == self.worker_id,
                    ScheduledJob.state == "running",
                )
            )
            if job is None:
                return
            repeat_seconds = int((job.payload or {}).get("_repeat_seconds") or 0)
            job.state = "scheduled" if repeat_seconds > 0 else "completed"
            job.due_at = now + timedelta(seconds=repeat_seconds) if repeat_seconds else now
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_error_code = None
            job.last_error_message = None
            if repeat_seconds:
                job.attempts = 0
            session.commit()

    def fail(
        self,
        job_id: str,
        *,
        error_code: str,
        safe_message: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        now = self.now_factory()
        with self.session_factory() as session:
            job = session.scalar(
                select(ScheduledJob).where(
                    ScheduledJob.id == job_id,
                    ScheduledJob.lease_owner == self.worker_id,
                    ScheduledJob.state == "running",
                )
            )
            if job is None:
                return
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_error_code = error_code[:80]
            job.last_error_message = " ".join(safe_message.split())[:300]
            if job.attempts >= job.max_attempts:
                job.state = "paused"
                if job.paused_notified_at is None:
                    self._pause_notifications(session, job)
                    job.paused_notified_at = now
            else:
                delay = retry_after_seconds or min(21_600, 30 * (2 ** (job.attempts - 1)))
                job.state = "retry"
                job.due_at = now + timedelta(seconds=max(1, delay))
            session.commit()

    @staticmethod
    def _pause_notifications(session: Session, job: ScheduledJob) -> None:
        user_ids = (
            [job.user_id]
            if job.user_id
            else list(
                session.scalars(
                    select(UserAccount.id).where(
                        UserAccount.role == "admin", UserAccount.state == "active"
                    )
                )
            )
        )
        for user_id in user_ids:
            if user_id:
                session.add(
                    UserNotification(
                        user_id=user_id,
                        event_type="job_paused",
                        title="Background task needs attention",
                        safe_message=f"{job.kind.replace('_', ' ').title()} paused after repeated failures.",
                        resource_type="scheduled_job",
                        resource_id=job.id,
                    )
                )

    def resume(self, job_id: str) -> bool:
        with self.session_factory() as session:
            job = session.get(ScheduledJob, job_id)
            if job is None or job.state != "paused":
                return False
            job.state = "scheduled"
            job.due_at = self.now_factory()
            job.attempts = 0
            job.paused_notified_at = None
            job.last_error_code = None
            job.last_error_message = None
            session.commit()
            return True

    def cancel(self, job_id: str) -> bool:
        with self.session_factory() as session:
            job = session.get(ScheduledJob, job_id)
            if job is None or job.state == "running":
                return False
            job.state = "cancelled"
            job.completed_at = self.now_factory()
            session.commit()
            return True

    def list_safe(self, *, user_id: str | None = None, admin: bool = False) -> list[dict]:
        with self.session_factory() as session:
            statement = select(ScheduledJob)
            if not admin:
                statement = statement.where(ScheduledJob.user_id == user_id)
            rows = session.scalars(
                statement.order_by(ScheduledJob.updated_at.desc()).limit(200)
            )
            return [
                {
                    "id": job.id,
                    "kind": job.kind,
                    "scope_type": job.scope_type,
                    "scope_id": job.scope_id,
                    "state": job.state,
                    "due_at": job.due_at,
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "last_error_code": job.last_error_code,
                    "last_error_message": job.last_error_message,
                    "updated_at": job.updated_at,
                    "completed_at": job.completed_at,
                }
                for job in rows
            ]


class DurableJobRunner:
    def __init__(
        self,
        service: DurableJobService,
        handlers: dict[str, JobHandler],
        *,
        concurrency: int = 2,
        poll_seconds: float = 2.0,
    ):
        self.service = service
        self.handlers = handlers
        self.concurrency = max(1, min(concurrency, 8))
        self.poll_seconds = max(0.1, poll_seconds)
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self.serve(), name="pmt-durable-jobs")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def serve(self) -> None:
        active: set[asyncio.Task] = set()
        try:
            while not self._stop.is_set():
                active = {task for task in active if not task.done()}
                while len(active) < self.concurrency:
                    job = self.service.claim(kinds=set(self.handlers))
                    if job is None:
                        break
                    task = asyncio.create_task(self._execute(job), name=f"pmt-job-{job.id}")
                    active.add(task)
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
        finally:
            if active:
                await asyncio.gather(*active, return_exceptions=True)

    async def run_once(self) -> bool:
        job = self.service.claim(kinds=set(self.handlers))
        if job is None:
            return False
        await self._execute(job)
        return True

    async def _execute(self, job: ScheduledJob) -> None:
        handler = self.handlers.get(job.kind)
        if handler is None:
            self.service.fail(
                job.id,
                error_code="handler_unavailable",
                safe_message="This task type is unavailable in the current worker.",
            )
            return
        try:
            result = handler(dict(job.payload or {}))
            if inspect.isawaitable(result):
                await result
        except RetryableJobError as exc:
            self.service.fail(
                job.id,
                error_code="retryable_failure",
                safe_message=str(exc),
                retry_after_seconds=exc.retry_after_seconds,
            )
        except Exception as exc:
            logger.error(
                "Durable job failed safely: kind=%s type=%s", job.kind, type(exc).__name__
            )
            self.service.fail(
                job.id,
                error_code=type(exc).__name__,
                safe_message="The background task failed safely.",
            )
        else:
            self.service.complete(job.id)
