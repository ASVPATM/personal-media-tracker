from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from watchtracker.app import create_app
from watchtracker.config import Settings
from watchtracker.models import ScheduledJob, UserAccount
from watchtracker.remote_client import (
    MemoryCredentialVault,
    RemoteClientError,
    RemoteDeviceClient,
    RemoteProfileStore,
)
from watchtracker.services.jobs import DurableJobService


def _server_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "access_mode": "server",
            "host": "127.0.0.1",
            "public_base_url": "https://family.example",
            "application_secret": (
                "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_" * 2
            ),
            "server_bootstrap_token": "bootstrap-token-that-is-long-and-random",
            "trusted_hosts": "family.example",
            "trusted_proxy_ips": "127.0.0.1,::1",
            "release_scheduler_enabled": False,
        }
    )


def _bootstrap(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/setup/bootstrap",
        json={
            "setup_token": "bootstrap-token-that-is-long-and-random",
            "username": "admin",
            "display_name": "Server Admin",
            "password": "correct horse battery",
        },
    )
    assert response.status_code == 201
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


def _test_client_sender(client: TestClient):
    def send(method: str, url: str, *, timeout: float, **kwargs):
        del timeout
        parsed = urlsplit(url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return client.request(method, path, **kwargs)

    return send


def test_remote_discovery_distinguishes_local_pmt_and_unavailable_server(tmp_path):
    store = RemoteProfileStore(tmp_path / "remote" / "client.sqlite3")

    local_only = RemoteDeviceClient(
        store,
        vault=MemoryCredentialVault(),
        send=lambda *_args, **_kwargs: httpx.Response(
            200,
            json={
                "product": "personal-media-tracker",
                "api_version": "1",
                "instance_id": "local-installation",
                "mode": "local",
                "library_authority": "embedded_local",
            },
        ),
    )
    with pytest.raises(RemoteClientError, match="local-only PMT library"):
        local_only.discover("https://local.example")

    wrong_host = RemoteDeviceClient(
        store,
        vault=MemoryCredentialVault(),
        send=lambda *_args, **_kwargs: httpx.Response(
            400,
            json={"error": {"code": "invalid_host"}},
        ),
    )
    with pytest.raises(RemoteClientError, match="Tailscale forwarding"):
        wrong_host.discover("https://local.example")

    unavailable = RemoteDeviceClient(
        store,
        vault=MemoryCredentialVault(),
        send=lambda *_args, **_kwargs: httpx.Response(502, text="Bad Gateway"),
    )
    with pytest.raises(RemoteClientError, match="local port 8000"):
        unavailable.discover("https://server.example")


def test_remote_device_reconnect_outbox_refresh_and_conflict(settings, app, tmp_path):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as server_client:
        _bootstrap(server_client)
        vault = MemoryCredentialVault()
        store = RemoteProfileStore(tmp_path / "remote" / "client.sqlite3")
        remote = RemoteDeviceClient(
            store,
            vault=vault,
            send=_test_client_sender(server_client),
        )
        profile = remote.connect(
            value="https://family.example",
            username="admin",
            password="correct horse battery",
            label="Home",
            device_label="Test Mac",
        )
        token = vault.get(profile.id, "access_token")
        bearer = {"Authorization": f"Bearer {token}"}
        created = server_client.post(
            "/api/entries/manual",
            headers=bearer,
            json={
                "canonical_title": "Offline-safe title",
                "media_type": "movie",
                "notes": "Server note",
            },
        ).json()["entry"]

        initial = remote.sync(profile.id)
        assert initial["cached_entries"] == 1
        assert store.cached(profile.id, "watch_entry")[0]["notes"] == "Server note"

        request_id = store.enqueue_entry_patch(
            profile.id,
            created["id"],
            created["version"],
            {"notes": "Queued safely"},
        )
        original_sender = remote.send
        remote.send = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            httpx.ConnectError("offline")
        )
        try:
            remote.sync(profile.id)
        except RemoteClientError:
            pass
        else:  # pragma: no cover - protects the offline contract
            raise AssertionError("An unreachable server must not acknowledge queued work")
        assert store.outbox(profile.id)[0]["request_id"] == request_id
        assert store.outbox(profile.id)[0]["state"] == "pending"

        remote.send = original_sender
        synced = remote.sync(profile.id)
        assert synced["applied"] == 1
        assert store.outbox(profile.id)[0]["state"] == "acknowledged"
        cached = store.cached(profile.id, "watch_entry")[0]
        assert cached["notes"] == "Queued safely"

        stale_request = store.enqueue_entry_patch(
            profile.id,
            created["id"],
            created["version"],
            {"notes": "Stale edit"},
        )
        conflict = remote.sync(profile.id)
        assert conflict["conflicts"] == 1
        replacement = store.rebase(profile.id, stale_request)
        assert replacement != stale_request
        assert remote.sync(profile.id)["applied"] == 1

        # Simulate an expired access token while the refresh token remains valid.
        # The next sync must rotate both credentials and continue normally.
        old_refresh = vault.get(profile.id, "refresh_token")
        vault.set(profile.id, "access_token", "expired-access-token")
        assert remote.sync(profile.id)["online"] is True
        assert vault.get(profile.id, "access_token") != "expired-access-token"
        assert vault.get(profile.id, "refresh_token") != old_refresh

        paused = store.set_enabled(profile.id, False)
        assert paused.enabled is False
        assert store.enabled_profiles() == []
        assert vault.get(profile.id, "refresh_token") is not None
        resumed = store.set_enabled(profile.id, True)
        assert resumed.enabled is True
        assert [item.id for item in store.enabled_profiles()] == [profile.id]

        handoff_profile, handoff_token = remote.browser_handoff(profile.id)
        assert handoff_profile.id == profile.id
        assert len(handoff_token) >= 32
        installed_window = TestClient(server, base_url="https://family.example")
        try:
            adopted = installed_window.post(
                "/api/v1/auth/browser/adopt",
                json={"handoff_token": handoff_token},
            )
            assert adopted.status_code == 200
            assert installed_window.get("/api/v1/me").json()["username"] == "admin"
            signed_out = installed_window.post(
                "/api/auth/logout",
                headers={
                    "Origin": "https://family.example",
                    "X-CSRF-Token": installed_window.cookies.get("pmt_csrf"),
                },
            )
            assert signed_out.status_code == 204
        finally:
            installed_window.close()
        replay = server_client.post(
            "/api/v1/auth/browser/adopt",
            json={"handoff_token": handoff_token},
        )
        assert replay.status_code == 401
        with pytest.raises(RemoteClientError, match="session expired"):
            remote.browser_handoff(profile.id)


