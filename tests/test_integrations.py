from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import FakeMetadata, manual_payload
from fastapi.testclient import TestClient
from sqlalchemy import select

from watchtracker.app import create_app
from watchtracker.integrations import (
    IntegrationEventInput,
    IntegrationPage,
    IntegrationProviderError,
    ProviderDefinition,
    ProviderRegistry,
)
from watchtracker.models import (
    AuditEvent,
    ExternalIdentity,
    IntegrationConflict,
    IntegrationCursor,
    IntegrationEvent,
    IntegrationOAuthGrant,
    ScheduledJob,
    ViewingEvent,
    WatchEntry,
)
from watchtracker.services.integration_auth import IntegrationAuthorizationService
from watchtracker.services.secrets import SecretStore

FAKE_DEFINITION = ProviderDefinition(
    slug="fixture",
    name="Fixture Provider",
    summary="Deterministic offline integration fixture.",
    capabilities=("test_connection", "pull_history"),
    requirements=("Synthetic data only",),
    secret_fields=("access_token",),
    implementation_state="beta",
)


class FakeAdapter:
    definition = FAKE_DEFINITION

    def __init__(self):
        self.calls = 0
        self.delay = 0.0
        self.error: IntegrationProviderError | None = None
        self.events: tuple[IntegrationEventInput, ...] = ()

    async def run(self, **kwargs):
        self.calls += 1
        assert set(kwargs["credentials"]) <= {"access_token"}
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return IntegrationPage(
            created=len(self.events),
            events=self.events,
            next_cursor={"page": kwargs["cursor"].get("page", 0) + 1},
            provider_version="fixture-v1",
            message="Synthetic preview complete.",
        )


@pytest.fixture
def integration_runtime(settings):
    adapter = FakeAdapter()
    registry = ProviderRegistry()
    registry.register_adapter(adapter)
    secrets = SecretStore(settings, keyring_enabled=False)
    app = create_app(
        settings,
        metadata_service=FakeMetadata(),
        secret_store=secrets,
        integration_registry=registry,
    )
    with TestClient(app) as client:
        yield client, adapter, secrets


def _create_connection(client: TestClient, token: str = "fixture-private-token") -> dict:
    response = client.post(
        "/api/integrations/connections",
        json={
            "provider_slug": "fixture",
            "label": "Private fixture",
            "capabilities": {"pull_history": "pull"},
            "credentials": {"access_token": token},
            "credential_storage": "local_secret_file",
        },
    )
    assert response.status_code == 201
    assert token not in response.text
    return response.json()


def test_provider_authorization_urls_match_supported_oauth_flows(client):
    trakt = client.post(
        "/api/v1/integrations/connections",
        json={
            "provider_slug": "trakt",
            "label": "Fixture Trakt",
            "configuration": {"client_id": "trakt-client"},
            "credentials": {
                "client_id": "trakt-client",
                "client_secret": "trakt-secret",
            },
            "capabilities": {"pull_history": "pull"},
        },
    )
    assert trakt.status_code == 201
    trakt_start = client.post(
        f"/api/v1/integrations/connections/{trakt.json()['id']}/oauth/start", json={}
    )
    assert trakt_start.status_code == 200
    trakt_query = parse_qs(urlsplit(trakt_start.json()["authorization_url"]).query)
    assert trakt_query["state"]
    assert "code_challenge" not in trakt_query
    assert trakt_query["redirect_uri"] == [trakt_start.json()["callback_url"]]

    mal = client.post(
        "/api/v1/integrations/connections",
        json={
            "provider_slug": "myanimelist",
            "label": "Fixture MAL",
            "configuration": {"client_id": "mal-client"},
            "credentials": {"client_id": "mal-client"},
            "capabilities": {"pull_status_progress": "pull"},
        },
    )
    assert mal.status_code == 201
    mal_start = client.post(
        f"/api/v1/integrations/connections/{mal.json()['id']}/oauth/start", json={}
    )
    assert mal_start.status_code == 200
    mal_query = parse_qs(urlsplit(mal_start.json()["authorization_url"]).query)
    assert mal_query["code_challenge_method"] == ["plain"]
    assert len(mal_query["code_challenge"][0]) >= 43


