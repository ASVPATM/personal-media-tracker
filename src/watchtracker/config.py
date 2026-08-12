from __future__ import annotations

import logging
import os
from datetime import datetime, tzinfo
from functools import lru_cache
from pathlib import Path
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


class Settings(BaseSettings):
    """Environment-backed settings with packaged and source-install defaults."""

    model_config = SettingsConfigDict(
        env_prefix="WATCHTRACKER_", env_file=PROJECT_ROOT / ".env", extra="ignore"
    )

    tmdb_token: str | None = Field(default=None, repr=False)
    data_dir: Path = DEFAULT_PATHS.data_dir
    config_dir: Path = DEFAULT_PATHS.config_dir
    log_dir: Path = DEFAULT_PATHS.log_dir
    backups_dir: Path = DEFAULT_PATHS.backups_dir
    env_path: Path = PROJECT_ROOT / ".env"
    database_path: Path | None = None
    cache_dir: Path = DEFAULT_PATHS.cache_dir
    cache_ttl_seconds: int = Field(default=21_600, ge=60, le=604_800)
    cache_max_entries: int = Field(default=500, ge=20, le=10_000)
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
        hosts = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
        if self.host:
            hosts.add(self.host.strip("[]"))
            hosts.add(self.host)
        return sorted(hosts)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.resolved_database_path}"

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
