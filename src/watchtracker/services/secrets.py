from __future__ import annotations

import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from watchtracker.config import Settings
from watchtracker.services.settings import persist_env_value, persist_env_values

SERVICE_NAME = "Personal Media Tracker"
LEGACY_SERVICE_NAME = "Personal Watch Tracker"
ACCOUNT_NAME = "tmdb-read-access-token"
TOKEN_KEY = "WATCHTRACKER_TMDB_TOKEN"
TMDB_NAMESPACE = "metadata.tmdb"
TMDB_SECRET_KEY = "access_token"


class KeyringLike(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


def _read_env_value(path: Path, key: str) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                value = line.partition("=")[2].strip()
                return value or None
    except OSError:
        pass
    return None


def _system_keyring() -> KeyringLike | None:
    try:
        import keyring

        backend = keyring.get_keyring()
        if getattr(backend, "priority", 0) <= 0:
            return None
        return keyring
    except Exception:
        return None


class SecretStore:
    """Namespaced credential storage without unexpected OS credential prompts.

    The private local file is the production default. The system keyring is
    queried only after the user has explicitly opted into it. A caller that
    injects a keyring backend is treated as an explicit opt-in, which keeps the
    class straightforward to exercise in tests and integrations.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        keyring_backend: KeyringLike | None = None,
        keyring_enabled: bool | None = None,
    ):
        self.settings = settings
        self.keyring = keyring_backend if keyring_backend is not None else _system_keyring()
        self.keyring_enabled = (
            keyring_backend is not None if keyring_enabled is None else keyring_enabled
        )
        self.initial_settings_token = settings.tmdb_token
        self._cached: tuple[str | None, str] | None = None
        self._named_cache: dict[tuple[str, str], tuple[str | None, str]] = {}

    @staticmethod
    def _parts(namespace: str, key: str) -> tuple[str, str]:
        namespace = namespace.strip().lower()
        key = key.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,119}", namespace):
            raise ValueError("secret namespace is invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", key):
            raise ValueError("secret key is invalid")
        return namespace, key

    @staticmethod
    def _env_key(namespace: str, key: str) -> str:
        encoded = re.sub(r"[^A-Z0-9]", "_", f"{namespace}_{key}".upper())
        return f"WATCHTRACKER_SECRET_{encoded}"

    @staticmethod
    def _keyring_account(namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    @staticmethod
    def _validate_secret(value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("secret must be a nonblank single line")
        return value

    def legacy_token(self) -> str | None:
        return _read_env_value(self.settings.resolved_env_path, TOKEN_KEY)

    def fallback_token(self) -> str | None:
        return _read_env_value(self.settings.fallback_secret_path, TOKEN_KEY)

    @property
    def keyring_available(self) -> bool:
        return self.keyring is not None

    def keyring_token(self, *, force: bool = False) -> str | None:
        if not self.keyring or not (self.keyring_enabled or force):
            return None
        try:
            token = self.keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
            if token:
                return token
            # Read the previous product label only after Keyring use is already
            # enabled or the user requests the explicit migration action.
            return self.keyring.get_password(LEGACY_SERVICE_NAME, ACCOUNT_NAME)
        except Exception:
            return None

    def get(self, *, refresh: bool = False) -> tuple[str | None, str]:
        if token := self.settings.environment_tmdb_token:
            return token, "environment"
        if self._cached is not None and not refresh:
            return self._cached
        if token := self.keyring_token():
            result = (token, "keychain")
        elif token := self.fallback_token():
            result = (token, "local_secret_file")
        elif token := self.legacy_token() or self.initial_settings_token:
            result = (token, "legacy_env")
        else:
            result = (None, "none")
        self._cached = result
        return result

    def get_named(
        self, namespace: str, key: str, *, refresh: bool = False
    ) -> tuple[str | None, str]:
        """Return one credential without ever probing Keychain before opt-in."""
        namespace, key = self._parts(namespace, key)
        if (namespace, key) == (TMDB_NAMESPACE, TMDB_SECRET_KEY):
            return self.get(refresh=refresh)
        environment_key = self._env_key(namespace, key)
        if (value := os.environ.get(environment_key)) and value.strip():
            return value.strip(), "environment"
        cache_key = (namespace, key)
        if cache_key in self._named_cache and not refresh:
            return self._named_cache[cache_key]
        value = None
        if self.keyring and self.keyring_enabled:
            with suppress(Exception):
                value = self.keyring.get_password(
                    SERVICE_NAME, self._keyring_account(namespace, key)
                )
        if value:
            result = (value, "keychain")
        elif value := _read_env_value(self.settings.fallback_secret_path, environment_key):
            result = (value, "local_secret_file")
        else:
            result = (None, "none")
        self._named_cache[cache_key] = result
        return result

    def save(
        self,
        token: str,
        *,
        storage: str | None = None,
    ) -> str:
        token = token.strip()
        if not token or "\n" in token or "\r" in token:
            raise ValueError("token must be a nonblank single line")
        explicit_storage = storage is not None
        target = storage or ("keychain" if self.keyring_enabled else "local_secret_file")
        if target not in {"keychain", "local_secret_file"}:
            raise ValueError("credential storage must be local_secret_file or keychain")
        if target == "keychain":
            if not self.keyring:
                raise ValueError("The operating system credential vault is unavailable")
            try:
                self.keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, token)
                self.keyring_enabled = True
                persist_env_value(self.settings.fallback_secret_path, TOKEN_KEY, None)
                self._cached = (token, "keychain")
                return "keychain"
            except Exception as exc:
                if explicit_storage:
                    raise ValueError(
                        "The operating system credential vault did not accept the credential. "
                        "Choose the local configuration file to avoid OS prompts."
                    ) from exc
        persist_env_value(self.settings.fallback_secret_path, TOKEN_KEY, token)
        self.keyring_enabled = False
        self._cached = (token, "local_secret_file")
        return "local_secret_file"

    def save_named(
        self,
        namespace: str,
        key: str,
        value: str,
        *,
        storage: str | None = None,
    ) -> str:
        namespace, key = self._parts(namespace, key)
        if (namespace, key) == (TMDB_NAMESPACE, TMDB_SECRET_KEY):
            return self.save(value, storage=storage)
        value = self._validate_secret(value)
        explicit_storage = storage is not None
        target = storage or ("keychain" if self.keyring_enabled else "local_secret_file")
        if target not in {"keychain", "local_secret_file"}:
            raise ValueError("credential storage must be local_secret_file or keychain")
        environment_key = self._env_key(namespace, key)
        if target == "keychain":
            if not self.keyring:
                raise ValueError("The operating system credential vault is unavailable")
            try:
                self.keyring.set_password(
                    SERVICE_NAME, self._keyring_account(namespace, key), value
                )
                self.keyring_enabled = True
                persist_env_value(self.settings.fallback_secret_path, environment_key, None)
                self._named_cache[(namespace, key)] = (value, "keychain")
                return "keychain"
            except Exception as exc:
                if explicit_storage:
                    raise ValueError(
                        "The operating system credential vault did not accept the credential. "
                        "Choose the local configuration file to avoid OS prompts."
                    ) from exc
        persist_env_value(self.settings.fallback_secret_path, environment_key, value)
        if self.keyring and self.keyring_enabled:
            with suppress(Exception):
                self.keyring.delete_password(
                    SERVICE_NAME, self._keyring_account(namespace, key)
                )
        self._named_cache[(namespace, key)] = (value, "local_secret_file")
        return "local_secret_file"

    def save_many_named(
        self,
        namespace: str,
        values: dict[str, str],
        *,
        storage: str | None = None,
    ) -> str:
        """Replace a credential set together when the selected backend supports it."""
        namespace, _ = self._parts(namespace, "credential_set")
        cleaned = {
            self._parts(namespace, key)[1]: self._validate_secret(value)
            for key, value in values.items()
        }
        if not cleaned:
            raise ValueError("credential set must not be empty")
        explicit_storage = storage is not None
        target = storage or ("keychain" if self.keyring_enabled else "local_secret_file")
        if target not in {"keychain", "local_secret_file"}:
            raise ValueError("credential storage must be local_secret_file or keychain")
        if target == "local_secret_file":
            changes = {self._env_key(namespace, key): value for key, value in cleaned.items()}
            persist_env_values(self.settings.fallback_secret_path, changes)
            for key, value in cleaned.items():
                if self.keyring and self.keyring_enabled:
                    with suppress(Exception):
                        self.keyring.delete_password(
                            SERVICE_NAME, self._keyring_account(namespace, key)
                        )
                self._named_cache[(namespace, key)] = (value, "local_secret_file")
            return "local_secret_file"
        if not self.keyring:
            if explicit_storage:
                raise ValueError("The operating system credential vault is unavailable")
            return self.save_many_named(namespace, cleaned, storage="local_secret_file")
        previous = {key: self.get_named(namespace, key, refresh=True) for key in cleaned}
        saved: list[str] = []
        try:
            for key, value in cleaned.items():
                self.keyring.set_password(
                    SERVICE_NAME, self._keyring_account(namespace, key), value
                )
                saved.append(key)
            persist_env_values(
                self.settings.fallback_secret_path,
                {self._env_key(namespace, key): None for key in cleaned},
            )
        except Exception as exc:
            for key in saved:
                prior, source = previous[key]
                with suppress(Exception):
                    if prior and source == "keychain":
                        self.keyring.set_password(
                            SERVICE_NAME, self._keyring_account(namespace, key), prior
                        )
                    else:
                        self.keyring.delete_password(
                            SERVICE_NAME, self._keyring_account(namespace, key)
                        )
            if explicit_storage:
                raise ValueError(
                    "The operating system credential vault did not accept the credential set."
                ) from exc
            return self.save_many_named(namespace, cleaned, storage="local_secret_file")
        self.keyring_enabled = True
        for key, value in cleaned.items():
            self._named_cache[(namespace, key)] = (value, "keychain")
        return "keychain"

    def clear(self) -> str:
        if self.keyring and self.keyring_enabled:
            with suppress(Exception):
                self.keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        self.keyring_enabled = False
        persist_env_value(self.settings.fallback_secret_path, TOKEN_KEY, None)
        self._cached = None
        token, source = self.get(refresh=True)
        return source if token else "none"

    def clear_named(self, namespace: str, key: str) -> str:
        namespace, key = self._parts(namespace, key)
        if (namespace, key) == (TMDB_NAMESPACE, TMDB_SECRET_KEY):
            return self.clear()
        if self.keyring and self.keyring_enabled:
            with suppress(Exception):
                self.keyring.delete_password(
                    SERVICE_NAME, self._keyring_account(namespace, key)
                )
        environment_key = self._env_key(namespace, key)
        persist_env_value(self.settings.fallback_secret_path, environment_key, None)
        self._named_cache.pop((namespace, key), None)
        value, source = self.get_named(namespace, key, refresh=True)
        return source if value else "none"

    def clear_namespace(self, namespace: str, keys: list[str]) -> None:
        """Clear only the explicitly registered fields for a disconnected connection."""
        for key in keys:
            self.clear_named(namespace, key)

    def copy_existing_keyring_to_local(self) -> str:
        """Read the OS keyring only after a deliberate migration action."""
        token = self.keyring_token(force=True)
        if not token:
            raise ValueError("No existing TMDb credential was found in the system vault")
        return self.save(token, storage="local_secret_file")

    def migrate_legacy(self, *, storage: str = "local_secret_file") -> str:
        token = self.legacy_token()
        if not token:
            raise ValueError("No legacy TMDb token is available to migrate")
        return self.save(token, storage=storage)
