from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MediaType = Literal["movie", "tv", "anime"]
WatchStatus = Literal["watched", "watching", "plan_to_watch", "dropped", "rewatching"]
Rating = Annotated[float, Field(ge=1, le=10)]
NonBlank = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProviderReference(ApiModel):
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    provider_id: str = Field(min_length=1, max_length=200)


class MetadataSourceSnapshot(ProviderReference):
    fields: dict[str, Any] = Field(default_factory=dict)
    external_ids: dict[str, str] = Field(default_factory=dict)


class CatalogData(ApiModel):
    canonical_title: NonBlank
    original_title: str | None = None
    release_year: int | None = Field(default=None, ge=1878, le=2200)
    release_date: date | None = None
    media_type: MediaType
    provider_format: str | None = None
    provider_source: str | None = None
    provider_id: str | None = None
    tmdb_movie_id: str | None = None
    tmdb_tv_id: str | None = None
    anilist_id: str | None = None
    mal_id: str | None = None
    poster_url: str | None = None
    overview: str | None = None
    provider_genres: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    country: str | None = None
    language: str | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    episode_count: int | None = Field(default=None, ge=0)
    public_score: float | None = None
    raw_provider_payload: dict[str, Any] | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    source_snapshots: list[MetadataSourceSnapshot] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)

    @field_validator("poster_url")
    @classmethod
    def safe_poster_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("poster URL must use HTTPS")
        return value.strip()


class SearchResult(ApiModel):
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    provider_id: str
    title: str
    original_title: str | None = None
    aliases: list[str] = Field(default_factory=list)
    year: int | None = None
    media_type: MediaType
    provider_format: str | None = None
    poster_url: str | None = None
    overview: str | None = None
    popularity: float | None = Field(default=None, ge=0)
    external_ids: dict[str, str] = Field(default_factory=dict)
    corroborating_results: list[ProviderReference] = Field(default_factory=list)

    @field_validator("poster_url")
    @classmethod
    def safe_poster_url(cls, value: str | None) -> str | None:
        return CatalogData.safe_poster_url(value)


class SearchResponse(ApiModel):
    results: list[SearchResult]
    warnings: list[str] = Field(default_factory=list)


