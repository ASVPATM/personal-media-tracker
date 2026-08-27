from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from watchtracker.config import Settings
from watchtracker.icons import DEFAULT_ICON_BACKGROUND, DEFAULT_ICON_TEXT
from watchtracker.models import UserPreference

LEGACY_ACCENT_COLORS = {
    "forest": "#345b4c",
    "ocean": "#315f86",
    "violet": "#6a4b8a",
    "rose": "#8b455d",
    "amber": "#8a5a15",
    "graphite": "#4f5e68",
}

DEFAULT_PREFERENCES: dict[str, Any] = {
    "onboarding_complete": False,
    "theme": "system",
    "accent": "forest",
    "accent_color": LEGACY_ACCENT_COLORS["forest"],
    "background_color": None,
    "background_strength": 16,
    "background_mode": "adaptive",
    "background_image_enabled": False,
    "background_image_opacity": 24,
    "background_image_tint": True,
    "media_artwork_tint": False,
    "media_artwork_full_color": False,
    "show_episode_progress": True,
    "icon_background_color": DEFAULT_ICON_BACKGROUND,
    "icon_text_color": DEFAULT_ICON_TEXT,
    "icon_follow_accent": False,
    "interface_language": "en",
    "advanced_ratings_enabled": False,
    "release_check_mode": None,
    "sidebar_mode": "expanded",
    "navigation_order": "standard",
    "settings_privacy_reminder_dismissed": False,
    "keyboard_shortcuts": {},
    "credential_storage": "local_secret_file",
    # Older releases could select the system keyring without clearly explaining
    # that some operating systems prompt during every lookup.  Require a fresh,
    # explicit choice before the app is allowed to query it at startup.
    "credential_vault_opt_in": False,
    "use_server_metadata_token": False,
}

# Window bounds and other machine-specific values may also live in the preferences
# file.  They must not be moved to another computer, where they can place the
# desktop window off screen.  These values are safe and useful to transfer.
PORTABLE_PREFERENCE_KEYS = frozenset(
    {
        "onboarding_complete",
        "theme",
        "accent",
        "accent_color",
        "background_color",
        "background_strength",
        "background_mode",
        "media_artwork_tint",
        "media_artwork_full_color",
        "show_episode_progress",
        "icon_background_color",
        "icon_text_color",
        "icon_follow_accent",
        "interface_language",
        "timezone",
        "language",
        "region",
        "advanced_ratings_enabled",
        "release_check_mode",
        "sidebar_mode",
        "navigation_order",
    }
)

# These settings are meaningful only on the current computer and must never be
# carried in an archive. In particular, importing a backup must not silently
# opt another computer into querying its OS credential store.
LOCAL_PREFERENCE_KEYS = frozenset(
    {
        "credential_storage",
        "credential_vault_opt_in",
        "keyboard_shortcuts",
        "background_image_enabled",
        "background_image_opacity",
        "background_image_tint",
        "settings_privacy_reminder_dismissed",
    }
)
ACCOUNT_ONLY_PREFERENCE_KEYS = frozenset({"use_server_metadata_token"})
WRITABLE_PREFERENCE_KEYS = (
    PORTABLE_PREFERENCE_KEYS | LOCAL_PREFERENCE_KEYS | ACCOUNT_ONLY_PREFERENCE_KEYS
)
SERVER_GLOBAL_PREFERENCE_KEYS = frozenset({"credential_storage", "credential_vault_opt_in"})


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".preferences-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            json.dump(value, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except Exception:
        with suppress(OSError):
            os.unlink(temporary_name)
        raise


