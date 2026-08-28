from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from watchtracker.integrations.base import (
    IntegrationEventInput,
    IntegrationPage,
    IntegrationProviderError,
    ProviderDefinition,
    ProviderRegistry,
)

MAX_RESPONSE_BYTES = 5_000_000


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _clean_changes(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None and item != ""}


def _year(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 1878 <= parsed <= 2200 else None


def _date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def _status(value: Any) -> str | None:
    return {
        "watching": "watching",
        "current": "watching",
        "completed": "watched",
        "complete": "watched",
        "watched": "watched",
        "plan_to_watch": "plan_to_watch",
        "planned": "plan_to_watch",
        "planning": "plan_to_watch",
        "plantowatch": "plan_to_watch",
        "on_hold": "paused",
        "onhold": "paused",
        "paused": "paused",
        "dropped": "dropped",
        "repeating": "rewatching",
        "rewatching": "rewatching",
    }.get(str(value or "").casefold().replace("-", "_"))


def _identities(ids: dict[str, Any], media_type: str) -> dict[str, str]:
    result: dict[str, str] = {}
    aliases = {
        "imdb": "imdb",
        "tvdb": "tvdb",
        "trakt": "trakt",
        "simkl": "simkl",
        "mal": "mal",
        "anilist": "anilist",
        "kitsu": "kitsu",
    }
    for source, target in aliases.items():
        value = ids.get(source)
        if value not in {None, ""}:
            result[target] = str(value)
    tmdb = ids.get("tmdb")
    if tmdb not in {None, ""}:
        result["tmdb_movie" if media_type == "movie" else "tmdb_tv"] = str(tmdb)
    return result


def _safe_base_url(value: str, *, allow_http_private: bool = True) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IntegrationProviderError("server_url_invalid", "The server address is invalid.")
    if parsed.username or parsed.password:
        raise IntegrationProviderError(
            "server_url_invalid", "Credentials cannot be included in the server address."
        )
    if parsed.scheme == "http" and not allow_http_private:
        raise IntegrationProviderError("https_required", "This provider requires HTTPS.")
    return value.rstrip("/") + "/"


class ProviderHttpAdapter:
    def __init__(self, definition: ProviderDefinition, client: httpx.AsyncClient | None = None):
        self.definition = definition
        self.client = client

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=7), follow_redirects=False
        )
        close = self.client is None
        try:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                data=form,
            )
        except httpx.TimeoutException as exc:
            raise IntegrationProviderError(
                "provider_timeout", "The provider timed out.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise IntegrationProviderError(
                "provider_unreachable", "The provider could not be reached.", retryable=True
            ) from exc
        finally:
            if close:
                await client.aclose()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise IntegrationProviderError(
                "provider_response_too_large", "The provider response was too large."
            )
        if response.status_code == 429:
            retry = response.headers.get("retry-after")
            raise IntegrationProviderError(
                "provider_rate_limited",
                "The provider rate limit was reached.",
                retryable=True,
                retry_after_seconds=int(retry) if retry and retry.isdigit() else None,
            )
        if response.status_code >= 500:
            raise IntegrationProviderError(
                "provider_unavailable",
                "The provider is temporarily unavailable.",
                retryable=True,
            )
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationProviderError(
                "provider_response_invalid", "The provider returned invalid data."
            ) from exc

    async def _oauth_get(
        self,
        url: str,
        *,
        credentials: dict[str, str],
        configuration: dict[str, Any],
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[httpx.Response, dict[str, str]]:
        access = credentials.get("access_token")
        request_headers = {**(headers or {})}
        if access:
            request_headers["Authorization"] = f"Bearer {access}"
        response = await self._request("GET", url, headers=request_headers, params=params)
        if response.status_code != 401 or not credentials.get("refresh_token"):
            return response, {}
        updates = await self._refresh(credentials, configuration)
        credentials.update(updates)
        request_headers["Authorization"] = f"Bearer {updates['access_token']}"
        response = await self._request("GET", url, headers=request_headers, params=params)
        return response, updates

    async def _refresh(
        self, credentials: dict[str, str], configuration: dict[str, Any]
    ) -> dict[str, str]:
        token_url = self.definition.oauth_token_url
        if not token_url:
            raise IntegrationProviderError(
                "authorization_expired", "Reconnect this provider account."
            )
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": credentials["refresh_token"],
            "client_id": credentials.get("client_id") or configuration.get("client_id"),
        }
        if configuration.get("oauth_redirect_uri"):
            payload["redirect_uri"] = configuration["oauth_redirect_uri"]
        if credentials.get("client_secret"):
            payload["client_secret"] = credentials["client_secret"]
        response = await self._request(
            "POST",
            token_url,
            json_body=payload if self.definition.slug in {"trakt", "simkl", "kitsu"} else None,
            form=payload if self.definition.slug == "myanimelist" else None,
        )
        if response.status_code >= 400:
            raise IntegrationProviderError(
                "authorization_expired", "Reconnect this provider account."
            )
        body = self._json(response)
        access = body.get("access_token") if isinstance(body, dict) else None
        if not access:
            raise IntegrationProviderError(
                "token_response_invalid", "The provider returned an invalid access token."
            )
        updates = {"access_token": str(access)}
        if body.get("refresh_token"):
            updates["refresh_token"] = str(body["refresh_token"])
        return updates