def _rating(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("personal rating must be a number") from exc
    if (
        not parsed.is_finite()
        or parsed < Decimal("1")
        or parsed > Decimal("10")
        or parsed != parsed.quantize(Decimal("0.1"))
    ):
        raise ValueError("personal rating must be from 1.0 to 10.0 in 0.1 increments")
    return float(parsed)


class EntryOptions(ApiModel):
    status: WatchStatus = "watched"
    personal_rating: Rating | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    user_tags: list[str] = Field(default_factory=list, max_length=100)
    started_date: date | None = None
    finished_date: date | None = None
    watched_date: date | None = None
    view_count: int | None = Field(default=None, ge=0, le=10_000)

    _validate_rating = field_validator("personal_rating", mode="before")(_rating)

    @model_validator(mode="after")
    def validate_completed_count(self):
        if self.status == "watched" and self.view_count == 0:
            raise ValueError("watched entries must have at least one completed viewing")
        return self


class FromSearchRequest(EntryOptions):
    result: SearchResult
    if_existing: Literal["return_existing", "mark_watched", "rewatch"] = "return_existing"


class ManualEntryRequest(EntryOptions, CatalogData):
    pass


class EntryPatch(ApiModel):
    status: WatchStatus | None = None
    personal_rating: Rating | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    user_tags: list[str] | None = Field(default=None, max_length=100)
    started_date: date | None = None
    finished_date: date | None = None
    watched_date: date | None = None
    view_count: int | None = Field(default=None, ge=0, le=10_000)
    is_favorite: bool | None = None
    genre_additions: list[str] | None = None
    genre_removals: list[str] | None = None
    subgenre_additions: list[str] | None = None
    subgenre_removals: list[str] | None = None

    _validate_rating = field_validator("personal_rating", mode="before")(_rating)


class ViewingCreate(ApiModel):
    viewed_on: date | None = None


class ViewingOut(ApiModel):
    id: str
    viewed_on: date | None
    source: str
    created_at: datetime

    _normalize_created_at = field_validator("created_at")(_as_utc)


class CatalogOut(ApiModel):
    id: str
    canonical_title: str
    original_title: str | None
    release_year: int | None
    release_date: date | None
    media_type: str
    provider_format: str | None
    provider_source: str | None
    provider_id: str | None
    tmdb_movie_id: str | None
    tmdb_tv_id: str | None
    anilist_id: str | None
    mal_id: str | None
    poster_url: str | None
    # Kept on the wire for backwards compatibility. The override is private
    # per-user state and is populated from WatchEntry during serialization.
    poster_override_url: str | None = None
    overview: str | None
    provider_genres: list[str]
    normalized_genres: list[str]
    inferred_subgenres: list[str]
    keywords: list[str]
    country: str | None
    language: str | None
    runtime_minutes: int | None
    episode_count: int | None
    public_score: float | None
    metadata_source: str
    metadata_provenance: dict[str, Any]
    metadata_field_sources: dict[str, Any]
    external_ids: dict[str, str] = Field(default_factory=dict)
    inference_version: str


class EntryOut(ApiModel):
    id: str
    version: int
    catalog_item: CatalogOut
    status: str
    personal_rating: float | None
    notes: str | None
    user_tags: list[str]
    started_date: date | None
    finished_date: date | None
    watched_date: date | None
    view_count: int
    is_favorite: bool
    episode_progress_explicit: bool
    rewatch_count: int
    effective_genres: list[str]
    effective_subgenres: list[str]
    genre_additions: list[str]
    genre_removals: list[str]
    subgenre_additions: list[str]
    subgenre_removals: list[str]
    import_context: dict[str, Any]
    viewing_events: list[ViewingOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    _normalize_timestamps = field_validator("created_at", "updated_at", "deleted_at")(_as_utc)


class MediaListCreate(ApiModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class MediaListPatch(ApiModel):
    pinned_to_navigation: bool | None = None
    name: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ] = None

    @model_validator(mode="after")
    def has_list_change(self):
        if self.pinned_to_navigation is None and self.name is None:
            raise ValueError("At least one list field must be changed.")
        return self


class MediaListMemberAdd(ApiModel):
    username: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    role: Literal["editor", "viewer"] = "viewer"


class MediaListMemberUpdate(ApiModel):
    role: Literal["editor", "viewer"]


class MediaListMembershipOut(ApiModel):
    id: str
    user_id: str
    username: str
    display_name: str
    role: Literal["owner", "editor", "viewer"]
    accepted_at: datetime

    _normalize_membership_time = field_validator("accepted_at")(_as_utc)


class MediaListItemOut(ApiModel):
    id: str
    catalog_item: CatalogOut
    entry: EntryOut | None = None
    tracked_by_viewer: bool = False
    added_by_user_id: str
    position: int
    shared_note: str | None = None
    added_at: datetime

    _normalize_added_at = field_validator("added_at")(_as_utc)


class MediaListOut(ApiModel):
    id: str
    version: int
    name: str
    pinned_to_navigation: bool
    visibility: Literal["private", "shared"] = "private"
    current_user_role: Literal["owner", "editor", "viewer"] = "owner"
    can_edit: bool = True
    can_manage_members: bool = True
    owner_user_id: str
    members: list[MediaListMembershipOut] = Field(default_factory=list)
    items: list[MediaListItemOut]
    created_at: datetime
    updated_at: datetime

    _normalize_list_timestamps = field_validator("created_at", "updated_at")(_as_utc)


class MediaListActivityOut(ApiModel):
    id: str
    action: str
    actor_user_id: str | None
    actor_display_name: str | None = None
    safe_payload: dict[str, Any]
    created_at: datetime

    _normalize_activity_time = field_validator("created_at")(_as_utc)


class ArtworkOption(ApiModel):
    poster_url: str
    language: str | None = None
    width: int | None = None
    height: int | None = None
    vote_average: float | None = None
    is_default: bool = False

    @field_validator("poster_url")
    @classmethod
    def safe_artwork_url(cls, value: str) -> str:
        return CatalogData.safe_poster_url(value) or ""


class ArtworkOptionsOut(ApiModel):
    supported: bool
    provider: str | None = None
    default_url: str | None = None
    selected_url: str | None = None
    options: list[ArtworkOption] = Field(default_factory=list)
    warning: str | None = None


class ArtworkSelection(ApiModel):
    poster_url: str | None = None

    @field_validator("poster_url")
    @classmethod
    def safe_selected_url(cls, value: str | None) -> str | None:
        return CatalogData.safe_poster_url(value)


class EntryMutationResponse(ApiModel):
    entry: EntryOut
    created: bool = False
    duplicate: bool = False
    action: str


class PaginatedEntries(ApiModel):
    items: list[EntryOut]
    total: int
    page: int
    page_size: int
    pages: int


class MetadataReviewOut(ApiModel):
    total: int
    entry: EntryOut | None = None


class RatingReviewOut(ApiModel):
    total: int
    entry: EntryOut | None = None


RatingAnswer = float | Literal["skip", "not_applicable"]


class RatingAssessmentCreate(ApiModel):
    entry_id: str = Field(min_length=36, max_length=36)
    answers: dict[str, RatingAnswer] = Field(default_factory=dict)
    private_reflection: str | None = Field(default=None, max_length=5_000)


class RatingAssessmentPatch(ApiModel):
    answers: dict[str, RatingAnswer] | None = None
    private_reflection: str | None = Field(default=None, max_length=5_000)
    expected_version: int = Field(ge=1)


class RatingAssessmentComplete(ApiModel):
    expected_version: int = Field(ge=1)
    rating_action: Literal["use_suggestion", "keep_rating", "set_rating", "save_without_change"]
    final_rating: Rating | None = None
    refinement_run_id: str | None = Field(default=None, min_length=36, max_length=36)

    _validate_final_rating = field_validator("final_rating", mode="before")(_rating)

    @model_validator(mode="after")
    def final_rating_matches_action(self):
        if self.rating_action == "set_rating" and self.final_rating is None:
            raise ValueError("final_rating is required when rating_action is set_rating")
        if self.rating_action != "set_rating" and self.final_rating is not None:
            raise ValueError("final_rating is accepted only when rating_action is set_rating")
        return self


class RatingComparisonUpdate(ApiModel):
    result: Literal["low", "high", "tie", "skip"]
    displayed_left_entry_id: str = Field(min_length=36, max_length=36)
    refinement_run_id: str | None = Field(default=None, min_length=36, max_length=36)


class RatingRefinementStart(ApiModel):
    scope: Literal["focused", "full"]
    entry_id: str | None = Field(default=None, min_length=36, max_length=36)


class RatingRefinementEntryUpdate(ApiModel):
    entry_id: str = Field(min_length=36, max_length=36)


class SeriesFollowUpdate(ApiModel):
    notify_new_episode: bool = True
    notify_new_season: bool = True
    include_specials: bool = False


class EpisodeViewingCreate(ApiModel):
    watched_on: date | None = None


class SeasonBulkUpdate(ApiModel):
    watched: bool
    watched_on: date | None = None
    confirmed: bool = False

    @model_validator(mode="after")
    def confirmation_required(self):
        if not self.confirmed:
            raise ValueError("confirmed must be true for a bulk season change")
        return self


class ReleaseEventUpdate(ApiModel):
    action: Literal["read", "unread", "dismiss"]


class OwnerLogin(ApiModel):
    username: str = Field(default="owner", min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1_024, repr=False)


class OwnerBootstrap(ApiModel):
    password: str = Field(min_length=12, max_length=1_024, repr=False)


class LocalServerRecovery(ApiModel):
    new_password: str = Field(min_length=12, max_length=1_024, repr=False)


class ServerBootstrap(ApiModel):
    setup_token: str = Field(min_length=24, max_length=1_024, repr=False)
    username: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)
    ] = "owner"
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ] = "Owner"
    password: str = Field(min_length=12, max_length=1_024, repr=False)


