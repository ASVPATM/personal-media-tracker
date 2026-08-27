"""Durable device-side state for a PMT Server connection.

The remote server remains authoritative.  This module stores only connection metadata,
an offline read cache, and idempotent pending mutations.  Access and refresh tokens are
kept in the operating-system credential vault and never written to SQLite or JSON.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from watchtracker import __version__


class RemoteClientError(RuntimeError):
    pass


class CredentialVault(Protocol):
    def get(self, profile_id: str, name: str) -> str | None: ...

    def set(self, profile_id: str, name: str, value: str) -> None: ...

    def delete(self, profile_id: str, name: str) -> None: ...


class KeyringCredentialVault:
    """Small wrapper that keeps native tokens in Keychain/Credential Manager/libsecret."""

    service = "personal-media-tracker.remote"

    @staticmethod
    def _key(profile_id: str, name: str) -> str:
        return f"{profile_id}:{name}"

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - depends on desktop extra
            raise RemoteClientError(
                "Secure device storage is unavailable. Install the desktop component and try again."
            ) from exc
        return keyring

    def get(self, profile_id: str, name: str) -> str | None:
        try:
            return self._keyring().get_password(self.service, self._key(profile_id, name))
        except Exception as exc:  # pragma: no cover - platform credential backend
            raise RemoteClientError(
                "The operating-system credential vault is unavailable."
            ) from exc

    def set(self, profile_id: str, name: str, value: str) -> None:
        try:
            self._keyring().set_password(self.service, self._key(profile_id, name), value)
        except Exception as exc:  # pragma: no cover - platform credential backend
            raise RemoteClientError(
                "The operating-system credential vault rejected the token."
            ) from exc

    def delete(self, profile_id: str, name: str) -> None:
        with suppress(Exception):
            self._keyring().delete_password(self.service, self._key(profile_id, name))


class MemoryCredentialVault:
    """Injectable test vault.  Production code always defaults to KeyringCredentialVault."""

    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get(self, profile_id: str, name: str) -> str | None:
        return self.values.get((profile_id, name))

    def set(self, profile_id: str, name: str, value: str) -> None:
        self.values[(profile_id, name)] = value

    def delete(self, profile_id: str, name: str) -> None:
        self.values.pop((profile_id, name), None)


@dataclass(frozen=True)
class ServerProfile:
    id: str
    label: str
    base_url: str
    instance_id: str
    api_version: str
    device_id: str
    server_version: str
    account_username: str
    created_at: str
    enabled: bool = True
    last_synced_at: str | None = None
    cursor: str | None = None


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_server_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if (
        parsed.scheme not in ({"http", "https"} if loopback else {"https"})
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RemoteClientError("Enter the HTTPS address shown by your PMT Server.")
    return url


class RemoteProfileStore:
    """SQLite-backed non-secret client cache and durable mutation outbox."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS server_profiles (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    instance_id TEXT NOT NULL UNIQUE,
                    api_version TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    server_version TEXT NOT NULL,
                    account_username TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_synced_at TEXT,
                    cursor TEXT
                );
                CREATE TABLE IF NOT EXISTS cached_resources (
                    profile_id TEXT NOT NULL REFERENCES server_profiles(id) ON DELETE CASCADE,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    version INTEGER,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (profile_id, resource_type, resource_id)
                );
                CREATE TABLE IF NOT EXISTS client_outbox (
                    request_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES server_profiles(id) ON DELETE CASCADE,
                    operation TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    client_timestamp TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    conflict TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_client_outbox_pending
                    ON client_outbox(profile_id, state, created_at);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(server_profiles)")
            }
            if "enabled" not in columns:
                connection.execute(
                    "ALTER TABLE server_profiles ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
                )
        if os.name != "nt":
            self.path.chmod(0o600)

    @staticmethod
    def _profile(row: sqlite3.Row) -> ServerProfile:
        values = dict(row)
        values["enabled"] = bool(values.get("enabled", 1))
        return ServerProfile(**values)

    def profiles(self) -> list[ServerProfile]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM server_profiles ORDER BY label COLLATE NOCASE, id"
            ).fetchall()
        return [self._profile(row) for row in rows]

    def enabled_profiles(self) -> list[ServerProfile]:
        return [profile for profile in self.profiles() if profile.enabled]

    def get_profile(self, profile_id: str) -> ServerProfile:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM server_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise RemoteClientError("This PMT Server connection no longer exists.")
        return self._profile(row)

    def save_profile(self, profile: ServerProfile) -> ServerProfile:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, created_at, cursor, last_synced_at FROM server_profiles "
                "WHERE instance_id = ?",
                (profile.instance_id,),
            ).fetchone()
            if existing:
                profile = ServerProfile(
                    **{
                        **asdict(profile),
                        "id": existing["id"],
                        "created_at": existing["created_at"],
                        "cursor": existing["cursor"],
                        "last_synced_at": existing["last_synced_at"],
                    }
                )
            values = asdict(profile)
            values["enabled"] = int(profile.enabled)
            if profile.enabled:
                connection.execute("UPDATE server_profiles SET enabled = 0")
            connection.execute(
                """
                INSERT INTO server_profiles
                    (id, label, base_url, instance_id, api_version, device_id,
                     server_version, account_username, enabled, created_at,
                     last_synced_at, cursor)
                VALUES
                    (:id, :label, :base_url, :instance_id, :api_version, :device_id,
                     :server_version, :account_username, :enabled, :created_at,
                     :last_synced_at, :cursor)
                ON CONFLICT(id) DO UPDATE SET
                    label=excluded.label, base_url=excluded.base_url,
                    api_version=excluded.api_version, device_id=excluded.device_id,
                    server_version=excluded.server_version,
                    account_username=excluded.account_username,
                    enabled=excluded.enabled
                """,
                values,
            )
        return profile

    def set_enabled(self, profile_id: str, enabled: bool) -> ServerProfile:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM server_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if exists is None:
                raise RemoteClientError("This PMT Server connection no longer exists.")
            if enabled:
                connection.execute("UPDATE server_profiles SET enabled = 0")
            connection.execute(
                "UPDATE server_profiles SET enabled = ? WHERE id = ?",
                (int(enabled), profile_id),
            )
        return self.get_profile(profile_id)

    def update_sync_state(self, profile_id: str, *, cursor: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE server_profiles SET cursor = ?, last_synced_at = ? WHERE id = ?",
                (cursor, _utc_iso(), profile_id),
            )

    def delete_profile(self, profile_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM server_profiles WHERE id = ?", (profile_id,))

    def cache(self, profile_id: str, resource_type: str, payload: dict[str, Any]) -> None:
        resource_id = str(payload.get("id") or "")
        if not resource_id:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cached_resources
                    (profile_id, resource_type, resource_id, version, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, resource_type, resource_id) DO UPDATE SET
                    version=excluded.version, payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    profile_id,
                    resource_type,
                    resource_id,
                    payload.get("version"),
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    _utc_iso(),
                ),
            )

    def cached(self, profile_id: str, resource_type: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM cached_resources WHERE profile_id = ? "
                "AND resource_type = ? ORDER BY updated_at DESC",
                (profile_id, resource_type),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def delete_cached(self, profile_id: str, resource_type: str, resource_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM cached_resources WHERE profile_id = ? "
                "AND resource_type = ? AND resource_id = ?",
                (profile_id, resource_type, resource_id),
            )

    def enqueue_entry_patch(
        self,
        profile_id: str,
        entry_id: str,
        base_version: int,
        payload: dict[str, Any],
    ) -> str:
        return self.enqueue(
            profile_id,
            operation="entry.patch",
            resource_type="watch_entry",
            resource_id=entry_id,
            base_version=base_version,
            payload=payload,
        )

    def enqueue(
        self,
        profile_id: str,
        *,
        operation: str,
        resource_type: str,
        resource_id: str,
        base_version: int,
        payload: dict[str, Any],
    ) -> str:
        allowed = {
            "entry.patch": "watch_entry",
            "list.patch": "media_list",
            "list.item.add": "media_list",
            "list.item.remove": "media_list",
        }
        if allowed.get(operation) != resource_type:
            raise RemoteClientError("This offline change type is not supported.")
        request_id = str(uuid4())
        now = _utc_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO client_outbox
                    (request_id, profile_id, operation, resource_type, resource_id,
                     base_version, payload, client_timestamp, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    request_id,
                    profile_id,
                    operation,
                    resource_type,
                    resource_id,
                    base_version,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    now,
                    now,
                    now,
                ),
            )
        return request_id

    def outbox(self, profile_id: str, *, states: tuple[str, ...] | None = None) -> list[dict]:
        parameters: list[Any] = [profile_id]
        statement = "SELECT * FROM client_outbox WHERE profile_id = ?"
        if states:
            statement += f" AND state IN ({','.join('?' for _ in states)})"
            parameters.extend(states)
        statement += " ORDER BY created_at, request_id"
        with self._connect() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        return [
            {
                **dict(row),
                "payload": json.loads(row["payload"]),
                "conflict": json.loads(row["conflict"]) if row["conflict"] else None,
            }
            for row in rows
        ]

    def record_outcome(self, request_id: str, result: dict[str, Any]) -> None:
        status = result.get("status")
        state = (
            "acknowledged"
            if status == "applied"
            else "conflict"
            if status == "conflict"
            else "failed"
        )
        error = (result.get("error") or {}).get("message")
        conflict = json.dumps(result.get("current")) if status == "conflict" else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE client_outbox SET state = ?, attempts = attempts + 1,
                    last_error = ?, conflict = ?, updated_at = ? WHERE request_id = ?
                """,
                (state, error, conflict, _utc_iso(), request_id),
            )

    def record_retryable_failure(self, request_id: str, message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE client_outbox SET attempts = attempts + 1, last_error = ?, "
                "updated_at = ? WHERE request_id = ?",
                (message[:300], _utc_iso(), request_id),
            )

    def discard(self, profile_id: str, request_id: str) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE client_outbox SET state = 'discarded', updated_at = ? "
                "WHERE profile_id = ? AND request_id = ? AND state = 'conflict'",
                (_utc_iso(), profile_id, request_id),
            ).rowcount
        if not updated:
            raise RemoteClientError("The conflicting change was not found.")

    def rebase(self, profile_id: str, request_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM client_outbox WHERE profile_id = ? AND request_id = ? "
                "AND state = 'conflict'",
                (profile_id, request_id),
            ).fetchone()
        if row is None or not row["conflict"]:
            raise RemoteClientError("The conflicting change was not found.")
        current = json.loads(row["conflict"])
        version = current.get("version") if isinstance(current, dict) else None
        if not isinstance(version, int):
            raise RemoteClientError("Reload this title before trying the edit again.")
        self.discard(profile_id, request_id)
        return self.enqueue(
            profile_id,
            operation=row["operation"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            base_version=version,
            payload=json.loads(row["payload"]),
        )


Send = Callable[..., Any]


class RemoteDeviceClient:
    """Versioned native-device client with rotation, reconnect, cache, and outbox."""

    def __init__(
        self,
        store: RemoteProfileStore,
        *,
        vault: CredentialVault | None = None,
        send: Send | None = None,
    ):
        self.store = store
        self.vault = vault or KeyringCredentialVault()
        self.send = send or httpx.request

    def _request(self, method: str, url: str, **kwargs):
        try:
            return self.send(method, url, timeout=10, **kwargs)
        except (httpx.HTTPError, OSError) as exc:
            raise RemoteClientError(
                "The PMT Server is currently unreachable. Your pending edits are safe on this device."
            ) from exc

    def discover(self, value: str) -> dict[str, Any]:
        base_url = normalize_server_url(value)
        response = self._request(
            "GET",
            f"{base_url}/api/v1/server/capabilities",
            headers={"Accept": "application/json", "User-Agent": f"PMT/{__version__}"},
        )
        if response.status_code != 200:
            error_code = None
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    error_code = (error_payload.get("error") or {}).get("code")
            except (TypeError, ValueError):
                pass
            if error_code == "invalid_host":
                raise RemoteClientError(
                    "This address reached PMT, but that app is not configured as a "
                    "PMT Server for this HTTPS hostname. Tailscale forwarding does not "
                    "convert a local-only library into a server."
                )
            if response.status_code >= 500:
                raise RemoteClientError(
                    "The private address is available, but PMT Server is not answering "
                    "behind it. Start PMT Server on the host and verify local port 8000."
                )
            raise RemoteClientError(
                "The address did not return PMT Server capabilities. Confirm that the "
                "dedicated server is running and Tailscale Serve points to its port 8000."
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RemoteClientError(
                "That address did not return a valid PMT Server identity."
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("product") != "personal-media-tracker"
            or str(payload.get("api_version")) != "1"
            or not payload.get("instance_id")
        ):
            raise RemoteClientError("That address is not a compatible PMT Server.")
        if payload.get("mode") != "server" or payload.get("library_authority") != "pmt_server":
            raise RemoteClientError(
                "This is a local-only PMT library, not a PMT Server. Install or start the "
                "separate PMT Server, then use the HTTPS address shown by that server."
            )
        return {**payload, "base_url": base_url}

    def connect(
        self,
        *,
        value: str,
        username: str,
        password: str,
        label: str,
        device_label: str,
    ) -> ServerProfile:
        capabilities = self.discover(value)
        profile_id = str(uuid4())
        existing = next(
            (
                row
                for row in self.store.profiles()
                if row.instance_id == capabilities["instance_id"]
            ),
            None,
        )
        device_id = existing.device_id if existing else str(uuid4())
        profile_id = existing.id if existing else profile_id
        response = self._request(
            "POST",
            f"{capabilities['base_url']}/api/v1/auth/device/login",
            json={
                "username": username,
                "password": password,
                "device_id": device_id,
                "device_label": device_label,
            },
        )
        if response.status_code != 200:
            raise RemoteClientError("The username or password is incorrect.")
        tokens = response.json()
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        if not refresh_token or not access_token:
            raise RemoteClientError("The server did not return a usable device session.")
        self.vault.set(profile_id, "refresh_token", refresh_token)
        self.vault.set(profile_id, "access_token", access_token)
        profile = ServerProfile(
            id=profile_id,
            label=" ".join(label.split())[:120] or "Home PMT Server",
            base_url=capabilities["base_url"],
            instance_id=capabilities["instance_id"],
            api_version=str(capabilities["api_version"]),
            device_id=device_id,
            server_version=str(capabilities.get("server_version") or "unknown"),
            account_username=username,
            enabled=True,
            created_at=existing.created_at if existing else _utc_iso(),
            last_synced_at=existing.last_synced_at if existing else None,
            cursor=existing.cursor if existing else None,
        )
        return self.store.save_profile(profile)

    def enroll(
        self,
        *,
        value: str,
        invitation_token: str,
        username: str,
        display_name: str,
        password: str,
        label: str,
        device_label: str,
    ) -> ServerProfile:
        """Redeem a server-issued invitation, then save a native device session."""
        capabilities = self.discover(value)
        response = self._request(
            "POST",
            f"{capabilities['base_url']}/api/v1/auth/invitations/redeem",
            json={
                "token": invitation_token,
                "username": username,
                "display_name": display_name,
                "password": password,
            },
        )
        if response.status_code != 201:
            try:
                detail = (response.json().get("error") or {}).get("message")
                if not detail:
                    detail = response.json().get("detail")
            except (AttributeError, TypeError, ValueError):
                detail = None
            raise RemoteClientError(
                str(detail or "The invitation is invalid, expired, or already used.")
            )
        return self.connect(
            value=capabilities["base_url"],
            username=username,
            password=password,
            label=label,
            device_label=device_label,
        )

    def _authorized(self, profile: ServerProfile, method: str, path: str, **kwargs):
        access = self.vault.get(profile.id, "access_token")
        if not access:
            return self._refresh_and_retry(profile, method, path, **kwargs)
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {access}"}
        response = self._request(method, f"{profile.base_url}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            return self._refresh_and_retry(profile, method, path, **kwargs)
        return response

    def _refresh_and_retry(self, profile: ServerProfile, method: str, path: str, **kwargs):
        refresh = self.vault.get(profile.id, "refresh_token")
        if not refresh:
            raise RemoteClientError("Sign in to this PMT Server again.")
        response = self._request(
            "POST",
            f"{profile.base_url}/api/v1/auth/device/refresh",
            json={"refresh_token": refresh},
        )
        if response.status_code != 200:
            self.vault.delete(profile.id, "access_token")
            self.vault.delete(profile.id, "refresh_token")
            raise RemoteClientError("This device session expired. Sign in again.")
        tokens = response.json()
        self.vault.set(profile.id, "access_token", tokens["access_token"])
        self.vault.set(profile.id, "refresh_token", tokens["refresh_token"])
        headers = {
            **kwargs.pop("headers", {}),
            "Authorization": f"Bearer {tokens['access_token']}",
        }
        return self._request(method, f"{profile.base_url}{path}", headers=headers, **kwargs)

    def browser_handoff(self, profile_id: str) -> tuple[ServerProfile, str]:
        """Return a short-lived, one-use token for opening the saved account UI."""
        profile = self.store.get_profile(profile_id)
        if not profile.enabled:
            raise RemoteClientError("This PMT Server connection is paused on this device.")
        response = self._authorized(
            profile,
            "POST",
            "/api/v1/auth/device/browser-session",
            json={},
        )
        if response.status_code != 200:
            raise RemoteClientError(
                "The saved PMT Server session could not open the account. Sign in again from Access & Devices."
            )
        try:
            token = response.json().get("handoff_token")
        except (AttributeError, TypeError, ValueError) as exc:
            raise RemoteClientError(
                "The PMT Server returned an invalid app-session response."
            ) from exc
        if not isinstance(token, str) or len(token) < 32:
            raise RemoteClientError("The PMT Server returned an invalid app-session response.")
        return profile, token

    def sync(self, profile_id: str) -> dict[str, Any]:
        profile = self.store.get_profile(profile_id)
        capabilities = self.discover(profile.base_url)
        if capabilities["instance_id"] != profile.instance_id:
            raise RemoteClientError(
                "The server at this address has a different identity. Review the connection before signing in."
            )
        pending = self.store.outbox(profile_id, states=("pending", "failed"))
        applied = conflicts = failed = 0
        for item in pending:
            mutation = {
                "request_id": item["request_id"],
                "operation": item["operation"],
                "resource_id": item["resource_id"],
                "base_version": item["base_version"],
                "payload": item["payload"],
                "client_timestamp": item["client_timestamp"],
            }
            try:
                response = self._authorized(
                    profile,
                    "POST",
                    "/api/v1/sync/push",
                    json={"device_id": profile.device_id, "mutations": [mutation]},
                )
                if response.status_code not in {200, 409}:
                    raise RemoteClientError("The server rejected a queued edit.")
                result = response.json()["results"][0]
                self.store.record_outcome(item["request_id"], result)
                if result.get("status") == "applied":
                    applied += 1
                    if result.get("resource"):
                        self.store.cache(
                            profile_id,
                            str(result.get("resource_type") or item["resource_type"]),
                            result["resource"],
                        )
                elif result.get("status") == "conflict":
                    conflicts += 1
                    if result.get("current"):
                        self.store.cache(
                            profile_id,
                            str(result.get("resource_type") or item["resource_type"]),
                            result["current"],
                        )
                else:
                    failed += 1
            except RemoteClientError as exc:
                self.store.record_retryable_failure(item["request_id"], str(exc))
                raise

        cursor = profile.cursor
        while True:
            parameters = {"limit": 200}
            if cursor:
                parameters["cursor"] = cursor
            response = self._authorized(profile, "GET", "/api/v1/sync/pull", params=parameters)
            if response.status_code != 200:
                raise RemoteClientError("The server change list could not be downloaded.")
            page = response.json()
            for change in page.get("changes", []):
                resource_type = change.get("resource_type")
                if resource_type not in {"watch_entry", "media_list"}:
                    continue
                path = (
                    f"/api/v1/entries/{change['resource_id']}"
                    if resource_type == "watch_entry"
                    else f"/api/v1/lists/{change['resource_id']}"
                )
                detail = self._authorized(
                    profile,
                    "GET",
                    path,
                )
                if detail.status_code == 200:
                    self.store.cache(profile_id, resource_type, detail.json())
                elif detail.status_code == 404:
                    self.store.delete_cached(
                        profile_id,
                        resource_type,
                        str(change["resource_id"]),
                    )
            cursor = page.get("cursor") or cursor
            if not page.get("has_more"):
                break
        self.store.update_sync_state(profile_id, cursor=cursor)
        return {
            "profile_id": profile_id,
            "online": True,
            "applied": applied,
            "conflicts": conflicts,
            "failed": failed,
            "pending": len(self.store.outbox(profile_id, states=("pending", "failed"))),
            "cached_entries": len(self.store.cached(profile_id, "watch_entry")),
            "synced_at": _utc_iso(),
        }

    def disconnect(self, profile_id: str) -> None:
        profile = self.store.get_profile(profile_id)
        with_context = None
        with suppress(RemoteClientError):
            with_context = self._authorized(profile, "POST", "/api/v1/auth/device/logout")
        if with_context is not None and with_context.status_code not in {204, 401}:
            raise RemoteClientError("The server could not close the device session.")
        self.vault.delete(profile_id, "access_token")
        self.vault.delete(profile_id, "refresh_token")
        self.store.delete_profile(profile_id)
