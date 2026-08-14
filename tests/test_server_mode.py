from __future__ import annotations

import os
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from watchtracker import __version__
from watchtracker.app import create_app
from watchtracker.config import Settings
from watchtracker.models import OwnerSession
from watchtracker.services.backups import DATABASE_MEMBER, ScheduledBackupService


def _server_settings(settings: Settings, **updates) -> Settings:
    values = {
        "access_mode": "server",
        "host": "127.0.0.1",
        "public_base_url": "https://owner.example",
        "application_secret": "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
        * 2,
        "trusted_hosts": "owner.example",
        "trusted_proxy_ips": "127.0.0.1,::1",
        "release_scheduler_enabled": False,
    }
    values.update(updates)
    return settings.model_copy(update=values)


def _bootstrap(client: TestClient, password: str = "correct horse battery"):
    return client.post(
        "/api/auth/bootstrap",
        headers={"Origin": "http://testserver"},
        json={"password": password},
    )


def test_access_configuration_fails_closed(settings, app):
    with pytest.raises(ValueError, match="loopback"):
        create_app(
            settings.model_copy(update={"host": "0.0.0.0"}),
            metadata_service=app.state.metadata,
            secret_store=app.state.secrets,
        )
    with pytest.raises(ValueError, match="HTTPS"):
        create_app(
            settings.model_copy(update={"access_mode": "server", "host": "127.0.0.1"}),
            metadata_service=app.state.metadata,
            secret_store=app.state.secrets,
        )
    unsafe = _server_settings(settings, trusted_hosts="*")
    with pytest.raises(ValueError, match="without wildcards"):
        create_app(
            unsafe,
            metadata_service=app.state.metadata,
            secret_store=app.state.secrets,
        )


def test_owner_bootstrap_locks_and_server_requires_an_owner(settings, app):
    server_app = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with (
        pytest.raises(RuntimeError, match="no owner account"),
        TestClient(server_app, base_url="https://owner.example"),
    ):
        pass

    with TestClient(app) as local_client:
        assert _bootstrap(local_client).status_code == 201
        assert _bootstrap(local_client).status_code == 409


def test_server_auth_csrf_session_password_and_headers(settings, app):
    password = "correct horse battery"
    with TestClient(app) as local_client:
        assert _bootstrap(local_client, password).status_code == 201

    server_app = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    origin = {"Origin": "https://owner.example"}
    with TestClient(server_app, base_url="https://owner.example") as client:
        anonymous = client.get("/api/entries")
        assert anonymous.status_code == 401
        assert client.get("/health").json() == {
            "status": "ok",
            "version": __version__,
            "database": "ready",
            "mode": "server",
        }
        assert (
            client.post(
                "/api/auth/login",
                headers=origin,
                json={"username": "owner", "password": "wrong"},
            ).status_code
            == 401
        )
        login = client.post(
            "/api/auth/login",
            headers=origin,
            json={"username": "owner", "password": password},
        )
        assert login.status_code == 200
        assert "HttpOnly" in login.headers.get_list("set-cookie")[0]
        assert all("Secure" in value for value in login.headers.get_list("set-cookie"))
        assert client.get("/api/entries").status_code == 200
        readiness = client.get("/api/server/readiness").json()
        assert readiness["last_connection_at"] is not None
        assert readiness["backup_status"] in {"idle", "running", "failed", "not_started"}
        assert client.post("/api/entries/manual", headers=origin, json={}).status_code == 403

        csrf = client.cookies.get("pmt_csrf")
        secure_headers = {**origin, "X-CSRF-Token": csrf}
        created = client.post(
            "/api/entries/manual",
            headers=secure_headers,
            json={"canonical_title": "Shared Browser Title", "media_type": "movie"},
        )
        assert created.status_code == 201
        assert client.get("/api/entries").json()["total"] == 1
        feed = client.post(
            "/api/exports/upcoming-releases/feed", headers=secure_headers, json={}
        )
        assert feed.status_code == 201
        feed_url = feed.json()["feed_url"]
        assert "token=" in feed_url
        calendar = client.get(feed_url)
        assert calendar.status_code == 200
        assert "BEGIN:VCALENDAR" in calendar.text
        revoked = client.delete("/api/exports/upcoming-releases/feed", headers=secure_headers)
        assert revoked.json()["revoked"] == 1
        assert client.get(feed_url).status_code == 404
        assert client.post("/api/auth/logout", headers=secure_headers).status_code == 204
        assert client.get("/api/entries").status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                headers=origin,
                json={"username": "owner", "password": password},
            ).status_code
            == 200
        )
        csrf = client.cookies.get("pmt_csrf")
        secure_headers = {**origin, "X-CSRF-Token": csrf}
        page = client.get("/")
        assert page.headers["strict-transport-security"].startswith("max-age=")

        changed = client.post(
            "/api/auth/password",
            headers=secure_headers,
            json={"current_password": password, "new_password": "a newer secure password"},
        )
        assert changed.status_code == 200
        assert client.get("/api/entries").status_code == 401
        relogin = client.post(
            "/api/auth/login",
            headers=origin,
            json={"username": "owner", "password": "a newer secure password"},
        )
        assert relogin.status_code == 200

        with server_app.state.session_factory() as session, session.begin():
            record = session.scalar(
                select(OwnerSession).where(OwnerSession.revoked_at.is_(None))
            )
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert client.get("/api/entries").status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                headers=origin,
                json={"username": "owner", "password": "a newer secure password"},
            ).status_code
            == 200
        )
        csrf = client.cookies.get("pmt_csrf")
        revoked_sessions = client.post(
            "/api/auth/sessions/revoke",
            headers={**origin, "X-CSRF-Token": csrf},
        )
        assert revoked_sessions.status_code == 200
        assert client.get("/api/entries").status_code == 401