@pytest.mark.asyncio
async def test_oauth_callback_accepts_sqlite_expiry_and_saves_rotatable_tokens(client):
    connection = client.post(
        "/api/v1/integrations/connections",
        json={
            "provider_slug": "trakt",
            "label": "OAuth callback fixture",
            "configuration": {"client_id": "oauth-client"},
            "credentials": {
                "client_id": "oauth-client",
                "client_secret": "oauth-secret",
            },
            "credential_storage": "local_secret_file",
            "capabilities": {"pull_history": "pull"},
        },
    ).json()
    started = client.post(
        f"/api/v1/integrations/connections/{connection['id']}/oauth/start", json={}
    ).json()
    state_value = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]

    def token_exchange(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://auth.trakt.tv/oauth/token"
        assert json.loads(request.content)["redirect_uri"] == started["callback_url"]
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 604800,
                "token_type": "Bearer",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_exchange)) as http:
        with client.app.state.session_factory() as session:
            service = IntegrationAuthorizationService(
                session,
                client.app.state.integrations,
                client.app.state.secrets,
                client=http,
            )
            completed = await service.callback("trakt", state=state_value, code="fixture-code")
            assert completed["connected"] is True
            grant = session.scalar(
                select(IntegrationOAuthGrant).where(
                    IntegrationOAuthGrant.connection_id == connection["id"]
                )
            )
            assert grant is not None and grant.expires_at is not None
    namespace = f"integration.{connection['id']}"
    assert (
        client.app.state.secrets.get_named(namespace, "refresh_token", refresh=True)[0]
        == "new-refresh"
    )


def test_enabling_scheduled_connection_queues_each_pull_capability(client):
    connection = client.post(
        "/api/v1/integrations/connections",
        json={
            "provider_slug": "trakt",
            "label": "Scheduled Trakt",
            "configuration": {"client_id": "scheduled-client"},
            "credentials": {"client_id": "scheduled-client"},
            "capabilities": {
                "pull_history": "pull",
                "pull_ratings": "pull",
                "pull_planned": "pull",
            },
            "schedule": {"interval_minutes": 360},
        },
    ).json()
    enabled = client.patch(
        f"/api/integrations/connections/{connection['id']}", json={"enabled": True}
    )
    assert enabled.status_code == 200
    with client.app.state.session_factory() as session:
        jobs = list(
            session.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.kind == "integration_sync",
                    ScheduledJob.scope_id == connection["id"],
                )
            )
        )
    assert {job.payload["capability"] for job in jobs} == {
        "pull_history",
        "pull_ratings",
        "pull_planned",
    }
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": False})
    with client.app.state.session_factory() as session:
        states = set(
            session.scalars(
                select(ScheduledJob.state).where(
                    ScheduledJob.kind == "integration_sync",
                    ScheduledJob.scope_id == connection["id"],
                )
            )
        )
    assert states == {"cancelled"}


def test_registry_catalog_and_connection_secrets_are_redacted(integration_runtime, settings):
    client, _adapter, secrets = integration_runtime
    catalog = client.get("/api/integrations/catalog").json()["providers"]
    assert catalog == [
        {
            "slug": "fixture",
            "name": "Fixture Provider",
            "summary": "Deterministic offline integration fixture.",
            "capabilities": ["test_connection", "pull_history"],
            "requirements": ["Synthetic data only"],
            "limitations": [],
            "secret_fields": ["access_token"],
            "configuration_fields": [],
            "authorization_type": "manual",
            "oauth_authorize_url": None,
            "oauth_token_url": None,
            "oauth_scopes": [],
            "terms_url": None,
            "terms_version": None,
            "implementation_state": "beta",
            "availability_reason": None,
            "available": True,
            "configured": False,
        }
    ]
    connection = _create_connection(client)
    assert connection["has_credentials"] is True
    namespace = f"integration.{connection['id']}"
    assert secrets.get_named(namespace, "access_token") == (
        "fixture-private-token",
        "local_secret_file",
    )
    response = client.get("/api/integrations/connections")
    assert "fixture-private-token" not in response.text
    assert "fixture-private-token" in settings.fallback_secret_path.read_text()
    backup = client.post("/api/backups", json={}).json()
    with zipfile.ZipFile(settings.resolved_backups_dir / backup["filename"]) as archive:
        assert b"fixture-private-token" not in b"".join(
            archive.read(name) for name in archive.namelist()
        )
    deleted = client.delete(f"/api/integrations/connections/{connection['id']}")
    assert deleted.status_code == 204
    assert secrets.get_named(namespace, "access_token", refresh=True) == (None, "none")
    assert "fixture-private-token" not in settings.fallback_secret_path.read_text()


