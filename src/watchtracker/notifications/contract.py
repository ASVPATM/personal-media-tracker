from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

EVENT_TYPES = frozenset(
    {
        "release.episode_announced",
        "release.episode_released",
        "release.season_announced",
        "release.schedule_changed",
        "release.upcoming",
        "collaboration.invited",
        "collaboration.membership_changed",
        "collaboration.activity",
        "integration.completed_with_conflicts",
        "integration.paused",
        "operations.job_paused",
        "notifications.endpoint_paused",
        "notifications.test",
    }
)

LEGACY_EVENT_TYPES = {
    "episode_announced": "release.episode_announced",
    "episode_released": "release.episode_released",
    "season_announced": "release.season_announced",
    "schedule_changed": "release.schedule_changed",
    "list_shared": "collaboration.invited",
    "list_role_changed": "collaboration.membership_changed",
    "list_unshared": "collaboration.membership_changed",
    "list_deleted": "collaboration.activity",
    "list_item_added": "collaboration.activity",
    "list_item_removed": "collaboration.activity",
    "job_paused": "operations.job_paused",
    "integration_completed_with_conflicts": "integration.completed_with_conflicts",
    "integration_paused": "integration.paused",
}


def normalize_event_type(value: str) -> str:
    normalized = LEGACY_EVENT_TYPES.get(value, value)
    if normalized not in EVENT_TYPES:
        raise ValueError("Unknown notification event type.")
    return normalized


def event_category(value: str) -> str:
    return normalize_event_type(value).split(".", 1)[0]


@dataclass(frozen=True)
class NotificationEvent:
    user_id: str
    event_type: str
    title: str
    safe_message: str
    source_kind: str
    source_key: str
    effective_date: date | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        normalize_event_type(self.event_type)
        if not self.user_id or not self.source_kind or not self.source_key:
            raise ValueError("Notification ownership and source are required.")
        if not self.title.strip() or len(self.title) > 160:
            raise ValueError("Notification title is invalid.")
        if len(self.safe_message) > 500:
            raise ValueError("Notification message is too large.")
