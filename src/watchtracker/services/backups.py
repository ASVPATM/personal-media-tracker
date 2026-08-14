from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from watchtracker import __version__
from watchtracker.config import Settings
from watchtracker.db import sqlite_integrity_check, sqlite_online_backup, upgrade_database
from watchtracker.models import SyncJob
from watchtracker.schemas import GeneralSettingsUpdate
from watchtracker.services.exports import watch_log_csv
from watchtracker.services.preferences import (
    PORTABLE_PREFERENCE_KEYS,
    PreferenceStore,
)

DATABASE_MEMBER = "database/watchtracker.sqlite3"
MANIFEST_MEMBER = "manifest.json"
CSV_MEMBER = "exports/watch-log.csv"
PREFERENCES_MEMBER = "settings/preferences.json"
# Stable on-disk identifier retained so every pre-rename archive remains valid.
BACKUP_FORMAT = "personal-watch-tracker-backup"
BACKUP_FORMAT_VERSION = 2
SUPPORTED_FORMAT_VERSIONS = {1, BACKUP_FORMAT_VERSION}


class BackupError(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S-%f")


def _sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return _sha256_stream(source)


def _sha256_seekable(source: BinaryIO) -> str:
    source.seek(0)
    value = _sha256_stream(source)
    source.seek(0)
    return value


def _seekable_size(source: BinaryIO) -> int:
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(0)
    return size


def _member_record(value: bytes) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}