def test_generic_secret_namespaces_and_environment_priority(settings, monkeypatch):
    secrets = SecretStore(settings, keyring_enabled=False)
    assert secrets.save_named("integration.demo", "access_token", "local-value") == (
        "local_secret_file"
    )
    assert secrets.get_named("integration.demo", "access_token") == (
        "local-value",
        "local_secret_file",
    )
    monkeypatch.setenv("WATCHTRACKER_SECRET_INTEGRATION_DEMO_ACCESS_TOKEN", "server-value")
    assert secrets.get_named("integration.demo", "access_token") == (
        "server-value",
        "environment",
    )
    assert secrets.clear_named("integration.demo", "access_token") == "environment"


def test_named_secret_can_move_from_keychain_to_local_file(settings):
    class NamedKeyring:
        def __init__(self):
            self.values = {}

        def get_password(self, service, account):
            return self.values.get((service, account))

        def set_password(self, service, account, value):
            self.values[(service, account)] = value

        def delete_password(self, service, account):
            self.values.pop((service, account), None)

    keyring = NamedKeyring()
    secrets = SecretStore(settings, keyring_backend=keyring, keyring_enabled=True)
    assert secrets.save_named("integration.demo", "access_token", "vault-value") == "keychain"
    assert (
        secrets.save_named(
            "integration.demo",
            "access_token",
            "local-value",
            storage="local_secret_file",
        )
        == "local_secret_file"
    )
    assert secrets.get_named("integration.demo", "access_token", refresh=True) == (
        "local-value",
        "local_secret_file",
    )


def test_oauth_credential_set_replaces_access_and_refresh_tokens_together(settings):
    secrets = SecretStore(settings, keyring_enabled=False)
    assert (
        secrets.save_many_named(
            "integration.oauth-demo",
            {"access_token": "access-one", "refresh_token": "refresh-one"},
        )
        == "local_secret_file"
    )
    secrets.save_many_named(
        "integration.oauth-demo",
        {"access_token": "access-two", "refresh_token": "refresh-two"},
    )
    assert secrets.get_named("integration.oauth-demo", "access_token", refresh=True) == (
        "access-two",
        "local_secret_file",
    )
    assert secrets.get_named("integration.oauth-demo", "refresh_token", refresh=True) == (
        "refresh-two",
        "local_secret_file",
    )


def test_identity_ledger_tracks_new_catalog_and_replay_is_idempotent(integration_runtime):
    client, adapter, _secrets = integration_runtime
    entry = client.post(
        "/api/entries/manual",
        json={
            **manual_payload("Identity fixture"),
            "provider_source": "tmdb_movie",
            "provider_id": "9001",
            "tmdb_movie_id": "9001",
        },
    ).json()["entry"]
    connection = _create_connection(client)
    adapter.events = (
        IntegrationEventInput(
            provider_event_id="history-1",
            event_kind="history.completed",
            safe_summary="Matched one synthetic completion.",
            payload_hash=hashlib.sha256(b"fixture-event").hexdigest(),
            identities={"tmdb_movie": "9001"},
        ),
    )
    enabled = client.patch(
        f"/api/integrations/connections/{connection['id']}", json={"enabled": True}
    )
    assert enabled.status_code == 200
    first = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    second = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    assert first["state"] == second["state"] == "succeeded"
    assert second["counts"]["skipped"] == 1
    with client.app.state.session_factory() as session:
        identities = session.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.catalog_item_id == entry["catalog_item"]["id"]
            )
        ).all()
        assert {(item.namespace, item.external_id) for item in identities} == {
            ("tmdb_movie", "9001")
        }
        assert len(session.scalars(select(IntegrationEvent)).all()) == 1
        cursor = session.scalar(select(IntegrationCursor))
        assert cursor and cursor.checkpoint == {"page": 2}
    adapter.error = IntegrationProviderError(
        "temporary", "Synthetic page failed before commit.", retryable=True
    )
    failed = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    assert failed["state"] == "failed"
    with client.app.state.session_factory() as session:
        assert session.scalar(select(IntegrationCursor)).checkpoint == {"page": 2}