def test_remote_device_enrollment_redeems_invitation_and_saves_session(settings, app, tmp_path):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as server_client:
        owner_headers = _bootstrap(server_client)
        invitation = server_client.post(
            "/api/v1/admin/invitations",
            headers=owner_headers,
            json={"role": "member", "expires_hours": 24},
        ).json()
        vault = MemoryCredentialVault()
        store = RemoteProfileStore(tmp_path / "enrolled" / "client.sqlite3")
        remote = RemoteDeviceClient(
            store,
            vault=vault,
            send=_test_client_sender(server_client),
        )

        profile = remote.enroll(
            value="https://family.example",
            invitation_token=invitation["token"],
            username="alex",
            display_name="Alex",
            password="a secure member password",
            label="Family server",
            device_label="Test Mac",
        )

        assert profile.account_username == "alex"
        assert profile.enabled is True
        assert vault.get(profile.id, "refresh_token")
        assert [item.id for item in store.enabled_profiles()] == [profile.id]
        with pytest.raises(RemoteClientError, match="invalid or has expired"):
            remote.enroll(
                value="https://family.example",
                invitation_token=invitation["token"],
                username="alex-two",
                display_name="Alex Two",
                password="another secure member password",
                label="Family server",
                device_label="Test Mac",
            )


def test_shared_list_roles_hide_private_library_state(settings, app):
    server = create_app(
        _server_settings(settings),
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server, base_url="https://family.example") as owner:
        owner_headers = _bootstrap(owner)
        invitation = owner.post(
            "/api/v1/admin/invitations",
            headers=owner_headers,
            json={"role": "member", "expires_hours": 24},
        ).json()
        redeemed = owner.post(
            "/api/v1/auth/invitations/redeem",
            json={
                "token": invitation["token"],
                "username": "family-member",
                "display_name": "Family Member",
                "password": "another secure password",
            },
        ).json()
        member_id = redeemed["account"]["id"]
        entry = owner.post(
            "/api/entries/manual",
            headers=owner_headers,
            json={
                "canonical_title": "A private favorite",
                "media_type": "movie",
                "personal_rating": 9.5,
                "notes": "Private owner note",
                "user_tags": ["private-tag"],
            },
        ).json()["entry"]
        media_list = owner.post(
            "/api/lists",
            headers=owner_headers,
            json={"name": "Household picks"},
        ).json()
        owner.post(
            f"/api/lists/{media_list['id']}/entries/{entry['id']}",
            headers=owner_headers,
        )
        shared = owner.post(
            f"/api/v1/lists/{media_list['id']}/members",
            headers=owner_headers,
            json={"username": "family-member", "role": "viewer"},
        )
        assert shared.status_code == 200

        member = TestClient(server, base_url="https://family.example")
        try:
            login = member.post(
                "/api/auth/login",
                headers={"Origin": "https://family.example"},
                json={
                    "username": "family-member",
                    "password": "another secure password",
                },
            )
            assert login.status_code == 200
            member_headers = {
                "Origin": "https://family.example",
                "X-CSRF-Token": member.cookies.get("pmt_csrf"),
            }
            detail = member.get(f"/api/v1/lists/{media_list['id']}").json()
            assert detail["current_user_role"] == "viewer"
            assert detail["items"][0]["tracked_by_viewer"] is False
            assert detail["items"][0]["entry"] is None
            assert "Private owner note" not in str(detail)
            assert "private-tag" not in str(detail)
            catalog_id = detail["items"][0]["catalog_item"]["id"]
            denied = member.delete(
                f"/api/v1/lists/{media_list['id']}/items/{catalog_id}",
                headers=member_headers,
            )
            assert denied.status_code == 409

            promoted = owner.patch(
                f"/api/v1/lists/{media_list['id']}/members/{member_id}",
                headers=owner_headers,
                json={"role": "editor"},
            )
            assert promoted.status_code == 200
            added = member.post(
                f"/api/v1/catalog/{catalog_id}/library",
                headers=member_headers,
            )
            assert added.status_code == 201
            member_entry = added.json()["entry"]
            assert member_entry["notes"] is None
            assert member_entry["personal_rating"] is None
            assert member_entry["user_tags"] == []
            assert (
                member.delete(
                    f"/api/v1/lists/{media_list['id']}/items/{catalog_id}",
                    headers=member_headers,
                ).status_code
                == 200
            )
            inbox = owner.get("/api/v1/notifications").json()
            assert inbox["unread"] >= 1
            assert all("Private owner note" not in str(item) for item in inbox["items"])
        finally:
            member.close()


