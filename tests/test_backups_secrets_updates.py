from __future__ import annotations

import hashlib
import io
import json
import zipfile

import httpx
import pytest
from conftest import manual_payload

from watchtracker.services.secrets import (
    ACCOUNT_NAME,
    LEGACY_SERVICE_NAME,
    SERVICE_NAME,
    SecretStore,
)
from watchtracker.services.updates import UpdateCheckError, UpdateService


class FakeKeyring:
    def __init__(self):
        self.values = {}

    @property
    def value(self):
        return self.values.get(SERVICE_NAME)

    @value.setter
    def value(self, item):
        if item is None:
            self.values.pop(SERVICE_NAME, None)
        else:
            self.values[SERVICE_NAME] = item

    def get_password(self, service_name, username):
        assert service_name in {SERVICE_NAME, LEGACY_SERVICE_NAME}
        assert username == ACCOUNT_NAME
        return self.values.get(service_name)

    def set_password(self, service_name, username, password):
        assert (service_name, username) == (SERVICE_NAME, ACCOUNT_NAME)
        self.values[service_name] = password

    def delete_password(self, service_name, username):
        assert (service_name, username) == (SERVICE_NAME, ACCOUNT_NAME)
        self.values.pop(service_name, None)


def test_secret_store_keyring_save_clear_and_environment_priority(settings, monkeypatch):
    keyring = FakeKeyring()
    store = SecretStore(settings, keyring_backend=keyring)
    assert store.get() == (None, "none")
    assert store.save("x" * 32) == "keychain"
    assert store.get() == ("x" * 32, "keychain")
    monkeypatch.setenv("WATCHTRACKER_TMDB_TOKEN", "environment-token")
    assert store.get() == ("environment-token", "environment")
    assert store.clear() == "environment"
    monkeypatch.delenv("WATCHTRACKER_TMDB_TOKEN")
    assert store.get() == (None, "none")


def test_secret_store_does_not_query_keyring_until_explicitly_enabled(settings):
    class CountingKeyring(FakeKeyring):
        def __init__(self):
            super().__init__()
            self.reads = 0

        def get_password(self, service_name, username):
            self.reads += 1
            return super().get_password(service_name, username)

    keyring = CountingKeyring()
    keyring.value = "existing-keychain-token-" + "k" * 24
    store = SecretStore(settings, keyring_backend=keyring, keyring_enabled=False)
    assert store.get() == (None, "none")
    assert keyring.reads == 0

    assert store.copy_existing_keyring_to_local() == "local_secret_file"
    assert keyring.reads == 1
    assert store.get() == (keyring.value, "local_secret_file")


def test_explicit_vault_migration_accepts_the_previous_product_label(settings):
    keyring = FakeKeyring()
    token = "legacy-service-token-" + "l" * 24
    keyring.values[LEGACY_SERVICE_NAME] = token
    store = SecretStore(settings, keyring_backend=keyring, keyring_enabled=False)
    assert store.get() == (None, "none")
    assert store.copy_existing_keyring_to_local() == "local_secret_file"
    assert store.get() == (token, "local_secret_file")


def test_metadata_api_never_returns_token(client):
    token = "private-token-" + "q" * 32
    saved = client.put("/api/settings/metadata", json={"tmdb_token": token})
    assert saved.status_code == 200
    assert token not in saved.text
    status = client.get("/api/settings/metadata")
    assert status.status_code == 200
    assert token not in status.text


