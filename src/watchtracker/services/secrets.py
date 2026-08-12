from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Protocol

from watchtracker.config import Settings
from watchtracker.services.settings import persist_env_value

SERVICE_NAME = "Personal Media Tracker"
LEGACY_SERVICE_NAME = "Personal Watch Tracker"
ACCOUNT_NAME = "tmdb-read-access-token"
TOKEN_KEY = "WATCHTRACKER_TMDB_TOKEN"


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
    """TMDb credential storage without unexpected OS credential prompts.

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

    def clear(self) -> str:
        if self.keyring and self.keyring_enabled:
            with suppress(Exception):
                self.keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        self.keyring_enabled = False
        persist_env_value(self.settings.fallback_secret_path, TOKEN_KEY, None)
        self._cached = None
        token, source = self.get(refresh=True)
        return source if token else "none"

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
