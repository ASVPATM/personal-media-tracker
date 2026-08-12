from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "Personal Media Tracker"
APP_AUTHOR = "Personal Media Tracker"
LEGACY_APP_NAME = "Personal Watch Tracker"
LEGACY_APP_AUTHOR = "Personal Watch Tracker"


def is_packaged() -> bool:
    """Return whether the process is running from a desktop bundle."""
    return bool(getattr(sys, "frozen", False) or os.environ.get("WATCHTRACKER_PACKAGED") == "1")


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    cache_dir: Path
    config_dir: Path
    log_dir: Path
    backups_dir: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / "watchtracker.sqlite3"

    @property
    def preferences_path(self) -> Path:
        return self.config_dir / "preferences.json"

    @property
    def fallback_secret_path(self) -> Path:
        return self.config_dir / "secrets.env"

    @property
    def instance_lock_path(self) -> Path:
        return self.data_dir / "watchtracker.instance.lock"

    @property
    def instance_state_path(self) -> Path:
        return self.data_dir / "watchtracker.instance.json"

    def ensure(self) -> None:
        for path in (
            self.data_dir,
            self.cache_dir,
            self.config_dir,
            self.log_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def platform_runtime_paths() -> RuntimePaths:
    dirs = PlatformDirs(APP_NAME, APP_AUTHOR, roaming=False, ensure_exists=False)
    legacy_dirs = PlatformDirs(
        LEGACY_APP_NAME,
        LEGACY_APP_AUTHOR,
        roaming=False,
        ensure_exists=False,
    )
    legacy_data_dir = Path(legacy_dirs.user_data_dir)
    legacy_config_dir = Path(legacy_dirs.user_config_dir)
    # Existing installations keep using their original directory so the public
    # product rename can never make a populated library appear to disappear.
    # New installations use the Personal Media Tracker directories.
    if (legacy_data_dir / "watchtracker.sqlite3").exists() or (
        legacy_config_dir / "preferences.json"
    ).exists():
        return RuntimePaths(
            data_dir=legacy_data_dir,
            cache_dir=Path(legacy_dirs.user_cache_dir),
            config_dir=legacy_config_dir,
            log_dir=Path(legacy_dirs.user_log_dir),
            backups_dir=legacy_data_dir / "backups",
        )
    data_dir = Path(dirs.user_data_dir)
    return RuntimePaths(
        data_dir=data_dir,
        cache_dir=Path(dirs.user_cache_dir),
        config_dir=Path(dirs.user_config_dir),
        log_dir=Path(dirs.user_log_dir),
        backups_dir=data_dir / "backups",
    )


def source_runtime_paths(project_root: Path) -> RuntimePaths:
    runtime_root = project_root / "data"
    return RuntimePaths(
        data_dir=runtime_root,
        cache_dir=project_root / "cache",
        config_dir=runtime_root / "config",
        log_dir=runtime_root / "logs",
        backups_dir=runtime_root / "backups",
    )
