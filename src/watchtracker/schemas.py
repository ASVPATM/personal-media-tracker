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
    provider: Literal["tmdb_movie", "tmdb_tv", "anilist", "mal"]
    provider_id: str
    title: str
    original_title: str | None = None
    year: int | None = None
    media_type: MediaType
    provider_format: str | None = None
    poster_url: str | None = None
    overview: str | None = None

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
    inference_version: str


class EntryOut(ApiModel):
    id: str
    catalog_item: CatalogOut
    status: str
    personal_rating: float | None
    notes: str | None
    user_tags: list[str]
    started_date: date | None
    finished_date: date | None
    watched_date: date | None
    view_count: int
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


class ImportCommitRequest(ApiModel):
    conflict_policy: Literal["preserve_existing", "overwrite"] | None = None
    allow_invalid: bool = False


class MetadataSettingsOut(ApiModel):
    tmdb_configured: bool
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


class MetadataSettingsUpdate(ApiModel):
    tmdb_token: str | None = Field(default=None, min_length=20, max_length=2_000)
    clear_tmdb_token: bool = False
    import_existing_keychain: bool = False
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
    media_artwork_tint: bool | None = None
    interface_language: Literal["en", "fr"] | None = None

    @field_validator("background_color", "accent_color")
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
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ErrorBody(ApiModel):
    code: str
    message: str
    details: Any | None = None