def test_coordinator_applies_only_normalized_safe_changes(integration_runtime):
    client, adapter, _secrets = integration_runtime
    entry = client.post(
        "/api/entries/manual",
        json={
            **manual_payload("Safe integration changes", status="plan_to_watch", view_count=0),
            "provider_source": "tmdb_movie",
            "provider_id": "safe-9002",
            "tmdb_movie_id": "safe-9002",
        },
    ).json()["entry"]
    connection = _create_connection(client)
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": True})
    adapter.events = (
        IntegrationEventInput(
            provider_event_id="safe-status-rating",
            event_kind="status.changed",
            safe_summary="Synthetic status and rating update.",
            payload_hash="safe-status-rating",
            identities={"tmdb_movie": "safe-9002"},
            changes={"personal_rating": 8.5, "status": "watching"},
            source_values={
                "rating": 17,
                "status": "current",
                "raw_payload": "must-not-be-stored",
            },
        ),
    )
    first = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    assert first["counts"] == {
        "created": 0,
        "updated": 1,
        "skipped": 0,
        "conflicts": 0,
        "errors": 0,
    }

    adapter.events = (
        IntegrationEventInput(
            provider_event_id="safe-completion",
            event_kind="history.completed",
            safe_summary="Synthetic completion update.",
            payload_hash="safe-completion",
            identities={"tmdb_movie": "safe-9002"},
            changes={"completed": True, "viewed_on": "2026-08-22"},
        ),
    )
    second = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    replay = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    assert second["counts"]["updated"] == 1
    assert replay["counts"]["skipped"] == 1
    with client.app.state.session_factory() as session:
        stored = session.get(WatchEntry, entry["id"])
        assert stored is not None
        assert stored.personal_rating == 8.5
        assert stored.status == "watched"
        assert stored.view_count == 1
        assert stored.watched_date.isoformat() == "2026-08-22"
        assert len(session.scalars(select(ViewingEvent)).all()) == 1
        audits = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "integration_sync")
        ).all()
        assert len(audits) == 2
        first_event = session.scalar(
            select(IntegrationEvent)
            .where(IntegrationEvent.event_kind == "status.changed")
            .order_by(IntegrationEvent.created_at)
        )
        assert first_event.source_values == {"rating": 17, "status": "current"}


def test_completed_event_with_repeat_claim_counts_the_completion_once(integration_runtime):
    client, adapter, _secrets = integration_runtime
    entry = client.post(
        "/api/entries/manual",
        json={
            **manual_payload(
                "Completion and repeat claim", status="plan_to_watch", view_count=0
            ),
            "provider_source": "tmdb_movie",
            "provider_id": "claim-9002",
            "tmdb_movie_id": "claim-9002",
        },
    ).json()["entry"]
    connection = _create_connection(client)
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": True})
    adapter.events = (
        IntegrationEventInput(
            provider_event_id="completion-with-repeat-zero",
            event_kind="history.completed",
            safe_summary="Synthetic completion with an aggregate repeat claim.",
            payload_hash="completion-with-repeat-zero",
            identities={"tmdb_movie": "claim-9002"},
            changes={
                "completed": True,
                "status": "watched",
                "repeat_count": 0,
                "viewed_on": "2026-08-22",
            },
        ),
    )

    result = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()

    assert result["counts"]["updated"] == 1
    with client.app.state.session_factory() as session:
        stored = session.get(WatchEntry, entry["id"])
        assert stored is not None
        assert stored.view_count == 1
        assert len(session.scalars(select(ViewingEvent)).all()) == 1


def test_local_rating_and_private_fields_are_never_overwritten(integration_runtime):
    client, adapter, _secrets = integration_runtime
    entry = client.post(
        "/api/entries/manual",
        json={
            **manual_payload(
                "Protected integration fields", personal_rating=8.0, notes="Owner note"
            ),
            "provider_source": "tmdb_movie",
            "provider_id": "protected-9003",
            "tmdb_movie_id": "protected-9003",
        },
    ).json()["entry"]
    connection = _create_connection(client)
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": True})
    adapter.events = (
        IntegrationEventInput(
            provider_event_id="rating-conflict",
            event_kind="rating.changed",
            safe_summary="Synthetic divergent rating.",
            payload_hash="rating-conflict",
            identities={"tmdb_movie": "protected-9003"},
            changes={"personal_rating": 9.0},
        ),
        IntegrationEventInput(
            provider_event_id="private-field-attempt",
            event_kind="entry.changed",
            safe_summary="Synthetic private field attempt.",
            payload_hash="private-field-attempt",
            identities={"tmdb_movie": "protected-9003"},
            changes={"notes": "Remote note", "technical_rating": 10},
        ),
    )
    result = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    assert result["counts"]["conflicts"] == 2
    with client.app.state.session_factory() as session:
        stored = session.get(WatchEntry, entry["id"])
        assert stored is not None
        assert stored.personal_rating == 8.0
        assert stored.notes == "Owner note"
        conflicts = session.scalars(select(IntegrationConflict)).all()
        assert {conflict.conflict_kind for conflict in conflicts} == {
            "personal_rating_diverged",
            "unsupported_remote_fields",
        }
        by_kind = {conflict.conflict_kind: conflict for conflict in conflicts}
        assert by_kind["unsupported_remote_fields"].remote_value == {
            "field_names": ["notes", "technical_rating"]
        }