def test_login_backoff_and_host_origin_proxy_rules(settings, app):
    with TestClient(app) as local_client:
        assert _bootstrap(local_client).status_code == 201
    server_app = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server_app, base_url="https://owner.example") as client:
        assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
        for _ in range(5):
            response = client.post(
                "/api/auth/login",
                headers={"Origin": "https://owner.example"},
                json={"username": "owner", "password": "wrong"},
            )
            assert response.status_code == 401
        blocked = client.post(
            "/api/auth/login",
            headers={"Origin": "https://owner.example"},
            json={"username": "owner", "password": "correct horse battery"},
        )
        assert blocked.status_code == 401
        foreign = client.post(
            "/api/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"username": "owner", "password": "correct horse battery"},
        )
        assert foreign.status_code == 403

    http_app = create_app(
        _server_settings(settings, trusted_proxy_ips="127.0.0.1"),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(http_app, base_url="http://owner.example") as client:
        assert client.get("/").status_code == 426
        assert client.get("/", headers={"X-Forwarded-Proto": "https"}).status_code == 426
        assert client.get("/health").status_code == 200
    with TestClient(
        http_app,
        base_url="http://owner.example",
        client=("127.0.0.1", 50_000),
    ) as client:
        assert client.get("/", headers={"X-Forwarded-Proto": "https"}).status_code == 200


def test_local_activation_creates_backup_and_secret_without_returning_it(
    settings, app, monkeypatch
):
    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def bind(self, _address):
            return None

    with TestClient(app) as client:
        monkeypatch.setattr("watchtracker.app.socket.socket", lambda *_args: Probe())
        before = client.get("/api/server/readiness").json()
        assert before["mode"] == "local"
        assert not settings.resolved_env_path.exists()
        assert not list(settings.resolved_backups_dir.glob("*.zip"))
        assert next(item for item in before["checks"] if item["key"] == "owner")["ok"] is False
        response = client.post(
            "/api/server/activate",
            headers={"Origin": "http://testserver"},
            json={
                "public_base_url": "https://tracker.example",
                "owner_password": "correct horse battery",
                "bind_host": "127.0.0.1",
                "port": 8765,
                "trusted_proxy_ips": ["127.0.0.1", "::1"],
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["restart_required"] is True
        assert "secret" not in str(result).casefold()
        assert (settings.resolved_backups_dir / result["backup"]).is_file()
        with zipfile.ZipFile(settings.resolved_backups_dir / result["backup"]) as archive:
            scrubbed = settings.resolved_data_dir / "scrubbed-backup.sqlite3"
            scrubbed.write_bytes(archive.read(DATABASE_MEMBER))
        with sqlite3.connect(scrubbed) as connection:
            assert connection.execute("SELECT COUNT(*) FROM owner_accounts").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM owner_sessions").fetchone()[0] == 0
            assert (
                connection.execute("SELECT COUNT(*) FROM calendar_feed_tokens").fetchone()[0]
                == 0
            )
        contents = settings.resolved_env_path.read_text(encoding="utf-8")
        assert "WATCHTRACKER_ACCESS_MODE=server" in contents
        assert "WATCHTRACKER_APPLICATION_SECRET=" in contents
        if os.name != "nt":
            assert settings.resolved_env_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_scheduled_backups_persist_status_and_apply_retention(settings, app):
    with TestClient(app):
        scheduler = ScheduledBackupService(
            app.state.backups,
            app.state.session_factory,
            interval_hours=24,
            retention=2,
        )
        for _ in range(3):
            result = await scheduler.run_once(force=True)
            assert result["status"] == "completed"
        files = list(
            settings.resolved_backups_dir.glob("personal-media-tracker-scheduled-*.zip")
        )
        assert len(files) == 2
        due = await scheduler.run_once()
        assert due["status"] == "not_due"
