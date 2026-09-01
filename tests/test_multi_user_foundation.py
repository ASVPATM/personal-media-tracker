from __future__ import annotations

import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from watchtracker.app import create_app
from watchtracker.authorization import (
    LOCAL_USER_ID,
    Principal,
    bind_principal,
    local_principal,
)
from watchtracker.config import Settings
from watchtracker.models import (
    CatalogItem,
    EpisodeRecord,
    EpisodeViewing,
    IntegrationConnection,
    MediaList,
    OwnerAccount,
    ReleaseEvent,
    SeasonRecord,
    SeriesTrackingSubscription,
    UserAccount,
    UserPreference,
    WatchEntry,
)
from watchtracker.schemas import CatalogData, EntryOptions
from watchtracker.services.entries import EntryNotFound, EntryService
from watchtracker.services.lists import MediaListService
from watchtracker.services.releases import ReleaseTrackingService


def _principal(user_id: str, *, role: str = "member") -> Principal:
    return Principal(
        user_id=user_id,
        role=role,  # type: ignore[arg-type]
        authentication_method="password",
    )


def _add_user(session, username: str) -> str:
    user_id = str(uuid4())
    session.add(
        UserAccount(
            id=user_id,
            username=username,
            normalized_username=username.casefold(),
            display_name=username.title(),
            role="member",
            state="active",
            locale="en",
            timezone="UTC",
        )
    )
    session.commit()
    return user_id


def _server_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "access_mode": "server",
            "host": "127.0.0.1",
            "public_base_url": "https://pmt.example",
            "application_secret": (
                "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_" * 2
            ),
            "trusted_hosts": "pmt.example",
            "trusted_proxy_ips": "127.0.0.1,::1",
            "release_scheduler_enabled": False,
        }
    )


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    origin = {"Origin": "https://pmt.example"}
    response = client.post(
        "/api/auth/login",
        headers=origin,
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {**origin, "X-CSRF-Token": client.cookies["pmt_csrf"]}


def test_two_users_share_catalog_schedule_but_not_private_state(app):
    with TestClient(app):
        with app.state.session_factory() as session:
            second_user_id = _add_user(session, "second-user")

        first = _principal(LOCAL_USER_ID, role="admin")
        second = _principal(second_user_id)
        catalog_data = CatalogData(
            canonical_title="One Shared Series",
            media_type="tv",
            provider_source="tmdb_tv",
            provider_id="shared-100",
            tmdb_tv_id="shared-100",
            poster_url="https://images.invalid/shared.jpg",
        )

        with app.state.session_factory() as session:
            bind_principal(session, first)
            first_entry = (
                EntryService(session, today=date(2026, 8, 26), principal=first)
                .create_or_handle_duplicate(
                    catalog_data,
                    EntryOptions(
                        status="watching",
                        personal_rating=9.0,
                        notes="first private note",
                    ),
                    trusted_metadata=True,
                )
                .entry
            )

        with app.state.session_factory() as session:
            bind_principal(session, second)
            second_entry = (
                EntryService(session, today=date(2026, 8, 26), principal=second)
                .create_or_handle_duplicate(
                    catalog_data,
                    EntryOptions(
                        status="plan_to_watch",
                        personal_rating=6.5,
                        notes="second private note",
                    ),
                )
                .entry
            )
            EntryService(session, today=date(2026, 8, 26)).set_poster_override(
                second_entry.id, "https://images.invalid/second-choice.jpg"
            )
            MediaListService(session).create("Same allowed name")

        with app.state.session_factory() as session:
            bind_principal(session, first)
            MediaListService(session).create("Same allowed name")
            assert (
                EntryService(session, today=date(2026, 8, 26)).get(first_entry.id).notes
                == "first private note"
            )
            assert (
                EntryService(session, today=date(2026, 8, 26))
                .get(first_entry.id)
                .catalog_item.poster_override_url
                is None
            )
            with pytest.raises(EntryNotFound):
                EntryService(session, today=date(2026, 8, 26)).get(second_entry.id)

        assert first_entry.catalog_item.id == second_entry.catalog_item.id
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(CatalogItem.id))) == 1
            assert session.scalar(select(func.count(WatchEntry.id))) == 2
            assert session.scalar(select(func.count(MediaList.id))) == 2
            season = SeasonRecord(
                catalog_item_id=first_entry.catalog_item.id,
                provider_source="tmdb_tv",
                provider_series_id="shared-100",
                provider_season_id="shared-season-1",
                season_number=1,
                fetched_at=datetime.now(UTC),
            )
            episode = EpisodeRecord(
                season=season,
                provider_source="tmdb_tv",
                provider_episode_id="shared-episode-1",
                episode_number=1,
                title="One schedule row",
                air_date=date(2026, 8, 1),
                fetched_at=datetime.now(UTC),
            )
            session.add(season)
            session.commit()
            episode_id = episode.id

        with app.state.session_factory() as session:
            bind_principal(session, first)
            marked = ReleaseTrackingService(session, today=date(2026, 8, 26)).mark_episode(
                episode_id, watched_on=date(2026, 8, 2)
            )
            assert marked["progress"]["watched"] == 1

        with app.state.session_factory() as session:
            bind_principal(session, second)
            untouched = ReleaseTrackingService(session, today=date(2026, 8, 26)).detail(
                second_entry.id
            )
            assert untouched["progress"]["watched"] == 0
            ReleaseTrackingService(session, today=date(2026, 8, 26)).mark_episode(
                episode_id, watched_on=date(2026, 8, 3)
            )

        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(SeasonRecord.id))) == 1
            assert session.scalar(select(func.count(EpisodeRecord.id))) == 1
            assert session.scalar(select(func.count(EpisodeViewing.id))) == 2
            watched_by = set(session.scalars(select(EpisodeViewing.user_id)))
            assert watched_by == {LOCAL_USER_ID, second_user_id}
            with pytest.raises(RuntimeError, match="cannot choose between multiple users"):
                local_principal(session)


