from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.config import Settings
from watchtracker.models import CalendarFeedToken, LoginThrottle, OwnerAccount, OwnerSession

SESSION_COOKIE = "pmt_session"
CSRF_COOKIE = "pmt_csrf"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    expires_at: datetime


class AuthService:
    """Single-owner Argon2id authentication with opaque, revocable sessions."""

    def __init__(self, session_factory: sessionmaker[Session], settings: Settings):
        self.session_factory = session_factory
        self.settings = settings
        self.passwords = PasswordHash.recommended()
        # A dummy hash keeps missing-owner and wrong-password work comparable.
        self._dummy_hash = self.passwords.hash(secrets.token_urlsafe(24))

    def _digest(self, purpose: str, value: str) -> str:
        secret = (self.settings.application_secret or "local-mode-session-key").encode()
        return hmac.new(secret, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()

    def owner_exists(self) -> bool:
        with self.session_factory() as session:
            return session.scalar(select(OwnerAccount.id).limit(1)) is not None

    def bootstrap(self, password: str) -> OwnerAccount:
        if self.settings.access_mode != "local":
            raise ValueError("Owner setup is available only while the app is local-only.")
        if len(password) < 12:
            raise ValueError("Use an owner password with at least 12 characters.")
        with self.session_factory() as session, session.begin():
            if session.scalar(select(OwnerAccount.id).limit(1)) is not None:
                raise ValueError("The owner account has already been set up.")
            owner = OwnerAccount(username="owner", password_hash=self.passwords.hash(password))
            session.add(owner)
            session.flush()
            return owner

    def require_server_owner(self) -> None:
        if self.settings.access_mode == "server" and not self.owner_exists():
            raise RuntimeError(
                "Server mode has no owner account. Return to local mode and complete "
                "Settings → Access & Devices before enabling shared access."
            )

    def verify_owner_password(self, password: str) -> bool:
        with self.session_factory() as session:
            owner = session.scalar(select(OwnerAccount).limit(1))
            return bool(owner and self.passwords.verify(password, owner.password_hash))

    def _identity(self, client_identity: str) -> str:
        return self._digest("login", client_identity.casefold())

    def login(self, username: str, password: str, client_identity: str) -> IssuedSession | None:
        now = datetime.now(UTC)
        identity_hash = self._identity(client_identity)
        with self.session_factory() as session, session.begin():
            session.execute(
                delete(OwnerSession).where(
                    or_(
                        OwnerSession.expires_at <= now,
                        OwnerSession.revoked_at.is_not(None),
                    )
                )
            )
            throttle = session.get(LoginThrottle, identity_hash)
            blocked = bool(
                throttle and throttle.blocked_until and _utc(throttle.blocked_until) > now
            )
            owner = session.scalar(
                select(OwnerAccount).where(OwnerAccount.username == username)
            )
            stored_hash = owner.password_hash if owner is not None else self._dummy_hash
            valid = self.passwords.verify(password, stored_hash)
            if blocked or owner is None or not valid:
                if throttle is None:
                    throttle = LoginThrottle(identity_hash=identity_hash, failure_count=0)
                    session.add(throttle)
                throttle.failure_count += 1
                delay = (
                    min(2 ** min(throttle.failure_count - 5, 10), 900)
                    if throttle.failure_count >= 5
                    else 0
                )
                throttle.blocked_until = now + timedelta(seconds=delay)
                return None
            if throttle is not None:
                session.delete(throttle)
            return self._issue(session, owner, now)

    def _issue(self, session: Session, owner: OwnerAccount, now: datetime) -> IssuedSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(hours=self.settings.session_ttl_hours)
        session.add(
            OwnerSession(
                owner_id=owner.id,
                token_hash=self._digest("session", session_token),
                csrf_hash=self._digest("csrf", csrf_token),
                expires_at=expires_at,
            )
        )
        return IssuedSession(session_token, csrf_token, expires_at)

    def authenticate(self, token: str | None) -> OwnerSession | None:
        if not token:
            return None
        token_hash = self._digest("session", token)
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(OwnerSession).where(OwnerSession.token_hash == token_hash)
            )
            if (
                record is None
                or record.revoked_at is not None
                or _utc(record.expires_at) <= now
            ):
                return None
            if _utc(record.last_seen_at) < now - timedelta(minutes=5):
                record.last_seen_at = now
            session.expunge(record)
            return record

    def valid_csrf(self, record: OwnerSession, value: str | None) -> bool:
        if not value:
            return False
        return hmac.compare_digest(record.csrf_hash, self._digest("csrf", value))

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(OwnerSession).where(
                    OwnerSession.token_hash == self._digest("session", token)
                )
            )
            if record is not None:
                record.revoked_at = datetime.now(UTC)

    def revoke_all(self) -> int:
        with self.session_factory() as session, session.begin():
            result = session.execute(delete(OwnerSession))
            return int(result.rowcount or 0)

    def change_password(self, current_password: str, new_password: str) -> bool:
        if len(new_password) < 12:
            return False
        with self.session_factory() as session, session.begin():
            owner = session.scalar(select(OwnerAccount).limit(1))
            if owner is None or not self.passwords.verify(
                current_password, owner.password_hash
            ):
                return False
            owner.password_hash = self.passwords.hash(new_password)
            owner.password_changed_at = datetime.now(UTC)
            session.execute(delete(OwnerSession))
            return True

    def issue_calendar_feed(self) -> str:
        raw = secrets.token_urlsafe(32)
        with self.session_factory() as session, session.begin():
            session.add(CalendarFeedToken(token_hash=self._digest("calendar-feed", raw)))
        return raw

    def validate_calendar_feed(self, raw: str | None) -> bool:
        if not raw:
            return False
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.token_hash == self._digest("calendar-feed", raw),
                    CalendarFeedToken.revoked_at.is_(None),
                )
            )
            if record is None:
                return False
            record.last_used_at = datetime.now(UTC)
            return True

    def revoke_calendar_feeds(self) -> int:
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            records = session.scalars(
                select(CalendarFeedToken).where(CalendarFeedToken.revoked_at.is_(None))
            ).all()
            for record in records:
                record.revoked_at = now
            return len(records)