class MediaServerAdapter(ProviderHttpAdapter):
    async def run(
        self,
        *,
        capability: str,
        direction: str,
        connection: dict[str, Any],
        credentials: dict[str, str],
        cursor: dict[str, Any],
        dry_run: bool,
    ) -> IntegrationPage:
        del direction, cursor, dry_run
        configuration = connection.get("configuration") or {}
        server_url = _safe_base_url(str(configuration.get("server_url") or ""))
        slug = self.definition.slug
        if slug == "jellyfin":
            response = await self._request(
                "GET",
                urljoin(server_url, "System/Info"),
                headers={"X-Emby-Token": credentials.get("api_key", "")},
            )
        elif slug == "emby":
            response = await self._request(
                "GET",
                urljoin(server_url, "emby/System/Info"),
                headers={"X-Emby-Token": credentials.get("api_key", "")},
            )
        else:
            response = await self._request(
                "GET",
                urljoin(server_url, "library/sections"),
                headers={"X-Plex-Token": credentials.get("token", "")},
            )
        if response.status_code in {401, 403}:
            raise IntegrationProviderError(
                "credentials_rejected", "The media server rejected the credential."
            )
        if response.status_code >= 400:
            raise IntegrationProviderError(
                "connection_failed", "The media server could not be verified."
            )
        if capability not in {"test_connection", "fetch_library_presence"}:
            raise IntegrationProviderError(
                "webhook_only", "Playback events arrive through the configured webhook."
            )
        return IntegrationPage(
            skipped=1,
            provider_version=response.headers.get("server") or "media-server",
            message="Media server connection verified.",
        )