def test_durable_jobs_coalesce_lease_retry_pause_and_resume(client, app):
    now = [datetime(2026, 8, 26, 12, 0, tzinfo=UTC)]
    first = DurableJobService(
        app.state.session_factory,
        worker_id="worker-a",
        lease_seconds=30,
        now_factory=lambda: now[0],
    )
    second = DurableJobService(
        app.state.session_factory,
        worker_id="worker-b",
        lease_seconds=30,
        now_factory=lambda: now[0],
    )
    with app.state.session_factory() as session:
        user_id = session.scalar(select(UserAccount.id))

    original = first.enqueue(
        "test_job",
        idempotency_key="test:durable:one",
        user_id=user_id,
        payload={"revision": 1},
        max_attempts=2,
    )
    duplicate = first.enqueue(
        "test_job",
        idempotency_key="test:durable:one",
        user_id=user_id,
        payload={"revision": 2},
        priority=5,
        max_attempts=2,
    )
    assert duplicate.id == original.id
    assert duplicate.payload == {"revision": 2}
    assert duplicate.priority == 5

    claimed = first.claim(kinds={"test_job"})
    assert claimed is not None
    assert second.claim(kinds={"test_job"}) is None
    first.fail(
        claimed.id,
        error_code="temporary",
        safe_message="Provider temporarily unavailable",
        retry_after_seconds=1,
    )
    assert second.claim(kinds={"test_job"}) is None
    now[0] += timedelta(seconds=2)
    retry = second.claim(kinds={"test_job"})
    assert retry is not None
    second.fail(
        retry.id,
        error_code="temporary",
        safe_message="Provider temporarily unavailable",
    )
    with app.state.session_factory() as session:
        paused = session.get(ScheduledJob, retry.id)
        assert paused.state == "paused"
        assert paused.lease_owner is None
        assert paused.last_error_message == "Provider temporarily unavailable"
    assert first.resume(retry.id) is True
    resumed = first.claim(kinds={"test_job"})
    assert resumed is not None
    first.complete(resumed.id)
    with app.state.session_factory() as session:
        assert session.get(ScheduledJob, resumed.id).state == "completed"