class InvitationCreate(ApiModel):
    role: Literal["admin", "member"] = "member"
    email: str | None = Field(default=None, max_length=320)
    expires_hours: int = Field(default=72, ge=1, le=720)


class InvitationRedeem(ApiModel):
    token: str = Field(min_length=24, max_length=1_024, repr=False)
    username: str | None = Field(default=None, min_length=3, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1_024, repr=False)


class AdminUserUpdate(ApiModel):
    state: Literal["active", "disabled"] | None = None
    role: Literal["admin", "member"] | None = None

    @model_validator(mode="after")
    def has_change(self):
        if self.state is None and self.role is None:
            raise ValueError("At least one account field must be changed.")
        return self


class NativeLogin(ApiModel):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1_024, repr=False)
    device_id: str = Field(min_length=8, max_length=80)
    device_label: str = Field(min_length=1, max_length=120)


class NativeRefresh(ApiModel):
    refresh_token: str = Field(min_length=32, max_length=1_024, repr=False)


class BrowserSessionAdopt(ApiModel):
    handoff_token: str = Field(min_length=32, max_length=1_024, repr=False)


class SyncMutation(ApiModel):
    request_id: str = Field(min_length=8, max_length=128)
    operation: Literal["entry.patch", "list.patch", "list.item.add", "list.item.remove"]
    resource_id: str = Field(min_length=36, max_length=36)
    base_version: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    client_timestamp: datetime