class TraktAdapter(ProviderHttpAdapter):
    BASE = "https://api.trakt.tv/"

    async def run(self, **kwargs: Any) -> IntegrationPage:
        capability = kwargs["capability"]
        credentials = kwargs["credentials"]
        configuration = kwargs["connection"].get("configuration") or {}
        cursor = kwargs["cursor"]
        endpoint = {
            "test_connection": "users/settings",
            "pull_history": "sync/history",
            "pull_ratings": "sync/ratings",
            "pull_status_progress": "sync/playback",
            "pull_planned": "sync/watchlist",
        }.get(capability)
        if endpoint is None:
            raise IntegrationProviderError("pull_only", "Trakt is read-only in PMT.")
        page = max(1, int(cursor.get("page") or 1))
        headers = {
            "trakt-api-version": "2",
            "trakt-api-key": credentials.get("client_id")
            or str(configuration.get("client_id") or ""),
        }
        response, updates = await self._oauth_get(
            urljoin(self.BASE, endpoint),
            credentials=credentials,
            configuration=configuration,
            headers=headers,
            params={"page": page, "limit": 100} if capability != "test_connection" else None,
        )
        if response.status_code in {401, 403}:
            raise IntegrationProviderError(
                "authorization_required", "Reconnect the Trakt account."
            )
        if response.status_code >= 400:
            raise IntegrationProviderError("provider_rejected", "Trakt rejected the request.")
        payload = self._json(response)
        if capability == "test_connection":
            profile = payload.get("user") or payload if isinstance(payload, dict) else {}
            return IntegrationPage(
                skipped=1,
                credential_updates=updates,
                remote_profile={
                    "username": profile.get("username"),
                    "ids": profile.get("ids", {}),
                },
                provider_version="trakt-v2",
                message="Trakt account verified.",
            )
        if not isinstance(payload, list):
            raise IntegrationProviderError(
                "provider_response_invalid", "Trakt returned invalid data."
            )
        events = tuple(self._event(item, capability) for item in payload[:100])
        pages = int(response.headers.get("x-pagination-page-count") or page)
        return IntegrationPage(
            events=events,
            next_cursor={"page": page + 1 if page < pages else 1},
            has_more=page < pages,
            credential_updates=updates,
            provider_version="trakt-v2",
            message=f"Trakt returned {len(events)} item(s).",
        )

    @staticmethod
    def _event(item: dict[str, Any], capability: str) -> IntegrationEventInput:
        media = item.get("movie") or item.get("show") or item.get("episode") or {}
        show = item.get("show") or {}
        media_type = "movie" if item.get("movie") else "tv"
        identity_source = show if item.get("episode") and show else media
        identities = _identities(identity_source.get("ids") or {}, media_type)
        changes: dict[str, Any] = {}
        if capability == "pull_history":
            changes = {"completed": True, "viewed_on": _date(item.get("watched_at"))}
        elif capability == "pull_ratings":
            changes = {"personal_rating": item.get("rating")}
        elif capability == "pull_planned":
            changes = {"status": "plan_to_watch"}
        elif capability == "pull_status_progress":
            changes = {"status": "watching"}
        episode = item.get("episode") or {}
        if episode:
            changes.update(
                {
                    "episode_completed": capability == "pull_history",
                    "season_number": episode.get("season"),
                    "episode_number": episode.get("number"),
                }
            )
            changes.pop("completed", None)
        return IntegrationEventInput(
            provider_event_id=str(item.get("id") or item.get("listed_at") or _hash(item)[:24]),
            event_kind={
                "pull_history": "history.completed",
                "pull_ratings": "rating.changed",
                "pull_planned": "status.planned",
                "pull_status_progress": "status.changed",
            }[capability],
            safe_summary="Imported one Trakt library item.",
            payload_hash=_hash(item),
            identities=identities,
            title=(show or media).get("title"),
            year=_year((show or media).get("year")),
            media_type=media_type,
            changes=_clean_changes(changes),
            source_values={
                "rating": item.get("rating"),
                "status": "plan_to_watch" if capability == "pull_planned" else None,
                "viewed_on": item.get("watched_at"),
            },
        )


