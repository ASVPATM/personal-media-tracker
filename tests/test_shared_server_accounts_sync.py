from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from watchtracker.app import create_app
from watchtracker.config import Settings
from watchtracker.services.backups import DATABASE_MEMBER


def _server_settings(settings: Settings, **updates) -> Settings:
    values = {
        "access_mode": "server",
        "host": "127.0.0.1",
        "public_base_url": "https://family.example",
        "application_secret": "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
        * 2,
        "server_bootstrap_token": "bootstrap-token-that-is-long-and-random",
        "trusted_hosts": "family.example",
        "trusted_proxy_ips": "127.0.0.1,::1",
        "release_scheduler_enabled": False,
    }
    values.update(updates)
    return settings.model_copy(update=values)


def _bootstrap_and_login(client: TestClient) -> dict[str, str]:
    bootstrap = client.post(
        "/api/v1/setup/bootstrap",
        json={
            "setup_token": "bootstrap-token-that-is-long-and-random",
            "username": "admin",
            "display_name": "Server Admin",
            "password": "correct horse battery",
        },
    )
    assert bootstrap.status_code == 201
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://family.example"},
        json={"username": "admin", "password": "correct horse battery"},
    )
    assert login.status_code == 200
    return {
        "Origin": "https://family.example",
        "X-CSRF-Token": client.cookies.get("pmt_csrf"),
    }


def test_headless_bootstrap_invitation_login_and_disable(settings, app):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as admin:
        capabilities = admin.get("/api/v1/server/capabilities").json()
        assert capabilities["setup_required"] is True
        assert capabilities["library_authority"] == "pmt_server"
        assert capabilities["features"]["icloud_library"] is False
        assert admin.get("/ready", headers={"Host": "127.0.0.1"}).status_code == 200
        headers = _bootstrap_and_login(admin)
        assert admin.get("/api/v1/me").json()["role"] == "admin"

        issued = admin.post(
            "/api/v1/admin/invitations",
            headers=headers,
            json={"role": "member", "expires_hours": 24},
        )
        assert issued.status_code == 201
        token = issued.json()["token"]
        accepted = admin.post(
            "/api/v1/auth/invitations/redeem",
            json={
                "token": token,
                "username": "family-member",
                "display_name": "Family Member",
                "password": "another secure password",
            },
        )
        assert accepted.status_code == 201
        member_id = accepted.json()["account"]["id"]
        assert (
            admin.post(
                "/api/v1/auth/invitations/redeem",
                json={
                    "token": token,
                    "username": "replay",
                    "display_name": "Replay",
                    "password": "another secure password",
                },
            ).status_code
            == 409
        )

        member = TestClient(server, base_url="https://family.example")
        try:
            assert (
                member.post(
                    "/api/auth/login",
                    headers={"Origin": "https://family.example"},
                    json={
                        "username": "family-member",
                        "password": "another secure password",
                    },
                ).status_code
                == 200
            )
            assert member.get("/api/v1/me").json()["id"] == member_id
            disabled = admin.patch(
                f"/api/v1/admin/users/{member_id}",
                headers=headers,
                json={"state": "disabled"},
            )
            assert disabled.status_code == 200
            assert member.get("/api/v1/me").status_code == 401
        finally:
            member.close()


def test_metadata_tokens_are_individual_by_default_with_explicit_server_fallback(settings, app):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as server_account:
        server_headers = _bootstrap_and_login(server_account)
        shared = server_account.put(
            "/api/settings/metadata",
            headers=server_headers,
            json={"tmdb_token": "shared-server-token-1234567890"},
        )
        assert shared.status_code == 200
        assert shared.json()["credential_scope"] == "server_shared"

        issued = server_account.post(
            "/api/v1/admin/invitations",
            headers=server_headers,
            json={"role": "member", "expires_hours": 24},
        ).json()
        accepted = server_account.post(
            "/api/v1/auth/invitations/redeem",
            json={
                "token": issued["token"],
                "username": "metadata-user",
                "display_name": "Metadata User",
                "password": "another secure password",
            },
        )
        assert accepted.status_code == 201

        member = TestClient(server, base_url="https://family.example")
        try:
            login = member.post(
                "/api/auth/login",
                headers={"Origin": "https://family.example"},
                json={
                    "username": "metadata-user",
                    "password": "another secure password",
                },
            )
            assert login.status_code == 200
            member_headers = {
                "Origin": "https://family.example",
                "X-CSRF-Token": member.cookies.get("pmt_csrf"),
            }
            initial = member.get("/api/settings/metadata").json()
            assert initial["tmdb_configured"] is False
            assert initial["server_token_available"] is True
            assert initial["use_server_token"] is False

            fallback = member.put(
                "/api/settings/metadata",
                headers=member_headers,
                json={"use_server_token": True},
            ).json()
            assert fallback["tmdb_configured"] is True
            assert fallback["credential_scope"] == "server_shared"

            individual = member.put(
                "/api/settings/metadata",
                headers=member_headers,
                json={"tmdb_token": "individual-user-token-123456789"},
            ).json()
            assert individual["individual_token_configured"] is True
            assert individual["credential_scope"] == "individual"
            assert "token" not in individual

            unchanged = server_account.get("/api/settings/metadata").json()
            assert unchanged["credential_scope"] == "server_shared"
            assert unchanged["tmdb_configured"] is True
        finally:
            member.close()


