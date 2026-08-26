from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from watchtracker.app import create_app
from watchtracker.config import Settings
from watchtracker.schemas import CatalogData, SearchResponse, SearchResult
from watchtracker.services.secrets import SecretStore


class MemoryKeyring:
    def __init__(self):
        self.value = None

    def get_password(self, _service_name, _username):
        return self.value

    def set_password(self, _service_name, _username, password):
        self.value = password

    def delete_password(self, _service_name, _username):
        self.value = None


class FakeMetadata:
    configured_token = None

    result = SearchResult(
        provider="tmdb_movie",
        provider_id="101",
        title="The Test Film",
        year=2024,
        media_type="movie",
        poster_url="https://images.invalid/poster.jpg",
        overview="A useful fake result.",
    )

    async def search(self, query: str, media_type: str | None = None) -> SearchResponse:
        if query == "fail":
            return SearchResponse(results=[], warnings=["One provider is unavailable."])
        results = [self.result]
        if media_type and media_type != "movie":
            results = []
        return SearchResponse(results=results)

    async def detail(self, result: SearchResult) -> CatalogData:
        from watchtracker.metadata import ProviderUnavailable

        if result.provider_id == "unavailable":
            raise ProviderUnavailable("TMDb is temporarily unavailable.")
        return CatalogData(
            canonical_title=result.title,
            release_year=result.year,
            media_type=result.media_type,
            provider_source=result.provider,
            provider_id=result.provider_id,
            tmdb_movie_id=result.provider_id if result.provider == "tmdb_movie" else None,
            provider_genres=["Drama", "Crime"],
            keywords=["character study"],
            poster_url=result.poster_url or self.result.poster_url,
            overview=result.overview or self.result.overview,
        )

    async def close(self) -> None:
        return None

    def configure_tmdb(self, token: str | None) -> None:
        self.configured_token = token

    def provider_catalog(self):
        return [
            {
                "slug": "tmdb",
                "media_types": ["movie", "tv"],
                "capabilities": ["artwork", "detail", "schedule", "search"],
                "requires_credential": True,
                "attribution": "TMDb",
            }
        ]

    def preferred_identity(
        self,
        external_ids: dict[str, str],
        *,
        capability: str,
        primary: tuple[str | None, str | None] = (None, None),
    ):
        del capability
        if primary[0] and primary[1]:
            return primary
        for provider in ("tvmaze", "tmdb_movie", "tmdb_tv", "mal", "anilist"):
            if external_ids.get(provider):
                return provider, external_ids[provider]
        return None

    async def series_schedule(
        self, provider: str, provider_id: str | None = None, *, refresh: bool = False
    ):
        del refresh
        if provider_id is None:
            provider_id = provider
            provider = "tmdb_tv"
        if provider_id == "unavailable":
            from watchtracker.metadata import ProviderUnavailable

            raise ProviderUnavailable("TMDb is temporarily unavailable.")
        return {
            "provider_source": provider,
            "provider_series_id": provider_id,
            "status": "Returning Series",
            "seasons": [
                {
                    "provider_season_id": "season-0",
                    "season_number": 0,
                    "title": "Specials",
                    "air_date": "2024-01-01",
                    "episode_count": 1,
                    "episodes": [
                        {
                            "provider_episode_id": "episode-special",
                            "episode_number": 1,
                            "title": "A Special",
                            "air_date": "2024-01-01",
                        }
                    ],
                },
                {
                    "provider_season_id": "season-1",
                    "season_number": 1,
                    "title": "Season 1",
                    "air_date": "2024-01-01",
                    "episode_count": 3,
                    "episodes": [
                        {
                            "provider_episode_id": "episode-1",
                            "episode_number": 1,
                            "title": "Released",
                            "air_date": "2024-01-01",
                            "runtime_minutes": 42,
                        },
                        {
                            "provider_episode_id": "episode-2",
                            "episode_number": 2,
                            "title": "Also Released",
                            "air_date": "2024-01-02",
                        },
                        {
                            "provider_episode_id": "episode-3",
                            "episode_number": 3,
                            "title": "Future",
                            "air_date": "2099-01-01",
                        },
                    ],
                },
            ],
        }

    async def artwork_options(self, provider: str, provider_id: str):
        assert provider in {"tmdb_movie", "tmdb_tv"}
        assert provider_id
        return [
            {
                "poster_url": "https://images.invalid/poster.jpg",
                "language": "en",
                "width": 500,
                "height": 750,
                "vote_average": 7.5,
            },
            {
                "poster_url": "https://images.invalid/alternate.jpg",
                "language": None,
                "width": 1000,
                "height": 1500,
                "vote_average": 8.2,
            },
        ]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        log_dir=tmp_path / "logs",
        backups_dir=tmp_path / "backups",
        database_path=tmp_path / "watchtracker.sqlite3",
        cache_dir=tmp_path / "cache",
        env_path=tmp_path / ".env",
        timezone="UTC",
        upload_limit_mb=1,
        tmdb_token=None,
        access_mode="local",
        database_url_override=None,
    )


@pytest.fixture
def app(settings):
    return create_app(
        settings,
        metadata_service=FakeMetadata(),
        secret_store=SecretStore(settings, keyring_backend=MemoryKeyring()),
    )


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def today(settings):
    return datetime.now(settings.tzinfo).date()


def manual_payload(title: str, **overrides):
    payload = {
        "canonical_title": title,
        "release_year": 2020,
        "media_type": "movie",
        "status": "watched",
        "provider_genres": ["Drama"],
    }
    payload.update(overrides)
    return payload