class KitsuAdapter(ProviderHttpAdapter):
    BASE = "https://kitsu.io/api/edge/"

    async def run(self, **kwargs: Any) -> IntegrationPage:
        capability = kwargs["capability"]
        credentials = kwargs["credentials"]
        configuration = kwargs["connection"].get("configuration") or {}
        remote_profile = kwargs["connection"].get("remote_profile") or {}
        cursor = kwargs["cursor"]
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        if capability == "test_connection":
            response, updates = await self._oauth_get(
                urljoin(self.BASE, "users"),
                credentials=credentials,
                configuration=configuration,
                headers=headers,
                params={"filter[self]": "true"},
            )
            if response.status_code >= 400:
                raise IntegrationProviderError(
                    "authorization_required", "Reconnect the Kitsu account."
                )
            body = self._json(response)
            user = (body.get("data") or [{}])[0]
            return IntegrationPage(
                skipped=1,
                credential_updates=updates,
                remote_profile={
                    "id": user.get("id"),
                    "name": (user.get("attributes") or {}).get("name"),
                },
                provider_version="kitsu-jsonapi",
                message="Kitsu account verified.",
            )
        offset = max(0, int(cursor.get("offset") or 0))
        user_id = str(configuration.get("remote_user_id") or remote_profile.get("id") or "")
        params: dict[str, Any] = {
            "include": "anime",
            "page[limit]": 100,
            "page[offset]": offset,
        }
        if not user_id:
            raise IntegrationProviderError(
                "profile_required", "Test the Kitsu connection before importing."
            )
        params["filter[userId]"] = user_id
        response, updates = await self._oauth_get(
            urljoin(self.BASE, "library-entries"),
            credentials=credentials,
            configuration=configuration,
            headers=headers,
            params=params,
        )
        if response.status_code >= 400:
            raise IntegrationProviderError("provider_rejected", "Kitsu rejected the request.")
        body = self._json(response)
        rows = body.get("data") or []
        included = {str(row.get("id")): row for row in body.get("included") or []}
        events = tuple(self._event(row, included) for row in rows[:100])
        has_next = bool((body.get("links") or {}).get("next"))
        return IntegrationPage(
            events=events,
            next_cursor={"offset": offset + len(rows) if has_next else 0},
            has_more=has_next,
            credential_updates=updates,
            provider_version="kitsu-jsonapi",
            message=f"Kitsu returned {len(events)} item(s).",
        )

    @staticmethod
    def _event(
        row: dict[str, Any], included: dict[str, dict[str, Any]]
    ) -> IntegrationEventInput:
        attributes = row.get("attributes") or {}
        relation = ((row.get("relationships") or {}).get("anime") or {}).get("data") or {}
        anime_id = str(relation.get("id") or "")
        anime = included.get(anime_id, {})
        anime_attributes = anime.get("attributes") or {}
        titles = anime_attributes.get("titles") or {}
        score = attributes.get("ratingTwenty")
        changes = _clean_changes(
            {
                "status": _status(attributes.get("status")),
                "personal_rating": float(score) / 2 if score not in {None, ""} else None,
                "episode_progress_count": attributes.get("progress"),
                "repeat_count": attributes.get("reconsumeCount"),
                "started_date": _date(attributes.get("startedAt")),
                "finished_date": _date(attributes.get("finishedAt")),
            }
        )
        return IntegrationEventInput(
            provider_event_id=str(row.get("id") or _hash(row)[:24]),
            event_kind="anime_list.changed",
            safe_summary="Imported one Kitsu anime-list item.",
            payload_hash=_hash(row),
            identities={"kitsu": anime_id} if anime_id else {},
            title=titles.get("en")
            or titles.get("en_jp")
            or anime_attributes.get("canonicalTitle"),
            year=_year(str(anime_attributes.get("startDate") or "")[:4]),
            media_type="anime",
            changes=changes,
            source_values={
                "rating": score,
                "status": attributes.get("status"),
                "progress": attributes.get("progress"),
                "repeat_count": attributes.get("reconsumeCount"),
                "started_date": attributes.get("startedAt"),
                "finished_date": attributes.get("finishedAt"),
            },
        )