def test_regular_user_can_change_password_and_old_sessions_are_revoked(settings, app):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as server_account:
        server_headers = _bootstrap_and_login(server_account)
        invitation = server_account.post(
            "/api/v1/admin/invitations",
            headers=server_headers,
            json={"role": "member", "expires_hours": 24},
        ).json()
        assert (
            server_account.post(
                "/api/v1/auth/invitations/redeem",
                json={
                    "token": invitation["token"],
                    "username": "password-user",
                    "display_name": "Password User",
                    "password": "original secure password",
                },
            ).status_code
            == 201
        )

        member = TestClient(server, base_url="https://family.example")
        other_session = TestClient(server, base_url="https://family.example")
        try:
            for client in (member, other_session):
                assert (
                    client.post(
                        "/api/auth/login",
                        headers={"Origin": "https://family.example"},
                        json={
                            "username": "password-user",
                            "password": "original secure password",
                        },
                    ).status_code
                    == 200
                )
            changed = member.post(
                "/api/auth/password",
                headers={
                    "Origin": "https://family.example",
                    "X-CSRF-Token": member.cookies.get("pmt_csrf"),
                },
                json={
                    "current_password": "original secure password",
                    "new_password": "replacement secure password",
                },
            )
            assert changed.status_code == 200
            assert changed.json() == {"changed": True, "sessions_revoked": True}
            assert member.get("/api/v1/me").status_code == 401
            assert other_session.get("/api/v1/me").status_code == 401
            assert (
                member.post(
                    "/api/auth/login",
                    headers={"Origin": "https://family.example"},
                    json={
                        "username": "password-user",
                        "password": "original secure password",
                    },
                ).status_code
                == 401
            )
            assert (
                member.post(
                    "/api/auth/login",
                    headers={"Origin": "https://family.example"},
                    json={
                        "username": "password-user",
                        "password": "replacement secure password",
                    },
                ).status_code
                == 200
            )
        finally:
            member.close()
            other_session.close()


def test_native_device_token_idempotent_sync_and_conflict(settings, app):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as client:
        _bootstrap_and_login(client)
        native = client.post(
            "/api/v1/auth/device/login",
            json={
                "username": "admin",
                "password": "correct horse battery",
                "device_id": "iphone-test-device",
                "device_label": "Test iPhone",
            },
        )
        assert native.status_code == 200
        tokens = native.json()
        bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
        created = client.post(
            "/api/entries/manual",
            headers=bearer,
            json={"canonical_title": "Synced title", "media_type": "movie"},
        )
        assert created.status_code == 201
        entry = created.json()["entry"]
        assert entry["version"] == 1

        mutation = {
            "device_id": "iphone-test-device",
            "mutations": [
                {
                    "request_id": "request-00000001",
                    "operation": "entry.patch",
                    "resource_id": entry["id"],
                    "base_version": 1,
                    "payload": {"notes": "Edited while offline"},
                    "client_timestamp": "2026-08-26T12:00:00Z",
                }
            ],
        }
        applied = client.post("/api/v1/sync/push", headers=bearer, json=mutation)
        assert applied.status_code == 200
        assert applied.json()["results"][0]["version"] == 2
        duplicate = client.post("/api/v1/sync/push", headers=bearer, json=mutation)
        assert duplicate.json()["results"][0]["duplicate"] is True

        mutation["mutations"][0]["request_id"] = "request-00000002"
        mutation["mutations"][0]["payload"] = {"notes": "Stale overwrite"}
        conflict = client.post("/api/v1/sync/push", headers=bearer, json=mutation).json()
        assert conflict["results"][0]["status"] == "conflict"
        assert conflict["results"][0]["current"]["notes"] == "Edited while offline"
        assert client.get("/api/v1/sync/pull", headers=bearer).json()["changes"]

        refreshed = client.post(
            "/api/v1/auth/device/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
        assert client.get("/api/v1/me", headers=bearer).status_code == 401


def test_server_disaster_backup_is_restorable_and_has_no_live_sessions(settings, app):
    server_settings = _server_settings(settings)
    server = create_app(
        server_settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as client:
        headers = _bootstrap_and_login(client)
        response = client.post("/api/v1/admin/backups", headers=headers)
        assert response.status_code == 201
        payload = response.json()
        assert payload["verification"]["status"] == "verified"
        archive_path = server_settings.resolved_backups_dir / payload["filename"]
        with zipfile.ZipFile(archive_path) as archive:
            restored = Path(server_settings.resolved_data_dir) / "server-backup-check.sqlite3"
            restored.write_bytes(archive.read(DATABASE_MEMBER))
        with sqlite3.connect(restored) as connection:
            assert connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0] == 0
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM user_accounts WHERE password_hash IS NOT NULL"
                ).fetchone()[0]
                == 1
            )