def _database_summary(path: Path) -> dict[str, Any]:
    """Read only actual database facts; never trust display counts in a manifest."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

        def count(table: str, where: str = "") -> int:
            if table not in tables:
                return 0
            # Table names and clauses here are fixed application constants.
            return int(
                connection.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
            )

        entry_columns = (
            {row[1] for row in connection.execute("PRAGMA table_info(watch_entries)")}
            if "watch_entries" in tables
            else set()
        )
        titles = count("watch_entries")
        if "deleted_at" in entry_columns:
            deleted_titles = count("watch_entries", "WHERE deleted_at IS NOT NULL")
        else:
            deleted_titles = 0
        revision = None
        if "alembic_version" in tables:
            row = connection.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchone()
            revision = row[0] if row else None
        return {
            "catalog_items": count("catalog_items"),
            "titles": titles,
            "active_titles": titles - deleted_titles,
            "deleted_titles": deleted_titles,
            "viewing_events": count("viewing_events"),
            "audit_events": count("audit_events"),
            "import_history": count("import_history"),
            "rating_assessments": count("rating_assessments"),
            "rating_comparisons": count("rating_comparisons"),
            "rating_refinement_runs": count("rating_refinement_runs"),
            "series_subscriptions": count("series_tracking_subscriptions"),
            "seasons": count("season_records"),
            "episodes": count("episode_records"),
            "episode_viewings": count("episode_viewings"),
            "release_events": count("release_events"),
            "database_revision": revision,
        }
    except sqlite3.DatabaseError as exc:
        raise BackupError("The tracker database could not be inspected.") from exc
    finally:
        connection.close()


def _scrub_server_auth(path: Path) -> None:
    """Remove machine/session authentication state from portable archives."""
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA busy_timeout = 5000")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        for table in (
            "calendar_feed_tokens",
            "owner_sessions",
            "login_throttles",
            "owner_accounts",
        ):
            if table in tables:
                connection.execute(f"DELETE FROM {table}")
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
        # The copied database retains WAL mode. Merge the scrub and VACUUM into the
        # main file because that is the only database member placed in the archive.
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and checkpoint[0] != 0:
            raise BackupError("The portable backup could not be safely finalized.")
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    # Verify the exact main-file view that an archive recipient will receive.
    with sqlite3.connect(f"file:{path}?immutable=1", uri=True) as connection:
        for table in (
            "calendar_feed_tokens",
            "owner_sessions",
            "login_throttles",
            "owner_accounts",
        ):
            if (
                table in tables
                and connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            ):
                raise BackupError("The portable backup retained server authentication state.")


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size: int
    created_at: str


@dataclass(frozen=True)
class PreparedBackup:
    database: Path
    manifest: dict[str, Any] | None
    preferences: dict[str, Any] | None
    source_kind: str


class BackupService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        session_factory: sessionmaker[Session],
    ):
        self.settings = settings
        self.engine = engine
        self.session_factory = session_factory
        self.preferences = PreferenceStore(settings)

    def create(self, *, prefix: str = "personal-media-tracker-backup") -> BackupResult:
        """Create a complete, portable and human-auditable library archive."""
        self.settings.resolved_backups_dir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(UTC).isoformat()
        destination = self.settings.resolved_backups_dir / f"{prefix}-{_stamp()}.zip"
        with tempfile.TemporaryDirectory(prefix="watchtracker-backup-") as temporary_dir:
            snapshot = Path(temporary_dir) / "watchtracker.sqlite3"
            sqlite_online_backup(self.settings.resolved_database_path, snapshot)
            _scrub_server_auth(snapshot)
            with self.session_factory() as session:
                csv_value = watch_log_csv(session)
            csv_bytes = csv_value.encode("utf-8")
            portable_preferences = self.preferences.portable()
            portable_preferences.update(
                {
                    "timezone": self.settings.timezone,
                    "language": self.settings.language,
                    "region": self.settings.region,
                }
            )
            preference_bytes = (
                json.dumps(portable_preferences, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            database_summary = _database_summary(snapshot)
            manifest = {
                "format": BACKUP_FORMAT,
                "format_version": BACKUP_FORMAT_VERSION,
                "application_version": __version__,
                "created_at": created_at,
                "includes_credentials": False,
                "contents": {
                    DATABASE_MEMBER: {
                        "sha256": _sha256_file(snapshot),
                        "size": snapshot.stat().st_size,
                    },
                    CSV_MEMBER: _member_record(csv_bytes),
                    PREFERENCES_MEMBER: _member_record(preference_bytes),
                },
                "database": database_summary,
                "portability": {
                    "full_database": True,
                    "preferences": sorted(PORTABLE_PREFERENCE_KEYS),
                    "credentials_excluded": True,
                    "machine_specific_window_state_excluded": True,
                    "server_authentication_state_excluded": True,
                },
            }
            temporary_zip = destination.with_suffix(".zip.tmp")
            try:
                with zipfile.ZipFile(
                    temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                ) as archive:
                    archive.write(snapshot, DATABASE_MEMBER)
                    archive.writestr(
                        MANIFEST_MEMBER, json.dumps(manifest, indent=2, sort_keys=True) + "\n"
                    )
                    archive.writestr(CSV_MEMBER, csv_bytes)
                    archive.writestr(PREFERENCES_MEMBER, preference_bytes)
                os.replace(temporary_zip, destination)
            except Exception:
                temporary_zip.unlink(missing_ok=True)
                raise
        return BackupResult(destination, destination.stat().st_size, created_at)

    @staticmethod
    def _validate_zip_members(archive: zipfile.ZipFile) -> set[str]:
        members = archive.infolist()
        if len(members) > 20:
            raise BackupError("The backup contains an unexpected number of files.")
        names = {member.filename for member in members}
        if len(names) != len(members):
            raise BackupError("The backup contains duplicate file names.")
        if any(
            member.flag_bits & 0x1
            or member.filename.startswith(("/", "\\"))
            or ".." in Path(member.filename).parts
            for member in members
        ):
            raise BackupError("The backup contains an unsafe file entry.")
        return names

    @staticmethod
    def _validate_member_size(info: zipfile.ZipInfo, maximum: int, label: str) -> None:
        if info.file_size > maximum:
            raise BackupError(f"The backup {label} is too large.")
        if info.file_size > 1024 * 1024 and (
            info.compress_size == 0 or info.file_size / info.compress_size > 250
        ):
            raise BackupError(f"The backup {label} has an unsafe compression ratio.")

    @staticmethod
    def _validate_record(archive: zipfile.ZipFile, member_name: str, record: Any) -> None:
        if not isinstance(record, dict):
            raise BackupError("The backup checksum manifest is incomplete.")
        expected_hash = record.get("sha256")
        expected_size = record.get("size")
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise BackupError("The backup checksum manifest is invalid.")
        info = archive.getinfo(member_name)
        if info.file_size != expected_size:
            raise BackupError(f"Backup verification failed for {member_name}.")
        with archive.open(info) as source:
            actual_hash = _sha256_stream(source)
        if actual_hash != expected_hash.lower():
            raise BackupError(f"Backup verification failed for {member_name}.")

    @staticmethod
    def _portable_preferences(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - PORTABLE_PREFERENCE_KEYS:
            raise BackupError("The portable preferences are not recognized.")
        try:
            validated = GeneralSettingsUpdate.model_validate(value)
        except ValidationError as exc:
            raise BackupError("The portable preferences are invalid.") from exc
        if any(
            key in value and value[key] is None
            for key in ("onboarding_complete", "theme", "language", "region")
        ):
            raise BackupError("The portable preferences are invalid.")
        return validated.model_dump(exclude_unset=True)

    def _apply_portable_runtime_values(self, value: dict[str, Any]) -> None:
        environment = os.environ
        for preference_key, environment_key in (
            ("timezone", "WATCHTRACKER_TIMEZONE"),
            ("language", "WATCHTRACKER_LANGUAGE"),
            ("region", "WATCHTRACKER_REGION"),
        ):
            if environment_key not in environment and preference_key in value:
                setattr(self.settings, preference_key, value[preference_key])

    def _database_from_upload(
        self, filename: str, source: BinaryIO, directory: Path
    ) -> PreparedBackup:
        candidate = directory / "incoming.sqlite3"
        manifest: dict[str, Any] | None = None
        portable_preferences: dict[str, Any] | None = None
        source_kind = "sqlite_database"
        source.seek(0)
        header = source.read(16)
        source.seek(0)
        if header.startswith(b"PK"):
            source_kind = "portable_archive"
            try:
                with zipfile.ZipFile(source) as archive:
                    names = self._validate_zip_members(archive)
                    if DATABASE_MEMBER not in names or MANIFEST_MEMBER not in names:
                        raise BackupError("This is not a Personal Media Tracker backup.")
                    manifest_info = archive.getinfo(MANIFEST_MEMBER)
                    self._validate_member_size(manifest_info, 64 * 1024, "manifest")
                    manifest = json.loads(archive.read(MANIFEST_MEMBER))
                    if (
                        not isinstance(manifest, dict)
                        or manifest.get("format") != BACKUP_FORMAT
                    ):
                        raise BackupError("The backup manifest is not recognized.")
                    format_version = manifest.get("format_version")
                    if format_version not in SUPPORTED_FORMAT_VERSIONS:
                        raise BackupError("This backup format version is not supported.")

                    database_info = archive.getinfo(DATABASE_MEMBER)
                    self._validate_member_size(
                        database_info, 2 * 1024 * 1024 * 1024, "database"
                    )
                    if format_version == BACKUP_FORMAT_VERSION:
                        required = {DATABASE_MEMBER, CSV_MEMBER, PREFERENCES_MEMBER}
                        if not required.issubset(names):
                            raise BackupError("The portable archive is incomplete.")
                        contents = manifest.get("contents")
                        if not isinstance(contents, dict):
                            raise BackupError("The backup checksum manifest is incomplete.")
                        for member_name in required:
                            self._validate_record(
                                archive, member_name, contents.get(member_name)
                            )
                        preference_info = archive.getinfo(PREFERENCES_MEMBER)
                        self._validate_member_size(
                            preference_info, 64 * 1024, "preferences file"
                        )
                        portable_preferences = self._portable_preferences(
                            json.loads(archive.read(PREFERENCES_MEMBER))
                        )
                    else:
                        source_kind = "legacy_backup_archive"

                    with archive.open(database_info) as source, candidate.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            except BackupError:
                raise
            except (
                zipfile.BadZipFile,
                KeyError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                RuntimeError,
            ) as exc:
                raise BackupError("The backup ZIP is invalid or incomplete.") from exc
        else:
            if not header.startswith(b"SQLite format 3\x00"):
                raise BackupError("Choose a tracker portable archive or SQLite database.")
            with candidate.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        try:
            sqlite_integrity_check(candidate)
        except RuntimeError as exc:
            raise BackupError(str(exc)) from exc
        return PreparedBackup(candidate, manifest, portable_preferences, source_kind)

    def inspect(self, filename: str, content: bytes) -> dict[str, Any]:
        """Validate a migration source and return an actual-data preview without mutating it."""
        return self.inspect_file(filename, io.BytesIO(content))

    def inspect_file(self, filename: str, source: BinaryIO) -> dict[str, Any]:
        """Stream-validate a migration source without mutating the active library."""
        size = _seekable_size(source)
        if not size:
            raise BackupError("The selected migration file is empty.")
        archive_sha256 = _sha256_seekable(source)
        with tempfile.TemporaryDirectory(prefix="watchtracker-inspect-") as temporary_dir:
            prepared = self._database_from_upload(filename, source, Path(temporary_dir))
            summary = _database_summary(prepared.database)
        manifest = prepared.manifest or {}
        return {
            "status": "ready",
            "filename": Path(filename).name,
            "sha256": archive_sha256,
            "size": size,
            "source_kind": prepared.source_kind,
            "format_version": manifest.get("format_version"),
            "source_application_version": manifest.get("application_version"),
            "created_at": manifest.get("created_at"),
            "preferences_included": prepared.preferences is not None,
            "credentials_included": False,
            **summary,
        }

    def restore(
        self,
        filename: str,
        content: bytes,
        *,
        import_existing: bool = False,
        expected_sha256: str | None = None,
    ) -> dict:
        return self.restore_file(
            filename,
            io.BytesIO(content),
            import_existing=import_existing,
            expected_sha256=expected_sha256,
        )

    def restore_file(
        self,
        filename: str,
        source: BinaryIO,
        *,
        import_existing: bool = False,
        expected_sha256: str | None = None,
    ) -> dict:
        if not _seekable_size(source):
            raise BackupError("The selected backup is empty.")
        if expected_sha256 is not None:
            actual_sha256 = _sha256_seekable(source)
            if len(expected_sha256) != 64 or not hmac.compare_digest(
                expected_sha256.lower(), actual_sha256
            ):
                raise BackupError(
                    "The selected migration file changed after inspection. Inspect it again."
                )
        current = self.settings.resolved_database_path
        self.settings.resolved_backups_dir.mkdir(parents=True, exist_ok=True)
        safety_path = (
            self.settings.resolved_backups_dir / f"pre-restore-safety-{_stamp()}.sqlite3"
        )
        with tempfile.TemporaryDirectory(prefix="watchtracker-restore-") as temporary_dir:
            prepared = self._database_from_upload(filename, source, Path(temporary_dir))
            if import_existing:
                original_copy = self.settings.resolved_backups_dir / (
                    f"import-source-{_stamp()}.sqlite3"
                )
                shutil.copy2(prepared.database, original_copy)
            sqlite_online_backup(current, safety_path)
            staged = current.with_suffix(".restore.tmp")
            shutil.copy2(prepared.database, staged)
            previous_preferences = self.preferences.load()
            previous_runtime_values = (
                self.settings.timezone,
                self.settings.language,
                self.settings.region,
            )
            preferences_changed = False
            try:
                self.engine.dispose()
                for companion in (
                    current.with_name(current.name + "-wal"),
                    current.with_name(current.name + "-shm"),
                ):
                    companion.unlink(missing_ok=True)
                os.replace(staged, current)
                migration = upgrade_database(self.settings)
                sqlite_integrity_check(current)
                if prepared.preferences is not None:
                    self.preferences.update(**prepared.preferences)
                    preferences_changed = True
                    self._apply_portable_runtime_values(prepared.preferences)
            except Exception as exc:
                staged.unlink(missing_ok=True)
                self.engine.dispose()
                for companion in (
                    current.with_name(current.name + "-wal"),
                    current.with_name(current.name + "-shm"),
                ):
                    companion.unlink(missing_ok=True)
                shutil.copy2(safety_path, current)
                if preferences_changed:
                    self.preferences.replace(previous_preferences)
                    (
                        self.settings.timezone,
                        self.settings.language,
                        self.settings.region,
                    ) = previous_runtime_values
                raise BackupError(
                    "Restore failed. The previous database was recovered from the safety backup."
                ) from exc
        return {
            "status": "restored",
            "safety_backup": safety_path.name,
            "migration_applied": migration.changed,
            "preferences_restored": prepared.preferences is not None,
            "restart_required": False,
        }


class ScheduledBackupService:
    """Persistent, bounded server backup loop; it never runs in local desktop mode."""

    JOB_NAME = "scheduled-backup"

    def __init__(
        self,
        backups: BackupService,
        session_factory: sessionmaker[Session],
        *,
        interval_hours: int,
        retention: int,
        now_factory=lambda: datetime.now(UTC),
    ):
        self.backups = backups
        self.session_factory = session_factory
        self.interval = timedelta(hours=interval_hours)
        self.retention = retention
        self.now_factory = now_factory
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            # A FastAPI application can be started again by test hosts and embedded
            # launchers, each with a new event loop. Do not retain a loop-bound Event.
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._loop(), name="pmt-scheduled-backup")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), timeout=min(self.interval.total_seconds(), 300)
                )

    async def run_once(self, *, force: bool = False) -> dict[str, Any]:
        now = self.now_factory()
        with self.session_factory() as session, session.begin():
            job = session.scalar(select(SyncJob).where(SyncJob.name == self.JOB_NAME))
            if job is None:
                job = SyncJob(name=self.JOB_NAME, state="idle", next_run_at=now)
                session.add(job)
                session.flush()
            if not force and job.next_run_at and _aware(job.next_run_at) > now:
                return {"status": "not_due", "next_run_at": job.next_run_at}
            job.state = "running"
            job.last_attempt_at = now
        try:
            result = await asyncio.to_thread(
                self.backups.create, prefix="personal-media-tracker-scheduled"
            )
            self._prune()
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Scheduled backup failed: type=%s", type(exc).__name__
            )
            with self.session_factory() as session, session.begin():
                job = session.scalar(select(SyncJob).where(SyncJob.name == self.JOB_NAME))
                job.state = "failed"
                job.failure_count += 1
                job.last_error_code = "backup_failed"
                job.last_error_message = "The scheduled backup could not be written."
                job.next_run_at = now + min(
                    timedelta(hours=2 ** min(job.failure_count - 1, 5)), self.interval
                )
            return {"status": "failed", "message": "The scheduled backup could not be written."}
        with self.session_factory() as session, session.begin():
            job = session.scalar(select(SyncJob).where(SyncJob.name == self.JOB_NAME))
            job.state = "idle"
            job.last_success_at = now
            job.next_run_at = now + self.interval
            job.failure_count = 0
            job.last_error_code = None
            job.last_error_message = None
        return {
            "status": "completed",
            "filename": result.path.name,
            "next_run_at": now + self.interval,
        }

    def _prune(self) -> None:
        files = sorted(
            self.backups.settings.resolved_backups_dir.glob(
                "personal-media-tracker-scheduled-*.zip"
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[self.retention :]:
            path.unlink(missing_ok=True)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
