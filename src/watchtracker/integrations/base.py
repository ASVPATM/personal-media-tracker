from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

ALL_CAPABILITIES = frozenset(
    {
        "test_connection",
        "pull_history",
        "pull_ratings",
        "pull_status_progress",
        "pull_planned",
        "push_history",
        "push_ratings",
        "push_status_progress",
        "receive_playback_event",
        "fetch_library_presence",
        "send_notification",
    }
)


@dataclass(frozen=True)
class ProviderDefinition:
    slug: str
    name: str
    summary: str
    capabilities: tuple[str, ...]
    requirements: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    secret_fields: tuple[str, ...] = ()
    implementation_state: str = "planned"
    availability_reason: str | None = None

    def __post_init__(self) -> None:
        unknown = set(self.capabilities) - ALL_CAPABILITIES
        if unknown:
            raise ValueError(f"unknown integration capabilities: {sorted(unknown)}")
        if not self.slug or not self.slug.replace("-", "").isalnum():
            raise ValueError(
                "provider slug must be stable lowercase letters, numbers, or dashes"
            )

    def serialize(self, *, adapter_available: bool) -> dict[str, Any]:
        value = asdict(self)
        value["available"] = adapter_available and self.implementation_state in {
            "beta",
            "stable",
        }
        if not value["available"] and not value["availability_reason"]:
            value["availability_reason"] = "This provider adapter is planned for a later slice."
        return value


@dataclass(frozen=True)
class IntegrationEventInput:
    event_kind: str
    safe_summary: str
    payload_hash: str
    provider_event_id: str | None = None
    idempotency_key: str | None = None
    canonical_target: str | None = None
    identities: dict[str, str] = field(default_factory=dict)
    title: str | None = None
    year: int | None = None
    media_type: str | None = None
    outcome: str = "previewed"
    changes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntegrationPage:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0
    events: tuple[IntegrationEventInput, ...] = ()
    next_cursor: dict[str, Any] | None = None
    provider_version: str | None = None
    retry_after_seconds: int | None = None
    message: str = "Integration run completed."

    @property
    def counts(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "conflicts": self.conflicts,
            "errors": self.errors,
        }


class IntegrationProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class IntegrationAdapter(Protocol):
    definition: ProviderDefinition

    async def run(
        self,
        *,
        capability: str,
        direction: str,
        connection: dict[str, Any],
        credentials: dict[str, str],
        cursor: dict[str, Any],
        dry_run: bool,
    ) -> IntegrationPage: ...


class ProviderRegistry:
    def __init__(self, definitions: tuple[ProviderDefinition, ...] = ()):
        self._definitions: dict[str, ProviderDefinition] = {}
        self._adapters: dict[str, IntegrationAdapter] = {}
        for definition in definitions:
            self.register_definition(definition)

    def register_definition(self, definition: ProviderDefinition) -> None:
        if definition.slug in self._definitions:
            raise ValueError(f"provider already registered: {definition.slug}")
        self._definitions[definition.slug] = definition

    def register_adapter(self, adapter: IntegrationAdapter) -> None:
        definition = adapter.definition
        current = self._definitions.get(definition.slug)
        if current is not None and current != definition:
            raise ValueError(f"adapter definition does not match provider: {definition.slug}")
        if current is None:
            self.register_definition(definition)
        self._adapters[definition.slug] = adapter

    def definition(self, slug: str) -> ProviderDefinition:
        try:
            return self._definitions[slug]
        except KeyError as exc:
            raise KeyError(f"unknown integration provider: {slug}") from exc

    def adapter(self, slug: str) -> IntegrationAdapter | None:
        return self._adapters.get(slug)

    def catalog(self) -> list[dict[str, Any]]:
        return [
            definition.serialize(adapter_available=slug in self._adapters)
            for slug, definition in sorted(self._definitions.items())
        ]


def default_registry() -> ProviderRegistry:
    planned = "Provider-specific setup is reserved for its tested implementation slice."
    definitions = (
        ProviderDefinition(
            "generic-scrobble",
            "Generic PMT webhook",
            "A versioned inbound playback contract for compatible players and automations.",
            ("receive_playback_event",),
            ("A provider-reachable PMT address",),
            ("PMT must be open and reachable when an event is sent.",),
            implementation_state="foundation",
            availability_reason=planned,
        ),
        ProviderDefinition(
            "jellyfin",
            "Jellyfin",
            "Automatic movie and episode completion through Jellyfin Webhooks.",
            ("test_connection", "receive_playback_event"),
            ("Jellyfin Webhook plugin", "A selected server user"),
            ("Loopback-only PMT cannot receive events from another device.",),
            ("api_key",),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "plex",
            "Plex",
            "Playback completion and rating events through official Plex webhooks.",
            ("test_connection", "receive_playback_event"),
            ("Plex Pass", "A provider-reachable PMT address"),
            ("Inbound capture ships after the generic webhook contract.",),
            ("token",),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "emby",
            "Emby",
            "Playback completion through a supported webhook or bounded pull.",
            ("test_connection", "receive_playback_event", "fetch_library_presence"),
            ("A compatible Emby server version",),
            ("The supported event mechanism must be confirmed during setup.",),
            ("api_key",),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "kodi",
            "Kodi",
            "Local-player completion through the generic playback contract.",
            ("receive_playback_event",),
            ("A Kodi automation or optional add-on",),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "trakt",
            "Trakt",
            "Previewed history, rating, planned-list, and progress interoperability.",
            (
                "test_connection",
                "pull_history",
                "pull_ratings",
                "pull_status_progress",
                "pull_planned",
                "push_history",
                "push_ratings",
                "push_status_progress",
            ),
            ("A Trakt API application for live sync",),
            ("Pull ships before push; outbound changes remain off by default.",),
            ("client_id", "client_secret", "access_token", "refresh_token"),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "anilist",
            "AniList",
            "Anime list status, progress, dates, repeat count, and personal score sync.",
            (
                "test_connection",
                "pull_ratings",
                "pull_status_progress",
                "pull_planned",
                "push_ratings",
                "push_status_progress",
            ),
            ("AniList authorization",),
            ("Tokens expire after one year and do not have refresh tokens.",),
            ("client_id", "client_secret", "access_token"),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "simkl",
            "Simkl",
            "One account for movie, television, and anime history and list state.",
            ("test_connection", "pull_history", "pull_ratings", "pull_status_progress"),
            ("Simkl authorization",),
            ("Pull ships before any outbound mutation.",),
            ("client_id", "client_secret", "access_token", "refresh_token"),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "myanimelist",
            "MyAnimeList",
            "Official account-list status, progress, dates, and personal score sync.",
            ("test_connection", "pull_ratings", "pull_status_progress", "pull_planned"),
            ("A MyAnimeList API client",),
            ("Jikan remains metadata-only and cannot authenticate an account.",),
            ("client_id", "client_secret", "access_token", "refresh_token"),
            availability_reason=planned,
        ),
        ProviderDefinition(
            "apprise",
            "Apprise API",
            "Optional delivery of allowlisted release and sync notifications.",
            ("test_connection", "send_notification"),
            ("A reachable Apprise API instance",),
            ("Private notes and ranking evidence are never included.",),
            ("api_key",),
            availability_reason=planned,
        ),
    )
    return ProviderRegistry(definitions)
