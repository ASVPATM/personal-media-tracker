from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.config import Settings
from watchtracker.models import (
    AccountInvitation,
    CalendarFeedToken,
    IntegrationConnection,
    LoginThrottle,
    OwnerAccount,
    ServerAuditEvent,
    UserAccount,
    UserSession,
    WatchEntry,
    WebhookCredential,
)

SESSION_COOKIE = "pmt_session"
CSRF_COOKIE = "pmt_csrf"
USERNAME_PATTERN = re.compile(r"^[\w.-]{3,80}$", re.UNICODE)
NATIVE_ACCESS_MINUTES = 15
NATIVE_REFRESH_DAYS = 30


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str | None
    expires_at: datetime
    session_id: str
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None


@dataclass(frozen=True)
class IssuedInvitation:
    invitation_id: str
    token: str
    kind: str
    expires_at: datetime


class AuthService:
    """Multi-user Argon2id authentication with opaque, revocable sessions."""

    def __init__(self, session_factory: sessionmaker[Session], settings: Settings):
        self.session_factory = session_factory
        self.settings = settings
        self.passwords = PasswordHash.recommended()
        self._dummy_hash = self.passwords.hash(secrets.token_urlsafe(24))

    def _digest(self, purpose: str, value: str) -> str:
        secret = (self.settings.application_secret or "local-mode-session-key").encode()
        return hmac.new(secret, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _validate_username(username: str) -> str:
        value = unicodedata.normalize("NFKC", username).strip()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError(
                "Usernames must be 3–80 characters using letters, numbers, '.', '-' or '_'."
            )
        return value

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 12:
            raise ValueError("Use a password with at least 12 characters.")

    @staticmethod
    def _audit(
        session: Session,
        event_type: str,
        summary: str,
        *,
        actor_user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> None:
        session.add(
            ServerAuditEvent(
                actor_user_id=actor_user_id,
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                safe_summary=summary[:300],
            )
        )

    def owner_exists(self) -> bool:
        """Compatibility name: true when an active password administrator exists."""
        with self.session_factory() as session:
            return (
                session.scalar(
                    select(UserAccount.id)
                    .where(
                        UserAccount.role == "admin",
                        UserAccount.state == "active",
                        UserAccount.password_hash.is_not(None),
                    )
                    .limit(1)
                )
                is not None
            )

    def server_account_identity(self) -> dict[str, str] | None:
        """Return the server-account sign-in hint for an authorized host-local UI."""
        with self.session_factory() as session:
            account = session.scalar(
                select(UserAccount)
                .where(
                    UserAccount.role == "admin",
                    UserAccount.state == "active",
                    UserAccount.password_hash.is_not(None),
                )
                .limit(1)
            )
            if account is None:
                return None
            return {
                "username": account.username,
                "display_name": account.display_name,
            }

    def bootstrap(
        self,
        password: str,
        *,
        username: str = "owner",
        display_name: str = "Owner",
        allow_server: bool = False,
    ) -> UserAccount:
        if self.settings.access_mode != "local" and not allow_server:
            raise ValueError("Administrator setup requires the one-time server setup flow.")
        self._validate_password(password)
        username = self._validate_username(username)
        normalized = _normalize(username)
        with self.session_factory() as session, session.begin():
            if (
                session.scalar(
                    select(UserAccount.id)
                    .where(
                        UserAccount.role == "admin",
                        UserAccount.password_hash.is_not(None),
                    )
                    .limit(1)
                )
                is not None
            ):
                raise ValueError("The server-owner account has already been set up.")
            user = session.scalar(
                select(UserAccount)
                .where(UserAccount.state == "active")
                .order_by(UserAccount.created_at, UserAccount.id)
                .limit(1)
            )
            password_hash = self.passwords.hash(password)
            if user is None:
                user = UserAccount(
                    username=username,
                    normalized_username=normalized,
                    display_name=display_name.strip() or username,
                    role="admin",
                    state="active",
                )
                session.add(user)
                session.flush()
            else:
                collision = session.scalar(
                    select(UserAccount.id).where(
                        UserAccount.normalized_username == normalized,
                        UserAccount.id != user.id,
                    )
                )
                if collision:
                    raise ValueError("That username is already in use.")
                user.username = username
                user.normalized_username = normalized
                user.display_name = display_name.strip() or username
                user.role = "admin"
                user.state = "active"
            user.password_hash = password_hash
            user.password_changed_at = datetime.now(UTC)

            # Retain the first-owner row only for downgrade compatibility.
            owner = session.get(OwnerAccount, user.id)
            if owner is None:
                session.add(
                    OwnerAccount(
                        id=user.id,
                        username=username,
                        password_hash=password_hash,
                    )
                )
            else:
                owner.username = username
                owner.password_hash = password_hash
                owner.password_changed_at = user.password_changed_at
            self._audit(
                session,
                "server_bootstrap_completed",
                "Initial server-owner account created.",
                actor_user_id=user.id,
                target_type="user",
                target_id=user.id,
            )
            session.flush()
            return user

    def bootstrap_server(
        self, token: str, password: str, *, username: str, display_name: str
    ) -> UserAccount:
        configured = self.settings.server_bootstrap_token
        if self.settings.access_mode != "server" or not configured:
            raise ValueError("Server bootstrap is not available.")
        if not hmac.compare_digest(configured, token):
            raise ValueError("The one-time setup token is invalid.")
        return self.bootstrap(
            password,
            username=username,
            display_name=display_name,
            allow_server=True,
        )

    def require_server_owner(self) -> None:
        if (
            self.settings.access_mode == "server"
            and not self.owner_exists()
            and not self.settings.server_bootstrap_token
        ):
            raise RuntimeError(
                "Server mode has no server-owner account. Set WATCHTRACKER_SERVER_BOOTSTRAP_TOKEN "
                "to a random one-time value, start PMT Server, and complete first-run setup."
            )

    def verify_owner_password(self, password: str) -> bool:
        with self.session_factory() as session:
            account = session.scalar(
                select(UserAccount)
                .where(
                    UserAccount.role == "admin",
                    UserAccount.state == "active",
                    UserAccount.password_hash.is_not(None),
                )
                .limit(1)
            )
            return bool(
                account
                and account.password_hash
                and self.passwords.verify(password, account.password_hash)
            )

    def _identity(self, client_identity: str, username: str = "") -> str:
        return self._digest("login", f"{client_identity.casefold()}:{_normalize(username)}")

    def login(
        self,
        username: str,
        password: str,
        client_identity: str,
        *,
        device_label: str | None = None,
    ) -> IssuedSession | None:
        now = datetime.now(UTC)
        normalized = _normalize(username)
        identity_hash = self._identity(client_identity, normalized)
        with self.session_factory() as session, session.begin():
            throttle = session.get(LoginThrottle, identity_hash)
            blocked = bool(
                throttle and throttle.blocked_until and _utc(throttle.blocked_until) > now
            )
            account = session.scalar(
                select(UserAccount).where(
                    or_(
                        UserAccount.normalized_username == normalized,
                        UserAccount.normalized_email == normalized,
                    )
                )
            )
            stored_hash = (
                account.password_hash
                if account is not None and account.password_hash
                else self._dummy_hash
            )
            valid = self.passwords.verify(password, stored_hash)
            if blocked or account is None or account.state != "active" or not valid:
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
            return self._issue_browser(session, account, now, device_label=device_label)

    def _issue_browser(
        self,
        session: Session,
        account: UserAccount,
        now: datetime,
        *,
        device_label: str | None,
        device_id: str | None = None,
        ttl: timedelta | None = None,
        scopes: list[str] | None = None,
    ) -> IssuedSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + (ttl or timedelta(hours=self.settings.session_ttl_hours))
        record = UserSession(
            user_id=account.id,
            session_kind="browser",
            device_id=device_id[:80] if device_id else None,
            device_label=(device_label or "Web browser")[:120],
            token_hash=self._digest("session", session_token),
            csrf_hash=self._digest("csrf", csrf_token),
            scopes=scopes or [],
            expires_at=expires_at,
        )
        session.add(record)
        session.flush()
        return IssuedSession(session_token, csrf_token, expires_at, record.id)

    def issue_browser_handoff(
        self, user_id: str, *, device_id: str, device_label: str
    ) -> IssuedSession:
        """Create a two-minute, one-use bridge from a native token to web cookies.

        The raw value is placed only in a URL fragment by the installed client, so
        it is never sent in a server request or access log. The browser exchanges it
        immediately and the database record is consumed atomically.
        """
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            account = session.get(UserAccount, user_id)
            if account is None or account.state != "active":
                raise ValueError("This account is not active.")
            return self._issue_browser(
                session,
                account,
                now,
                device_label=f"PMT app handoff · {device_label}"[:120],
                device_id=device_id,
                ttl=timedelta(minutes=2),
                scopes=["browser:handoff"],
            )

    def adopt_browser_handoff(self, token: str, *, device_label: str) -> IssuedSession | None:
        """Consume a native-app handoff and return a normal browser session."""
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(UserSession).where(
                    UserSession.token_hash == self._digest("session", token),
                    UserSession.session_kind == "browser",
                )
            )
            account = session.get(UserAccount, record.user_id) if record else None
            if (
                record is None
                or record.revoked_at is not None
                or _utc(record.expires_at) <= now
                or record.scopes != ["browser:handoff"]
                or account is None
                or account.state != "active"
            ):
                return None
            device_id = record.device_id
            if device_id:
                session.execute(
                    delete(UserSession).where(
                        UserSession.user_id == account.id,
                        UserSession.session_kind == "browser",
                        UserSession.device_id == device_id,
                        UserSession.id != record.id,
                    )
                )
            session.delete(record)
            session.flush()
            return self._issue_browser(
                session,
                account,
                now,
                device_label=device_label,
                device_id=device_id,
            )

    def login_trusted_legacy_host(self) -> IssuedSession | None:
        """Open a migrated personal profile from its verified desktop host.

        Older PMT releases promoted the one local profile to the server account
        when Shared Access was enabled.  Requiring that same person to sign into
        their own Mac made server hosting replace the local-app experience.  The
        launcher supplies a random, per-process secret over loopback; the route
        verifies that proof before calling this method.  Fresh dedicated server
        accounts and remote browsers never qualify.
        """
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            account = session.scalar(
                select(UserAccount)
                .where(
                    UserAccount.role == "admin",
                    UserAccount.state == "active",
                    select(WatchEntry.id)
                    .where(
                        WatchEntry.user_id == UserAccount.id,
                        WatchEntry.deleted_at.is_(None),
                    )
                    .exists(),
                )
                .order_by(UserAccount.created_at, UserAccount.id)
                .limit(1)
            )
            if account is None:
                return None
            issued = self._issue_browser(
                session,
                account,
                now,
                device_label="PMT app · trusted server Mac",
            )
            self._audit(
                session,
                "trusted_host_profile_opened",
                "Migrated personal profile opened from the verified native server host.",
                actor_user_id=account.id,
                target_type="user",
                target_id=account.id,
            )
            return issued

    def login_native(
        self,
        username: str,
        password: str,
        client_identity: str,
        *,
        device_id: str,
        device_label: str,
    ) -> IssuedSession | None:
        issued = self.login(username, password, client_identity, device_label=device_label)
        if issued is None:
            return None
        with self.session_factory() as session, session.begin():
            browser = session.get(UserSession, issued.session_id)
            if browser is None:
                return None
            account = session.get(UserAccount, browser.user_id)
            session.delete(browser)
            session.flush()
            return self._issue_native(
                session,
                account,
                datetime.now(UTC),
                device_id=device_id,
                device_label=device_label,
            )

    def _issue_native(
        self,
        session: Session,
        account: UserAccount,
        now: datetime,
        *,
        device_id: str,
        device_label: str,
    ) -> IssuedSession:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(48)
        expires_at = now + timedelta(minutes=NATIVE_ACCESS_MINUTES)
        refresh_expires_at = now + timedelta(days=NATIVE_REFRESH_DAYS)
        record = UserSession(
            user_id=account.id,
            session_kind="native",
            device_id=device_id[:80],
            device_label=device_label[:120],
            token_hash=self._digest("session", access),
            refresh_token_hash=self._digest("refresh", refresh),
            scopes=["library:read", "library:write", "sync"],
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
        )
        session.add(record)
        session.flush()
        return IssuedSession(
            access,
            None,
            expires_at,
            record.id,
            refresh_token=refresh,
            refresh_expires_at=refresh_expires_at,
        )

    def refresh_native(self, refresh_token: str) -> IssuedSession | None:
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(UserSession).where(
                    UserSession.refresh_token_hash == self._digest("refresh", refresh_token),
                    UserSession.session_kind == "native",
                )
            )
            account = session.get(UserAccount, record.user_id) if record else None
            if (
                record is None
                or account is None
                or account.state != "active"
                or record.revoked_at is not None
                or record.refresh_expires_at is None
                or _utc(record.refresh_expires_at) <= now
            ):
                return None
            access = secrets.token_urlsafe(32)
            refresh = secrets.token_urlsafe(48)
            record.token_hash = self._digest("session", access)
            record.refresh_token_hash = self._digest("refresh", refresh)
            record.expires_at = now + timedelta(minutes=NATIVE_ACCESS_MINUTES)
            record.refresh_expires_at = now + timedelta(days=NATIVE_REFRESH_DAYS)
            record.last_seen_at = now
            return IssuedSession(
                access,
                None,
                record.expires_at,
                record.id,
                refresh_token=refresh,
                refresh_expires_at=record.refresh_expires_at,
            )

    def authenticate(self, token: str | None, *, kind: str | None = None) -> UserSession | None:
        if not token:
            return None
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            statement = select(UserSession).where(
                UserSession.token_hash == self._digest("session", token)
            )
            if kind:
                statement = statement.where(UserSession.session_kind == kind)
            record = session.scalar(statement)
            if (
                record is None
                or record.revoked_at is not None
                or _utc(record.expires_at) <= now
            ):
                return None
            account = session.get(UserAccount, record.user_id)
            if account is None or account.state != "active":
                return None
            if _utc(record.last_seen_at) < now - timedelta(minutes=5):
                record.last_seen_at = now
            session.expunge(record)
            return record

    def valid_csrf(self, record: UserSession, value: str | None) -> bool:
        if not value or record.session_kind != "browser" or not record.csrf_hash:
            return False
        return hmac.compare_digest(record.csrf_hash, self._digest("csrf", value))

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(UserSession).where(
                    UserSession.token_hash == self._digest("session", token)
                )
            )
            if record is not None:
                now = datetime.now(UTC)
                record.revoked_at = now
                if record.device_id:
                    # A browser session opened by an installed app shares its opaque
                    # device identifier with the native refresh session. Signing out
                    # from that window must therefore require a real sign-in next time.
                    for linked in session.scalars(
                        select(UserSession).where(
                            UserSession.user_id == record.user_id,
                            UserSession.device_id == record.device_id,
                            UserSession.revoked_at.is_(None),
                        )
                    ):
                        linked.revoked_at = now

    def revoke_all(self, user_id: str | None = None) -> int:
        with self.session_factory() as session, session.begin():
            statement = delete(UserSession)
            if user_id is not None:
                statement = statement.where(UserSession.user_id == user_id)
            result = session.execute(statement)
            return int(result.rowcount or 0)

    def list_sessions(self, user_id: str) -> list[dict]:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            records = session.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                )
                .order_by(UserSession.last_seen_at.desc())
            )
            return [
                {
                    "id": record.id,
                    "kind": record.session_kind,
                    "device_id": record.device_id,
                    "device_label": record.device_label or "Unknown device",
                    "created_at": record.created_at,
                    "last_seen_at": record.last_seen_at,
                    "expires_at": record.expires_at,
                    "active": _utc(record.expires_at) > now,
                }
                for record in records
            ]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(UserSession).where(
                    UserSession.id == session_id, UserSession.user_id == user_id
                )
            )
            if record is None:
                return False
            record.revoked_at = datetime.now(UTC)
            return True

    def change_password(
        self, current_password: str, new_password: str, *, user_id: str | None = None
    ) -> bool:
        try:
            self._validate_password(new_password)
        except ValueError:
            return False
        with self.session_factory() as session, session.begin():
            statement = select(UserAccount).where(
                UserAccount.state == "active", UserAccount.password_hash.is_not(None)
            )
            if user_id is not None:
                statement = statement.where(UserAccount.id == user_id)
            account = session.scalar(statement.limit(1))
            if (
                account is None
                or not account.password_hash
                or not self.passwords.verify(current_password, account.password_hash)
            ):
                return False
            account.password_hash = self.passwords.hash(new_password)
            account.password_changed_at = datetime.now(UTC)
            owner = session.get(OwnerAccount, account.id)
            if owner is not None:
                owner.password_hash = account.password_hash
                owner.password_changed_at = account.password_changed_at
            session.execute(delete(UserSession).where(UserSession.user_id == account.id))
            self._audit(
                session,
                "password_changed",
                "Account password changed; sessions revoked.",
                actor_user_id=account.id,
                target_type="user",
                target_id=account.id,
            )
            return True

    def recover_server_account_password(self, new_password: str) -> dict[str, str]:
        """Reset the sole server account after launcher-token host verification."""
        self._validate_password(new_password)
        with self.session_factory() as session, session.begin():
            account = session.scalar(
                select(UserAccount)
                .where(
                    UserAccount.role == "admin",
                    UserAccount.state == "active",
                    UserAccount.password_hash.is_not(None),
                )
                .limit(1)
            )
            if account is None:
                raise ValueError("No active server account is available for recovery.")
            account.password_hash = self.passwords.hash(new_password)
            account.password_changed_at = datetime.now(UTC)
            owner = session.get(OwnerAccount, account.id)
            if owner is not None:
                owner.password_hash = account.password_hash
                owner.password_changed_at = account.password_changed_at
            session.execute(delete(UserSession).where(UserSession.user_id == account.id))
            self._audit(
                session,
                "server_account_recovered_locally",
                "Server-account password reset from the authenticated native host window; sessions revoked.",
                actor_user_id=account.id,
                target_type="user",
                target_id=account.id,
            )
            return {
                "id": account.id,
                "username": account.username,
                "display_name": account.display_name,
            }

    def create_invitation(
        self,
        actor_user_id: str,
        *,
        role: str = "member",
        email: str | None = None,
        expires_hours: int = 72,
        recovery_for_user_id: str | None = None,
    ) -> IssuedInvitation:
        if role not in {"admin", "member"}:
            raise ValueError("Invitation role is invalid.")
        raw = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        kind = "recovery" if recovery_for_user_id else "signup"
        with self.session_factory() as session, session.begin():
            actor = session.get(UserAccount, actor_user_id)
            if actor is None or actor.state != "active" or actor.role != "admin":
                raise PermissionError("Administrator access is required.")
            target = (
                session.get(UserAccount, recovery_for_user_id) if recovery_for_user_id else None
            )
            if recovery_for_user_id and target is None:
                raise LookupError("User account not found.")
            invitation = AccountInvitation(
                created_by_user_id=actor_user_id,
                recovery_for_user_id=recovery_for_user_id,
                kind=kind,
                role=target.role if target else role,
                token_hash=self._digest("invitation", raw),
                email=email.strip() if email else None,
                expires_at=now + timedelta(hours=expires_hours),
            )
            session.add(invitation)
            session.flush()
            self._audit(
                session,
                "recovery_created" if target else "invitation_created",
                "A short-lived account token was created.",
                actor_user_id=actor_user_id,
                target_type="user" if target else "invitation",
                target_id=target.id if target else invitation.id,
            )
            return IssuedInvitation(invitation.id, raw, kind, invitation.expires_at)

    def list_invitations(self) -> list[dict]:
        with self.session_factory() as session:
            return [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "role": item.role,
                    "email": item.email,
                    "created_at": item.created_at,
                    "expires_at": item.expires_at,
                    "consumed_at": item.consumed_at,
                    "revoked_at": item.revoked_at,
                }
                for item in session.scalars(
                    select(AccountInvitation).order_by(AccountInvitation.created_at.desc())
                )
            ]

    def revoke_invitation(self, actor_user_id: str, invitation_id: str) -> bool:
        with self.session_factory() as session, session.begin():
            invitation = session.get(AccountInvitation, invitation_id)
            if invitation is None:
                return False
            invitation.revoked_at = datetime.now(UTC)
            self._audit(
                session,
                "invitation_revoked",
                "An account token was revoked.",
                actor_user_id=actor_user_id,
                target_type="invitation",
                target_id=invitation.id,
            )
            return True

    def redeem_invitation(
        self,
        token: str,
        password: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
    ) -> UserAccount:
        self._validate_password(password)
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            invitation = session.scalar(
                select(AccountInvitation).where(
                    AccountInvitation.token_hash == self._digest("invitation", token)
                )
            )
            if (
                invitation is None
                or invitation.revoked_at is not None
                or invitation.consumed_at is not None
                or _utc(invitation.expires_at) <= now
            ):
                raise ValueError("The invitation is invalid or has expired.")
            if invitation.kind == "recovery":
                account = session.get(UserAccount, invitation.recovery_for_user_id)
                if account is None:
                    raise ValueError("The recovery invitation is no longer valid.")
                account.password_hash = self.passwords.hash(password)
                account.password_changed_at = now
                account.state = "active"
                session.execute(delete(UserSession).where(UserSession.user_id == account.id))
            else:
                if not username:
                    raise ValueError("A username is required.")
                clean_username = self._validate_username(username)
                normalized_username = _normalize(clean_username)
                normalized_email = _normalize(invitation.email) if invitation.email else None
                collision = session.scalar(
                    select(UserAccount.id).where(
                        UserAccount.normalized_username == normalized_username
                    )
                )
                if not collision and normalized_email:
                    collision = session.scalar(
                        select(UserAccount.id).where(
                            UserAccount.normalized_email == normalized_email
                        )
                    )
                if collision:
                    raise ValueError("That username or email is already in use.")
                account = UserAccount(
                    username=clean_username,
                    normalized_username=normalized_username,
                    email=invitation.email,
                    normalized_email=normalized_email,
                    display_name=(display_name or clean_username).strip()[:120],
                    password_hash=self.passwords.hash(password),
                    password_changed_at=now,
                    role=invitation.role,
                    state="active",
                )
                session.add(account)
                session.flush()
            invitation.consumed_at = now
            self._audit(
                session,
                "recovery_redeemed" if invitation.kind == "recovery" else "invitation_redeemed",
                "An account token was redeemed.",
                actor_user_id=account.id,
                target_type="user",
                target_id=account.id,
            )
            return account

    def list_users(self) -> list[dict]:
        with self.session_factory() as session:
            return [
                {
                    "id": item.id,
                    "username": item.username,
                    "display_name": item.display_name,
                    "email": item.email,
                    "role": item.role,
                    "state": item.state,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
                for item in session.scalars(
                    select(UserAccount).order_by(UserAccount.created_at, UserAccount.id)
                )
            ]

    def update_user(
        self,
        actor_user_id: str,
        user_id: str,
        *,
        state: str | None = None,
        role: str | None = None,
    ) -> dict:
        if state not in {None, "active", "disabled"} or role not in {
            None,
            "admin",
            "member",
        }:
            raise ValueError("Account update is invalid.")
        with self.session_factory() as session, session.begin():
            account = session.get(UserAccount, user_id)
            if account is None:
                raise LookupError("User account not found.")
            removing_admin = account.role == "admin" and (
                state == "disabled" or role == "member"
            )
            if removing_admin:
                active_admins = session.scalar(
                    select(func.count(UserAccount.id)).where(
                        UserAccount.role == "admin", UserAccount.state == "active"
                    )
                )
                if int(active_admins or 0) <= 1:
                    raise ValueError("The active server-owner account cannot be removed.")
            if state:
                account.state = state
            if role:
                account.role = role
            if account.state == "disabled":
                session.execute(delete(UserSession).where(UserSession.user_id == account.id))
                now = datetime.now(UTC)
                for feed in session.scalars(
                    select(CalendarFeedToken).where(
                        CalendarFeedToken.user_id == account.id,
                        CalendarFeedToken.revoked_at.is_(None),
                    )
                ):
                    feed.revoked_at = now
                connections = list(
                    session.scalars(
                        select(IntegrationConnection).where(
                            IntegrationConnection.user_id == account.id
                        )
                    )
                )
                for connection in connections:
                    connection.enabled = False
                    connection.paused_reason = "account_disabled"
                    for credential in session.scalars(
                        select(WebhookCredential).where(
                            WebhookCredential.connection_id == connection.id,
                            WebhookCredential.revoked_at.is_(None),
                        )
                    ):
                        credential.revoked_at = now
            self._audit(
                session,
                "user_updated",
                "A user account was updated; disabled sessions were revoked.",
                actor_user_id=actor_user_id,
                target_type="user",
                target_id=account.id,
            )
            session.flush()
            return {
                "id": account.id,
                "username": account.username,
                "display_name": account.display_name,
                "role": account.role,
                "state": account.state,
            }

    def issue_calendar_feed(self, user_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        with self.session_factory() as session, session.begin():
            session.add(
                CalendarFeedToken(
                    user_id=user_id,
                    token_hash=self._digest("calendar-feed", raw),
                )
            )
        return raw

    def validate_calendar_feed(self, raw: str | None) -> str | None:
        if not raw:
            return None
        with self.session_factory() as session, session.begin():
            record = session.scalar(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.token_hash == self._digest("calendar-feed", raw),
                    CalendarFeedToken.revoked_at.is_(None),
                )
            )
            if record is None:
                return None
            record.last_used_at = datetime.now(UTC)
            return record.user_id

    def revoke_calendar_feeds(self, user_id: str) -> int:
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            records = session.scalars(
                select(CalendarFeedToken).where(
                    CalendarFeedToken.user_id == user_id,
                    CalendarFeedToken.revoked_at.is_(None),
                )
            ).all()
            for record in records:
                record.revoked_at = now
            return len(records)