def test_strong_unmatched_identity_creates_missing_entry(integration_runtime):
    client, adapter, _secrets = integration_runtime
    connection = _create_connection(client)
    adapter.events = (
        IntegrationEventInput(
            event_kind="rating.changed",
            safe_summary="Unmatched synthetic title.",
            payload_hash="unmatched",
            identities={"trakt": "not-linked"},
            title="Not in PMT",
            year=2026,
            media_type="movie",
        ),
    )
    result = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": True},
    ).json()
    assert result["state"] == "previewed"
    assert result["counts"]["created"] == 1
    events = client.get(f"/api/integrations/connections/{connection['id']}/events").json()[
        "events"
    ]
    assert events[0]["outcome"] == "would_create"
    assert "not-linked" not in events[0]["safe_summary"]
    replay = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": True},
    ).json()
    assert replay["counts"]["skipped"] == 1
    with client.app.state.session_factory() as session:
        assert len(session.scalars(select(IntegrationConflict)).all()) == 0
        assert session.scalar(select(IntegrationCursor)) is None
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": True})
    applied = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    ).json()
    assert applied["counts"]["created"] == 1
    assert applied["counts"]["updated"] == 0
    with client.app.state.session_factory() as session:
        assert session.scalar(select(IntegrationCursor)) is not None
        assert (
            session.scalar(
                select(WatchEntry)
                .join(
                    ExternalIdentity,
                    WatchEntry.catalog_item_id == ExternalIdentity.catalog_item_id,
                )
                .where(
                    ExternalIdentity.namespace == "trakt",
                    ExternalIdentity.external_id == "not-linked",
                )
            )
            is not None
        )


def test_soft_deleted_identity_remains_a_tombstone(integration_runtime):
    client, adapter, _secrets = integration_runtime
    entry = client.post(
        "/api/entries/manual",
        json={
            **manual_payload("Deleted integration identity"),
            "provider_source": "tmdb_movie",
            "provider_id": "deleted-9004",
            "tmdb_movie_id": "deleted-9004",
        },
    ).json()["entry"]
    assert client.delete(f"/api/entries/{entry['id']}").status_code == 204
    connection = _create_connection(client)
    adapter.events = (
        IntegrationEventInput(
            provider_event_id="deleted-completion",
            event_kind="history.completed",
            safe_summary="Synthetic completion for a deleted title.",
            payload_hash="deleted-completion",
            identities={"tmdb_movie": "deleted-9004"},
            changes={"completed": True, "viewed_on": "2026-08-22"},
        ),
    )
    result = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": True},
    ).json()
    assert result["counts"]["skipped"] == 1
    events = client.get(f"/api/integrations/connections/{connection['id']}/events").json()[
        "events"
    ]
    assert events[0]["outcome"] == "tombstone_skipped"
    with client.app.state.session_factory() as session:
        stored = session.get(WatchEntry, entry["id"])
        assert stored is not None and stored.deleted_at is not None
        assert len(session.scalars(select(IntegrationConflict)).all()) == 0


def test_repeated_failures_pause_connection_and_redact_token(integration_runtime):
    client, adapter, _secrets = integration_runtime
    secret = "do-not-log-this-token"
    connection = _create_connection(client, secret)
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": True})
    adapter.error = IntegrationProviderError(
        "rate_limited",
        f"Authorization Bearer {secret} was rate limited.",
        retryable=True,
        retry_after_seconds=30,
    )
    for _ in range(5):
        result = client.post(
            f"/api/integrations/connections/{connection['id']}/runs",
            json={"capability": "pull_history", "direction": "pull", "dry_run": False},
        ).json()
    assert result["state"] == "failed"
    assert secret not in str(result)
    stored = client.get("/api/integrations/connections").json()["connections"][0]
    assert stored["state"] == "paused"
    assert stored["failure_count"] == 5
    blocked = client.post(
        f"/api/integrations/connections/{connection['id']}/runs",
        json={"capability": "pull_history", "direction": "pull", "dry_run": False},
    )
    assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_runs_coalesce(integration_runtime):
    client, adapter, _secrets = integration_runtime
    connection = _create_connection(client)
    client.patch(f"/api/integrations/connections/{connection['id']}", json={"enabled": True})
    adapter.delay = 0.08
    coordinator = client.app.state.integration_coordinator
    first, second = await asyncio.gather(
        coordinator.run(connection["id"], capability="pull_history", direction="pull"),
        coordinator.run(connection["id"], capability="pull_history", direction="pull"),
    )
    assert adapter.calls == 1
    assert {first.get("coalesced", False), second.get("coalesced", False)} == {False, True}