def test_shared_schedule_change_fans_out_private_events_once(app):
    now = datetime.now(UTC)
    with TestClient(app):
        with app.state.session_factory() as session:
            second_user_id = _add_user(session, "release-member")
            catalog = CatalogItem(
                canonical_title="Fanout series",
                normalized_title="fanout series",
                media_type="tv",
                provider_source="tmdb_tv",
                provider_id="fanout-1",
                tmdb_tv_id="fanout-1",
            )
            first_entry = WatchEntry(
                user_id=LOCAL_USER_ID,
                catalog_item=catalog,
                status="watching",
            )
            second_entry = WatchEntry(
                user_id=second_user_id,
                catalog_item=catalog,
                status="watching",
            )
            session.add_all((first_entry, second_entry))
            session.flush()
            session.add_all(
                (
                    SeriesTrackingSubscription(
                        entry_id=first_entry.id,
                        enabled=True,
                        notify_new_episode=True,
                        notify_new_season=True,
                        last_success_at=now,
                    ),
                    SeriesTrackingSubscription(
                        entry_id=second_entry.id,
                        enabled=True,
                        notify_new_episode=True,
                        notify_new_season=True,
                        last_success_at=now,
                    ),
                )
            )
            session.commit()
            first_entry_id = first_entry.id
            second_entry_id = second_entry.id

        payload = {
            "provider_source": "tmdb_tv",
            "provider_series_id": "fanout-1",
            "status": "Returning Series",
            "seasons": [
                {
                    "provider_season_id": "fanout-season-1",
                    "season_number": 1,
                    "title": "Season 1",
                    "air_date": "2026-09-01",
                    "episode_count": 1,
                    "episodes": [
                        {
                            "provider_episode_id": "fanout-episode-1",
                            "episode_number": 1,
                            "title": "A shared announcement",
                            "air_date": "2026-09-01",
                        }
                    ],
                }
            ],
        }
        app.state.release_sync._apply(first_entry_id, payload, user_id=LOCAL_USER_ID)
        # The second user's later fetch sees the same cache and does not duplicate events.
        app.state.release_sync._apply(second_entry_id, payload, user_id=second_user_id)

        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(SeasonRecord.id))) == 1
            assert session.scalar(select(func.count(EpisodeRecord.id))) == 1
            events = list(session.scalars(select(ReleaseEvent)))
            assert {event.user_id for event in events} == {LOCAL_USER_ID, second_user_id}
            assert {event.entry_id for event in events} == {
                first_entry_id,
                second_entry_id,
            }
            assert len(events) == 4


