from __future__ import annotations

import ipaddress
import logging
import os
from datetime import datetime, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from watchtracker.runtime import is_packaged, platform_runtime_paths, source_runtime_paths

PACKAGE_DIR = Path(__file__).resolve().parent
# Editable/source installs live under <project>/src/watchtracker. A regular wheel
# install has no writable project root, so relative data paths deliberately follow
# the directory where the user launches the command.
PROJECT_ROOT = PACKAGE_DIR.parent.parent if PACKAGE_DIR.parent.name == "src" else Path.cwd()
MIGRATIONS_DIR = PACKAGE_DIR / "migrations"
DEFAULT_PATHS = (
    platform_runtime_paths() if is_packaged() else source_runtime_paths(PROJECT_ROOT)
)
RUNTIME_ENV_PATH = (
    DEFAULT_PATHS.config_dir / "server.env" if is_packaged() else PROJECT_ROOT / ".env"
)


class Settings(BaseSettings):
    """Environment-backed settings with packaged and source-install defaults."""

    model_config = SettingsConfigDict(
        env_prefix="WATCHTRACKER_", env_file=RUNTIME_ENV_PATH, extra="ignore"
    )

    tmdb_token: str | None = Field(default=None, repr=False)
    data_dir: Path = DEFAULT_PATHS.data_dir
    config_dir: Path = DEFAULT_PATHS.config_dir
    log_dir: Path = DEFAULT_PATHS.log_dir
    backups_dir: Path = DEFAULT_PATHS.backups_dir
    # A packaged app bundle is read-only after installation/signing. Server-mode
    # settings therefore live beside the other per-user configuration, while a
    # source checkout keeps the familiar project-root .env behaviour.
    env_path: Path = RUNTIME_ENV_PATH
    database_path: Path | None = None
    cache_dir: Path = DEFAULT_PATHS.cache_dir
    cache_ttl_seconds: int = Field(default=21_600, ge=60, le=604_800)
    cache_max_entries: int = Field(default=500, ge=20, le=10_000)
    release_check_interval_minutes: int = Field(default=360, ge=15, le=10_080)
    release_sync_batch_size: int = Field(default=20, ge=1, le=100)
    release_scheduler_enabled: bool = True
    server_backup_interval_hours: int = Field(default=24, ge=1, le=720)
    server_backup_retention: int = Field(default=14, ge=2, le=365)
    anilist_enabled: bool = False
    language: str = "en-US"
    region: str = "US"
    timezone: str | None = None
    upload_limit_mb: int = Field(default=20, ge=1, le=100)
    backup_upload_limit_mb: int = Field(default=512, ge=1, le=2_048)
    import_max_members: int = Field(default=50, ge=1, le=500)
    import_max_rows: int = Field(default=100_000, ge=100, le=1_000_000)
    import_max_cell_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    import_max_decompressed_mb: int = Field(default=100, ge=1, le=1_000)
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    release_mode: bool = Field(default_factory=is_packaged)
    native_actions: bool = False
    repository_url: str = "https://github.com/ASVPATM/personal-media-tracker"
    access_mode: Literal["local", "server"] = "local"
    public_base_url: str | None = None
    application_secret: str | None = Field(default=None, repr=False)
    trusted_hosts: str = ""
    trusted_proxy_ips: str = ""
    session_ttl_hours: int = Field(default=168, ge=1, le=2_160)
    database_url_override: str | None = Field(default=None, repr=False)

    @field_validator("tmdb_token", "timezone", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError("invalid log level")
        return normalized

    def resolve_path(self, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def packaged(self) -> bool:
        return self.release_mode or is_packaged()

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_config_dir(self) -> Path:
        return self.resolve_path(self.config_dir)

    @property
    def resolved_log_dir(self) -> Path:
        return self.resolve_path(self.log_dir)

    @property
    def resolved_backups_dir(self) -> Path:
        return self.resolve_path(self.backups_dir)

    @property
    def resolved_database_path(self) -> Path:
        return (
            self.resolve_path(self.database_path)
            if self.database_path is not None
            else self.resolved_data_dir / "watchtracker.sqlite3"
        )

    @property
    def resolved_cache_dir(self) -> Path:
        return self.resolve_path(self.cache_dir)

    @property
    def resolved_env_path(self) -> Path:
        return self.resolve_path(self.env_path)

    @property
    def preferences_path(self) -> Path:
        return self.resolved_config_dir / "preferences.json"

    @property
    def fallback_secret_path(self) -> Path:
        return self.resolved_config_dir / "secrets.env"

    @property
    def instance_lock_path(self) -> Path:
        return self.resolved_data_dir / "watchtracker.instance.lock"

    @property
    def instance_state_path(self) -> Path:
        return self.resolved_data_dir / "watchtracker.instance.json"

    def ensure_runtime_directories(self) -> None:
        for path in (
            self.resolved_data_dir,
            self.resolved_cache_dir,
            self.resolved_config_dir,
            self.resolved_log_dir,
            self.resolved_backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                path.chmod(0o700)

    @property
    def environment_tmdb_token(self) -> str | None:
        value = os.environ.get("WATCHTRACKER_TMDB_TOKEN")
        return value.strip() if value and value.strip() else None

    @property
    def allowed_hosts(self) -> list[str]:
        if self.access_mode == "server":
            return sorted(set(self.trusted_host_values))
        hosts = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
        if self.host:
            hosts.add(self.host.strip("[]"))
            hosts.add(self.host)
        return sorted(hosts)

    @property
    def database_url(self) -> str:
        return self.database_url_override or f"sqlite:///{self.resolved_database_path}"

    @property
    def trusted_host_values(self) -> list[str]:
        return [
            item.strip().casefold().strip("[]")
            for item in self.trusted_hosts.split(",")
            if item.strip()
        ]

    @property
    def trusted_proxy_values(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxy_ips.split(",") if item.strip()]

    @property
    def public_origin(self) -> str | None:
        if not self.public_base_url:
            return None
        parsed = urlsplit(self.public_base_url)
        if not parsed.scheme or not parsed.hostname:
            return None
        default_port = 443 if parsed.scheme == "https" else 80
        port = "" if (parsed.port or default_port) == default_port else f":{parsed.port}"
        return f"{parsed.scheme}://{parsed.hostname.casefold()}{port}"

    @staticmethod
    def is_loopback_host(value: str) -> bool:
        host = value.strip().strip("[]").casefold()
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def access_configuration_errors(self) -> list[str]:
        """Return safe, user-facing readiness failures without exposing secret values."""
        errors: list[str] = []
        if self.access_mode == "local":
            if not self.is_loopback_host(self.host):
                errors.append("Local mode must bind to a loopback address.")
            return errors
        parsed = urlsplit(self.public_base_url or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            errors.append("Server mode requires a clean HTTPS public base URL.")
        if (
            not self.application_secret
            or len(self.application_secret) < 64
            or len(set(self.application_secret)) < 16
            or self.application_secret.casefold() in {"change-me", "changeme", "secret"}
        ):
            errors.append("Server mode requires a strong persisted application secret.")
        hosts = self.trusted_host_values
        if not hosts or any("*" in item for item in hosts):
            errors.append("Server mode requires explicit trusted hosts without wildcards.")
        elif parsed.hostname and parsed.hostname.casefold() not in hosts:
            errors.append("The public base URL host must be in the trusted-host list.")
        for value in self.trusted_proxy_values:
            try:
                ipaddress.ip_address(value)
            except ValueError:
                errors.append("Trusted proxies must be explicit IP addresses.")
                break
        if not self.trusted_proxy_values:
            errors.append("Server mode requires an explicit trusted-proxy IP list.")
        return errors

    def require_safe_access_configuration(self) -> None:
        errors = self.access_configuration_errors()
        if errors:
            raise ValueError(" ".join(errors))

    @property
    def tzinfo(self) -> tzinfo:
        if self.timezone:
            try:
                return ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"Unknown timezone: {self.timezone}") from exc
        # A fixed-offset local tzinfo is still more accurate for "today" than
        # silently falling back to UTC. Set an IANA name for DST-aware future dates.
        return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


@lru_cache
def get_settings() -> Settings:
    return Settings()