class PreferenceStore:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | None = None,
    ):
        self.settings = settings
        self.path = settings.preferences_path
        self.session_factory = session_factory
        self._write_lock = threading.RLock()

    def bind_session_factory(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def _file_value(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("preferences root must be an object")
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return value

    def load(self, user_id: str | None = None) -> dict[str, Any]:
        file_value = self._file_value()
        if user_id is not None and self.settings.access_mode == "server":
            # Only installation credential-vault choices are shared. Interface,
            # keyboard, diary, and release preferences come from this user row.
            value = {
                key: item
                for key, item in file_value.items()
                if key in SERVER_GLOBAL_PREFERENCE_KEYS
            }
        else:
            value = file_value
        merged = {**DEFAULT_PREFERENCES, **value}
        if user_id is not None and self.session_factory is not None:
            with self.session_factory() as session:
                record = session.get(UserPreference, user_id)
                if record is not None:
                    merged.update(record.preferences or {})
        # Accent presets were removed in 2.2. Preserve the exact colour chosen
        # by older releases and present it through the single custom picker.
        accent_color = merged.get("accent_color")
        if not isinstance(accent_color, str) or not accent_color.startswith("#"):
            merged["accent_color"] = LEGACY_ACCENT_COLORS.get(
                str(merged.get("accent")), LEGACY_ACCENT_COLORS["forest"]
            )
        return merged

    def update(self, *, user_id: str | None = None, **changes: Any) -> dict[str, Any]:
        # FastAPI may handle two settings requests on different worker threads
        # (for example, an automatic colour save and an explicit General save).
        # Keep the read-modify-write cycle indivisible so neither update can
        # replace the other with an older preferences snapshot.
        with self._write_lock:
            allowed = {
                key: item for key, item in changes.items() if key in WRITABLE_PREFERENCE_KEYS
            }
            file_value = self.load()
            if user_id is not None and self.settings.access_mode == "server":
                file_changes = {
                    key: item
                    for key, item in allowed.items()
                    if key in SERVER_GLOBAL_PREFERENCE_KEYS
                }
                database_changes = {
                    key: item
                    for key, item in allowed.items()
                    if key not in SERVER_GLOBAL_PREFERENCE_KEYS
                }
            else:
                file_changes = {
                    key: item
                    for key, item in allowed.items()
                    if key in LOCAL_PREFERENCE_KEYS
                    or user_id is None
                    or self.settings.access_mode == "local"
                }
                database_changes = {
                    key: item
                    for key, item in allowed.items()
                    if key in PORTABLE_PREFERENCE_KEYS
                }
            if file_changes:
                file_value.update(file_changes)
                _atomic_json(self.path, file_value)
            if user_id is not None and self.session_factory is not None and database_changes:
                with self.session_factory() as session, session.begin():
                    record = session.get(UserPreference, user_id)
                    if record is None:
                        record = UserPreference(user_id=user_id, preferences={})
                        session.add(record)
                    record.preferences = {
                        **(record.preferences or {}),
                        **database_changes,
                    }
            return self.load(user_id)

    def migrate_legacy_user_preferences(self) -> bool:
        """Copy an existing single-user JSON profile into its new database owner once."""
        if self.session_factory is None:
            return False
        legacy = {
            key: item
            for key, item in self._file_value().items()
            if key in WRITABLE_PREFERENCE_KEYS and key not in SERVER_GLOBAL_PREFERENCE_KEYS
        }
        if not legacy:
            return False
        from watchtracker.models import UserAccount

        with self.session_factory() as session, session.begin():
            user_ids = list(
                session.scalars(select(UserAccount.id).order_by(UserAccount.id).limit(2))
            )
            if len(user_ids) != 1:
                return False
            record = session.get(UserPreference, user_ids[0])
            if record is None:
                record = UserPreference(user_id=user_ids[0], preferences={})
                session.add(record)
            if record.preferences:
                return False
            record.preferences = legacy
        return True

    def portable(self, user_id: str | None = None) -> dict[str, Any]:
        """Return preferences that are safe to carry between installations."""
        value = self.load(user_id)
        return {key: value[key] for key in PORTABLE_PREFERENCE_KEYS if key in value}

    def replace(self, value: dict[str, Any]) -> dict[str, Any]:
        _atomic_json(self.path, value)
        return value

    def apply_runtime_values(self) -> dict[str, Any]:
        value = self.load()
        environment = os.environ
        if "WATCHTRACKER_TIMEZONE" not in environment and value.get("timezone"):
            self.settings.timezone = value["timezone"]
        if "WATCHTRACKER_LANGUAGE" not in environment and value.get("language"):
            self.settings.language = value["language"]
        if "WATCHTRACKER_REGION" not in environment and value.get("region"):
            self.settings.region = value["region"]
        return value