class SyncPushRequest(ApiModel):
    device_id: str = Field(min_length=8, max_length=80)
    mutations: list[SyncMutation] = Field(min_length=1, max_length=100)


class RemoteServerDiscover(ApiModel):
    server_url: str = Field(min_length=8, max_length=500)


class RemoteServerConnect(RemoteServerDiscover):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1_024, repr=False)
    label: str = Field(default="Home PMT Server", min_length=1, max_length=120)
    device_label: str = Field(
        default="Personal Media Tracker desktop", min_length=1, max_length=120
    )


class RemoteServerEnroll(RemoteServerDiscover):
    invitation_token: str = Field(min_length=24, max_length=1_024, repr=False)
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1_024, repr=False)
    label: str = Field(default="Home PMT Server", min_length=1, max_length=120)
    device_label: str = Field(
        default="Personal Media Tracker desktop", min_length=1, max_length=120
    )


class RemoteServerConnectionState(ApiModel):
    enabled: bool


class RemoteEntryPatch(ApiModel):
    entry_id: str = Field(min_length=36, max_length=36)
    base_version: int = Field(ge=1)
    payload: EntryPatch


class RemoteOfflineMutation(ApiModel):
    operation: Literal["entry.patch", "list.patch", "list.item.add", "list.item.remove"]
    resource_id: str = Field(min_length=36, max_length=36)
    base_version: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class RemoteConflictResolution(ApiModel):
    action: Literal["discard", "retry_with_latest"]


class OwnerPasswordChange(ApiModel):
    current_password: str = Field(min_length=1, max_length=1_024, repr=False)
    new_password: str = Field(min_length=12, max_length=1_024, repr=False)


class ServerActivationRequest(ApiModel):
    public_base_url: str = Field(min_length=12, max_length=500)
    owner_password: str = Field(min_length=12, max_length=1_024, repr=False)
    bind_host: str = Field(default="127.0.0.1", min_length=2, max_length=255)
    port: int = Field(default=8000, ge=1, le=65_535)
    trusted_proxy_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])

    @field_validator("public_base_url")
    @classmethod
    def clean_https_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("public_base_url must be an HTTPS origin without a path")
        return value


class ImportCommitRequest(ApiModel):
    conflict_policy: Literal["preserve_existing", "overwrite"] | None = None
    allow_invalid: bool = False


class MetadataSettingsOut(ApiModel):
    tmdb_configured: bool
    tvmaze_enabled: bool = True
    tvmaze_requires_key: bool = False
    wikidata_enabled: bool = True
    wikidata_requires_key: bool = False
    anilist_enabled: bool = False
    anilist_requires_key: bool = False
    jikan_requires_key: bool = False
    saved_locally: bool = True
    storage: Literal["none", "environment", "keychain", "local_secret_file", "legacy_env"] = (
        "none"
    )
    legacy_token_available: bool = False
    preferred_storage: Literal["keychain", "local_secret_file"] = "local_secret_file"
    keychain_available: bool = False
    credential_scope: Literal["local", "individual", "server_shared"] = "local"
    individual_token_configured: bool = False
    server_token_available: bool = False
    use_server_token: bool = False


class MetadataSettingsUpdate(ApiModel):
    tmdb_token: str | None = Field(default=None, min_length=20, max_length=2_000)
    clear_tmdb_token: bool = False
    import_existing_keychain: bool = False
    use_server_token: bool | None = None
    credential_storage: Literal["keychain", "local_secret_file"] = "local_secret_file"

    @field_validator("tmdb_token")
    @classmethod
    def validate_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if "\n" in value or "\r" in value:
            raise ValueError("token must be a single line")
        return value

    @model_validator(mode="after")
    def has_an_action(self):
        if (
            not self.clear_tmdb_token
            and not self.import_existing_keychain
            and not self.tmdb_token
            and self.use_server_token is None
        ):
            raise ValueError("provide a TMDb token or request that it be cleared")
        return self