def test_two_user_server_api_and_exports_fail_closed(settings, app):
    admin_password = "correct horse battery"
    member_password = "member synthetic password"
    with TestClient(app) as local_client:
        assert (
            local_client.post(
                "/api/auth/bootstrap",
                headers={"Origin": "http://testserver"},
                json={"password": admin_password},
            ).status_code
            == 201
        )

    member_id = str(uuid4())
    member_hash = app.state.auth.passwords.hash(member_password)
    with app.state.session_factory() as session, session.begin():
        session.add(
            UserAccount(
                id=member_id,
                username="member",
                normalized_username="member",
                display_name="Synthetic Member",
                password_hash=member_hash,
                role="member",
                state="active",
                locale="en",
                timezone="UTC",
            )
        )
        session.add(UserPreference(user_id=member_id, preferences={}))
        # Order 5 replaces this compatibility bridge with general user sessions.
        session.add(
            OwnerAccount(
                id=member_id,
                username="member",
                password_hash=member_hash,
            )
        )

    server_settings = _server_settings(settings)
    admin_app = create_app(
        server_settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    member_app = create_app(
        server_settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    admin_client = TestClient(admin_app, base_url="https://pmt.example")
    member_client = TestClient(member_app, base_url="https://pmt.example")
    with admin_client, member_client:
        admin_headers = _login(admin_client, "owner", admin_password)
        member_headers = _login(member_client, "member", member_password)

        def add(client, headers, title, **extra):
            response = client.post(
                "/api/entries/manual",
                headers=headers,
                json={
                    "canonical_title": title,
                    "media_type": "movie",
                    "status": "watched",
                    "personal_rating": 8.0,
                    "notes": f"private note for {title}",
                    **extra,
                },
            )
            assert response.status_code == 201
            return response.json()["entry"]

        admin_entry = add(admin_client, admin_headers, "ADMIN-ONLY-SENTINEL")
        member_entry = add(member_client, member_headers, "MEMBER-ONLY-SENTINEL")
        admin_shared = add(
            admin_client,
            admin_headers,
            "Shared catalog sentinel",
            provider_source="tmdb_movie",
            provider_id="shared-api-1",
            tmdb_movie_id="shared-api-1",
        )
        member_shared = add(
            member_client,
            member_headers,
            "Shared catalog sentinel",
            provider_source="tmdb_movie",
            provider_id="shared-api-1",
            tmdb_movie_id="shared-api-1",
        )
        # Manual API identity claims are untrusted. A second tenant cannot use a
        # guessed provider ID to attach to the first tenant's private catalog row.
        assert admin_shared["catalog_item"]["id"] != member_shared["catalog_item"]["id"]
        assert member_shared["catalog_item"]["provider_source"] is None
        assert member_shared["catalog_item"]["provider_id"] is None

        assert admin_client.get(f"/api/entries/{member_entry['id']}").status_code == 404
        assert member_client.get(f"/api/entries/{admin_entry['id']}").status_code == 404
        assert (
            member_client.patch(
                f"/api/entries/{admin_entry['id']}",
                headers=member_headers,
                json={"notes": "attempted overwrite"},
            ).status_code
            == 404
        )
        assert (
            member_client.delete(
                f"/api/entries/{admin_entry['id']}", headers=member_headers
            ).status_code
            == 404
        )
        admin_viewing_id = admin_entry["viewing_events"][0]["id"]
        assert (
            member_client.delete(
                f"/api/entries/{admin_entry['id']}/viewings/{admin_viewing_id}",
                headers=member_headers,
            ).status_code
            == 404
        )
        assert member_client.get(f"/api/entries/{admin_entry['id']}/artwork").status_code == 404

        admin_list = admin_client.post(
            "/api/lists", headers=admin_headers, json={"name": "Private list"}
        ).json()
        assert (
            admin_client.post(
                f"/api/lists/{admin_list['id']}/entries/{admin_entry['id']}",
                headers=admin_headers,
            ).status_code
            == 200
        )
        assert member_client.get(f"/api/lists/{admin_list['id']}").status_code == 404
        assert (
            member_client.patch(
                f"/api/lists/{admin_list['id']}",
                headers=member_headers,
                json={"pinned_to_navigation": True},
            ).status_code
            == 404
        )

        assert (
            admin_client.put(
                "/api/settings/general", headers=admin_headers, json={"theme": "dark"}
            ).status_code
            == 200
        )
        assert admin_client.get("/api/settings/general").json()["theme"] == "dark"
        member_general = member_client.get("/api/settings/general").json()
        assert member_general["theme"] == "system"
        assert member_general["data_location"] == "Managed by PMT Server"
        assert member_general["database_size"] == 0
        assert member_general["last_backup_at"] is None
        assert member_client.get("/api/server/readiness").status_code == 403

        for client, headers in (
            (admin_client, admin_headers),
            (member_client, member_headers),
        ):
            assert (
                client.put(
                    "/api/settings/general",
                    headers=headers,
                    json={"advanced_ratings_enabled": True},
                ).status_code
                == 200
            )
        assessment = admin_client.post(
            "/api/ratings/assessments",
            headers=admin_headers,
            json={
                "entry_id": admin_entry["id"],
                "rubric_version": "guided-rubric-v3",
                "answers": {"impact": 4.5},
                "private_reflection": "ADMIN-ASSESSMENT-SENTINEL",
            },
        ).json()
        assert (
            member_client.get(f"/api/ratings/assessments/{assessment['id']}").status_code == 404
        )
        run = admin_client.post(
            "/api/ratings/refinement-runs",
            headers=admin_headers,
            json={"scope": "focused", "entry_id": admin_entry["id"]},
        ).json()
        assert member_client.get(f"/api/ratings/refinement-runs/{run['id']}").status_code == 404

        preview = admin_client.post(
            "/api/imports/preview",
            headers=admin_headers,
            data={"import_kind": "csv"},
            files={
                "file": (
                    "admin.csv",
                    b"title,media_type,status\nADMIN-IMPORT-SENTINEL,movie,watched\n",
                    "text/csv",
                )
            },
        )
        assert preview.status_code == 200
        assert (
            member_client.post(
                f"/api/imports/{preview.json()['preview_id']}/commit",
                headers=member_headers,
                json={"allow_invalid": False},
            ).status_code
            == 404
        )

        with admin_app.state.session_factory() as session, session.begin():
            connection = IntegrationConnection(
                user_id=LOCAL_USER_ID,
                provider_slug="synthetic",
                label="ADMIN-INTEGRATION-SENTINEL",
                enabled=False,
            )
            session.add(connection)
            release_event = ReleaseEvent(
                user_id=LOCAL_USER_ID,
                entry_id=admin_entry["id"],
                event_type="episode_announced",
                dedupe_key="admin-release-sentinel",
            )
            session.add(release_event)
            session.flush()
            connection_id = connection.id
            release_event_id = release_event.id
        assert (
            "ADMIN-INTEGRATION-SENTINEL"
            in admin_client.get("/api/integrations/connections").text
        )
        assert (
            "ADMIN-INTEGRATION-SENTINEL"
            not in member_client.get("/api/integrations/connections").text
        )
        assert (
            member_client.get(f"/api/integrations/connections/{connection_id}/runs").status_code
            == 404
        )
        assert (
            member_client.patch(
                f"/api/releases/notifications/{release_event_id}",
                headers=member_headers,
                json={"action": "read"},
            ).status_code
            == 404
        )
        assert member_client.get(f"/api/series/{admin_entry['id']}").status_code == 404

        feed = admin_client.post(
            "/api/exports/upcoming-releases/feed", headers=admin_headers, json={}
        ).json()
        assert (
            member_client.delete(
                "/api/exports/upcoming-releases/feed", headers=member_headers
            ).json()["revoked"]
            == 0
        )
        assert admin_client.get(feed["feed_url"]).status_code == 200

        for path in (
            "/api/entries",
            "/api/stats",
            "/api/insights",
            "/api/insights/titles",
            "/api/rankings",
            "/api/exports/preference-profile.json",
            "/api/exports/preference-profile.md",
            "/api/exports/advanced-ratings.json",
            "/api/exports/watch-log.csv",
        ):
            admin_response = admin_client.get(path)
            member_response = member_client.get(path)
            assert admin_response.status_code == member_response.status_code == 200, path
            assert b"MEMBER-ONLY-SENTINEL" not in admin_response.content, path
            assert b"ADMIN-ONLY-SENTINEL" not in member_response.content, path

        for client, own, foreign in (
            (admin_client, b"ADMIN-ONLY-SENTINEL", b"MEMBER-ONLY-SENTINEL"),
            (member_client, b"MEMBER-ONLY-SENTINEL", b"ADMIN-ONLY-SENTINEL"),
        ):
            response = client.get("/api/exports/obsidian-vault.zip")
            assert response.status_code == 200
            with zipfile.ZipFile(BytesIO(response.content)) as archive:
                contents = b"\n".join(archive.read(name) for name in archive.namelist())
            assert own in contents
            assert foreign not in contents

        # The legacy whole-database archive is never exposed as a personal server export.
        assert admin_client.get("/api/exports/portable-library.zip").status_code == 409
