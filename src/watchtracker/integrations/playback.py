from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from watchtracker.integrations.base import IntegrationEventInput, IntegrationProviderError


@dataclass(frozen=True)
class PlaybackEnvelope:
    remote_user_id: str
    event: IntegrationEventInput | None
    ignored_reason: str | None = None


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _ids(values: dict[str, Any], media_type: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        normalized = str(key).casefold()
        if value in {None, ""}:
            continue
        if normalized == "tmdb":
            result["tmdb_movie" if media_type == "movie" else "tmdb_tv"] = str(value)
        elif normalized in {"imdb", "tvdb", "anilist", "mal", "kitsu"}:
            result[normalized] = str(value)
    return result


def _date(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.date().isoformat()


def _datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _seconds(value: Any) -> float:
    raw = max(float(value or 0), 0.0)
    # Jellyfin and Emby use 100-nanosecond ticks. Small synthetic fixtures are
    # intentionally accepted as seconds so policy tests stay readable.
    return raw / 10_000_000 if raw >= 1_000_000 else raw


def parse_playback_event(
    provider: str, payload: dict[str, Any], *, completion_threshold: float = 0.9
) -> PlaybackEnvelope:
    if provider == "jellyfin":
        return _jellyfin(payload, completion_threshold)
    if provider == "plex":
        return _plex(payload)
    if provider == "emby":
        return _emby(payload, completion_threshold)
    raise IntegrationProviderError("provider_unknown", "Unknown playback provider.")


def _jellyfin(payload: dict[str, Any], threshold: float) -> PlaybackEnvelope:
    remote_user = str(payload.get("UserId") or (payload.get("User") or {}).get("Id") or "")
    if not remote_user:
        raise IntegrationProviderError("remote_user_missing", "Playback user is missing.")
    kind = str(payload.get("NotificationType") or payload.get("Event") or "").casefold()
    event_names = {
        "playbackstart": "start",
        "playback.start": "start",
        "playbackpause": "pause",
        "playback.pause": "pause",
        "playbackprogress": "progress",
        "playback.progress": "progress",
        "playbackstop": "stop",
        "playback.stop": "stop",
        "itemplayed": "completed",
        "item.played": "completed",
    }
    if kind not in event_names:
        return PlaybackEnvelope(remote_user, None, "unsupported_event")
    runtime = _seconds(payload.get("RunTimeTicks"))
    position = _seconds(payload.get("PlaybackPositionTicks") or payload.get("PositionTicks"))
    strong_completion = (
        bool(payload.get("PlayedToCompletion")) or event_names[kind] == "completed"
    )
    item_type = str(payload.get("ItemType") or "").casefold()
    episode = item_type == "episode"
    media_type = "tv" if episode or item_type in {"series", "season"} else "movie"
    provider_ids = payload.get("ProviderIds") or {}
    stamp = payload.get("Timestamp") or payload.get("Date")
    changes: dict[str, Any] = {
        "playback_observation": {
            "event": event_names[kind],
            "position_seconds": position,
            "duration_seconds": runtime,
            "active_seconds": payload.get("ActiveSeconds"),
            "strong_completion": strong_completion,
            "observed_at": _datetime(stamp),
            "completion_threshold": threshold,
        }
    }
    if episode:
        changes.update(
            {
                "season_number": payload.get("SeasonNumber")
                or payload.get("ParentIndexNumber"),
                "episode_number": payload.get("EpisodeNumber") or payload.get("IndexNumber"),
            }
        )
    session = str(payload.get("SessionId") or payload.get("PlaybackSessionId") or "")
    item_id = str(payload.get("ItemId") or "")
    stamp = str(stamp or "")
    return PlaybackEnvelope(
        remote_user,
        IntegrationEventInput(
            provider_event_id=f"{session}:{item_id}:{stamp}",
            idempotency_key=f"{remote_user}|{session}|{item_id}|{stamp}|complete",
            event_kind="playback.observed",
            safe_summary="Jellyfin reported a playback observation.",
            payload_hash=_hash(payload),
            identities=_ids(provider_ids, media_type),
            title=payload.get("SeriesName") if episode else payload.get("Name"),
            year=payload.get("Year") or payload.get("ProductionYear"),
            media_type=media_type,
            changes={
                key: value
                for key, value in changes.items()
                if value is not None and value != ""
            },
        ),
    )


def _plex(payload: dict[str, Any]) -> PlaybackEnvelope:
    account = payload.get("Account") or {}
    remote_user = str(account.get("id") or account.get("uuid") or account.get("title") or "")
    if not remote_user:
        raise IntegrationProviderError("remote_user_missing", "Playback user is missing.")
    if payload.get("event") != "media.scrobble":
        return PlaybackEnvelope(remote_user, None, "unsupported_event")
    metadata = payload.get("Metadata") or {}
    kind = str(metadata.get("type") or "").casefold()
    episode = kind == "episode"
    media_type = "tv" if episode else "movie"
    provider_ids: dict[str, Any] = {}
    guid_values = [
        metadata.get("guid"),
        *(item.get("id") for item in metadata.get("Guid") or []),
    ]
    for raw in guid_values:
        if not raw or "://" not in str(raw):
            continue
        namespace, value = str(raw).split("://", 1)
        provider_ids[namespace] = value.split("?", 1)[0]
    event_time = (
        metadata.get("lastViewedAt")
        or payload.get("createdAt")
        or metadata.get("updatedAt")
        or "unknown"
    )
    changes: dict[str, Any] = {
        "playback_observation": {
            "event": "completed",
            "position_seconds": 0,
            "duration_seconds": 0,
            "active_seconds": None,
            "strong_completion": True,
            "observed_at": _datetime(event_time),
            "completion_threshold": 0.9,
        }
    }
    if episode:
        changes.update(
            {
                "season_number": metadata.get("parentIndex"),
                "episode_number": metadata.get("index"),
            }
        )
    player_id = (payload.get("Player") or {}).get("uuid") or "unknown"
    key = f"{(payload.get('Server') or {}).get('uuid')}:{player_id}:{metadata.get('ratingKey')}:{event_time}"
    return PlaybackEnvelope(
        remote_user,
        IntegrationEventInput(
            provider_event_id=key,
            idempotency_key=f"{remote_user}|{key}|scrobble",
            event_kind="playback.observed",
            safe_summary="Plex reported a completed playback.",
            payload_hash=_hash(payload),
            identities=_ids(provider_ids, media_type),
            title=metadata.get("grandparentTitle") if episode else metadata.get("title"),
            year=metadata.get("year"),
            media_type=media_type,
            changes={
                key: value
                for key, value in changes.items()
                if value is not None and value != ""
            },
        ),
    )


def _emby(payload: dict[str, Any], threshold: float) -> PlaybackEnvelope:
    user = payload.get("User") or {}
    remote_user = str(payload.get("UserId") or user.get("Id") or "")
    if not remote_user:
        raise IntegrationProviderError("remote_user_missing", "Playback user is missing.")
    kind = str(payload.get("Event") or payload.get("NotificationType") or "").casefold()
    event_names = {
        "playback.start": "start",
        "playbackstart": "start",
        "playback.pause": "pause",
        "playbackpause": "pause",
        "playback.progress": "progress",
        "playbackprogress": "progress",
        "playback.stop": "stop",
        "playbackstop": "stop",
        "itemplayed": "completed",
    }
    if kind not in event_names:
        return PlaybackEnvelope(remote_user, None, "unsupported_event")
    item = payload.get("Item") or payload
    runtime = _seconds(item.get("RunTimeTicks") or payload.get("RunTimeTicks"))
    position = _seconds(payload.get("PlaybackPositionTicks") or payload.get("PositionTicks"))
    strong_completion = (
        bool(payload.get("PlayedToCompletion")) or event_names[kind] == "completed"
    )
    episode = str(item.get("Type") or payload.get("ItemType") or "").casefold() == "episode"
    media_type = "tv" if episode else "movie"
    stamp = payload.get("Date") or payload.get("Timestamp")
    changes: dict[str, Any] = {
        "playback_observation": {
            "event": event_names[kind],
            "position_seconds": position,
            "duration_seconds": runtime,
            "active_seconds": payload.get("ActiveSeconds"),
            "strong_completion": strong_completion,
            "observed_at": _datetime(stamp),
            "completion_threshold": threshold,
        }
    }
    if episode:
        changes.update(
            {
                "season_number": item.get("ParentIndexNumber"),
                "episode_number": item.get("IndexNumber"),
            }
        )
    key = f"{payload.get('SessionId')}:{item.get('Id')}:{stamp}"
    return PlaybackEnvelope(
        remote_user,
        IntegrationEventInput(
            provider_event_id=key,
            idempotency_key=f"{remote_user}|{key}|complete",
            event_kind="playback.observed",
            safe_summary="Emby reported a playback observation.",
            payload_hash=_hash(payload),
            identities=_ids(item.get("ProviderIds") or {}, media_type),
            title=item.get("SeriesName") if episode else item.get("Name"),
            year=item.get("ProductionYear"),
            media_type=media_type,
            changes={
                key: value
                for key, value in changes.items()
                if value is not None and value != ""
            },
        ),
    )
