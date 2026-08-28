from __future__ import annotations

from sqlalchemy import select

from watchtracker.models import NotificationOutbox
from watchtracker.notifications import NotificationEvent, NotificationService


def test_notification_settings_keep_destination_secret_out_of_api_and_database(client):
    destination = "https://notify.example.invalid/notify"
    created = client.post(
        "/api/v1/notification-endpoints",
        json={
            "label": "Household alerts",
            "adapter": "apprise_api",
            "destination": destination,
            "credential_storage": "local_secret_file",
        },
    )
    assert created.status_code == 201
    assert destination not in created.text
    endpoint = created.json()
    settings = client.get("/api/v1/notification-settings")
    assert settings.status_code == 200
    assert destination not in settings.text

    rules = client.put(
        "/api/v1/notification-settings",
        json={
            "rules": [
                {
                    "event_pattern": "integration.*",
                    "endpoint_id": endpoint["id"],
                    "external_enabled": True,
                    "timezone": "UTC",
                }
            ]
        },
    )
    assert rules.status_code == 200
    with client.app.state.session_factory() as session:
        user_id = session.info.get("user_id")
        if user_id is None:
            from watchtracker.authorization import current_user_id

            user_id = current_user_id(session)
        event = NotificationEvent(
            user_id=user_id,
            event_type="integration.paused",
            title="Trakt",
            safe_message="This integration paused after repeated failures.",
            source_kind="integration_connection",
            source_key="fixture:paused:5",
        )
        NotificationService.emit(session, event)
        NotificationService.route_existing(session, event)
        session.commit()
        rows = list(session.scalars(select(NotificationOutbox)))
        assert len(rows) == 1
        assert destination not in str(rows[0].__dict__)


def test_unified_inbox_supports_source_scoped_read_and_dismiss(client):
    with client.app.state.session_factory() as session:
        from watchtracker.authorization import current_user_id

        row = NotificationService.emit(
            session,
            NotificationEvent(
                user_id=current_user_id(session),
                event_type="collaboration.invited",
                title="Weekend list",
                safe_message="A list was shared with you.",
                source_kind="media_list",
                source_key="fixture-list",
            ),
        )
        session.commit()
        notification_id = row.id
    inbox = client.get("/api/v1/notifications").json()
    assert inbox["unread"] == 1
    assert inbox["items"][0]["source_kind"] == "inbox"
    updated = client.patch(
        f"/api/v1/notifications/inbox/{notification_id}", json={"action": "read"}
    )
    assert updated.status_code == 200
    assert updated.json()["unread"] == 0
    dismissed = client.patch(
        f"/api/v1/notifications/inbox/{notification_id}",
        json={"action": "dismiss"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["items"] == []


def test_managed_docker_apprise_endpoint_is_opt_in_and_never_disclosed(client):
    settings = client.get("/api/v1/notification-settings").json()
    assert settings["managed_apprise_api_available"] is False

    destination = "http://apprise:8000/notify/pmt"
    client.app.state.settings.managed_apprise_api_url = destination
    settings = client.get("/api/v1/notification-settings")
    assert settings.json()["managed_apprise_api_available"] is True
    assert destination not in settings.text

    created = client.post("/api/v1/notification-endpoints/managed-apprise")
    assert created.status_code == 201
    assert created.json()["label"] == "Docker Apprise API"
    assert created.json()["adapter"] == "apprise_api"
    assert destination not in created.text

    repeated = client.post("/api/v1/notification-endpoints/managed-apprise")
    assert repeated.status_code == 201
    assert repeated.json()["id"] == created.json()["id"]