def test_backup_round_trip_preserves_data_and_excludes_credentials(client, settings):
    first = client.post(
        "/api/entries/manual", json=manual_payload("Before backup", notes="private note")
    ).json()["entry"]
    token = "tmdb-read-access-token-" + "z" * 32
    assert client.put("/api/settings/metadata", json={"tmdb_token": token}).status_code == 200
    assert (
        client.put(
            "/api/settings/general",
            json={
                "theme": "dark",
                "accent": "violet",
                "accent_color": "#8a55aa",
                "background_color": "#354a61",
                "background_strength": 64,
                "background_mode": "full",
                "media_artwork_tint": True,
                "interface_language": "fr",
                "release_check_mode": "manual",
                "keyboard_shortcuts": {"library": "Meta+Alt+KeyL"},
                "timezone": "America/Los_Angeles",
            },
        ).status_code
        == 200
    )

    created = client.post("/api/backups", json={})
    assert created.status_code == 200
    backup_path = settings.resolved_backups_dir / created.json()["filename"]
    assert backup_path.exists()
    with zipfile.ZipFile(backup_path) as archive:
        assert set(archive.namelist()) == {
            "database/watchtracker.sqlite3",
            "manifest.json",
            "exports/watch-log.csv",
            "settings/preferences.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == 2
        assert manifest["includes_credentials"] is False
        assert manifest["database"]["active_titles"] == 1
        for name, record in manifest["contents"].items():
            value = archive.read(name)
            assert record == {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
        portable_preferences = json.loads(archive.read("settings/preferences.json"))
        assert portable_preferences["theme"] == "dark"
        assert portable_preferences["accent"] == "violet"
        assert portable_preferences["accent_color"] == "#8a55aa"
        assert portable_preferences["background_color"] == "#354a61"
        assert portable_preferences["background_strength"] == 64
        assert portable_preferences["background_mode"] == "full"
        assert portable_preferences["media_artwork_tint"] is True
        assert portable_preferences["interface_language"] == "fr"
        assert portable_preferences["release_check_mode"] == "manual"
        assert "keyboard_shortcuts" not in portable_preferences
        assert "credential_storage" not in portable_preferences
        assert "window" not in portable_preferences
        combined = b"".join(archive.read(name) for name in archive.namelist())
        assert token.encode() not in combined

    client.post("/api/entries/manual", json=manual_payload("After backup"))
    client.put("/api/settings/general", json={"theme": "light", "timezone": "UTC"})
    assert client.get("/api/entries").json()["total"] == 2
    original_manager = client.app.state.enrichment
    restored = client.post(
        "/api/backups/restore",
        files={"file": (backup_path.name, backup_path.read_bytes(), "application/zip")},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "restored"
    entries = client.get("/api/entries").json()
    assert entries["total"] == 1
    assert entries["items"][0]["id"] == first["id"]
    assert entries["items"][0]["notes"] == "private note"
    assert restored.json()["preferences_restored"] is True
    general = client.get("/api/settings/general").json()
    assert general["theme"] == "dark"
    assert general["accent"] == "violet"
    assert general["accent_color"] == "#8a55aa"
    assert general["background_color"] == "#354a61"
    assert general["background_strength"] == 64
    assert general["background_mode"] == "full"
    assert general["media_artwork_tint"] is True
    assert general["interface_language"] == "fr"
    assert general["release_check_mode"] == "manual"
    # Shortcuts are device-local, so a portable restore must not overwrite the
    # shortcut already configured on this device.
    assert general["keyboard_shortcuts"] == {"library": "Meta+Alt+KeyL"}
    assert general["timezone"] == "America/Los_Angeles"
    assert (settings.resolved_backups_dir / restored.json()["safety_backup"]).exists()
    assert client.app.state.enrichment is not original_manager
    assert client.get("/api/metadata/enrichment").json()["status"] == "idle"


def test_portable_export_can_be_inspected_and_hash_is_bound_before_import(client):
    kept = client.post(
        "/api/entries/manual",
        json=manual_payload("Portable title", personal_rating=9.4, notes="keep all of me"),
    ).json()["entry"]
    removed = client.post(
        "/api/entries/manual", json=manual_payload("Recoverable title")
    ).json()["entry"]
    assert client.delete(f"/api/entries/{removed['id']}").status_code == 204

    exported = client.get("/api/exports/portable-library.zip")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert "personal-media-tracker-everything-" in exported.headers["content-disposition"]

    inspected = client.post(
        "/api/data/portable/inspect",
        files={"file": ("everything.zip", exported.content, "application/zip")},
    )
    assert inspected.status_code == 200
    preview = inspected.json()
    assert preview["status"] == "ready"
    assert preview["source_kind"] == "portable_archive"
    assert preview["active_titles"] == 1
    assert preview["deleted_titles"] == 1
    assert preview["viewing_events"] == 2
    assert preview["preferences_included"] is True
    assert client.get(f"/api/entries/{kept['id']}").status_code == 200

    client.post("/api/entries/manual", json=manual_payload("Must remain"))
    rejected = client.post(
        "/api/data/portable/import",
        files={"file": ("everything.zip", exported.content, "application/zip")},
        data={"archive_sha256": "0" * 64},
    )
    assert rejected.status_code == 400
    assert "changed after inspection" in rejected.json()["error"]["message"]
    assert client.get("/api/entries", params={"include_deleted": True}).json()["total"] == 3

    imported = client.post(
        "/api/data/portable/import",
        files={"file": ("everything.zip", exported.content, "application/zip")},
        data={"archive_sha256": preview["sha256"]},
    )
    assert imported.status_code == 200
    assert imported.json()["status"] == "restored"
    assert imported.json()["preferences_restored"] is True
    assert client.get("/api/entries").json()["total"] == 1
    assert client.get("/api/entries", params={"include_deleted": True}).json()["total"] == 2


def test_portable_archive_checksum_corruption_is_rejected(client):
    client.post("/api/entries/manual", json=manual_payload("Checksum safe"))
    exported = client.get("/api/exports/portable-library.zip").content
    rewritten = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(exported)) as source,
        zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as destination,
    ):
        for name in source.namelist():
            value = source.read(name)
            if name == "settings/preferences.json":
                value = b'{"theme":"light"}\n'
            destination.writestr(name, value)
    response = client.post(
        "/api/data/portable/inspect",
        files={"file": ("corrupt.zip", rewritten.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "verification failed" in response.json()["error"]["message"]


def test_legacy_v1_backup_remains_importable(client, settings):
    client.post("/api/entries/manual", json=manual_payload("Legacy backup title"))
    created = client.post("/api/backups", json={}).json()
    backup_path = settings.resolved_backups_dir / created["filename"]
    legacy = io.BytesIO()
    with (
        zipfile.ZipFile(backup_path) as source,
        zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as destination,
    ):
        manifest = json.loads(source.read("manifest.json"))
        manifest["format_version"] = 1
        manifest.pop("contents", None)
        destination.writestr("manifest.json", json.dumps(manifest))
        destination.writestr(
            "database/watchtracker.sqlite3", source.read("database/watchtracker.sqlite3")
        )
        destination.writestr("exports/watch-log.csv", source.read("exports/watch-log.csv"))
    inspected = client.post(
        "/api/data/portable/inspect",
        files={"file": ("legacy.zip", legacy.getvalue(), "application/zip")},
    )
    assert inspected.status_code == 200
    assert inspected.json()["source_kind"] == "legacy_backup_archive"
    assert inspected.json()["preferences_included"] is False


def test_invalid_restore_is_rejected_without_changing_library(client):
    client.post("/api/entries/manual", json=manual_payload("Safe"))
    response = client.post(
        "/api/backups/restore",
        files={"file": ("invalid.db", b"not a database", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert client.get("/api/entries").json()["total"] == 1


def test_unknown_backup_format_version_is_rejected(client, settings):
    client.post("/api/entries/manual", json=manual_payload("Format stays safe"))
    created = client.post("/api/backups", json={}).json()
    backup_path = settings.resolved_backups_dir / created["filename"]
    rewritten = io.BytesIO()
    with (
        zipfile.ZipFile(backup_path) as source,
        zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as destination,
    ):
        for name in source.namelist():
            value = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(value)
                manifest["format_version"] = 999
                value = json.dumps(manifest).encode()
            destination.writestr(name, value)

    response = client.post(
        "/api/backups/restore",
        files={"file": ("future.zip", rewritten.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "backup_error"
    assert client.get("/api/entries").json()["total"] == 1


def test_backup_with_invalid_manifest_encoding_is_rejected(client, settings):
    client.post("/api/entries/manual", json=manual_payload("Encoding stays safe"))
    created = client.post("/api/backups", json={}).json()
    backup_path = settings.resolved_backups_dir / created["filename"]
    rewritten = io.BytesIO()
    with (
        zipfile.ZipFile(backup_path) as source,
        zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as destination,
    ):
        for name in source.namelist():
            destination.writestr(
                name,
                b"\xff\xfe\xfa" if name == "manifest.json" else source.read(name),
            )

    response = client.post(
        "/api/backups/restore",
        files={"file": ("bad-encoding.zip", rewritten.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "backup_error"
    assert client.get("/api/entries").json()["total"] == 1


@pytest.mark.asyncio
async def test_update_checker_newer_current_invalid_and_offline():
    def response(request: httpx.Request):
        assert request.method == "GET"
        assert request.content == b""
        return httpx.Response(
            200,
            json={
                "tag_name": "v2.1.0",
                "html_url": "https://github.com/ASVPATM/personal-media-tracker/releases/tag/v2.1.0",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await UpdateService(
            "https://github.com/ASVPATM/personal-media-tracker", "2.0.0", client=client
        ).check()
    assert result["update_available"] is True

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "tag_name": "2.0.0",
                    "html_url": "https://github.com/ASVPATM/personal-media-tracker/releases/tag/v2.0.0",
                },
            )
        )
    ) as client:
        current = await UpdateService("https://github.com/o/r", "2.0.0", client=client).check()
    assert current["update_available"] is False

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"bad": True}))
    ) as client:
        with pytest.raises(UpdateCheckError):
            await UpdateService("https://github.com/o/r", "2.0.0", client=client).check()

    async def offline(_request):
        raise httpx.ConnectError("offline")

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
        with pytest.raises(UpdateCheckError, match="connection"):
            await UpdateService("https://github.com/o/r", "2.0.0", client=client).check()
