from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from watchtracker.integrations.playback import parse_playback_event


def test_jellyfin_completion_is_normalized_without_raw_payload():
    parsed = parse_playback_event(
        "jellyfin",
        {
            "NotificationType": "PlaybackStop",
            "UserId": "remote-alex",
            "SessionId": "session-1",
            "ItemId": "episode-8",
            "ItemType": "Episode",
            "SeriesName": "Fixture Show",
            "ParentIndexNumber": 1,
            "IndexNumber": 8,
            "RunTimeTicks": 1000,
            "PlaybackPositionTicks": 950,
            "PlayedToCompletion": True,
            "Timestamp": "2026-08-27T12:00:00Z",
            "ProviderIds": {"Tmdb": "202", "Tvdb": "303"},
        },
    )
    assert parsed.remote_user_id == "remote-alex"
    assert parsed.event is not None
    assert parsed.event.identities == {"tmdb_tv": "202", "tvdb": "303"}
    observation = parsed.event.changes["playback_observation"]
    assert observation["event"] == "stop"
    assert observation["strong_completion"] is True
    assert parsed.event.changes["season_number"] == 1
    assert parsed.event.changes["episode_number"] == 8


def test_media_server_incomplete_and_duplicate_provider_keys_are_bounded():
    payload = {
        "Event": "playback.stop",
        "UserId": "remote-sam",
        "SessionId": "session-2",
        "PlaybackPositionTicks": 200,
        "Item": {"Id": "movie-1", "Type": "Movie", "RunTimeTicks": 1000},
    }
    parsed = parse_playback_event("emby", payload)
    assert parsed.event is not None
    observation = parsed.event.changes["playback_observation"]
    assert observation["event"] == "stop"
    assert observation["position_seconds"] == 200
    assert observation["duration_seconds"] == 1000


def test_plex_scrobble_uses_last_viewed_time_and_one_time_url_credential(client):
    parsed = parse_playback_event(
        "plex",
        {
            "event": "media.scrobble",
            "Account": {"id": "plex-alex"},
            "Server": {"uuid": "server-1"},
            "Player": {"uuid": "player-1"},
            "Metadata": {
                "type": "movie",
                "ratingKey": "55",
                "title": "Fixture Movie",
                "lastViewedAt": 1_787_832_000,
                "Guid": [{"id": "tmdb://505"}],
            },
        },
    )
    assert parsed.event is not None
    assert parsed.event.changes["playback_observation"]["observed_at"].startswith("2026-08-27")
    assert parsed.event.changes["playback_observation"]["strong_completion"] is True
    assert parsed.event.provider_event_id.endswith(":player-1:55:1787832000")

    connection = client.post(
        "/api/v1/integrations/connections",
        json={
            "provider_slug": "plex",
            "label": "Fixture Plex",
            "configuration": {"server_url": "http://127.0.0.1:32400"},
            "credentials": {"token": "plex-private-token"},
            "capabilities": {"receive_playback_event": True},
        },
    )
    assert connection.status_code == 201
    issued = client.post(
        f"/api/v1/integrations/connections/{connection.json()['id']}/webhook-credential",
        json={},
    )
    assert issued.status_code == 200
    body = issued.json()
    query = parse_qs(urlsplit(body["callback_url"]).query)
    assert body["credential_transport"] == "query"
    assert body["token"] == ""
    assert body["token_header"] == ""
    assert len(query["token"][0]) >= 40
