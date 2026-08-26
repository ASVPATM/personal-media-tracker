from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from watchtracker.schemas import CatalogData, SearchResult


@dataclass(frozen=True)
class MetadataProviderDefinition:
    slug: str
    result_slugs: tuple[str, ...]
    media_types: tuple[str, ...]
    capabilities: frozenset[str]
    priority: int
    requires_credential: bool = False
    attribution: str | None = None


class MetadataProvider(Protocol):
    definition: MetadataProviderDefinition

    async def search(self, query: str, media_type: str) -> list[SearchResult]: ...

    async def detail(self, provider: str, provider_id: str) -> CatalogData: ...

    async def artwork_options(self, provider: str, provider_id: str) -> list[dict]: ...

    async def series_schedule(
        self, provider: str, provider_id: str, *, refresh: bool = False
    ) -> dict: ...


class MetadataProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MetadataProvider] = {}
        self._result_slugs: dict[str, MetadataProvider] = {}

    def register(self, provider: MetadataProvider) -> None:
        slug = provider.definition.slug
        if slug in self._providers:
            raise ValueError(f"metadata provider already registered: {slug}")
        self._providers[slug] = provider
        for result_slug in provider.definition.result_slugs:
            if result_slug in self._result_slugs:
                raise ValueError(f"metadata result provider already registered: {result_slug}")
            self._result_slugs[result_slug] = provider

    def searchers(self, media_type: str) -> list[MetadataProvider]:
        return sorted(
            (
                provider
                for provider in self._providers.values()
                if media_type in provider.definition.media_types
                and "search" in provider.definition.capabilities
            ),
            key=lambda provider: provider.definition.priority,
        )

    def for_result(self, provider_slug: str) -> MetadataProvider | None:
        return self._result_slugs.get(provider_slug)

    def definitions(self) -> list[MetadataProviderDefinition]:
        return sorted(
            (provider.definition for provider in self._providers.values()),
            key=lambda definition: definition.priority,
        )