class MyAnimeListAdapter(ProviderHttpAdapter):
    BASE = "https://api.myanimelist.net/v2/"

    async def run(self, **kwargs: Any) -> IntegrationPage:
        capability = kwargs["capability"]
        credentials = kwargs["credentials"]
        configuration = kwargs["connection"].get("configuration") or {}
        cursor = kwargs["cursor"]
        if capability == "test_connection":
            endpoint = "users/@me"
            params = None
        else:
            endpoint = "users/@me/animelist"
            params = {
                "fields": "list_status,num_episodes,start_date,alternative_titles",
                "limit": 1000,
                "offset": max(0, int(cursor.get("offset") or 0)),
            }
        response, updates = await self._oauth_get(
            urljoin(self.BASE, endpoint),
            credentials=credentials,
            configuration=configuration,
            params=params,
        )
        if response.status_code >= 400:
            raise IntegrationProviderError(
                "authorization_required", "Reconnect the MyAnimeList account."
            )
        body = self._json(response)
        if capability == "test_connection":
            return IntegrationPage(
                skipped=1,
                credential_updates=updates,
                remote_profile={"id": body.get("id"), "name": body.get("name")},
                provider_version="mal-v2",
                message="MyAnimeList account verified.",
            )
        rows = body.get("data") or []
        events = tuple(self._event(row) for row in rows[:1000])
        has_next = bool((body.get("paging") or {}).get("next"))
        offset = int((params or {}).get("offset") or 0)
        return IntegrationPage(
            events=events,
            next_cursor={"offset": offset + len(rows) if has_next else 0},
            has_more=has_next,
            credential_updates=updates,
            provider_version="mal-v2",
            message=f"MyAnimeList returned {len(events)} item(s).",
        )

    @staticmethod
    def _event(row: dict[str, Any]) -> IntegrationEventInput:
        node = row.get("node") or {}
        status = row.get("list_status") or {}
        changes = _clean_changes(
            {
                "status": _status(status.get("status")),
                "personal_rating": status.get("score") or None,
                "episode_progress_count": status.get("num_episodes_watched"),
                "repeat_count": status.get("num_times_rewatched"),
                "started_date": _date(status.get("start_date")),
                "finished_date": _date(status.get("finish_date")),
            }
        )
        return IntegrationEventInput(
            provider_event_id=f"mal:{node.get('id')}",
            event_kind="anime_list.changed",
            safe_summary="Imported one MyAnimeList anime-list item.",
            payload_hash=_hash(row),
            identities={"mal": str(node.get("id"))},
            title=node.get("title"),
            year=_year(str(node.get("start_date") or "")[:4]),
            media_type="anime",
            changes=changes,
            source_values={
                "rating": status.get("score"),
                "status": status.get("status"),
                "progress": status.get("num_episodes_watched"),
                "repeat_count": status.get("num_times_rewatched"),
                "started_date": status.get("start_date"),
                "finished_date": status.get("finish_date"),
            },
        )


class SimklAdapter(ProviderHttpAdapter):
    BASE = "https://api.simkl.com/"

    async def run(self, **kwargs: Any) -> IntegrationPage:
        capability = kwargs["capability"]
        credentials = kwargs["credentials"]
        configuration = kwargs["connection"].get("configuration") or {}
        cursor = kwargs["cursor"]
        endpoint = "users/settings" if capability == "test_connection" else "sync/all-items"
        headers = {
            "simkl-api-key": credentials.get("client_id")
            or str(configuration.get("client_id") or "")
        }
        response, updates = await self._oauth_get(
            urljoin(self.BASE, endpoint),
            credentials=credentials,
            configuration=configuration,
            headers=headers,
            params=(
                {"date_from": cursor["completed_at"]}
                if capability != "test_connection" and cursor.get("completed_at")
                else None
            ),
        )
        if response.status_code >= 400:
            raise IntegrationProviderError(
                "authorization_required", "Reconnect the Simkl account."
            )
        body = self._json(response)
        if capability == "test_connection":
            return IntegrationPage(
                skipped=1,
                credential_updates=updates,
                remote_profile={"account": body.get("account", {})},
                provider_version="simkl-v1",
                message="Simkl account verified.",
            )
        events: list[IntegrationEventInput] = []
        for group, media_type in (("movies", "movie"), ("shows", "tv"), ("anime", "anime")):
            for row in (body.get(group) or [])[:1000]:
                events.append(self._event(row, media_type))
        return IntegrationPage(
            events=tuple(events),
            next_cursor={"completed_at": datetime.now(UTC).isoformat()},
            credential_updates=updates,
            provider_version="simkl-v1",
            message=f"Simkl returned {len(events)} item(s).",
        )

    @staticmethod
    def _event(row: dict[str, Any], media_type: str) -> IntegrationEventInput:
        media = row.get("movie") or row.get("show") or row.get("anime") or row
        ids = media.get("ids") or row.get("ids") or {}
        state = row.get("status") or (row.get("list") or {}).get("status")
        changes = _clean_changes(
            {
                "status": _status(state),
                "personal_rating": row.get("user_rating") or row.get("rating"),
                "episode_progress_count": row.get("watched_episodes_count"),
                "viewed_on": _date(row.get("last_watched_at")),
                "completed": state in {"completed", "watched"},
            }
        )
        return IntegrationEventInput(
            provider_event_id=f"simkl:{ids.get('simkl') or _hash(row)[:20]}",
            event_kind="library.changed",
            safe_summary="Imported one Simkl library item.",
            payload_hash=_hash(row),
            identities=_identities(ids, media_type),
            title=media.get("title"),
            year=_year(media.get("year")),
            media_type=media_type,
            changes=changes,
            source_values={
                "rating": row.get("user_rating") or row.get("rating"),
                "status": state,
                "progress": row.get("watched_episodes_count"),
                "viewed_on": row.get("last_watched_at"),
            },
        )