class GeneralSettingsUpdate(ApiModel):
    timezone: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    region: str | None = Field(default=None, min_length=2, max_length=10)
    onboarding_complete: bool | None = None
    theme: Literal["system", "light", "dark"] | None = None
    accent: Literal["forest", "ocean", "violet", "rose", "amber", "graphite"] | None = None
    accent_color: str | None = Field(default=None, max_length=7)
    background_color: str | None = Field(default=None, max_length=7)
    background_strength: int | None = Field(default=None, ge=0, le=100)
    background_mode: Literal["adaptive", "full"] | None = None
    background_image_enabled: bool | None = None
    background_image_opacity: int | None = Field(default=None, ge=0, le=100)
    background_image_tint: bool | None = None
    media_artwork_tint: bool | None = None
    media_artwork_full_color: bool | None = None
    icon_background_color: str | None = Field(default=None, max_length=7)
    icon_text_color: str | None = Field(default=None, max_length=7)
    icon_follow_accent: bool | None = None
    interface_language: Literal["en", "fr", "zh-CN"] | None = None
    advanced_ratings_enabled: bool | None = None
    release_check_mode: Literal["manual", "automatic"] | None = None
    sidebar_mode: Literal["expanded", "minimized"] | None = None
    navigation_order: Literal["standard", "reversed"] | None = None
    settings_privacy_reminder_dismissed: bool | None = None
    keyboard_shortcuts: dict[str, str] | None = None

    @field_validator("keyboard_shortcuts")
    @classmethod
    def valid_keyboard_shortcuts(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        allowed = {
            "quick_add",
            "library",
            "currently_watching",
            "active_shows",
            "rankings",
            "insights",
            "settings",
        }
        if set(value) - allowed:
            raise ValueError("unknown keyboard shortcut action")
        cleaned: dict[str, str] = {}
        for action, shortcut in value.items():
            shortcut = shortcut.strip()
            if not shortcut:
                continue
            if len(shortcut) > 80 or any(ord(character) < 32 for character in shortcut):
                raise ValueError("invalid keyboard shortcut")
            cleaned[action] = shortcut
        if len(set(cleaned.values())) != len(cleaned):
            raise ValueError("each keyboard shortcut must be unique")
        return cleaned

    @field_validator(
        "background_color", "accent_color", "icon_background_color", "icon_text_color"
    )
    @classmethod
    def valid_hex_color(cls, value: str | None) -> str | None:
        if value in {None, ""}:
            return None
        if (
            len(value) != 7
            or value[0] != "#"
            or any(character not in "0123456789abcdefABCDEF" for character in value[1:])
        ):
            raise ValueError("color must be a six-digit hex color")
        return value.lower()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class MetadataEnrichmentStart(ApiModel):
    limit: int = Field(default=500, ge=1, le=2_000)


class MetadataEnrichmentStatus(ApiModel):
    status: Literal["idle", "running", "completed", "failed", "cancelled"]
    total: int = 0
    processed: int = 0
    enriched: int = 0
    needs_confirmation: int = 0
    skipped: int = 0
    failed: int = 0
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    match_reasons: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IntegrationConnectionCreate(ApiModel):
    provider_slug: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]
    label: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    configuration: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, bool | Literal["pull", "push", "both", "off"]] = Field(
        default_factory=dict
    )
    schedule: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
    credential_storage: Literal["local_secret_file", "keychain"] | None = None

    @field_validator("credentials")
    @classmethod
    def bounded_credentials(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 12 or any(
            not secret.strip() or len(secret) > 8_000 for secret in value.values()
        ):
            raise ValueError("credential fields must be nonblank and bounded")
        return value


class IntegrationConnectionState(ApiModel):
    enabled: bool


class IntegrationRunCreate(ApiModel):
    capability: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]
    direction: Literal["pull", "push", "inbound", "outbound", "test"]
    dry_run: bool = False


class ErrorBody(ApiModel):
    code: str
    message: str
    details: Any | None = None