class AniListAdapter(ProviderHttpAdapter):
    URL = "https://graphql.anilist.co"

    async def run(self, **kwargs: Any) -> IntegrationPage:
        credentials = kwargs["credentials"]
        capability = kwargs["capability"]
        query = (
            "query { Viewer { id name } }"
            if capability == "test_connection"
            else "query { MediaListCollection(type: ANIME) { lists { entries { id status score progress repeat startedAt { year month day } completedAt { year month day } media { id title { userPreferred } startDate { year } } } } } }"
        )
        response = await self._request(
            "POST",
            self.URL,
            headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            json_body={"query": query},
        )
        if response.status_code >= 400:
            raise IntegrationProviderError(
                "authorization_required", "Reconnect the AniList account."
            )
        body = self._json(response)
        if body.get("errors"):
            raise IntegrationProviderError("provider_rejected", "AniList rejected the request.")
        data = body.get("data") or {}
        if capability == "test_connection":
            return IntegrationPage(
                skipped=1,
                remote_profile=data.get("Viewer") or {},
                provider_version="anilist-graphql",
                message="AniList account verified.",
            )
        rows = [
            entry
            for listing in ((data.get("MediaListCollection") or {}).get("lists") or [])
            for entry in listing.get("entries") or []
        ]
        events = tuple(self._event(row) for row in rows[:2000])
        return IntegrationPage(
            events=events,
            next_cursor={"complete": True},
            provider_version="anilist-graphql",
            message=f"AniList returned {len(events)} item(s).",
        )

    @staticmethod
    def _event(row: dict[str, Any]) -> IntegrationEventInput:
        media = row.get("media") or {}

        def parts(value: dict[str, Any] | None) -> str | None:
            value = value or {}
            if not value.get("year"):
                return None
            return f"{value['year']:04d}-{int(value.get('month') or 1):02d}-{int(value.get('day') or 1):02d}"

        changes = _clean_changes(
            {
                "status": _status(row.get("status")),
                "personal_rating": row.get("score") or None,
                "episode_progress_count": row.get("progress"),
                "repeat_count": row.get("repeat"),
                "started_date": parts(row.get("startedAt")),
                "finished_date": parts(row.get("completedAt")),
            }
        )
        return IntegrationEventInput(
            provider_event_id=f"anilist:{row.get('id')}",
            event_kind="anime_list.changed",
            safe_summary="Imported one AniList anime-list item.",
            payload_hash=_hash(row),
            identities={"anilist": str(media.get("id"))},
            title=(media.get("title") or {}).get("userPreferred"),
            year=_year((media.get("startDate") or {}).get("year")),
            media_type="anime",
            changes=changes,
        )


def build_live_adapters(
    registry: ProviderRegistry, *, allow_anilist: bool = False
) -> tuple[ProviderHttpAdapter, ...]:
    adapters: list[ProviderHttpAdapter] = [
        MediaServerAdapter(registry.definition("jellyfin")),
        MediaServerAdapter(registry.definition("plex")),
        MediaServerAdapter(registry.definition("emby")),
        TraktAdapter(registry.definition("trakt")),
        KitsuAdapter(registry.definition("kitsu")),
        MyAnimeListAdapter(registry.definition("myanimelist")),
        SimklAdapter(registry.definition("simkl")),
    ]
    if allow_anilist:
        adapters.append(AniListAdapter(registry.definition("anilist")))
    return tuple(adapters)
