from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from watchtracker.catalog_visibility import PUBLIC_METADATA_PROVIDERS
from watchtracker.metadata.cache import cache_key
from watchtracker.metadata.http import ProviderError
from watchtracker.models import (
    CatalogItem,
    ExternalIdentity,
    RecommendationCandidateSnapshot,
    RecommendationCandidateSnapshotItem,
    RecommendationCatalogCandidate,
    RecommendationFeedback,
    RecommendationResult,
    RecommendationRun,
    RecommendationSignalSnapshot,
    UserRecommendationPreference,
    WatchEntry,
    utcnow,
)
from watchtracker.recommendations.contract import (
    MAX_CANDIDATES,
    EngineCandidate,
    canonical_json_value,
    clamp01,
)
from watchtracker.recommendations.policy import eligible_catalog_item
from watchtracker.schemas import CatalogData
from watchtracker.services.entries import replace_catalog_from_trusted_provider
from watchtracker.taxonomy import INFERENCE_VERSION, infer_taxonomy, normalize_title

CATALOG_SNAPSHOT_TTL = timedelta(hours=24)
LIVE_SOURCE_LIMIT = 60
RECOMMENDATION_TASTE_PROJECTION_VERSION = "taxonomy-to-v4-v1"
PUBLIC_CATALOG_PROVIDERS = PUBLIC_METADATA_PROVIDERS
SOURCE_POLICY = {
    "tvmaze_catalog": {
        "terms": "https://www.tvmaze.com/api#licensing",
        "attribution": "TVmaze",
        "keyless": True,
        "max_pages_per_refresh": 1,
        "max_items_per_refresh": LIVE_SOURCE_LIMIT,
        "cache_hours": 24,
    }
}


class CandidateSource(Protocol):
    slug: str

    async def refresh(self, session: Session, *, limit: int) -> int: ...


class TVMazeCatalogSource:
    """One bounded keyless discovery page using PMT's existing resilient client."""

    slug = "tvmaze_catalog"

    def __init__(self, metadata_service: Any):
        self.client = getattr(metadata_service, "tvmaze", None)

    @property
    def available(self) -> bool:
        return bool(self.client and getattr(self.client, "http", None))

    async def refresh(self, session: Session, *, limit: int = LIVE_SOURCE_LIMIT) -> int:
        if not self.available:
            return 0
        key = cache_key("tvmaze", "recommendation-catalog", {"page": 0, "schema": 1})
        payload = self.client.cache.get(key)
        if payload is None:
            payload = await self.client.http.request_json_value(
                "TVmaze",
                "GET",
                f"{self.client.base_url}/shows",
                params={"page": 0},
                headers=self.client.headers,
            )
            self.client.cache.set(key, payload)
        if not isinstance(payload, list):
            raise ProviderError("TVmaze", "Unexpected discovery response")
        touched = 0
        fetched_at = utcnow()
        for raw in payload[: min(LIVE_SOURCE_LIMIT, max(1, limit))]:
            if not isinstance(raw, dict):
                continue
            try:
                proposed_item: CatalogItem | None = None
                provider_id = raw.get("id")
                title = " ".join(str(raw.get("name") or "").split())[:500]
                if provider_id is None or not title:
                    continue
                provider_id = str(provider_id)[:80]
                if not provider_id:
                    continue
                image = raw.get("image") if isinstance(raw.get("image"), dict) else {}
                poster = image.get("original") or image.get("medium")
                poster = str(poster)[:2_000] if poster else None
                if poster and not poster.startswith("https://"):
                    poster = None
                premiered = str(raw.get("premiered") or "")
                year = int(premiered[:4]) if premiered[:4].isdigit() else None
                if year is not None and not 1878 <= year <= 2200:
                    year = None
                rating = raw.get("rating") if isinstance(raw.get("rating"), dict) else {}
                public_score = rating.get("average")
                if (
                    isinstance(public_score, bool)
                    or not isinstance(public_score, (int, float))
                    or not math.isfinite(float(public_score))
                    or not 0 <= float(public_score) <= 10
                ):
                    public_score = None
                else:
                    public_score = float(public_score)
                network = raw.get("network") or raw.get("webChannel") or {}
                network = network if isinstance(network, dict) else {}
                country_row = network.get("country")
                country_row = country_row if isinstance(country_row, dict) else {}
                country = " ".join(str(country_row.get("code") or "").split())[:100] or None
                genres: list[str] = []
                seen_genres: set[str] = set()
                for value in raw.get("genres") or []:
                    genre = " ".join(str(value).split())[:100]
                    if not genre or genre.casefold() in seen_genres:
                        continue
                    seen_genres.add(genre.casefold())
                    genres.append(genre)
                    if len(genres) >= 30:
                        break
                runtime = raw.get("averageRuntime") or raw.get("runtime")
                if isinstance(runtime, bool) or not isinstance(runtime, (int, float)):
                    runtime = None
                else:
                    runtime = int(runtime)
                    if not 1 <= runtime <= 1_500:
                        runtime = None
                language = " ".join(str(raw.get("language") or "").split())[:30] or None
                provider_format = " ".join(str(raw.get("type") or "series").split())[:50]
                show_url = str(raw.get("url") or "")[:2_000] or None
                if show_url and not show_url.startswith("https://"):
                    show_url = None
                identity = session.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.namespace == "tvmaze",
                        ExternalIdentity.external_id == provider_id,
                    )
                )
                item = session.get(CatalogItem, identity.catalog_item_id) if identity else None
                if item is None:
                    item = session.scalar(
                        select(CatalogItem).where(
                            CatalogItem.provider_source == "tvmaze",
                            CatalogItem.provider_id == provider_id,
                        )
                    )
                values = {
                    "canonical_title": title,
                    "normalized_title": normalize_title(title)[:500],
                    "release_year": year,
                    "media_type": "tv",
                    "provider_format": provider_format,
                    "poster_url": poster,
                    "provider_genres": genres,
                    "normalized_genres": genres,
                    "country": country,
                    "language": language,
                    "runtime_minutes": runtime,
                    "public_score": public_score,
                    "metadata_source": "tvmaze",
                    "metadata_provenance": {
                        "discovery": "tvmaze_show_index",
                        "attribution": "TVmaze",
                        "license_url": SOURCE_POLICY["tvmaze_catalog"]["terms"],
                        "show_url": show_url,
                        "provider_identity_verified": True,
                        "provider_identity_source": "tvmaze",
                    },
                    "metadata_fetched_at": fetched_at,
                }
                if item is None:
                    proposed_item = CatalogItem(
                        provider_source="tvmaze",
                        provider_id=provider_id,
                        overview=None,
                        inferred_subgenres=[],
                        keywords=[],
                        metadata_field_sources={},
                        taste_evidence={},
                        raw_provider_payload=None,
                        **values,
                    )
                    try:
                        with session.begin_nested():
                            session.add(proposed_item)
                            session.flush()
                        item = proposed_item
                    except IntegrityError:
                        # Another worker may have completed the same bounded refresh.
                        # Reuse its canonical row without rolling back the caller's
                        # whole recommendation transaction.
                        identity = session.scalar(
                            select(ExternalIdentity).where(
                                ExternalIdentity.namespace == "tvmaze",
                                ExternalIdentity.external_id == provider_id,
                            )
                        )
                        item = (
                            session.get(CatalogItem, identity.catalog_item_id)
                            if identity
                            else session.scalar(
                                select(CatalogItem).where(
                                    CatalogItem.provider_source == "tvmaze",
                                    CatalogItem.provider_id == provider_id,
                                )
                            )
                        )
                        if item is None:
                            continue
                else:
                    was_verified = bool(
                        (item.metadata_provenance or {}).get("provider_identity_verified")
                    )
                    if not was_verified:
                        retained_external_ids = (
                            {
                                row.namespace: row.external_id
                                for row in session.scalars(
                                    select(ExternalIdentity).where(
                                        ExternalIdentity.catalog_item_id == item.id
                                    )
                                )
                            }
                            if was_verified
                            else {}
                        )
                        replace_catalog_from_trusted_provider(
                            session,
                            item,
                            CatalogData(
                                canonical_title=title,
                                release_year=year,
                                media_type="tv",
                                provider_format=provider_format,
                                provider_source="tvmaze",
                                provider_id=provider_id,
                                tmdb_movie_id=item.tmdb_movie_id if was_verified else None,
                                tmdb_tv_id=item.tmdb_tv_id if was_verified else None,
                                anilist_id=item.anilist_id if was_verified else None,
                                mal_id=item.mal_id if was_verified else None,
                                poster_url=poster,
                                overview=None,
                                provider_genres=genres,
                                keywords=[],
                                country=country,
                                language=language,
                                runtime_minutes=runtime,
                                public_score=public_score,
                                external_ids={
                                    **retained_external_ids,
                                    "tvmaze": provider_id,
                                },
                            ),
                        )
                        item.metadata_provenance = {
                            **(item.metadata_provenance or {}),
                            "discovery": "tvmaze_show_index",
                            "attribution": "TVmaze",
                            "license_url": SOURCE_POLICY["tvmaze_catalog"]["terms"],
                            "show_url": show_url,
                        }
                        identity = session.scalar(
                            select(ExternalIdentity).where(
                                ExternalIdentity.namespace == "tvmaze",
                                ExternalIdentity.external_id == provider_id,
                            )
                        )
                    elif item.provider_source == "tvmaze":
                        # The keyless show index is intentionally shallow. Refresh
                        # only facts it actually supplied; never erase richer
                        # trusted detail already shared by users.
                        item.canonical_title = title
                        item.normalized_title = normalize_title(title)[:500]
                        if item.media_type != "anime":
                            item.media_type = "tv"
                        if raw.get("type"):
                            item.provider_format = provider_format
                        if year is not None:
                            item.release_year = year
                        if poster is not None:
                            item.poster_url = poster
                        if isinstance(raw.get("genres"), list) and genres:
                            item.provider_genres = genres
                            taxonomy = infer_taxonomy(
                                genres,
                                item.keywords or [],
                                media_type="tv",
                            )
                            item.normalized_genres = taxonomy.genres
                            item.inferred_subgenres = taxonomy.subgenres
                            item.taste_evidence = taxonomy.taste_evidence
                            item.inference_version = INFERENCE_VERSION
                        if country is not None:
                            item.country = country
                        if language is not None:
                            item.language = language
                        if runtime is not None:
                            item.runtime_minutes = runtime
                        if public_score is not None:
                            item.public_score = public_score
                        item.metadata_fetched_at = fetched_at
                        item.updated_at = fetched_at
                        item.metadata_provenance = {
                            **(item.metadata_provenance or {}),
                            "discovery": "tvmaze_show_index",
                            "attribution": "TVmaze",
                            "license_url": SOURCE_POLICY["tvmaze_catalog"]["terms"],
                            "show_url": show_url,
                            "provider_identity_verified": True,
                            "provider_identity_source": "tvmaze",
                        }
                if identity is None:
                    proposed_identity = ExternalIdentity(
                        catalog_item_id=item.id,
                        namespace="tvmaze",
                        external_id=provider_id,
                        provenance="recommendation_catalog",
                        confidence=1.0,
                        verified_at=fetched_at,
                    )
                    try:
                        with session.begin_nested():
                            session.add(proposed_identity)
                            session.flush()
                    except IntegrityError:
                        existing_identity = session.scalar(
                            select(ExternalIdentity).where(
                                ExternalIdentity.namespace == "tvmaze",
                                ExternalIdentity.external_id == provider_id,
                            )
                        )
                        if existing_identity is None:
                            continue
                        canonical = session.get(CatalogItem, existing_identity.catalog_item_id)
                        if canonical is None:
                            continue
                        if proposed_item is not None and proposed_item.id != canonical.id:
                            # The catalog insert can win while the identity insert
                            # loses to another worker that coalesced this TVmaze ID
                            # under a different provider. The proposed row is still
                            # private to this transaction and has no dependents, so
                            # remove it instead of retaining a duplicate global item.
                            session.delete(proposed_item)
                            session.flush()
                        item = canonical
                touched += 1
            except (TypeError, ValueError, OverflowError):
                # One malformed public row cannot fail the user's whole run.
                continue
        session.flush()
        return touched


def _metadata_quality(item: CatalogItem) -> float:
    facts = (
        bool(item.poster_url),
        bool(item.overview),
        bool(item.normalized_genres or item.provider_genres),
        bool(item.release_year),
        bool(item.language or item.country),
    )
    return sum(facts) / len(facts)


def _scoring_payload(
    item: CatalogItem, candidate: RecommendationCatalogCandidate
) -> dict[str, Any]:
    taste: dict[str, float] = {}
    allowed_taste = {
        "engagement_pacing",
        "distinctiveness_freshness",
        "emotional_intellectual_intensity",
        "consistency_tolerance",
        "personal_significance",
        "return_desire",
        "commitment_fit",
    }
    if (item.metadata_provenance or {}).get("recommendation_taste_contract") == (
        "v4-candidate-taste-v1"
    ):
        for key, raw in (item.taste_evidence or {}).items():
            if (
                key not in allowed_taste
                or not isinstance(raw, (int, float))
                or isinstance(raw, bool)
            ):
                continue
            value = float(raw)
            taste[key] = clamp01((value - 1) / 4 if value > 1 else value)
    elif item.inference_version == INFERENCE_VERSION:
        # Normal PMT metadata stores evidence-bearing taxonomy values, not numeric
        # recommendation features. Only project dimensions whose meaning matches a
        # v4 question directly; never invent title consistency, significance, or
        # return desire from genre labels. This versioned mapping is frozen into the
        # candidate snapshot and can evolve without reinterpreting old results.
        intensity_values: list[float] = []
        mappings = {
            "darkness_tone": {"dark": 0.80, "light": 0.25},
            "narrative_complexity": {"complex": 0.75},
            "emotional_register": {
                "tense": 0.80,
                "melancholic": 0.65,
                "uplifting": 0.45,
                "comforting": 0.25,
            },
        }
        raw_evidence = item.taste_evidence or {}
        if isinstance(raw_evidence, dict):
            for source_dimension, value_map in mappings.items():
                rows = raw_evidence.get(source_dimension)
                if not isinstance(rows, list):
                    continue
                for row in rows[:20]:
                    if not isinstance(row, dict) or not isinstance(row.get("evidence"), str):
                        continue
                    projected = value_map.get(str(row.get("value") or ""))
                    if projected is not None:
                        intensity_values.append(projected)
        if intensity_values:
            taste["emotional_intellectual_intensity"] = clamp01(
                sum(intensity_values) / len(intensity_values)
            )
    return EngineCandidate(
        catalog_id=item.id,
        title=item.canonical_title,
        media_type=item.media_type,
        genres=[
            str(value).casefold()
            for value in (item.normalized_genres or item.provider_genres or [])
        ],
        subgenres=[str(value).casefold() for value in (item.inferred_subgenres or [])],
        keywords=[str(value).casefold() for value in (item.keywords or [])],
        language=item.language.casefold() if item.language else None,
        country=item.country.casefold() if item.country else None,
        provider_format=item.provider_format.casefold() if item.provider_format else None,
        public_score=item.public_score,
        source_score=candidate.source_score,
        taste_evidence=taste,
    ).model_dump(mode="json")


def _candidate_rows(
    session: Session,
    *,
    user_id: str,
    preferences: UserRecommendationPreference,
) -> list[RecommendationCatalogCandidate]:
    owned = select(WatchEntry.catalog_item_id).where(WatchEntry.user_id == user_id)
    rejected = (
        select(RecommendationResult.catalog_item_id)
        .join(RecommendationRun, RecommendationRun.id == RecommendationResult.run_id)
        .join(
            RecommendationFeedback,
            RecommendationFeedback.result_id == RecommendationResult.id,
        )
        .where(
            RecommendationRun.user_id == user_id,
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.feedback.in_(("not_interested", "already_seen")),
        )
    )
    catalog = list(
        session.scalars(
            select(CatalogItem)
            .where(
                CatalogItem.id.not_in(owned),
                CatalogItem.id.not_in(rejected),
                CatalogItem.provider_source.in_(PUBLIC_CATALOG_PROVIDERS),
                CatalogItem.provider_id.is_not(None),
                CatalogItem.metadata_provenance["provider_identity_verified"]
                .as_boolean()
                .is_(True),
            )
            .order_by(CatalogItem.normalized_title, CatalogItem.id)
            .limit(MAX_CANDIDATES * 2)
        )
    )
    identity_rows = list(
        session.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.catalog_item_id.in_([item.id for item in catalog])
            )
        )
    )
    identity_keys: dict[str, set[tuple[str, str]]] = {}
    for identity in identity_rows:
        identity_keys.setdefault(identity.catalog_item_id, set()).add(
            (identity.namespace, identity.external_id)
        )
    for item in catalog:
        if item.provider_source and item.provider_id:
            identity_keys.setdefault(item.id, set()).add(
                (item.provider_source, item.provider_id)
            )
    catalog.sort(
        key=lambda item: (
            -_metadata_quality(item),
            item.normalized_title,
            item.id,
        )
    )
    excluded_types = set(preferences.excluded_media_types or [])
    excluded_genres = {str(value).casefold() for value in (preferences.excluded_genres or [])}
    now = utcnow()
    candidates: list[RecommendationCatalogCandidate] = []
    seen_identities: set[tuple[str, str]] = set()
    for item in catalog:
        if not eligible_catalog_item(
            item,
            excluded_media_types=excluded_types,
            excluded_genres=excluded_genres,
        ):
            continue
        keys = identity_keys.get(item.id, set())
        if keys & seen_identities:
            continue
        seen_identities.update(keys)
        candidate = session.scalar(
            select(RecommendationCatalogCandidate).where(
                RecommendationCatalogCandidate.catalog_item_id == item.id
            )
        )
        source = item.provider_source
        # This describes discovery-source trust only. Public rating is scored
        # separately, so it must not be counted twice here.
        source_score = 0.55 if source == "tvmaze" else 0.5
        fetched_at = item.metadata_fetched_at or item.updated_at or item.created_at or now
        expires_at = fetched_at + CATALOG_SNAPSHOT_TTL
        if candidate is None:
            candidate = RecommendationCatalogCandidate(
                catalog_item_id=item.id,
                source=source,
                reason_code="eligible_catalog_item",
                source_score=source_score,
                language=item.language,
                provenance={
                    "provider_source": item.provider_source,
                    "provider_id": item.provider_id,
                },
                fetched_at=fetched_at,
                expires_at=expires_at,
            )
            session.add(candidate)
            session.flush()
        else:
            candidate.source = source
            candidate.reason_code = "eligible_catalog_item"
            candidate.source_score = source_score
            candidate.language = item.language
            candidate.provenance = {
                "provider_source": item.provider_source,
                "provider_id": item.provider_id,
                "attribution": (item.metadata_provenance or {}).get("attribution"),
                "license_url": (item.metadata_provenance or {}).get("license_url"),
            }
            candidate.fetched_at = fetched_at
            candidate.expires_at = expires_at
        candidates.append(candidate)
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates


def count_unseen_candidates(
    session: Session, *, user_id: str, preferences: UserRecommendationPreference
) -> int:
    owned = set(
        session.scalars(select(WatchEntry.catalog_item_id).where(WatchEntry.user_id == user_id))
    )
    rejected = set(
        session.scalars(
            select(RecommendationResult.catalog_item_id)
            .join(RecommendationRun, RecommendationRun.id == RecommendationResult.run_id)
            .join(
                RecommendationFeedback,
                RecommendationFeedback.result_id == RecommendationResult.id,
            )
            .where(
                RecommendationRun.user_id == user_id,
                RecommendationFeedback.user_id == user_id,
                RecommendationFeedback.feedback.in_(("not_interested", "already_seen")),
            )
        )
    )
    excluded_types = set(preferences.excluded_media_types or [])
    excluded_genres = {str(value).casefold() for value in (preferences.excluded_genres or [])}
    return sum(
        item.id not in owned
        and item.id not in rejected
        and eligible_catalog_item(
            item,
            excluded_media_types=excluded_types,
            excluded_genres=excluded_genres,
        )
        for item in session.scalars(
            select(CatalogItem)
            .where(
                CatalogItem.provider_source.in_(PUBLIC_CATALOG_PROVIDERS),
                CatalogItem.provider_id.is_not(None),
                CatalogItem.metadata_provenance["provider_identity_verified"]
                .as_boolean()
                .is_(True),
            )
            .order_by(CatalogItem.id)
            .limit(MAX_CANDIDATES * 2)
        )
    )


def count_owned_unverified_provider_items(session: Session, *, user_id: str) -> int:
    """Count historical provider rows that need a trusted metadata refresh.

    Older PMT databases predate the trusted-provider provenance marker. They are
    intentionally not promoted by migration because legacy/manual payloads could
    claim a provider ID. A normal metadata refresh writes the marker safely.
    """

    return len(
        list(
            session.scalars(
                select(CatalogItem.id)
                .join(WatchEntry, WatchEntry.catalog_item_id == CatalogItem.id)
                .where(
                    WatchEntry.user_id == user_id,
                    CatalogItem.provider_source.in_(PUBLIC_CATALOG_PROVIDERS),
                    CatalogItem.provider_id.is_not(None),
                    CatalogItem.metadata_provenance["provider_identity_verified"]
                    .as_boolean()
                    .is_not(True),
                )
                .distinct()
                .limit(MAX_CANDIDATES)
            )
        )
    )


async def candidate_snapshot(
    session: Session,
    *,
    user_id: str,
    preferences: UserRecommendationPreference,
    signals: RecommendationSignalSnapshot,
    live_source: CandidateSource | None = None,
    minimum_candidates: int = 24,
) -> RecommendationCandidateSnapshot:
    candidates = _candidate_rows(session, user_id=user_id, preferences=preferences)
    warning_codes: list[str] = []
    fallback = False
    now = datetime.now(UTC)
    stale_before_refresh = any(
        candidate.expires_at is None
        or (
            candidate.expires_at.replace(tzinfo=UTC)
            if candidate.expires_at.tzinfo is None
            else candidate.expires_at.astimezone(UTC)
        )
        <= now
        for candidate in candidates
    )
    if (
        (len(candidates) < minimum_candidates or stale_before_refresh)
        and preferences.use_live_discovery
        and live_source is not None
    ):
        try:
            await live_source.refresh(session, limit=LIVE_SOURCE_LIMIT)
            session.flush()
            candidates = _candidate_rows(session, user_id=user_id, preferences=preferences)
        except ProviderError:
            fallback = True
            warning_codes.append("provider_unavailable")
    stale_after_refresh = any(
        candidate.expires_at is None
        or (
            candidate.expires_at.replace(tzinfo=UTC)
            if candidate.expires_at.tzinfo is None
            else candidate.expires_at.astimezone(UTC)
        )
        <= now
        for candidate in candidates
    )
    if stale_after_refresh:
        warning_codes.append("stale_candidates")
    material = canonical_json_value(
        {
            "preference_revision": preferences.version,
            "signal_hash": signals.source_hash,
            "candidates": [
                {
                    "id": item.id,
                    "catalog": item.catalog_item_id,
                    "source": item.source,
                    "score": item.source_score,
                    "fetched_at": item.fetched_at.isoformat(),
                    "scoring": _scoring_payload(item.catalog_item, item),
                }
                for item in candidates
            ],
            "fallback": fallback,
            "warnings": warning_codes,
        }
    )
    source_hash = hashlib.sha256(
        json.dumps(material, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    reusable = session.scalar(
        select(RecommendationCandidateSnapshot)
        .where(
            RecommendationCandidateSnapshot.user_id == user_id,
            RecommendationCandidateSnapshot.source_hash == source_hash,
            RecommendationCandidateSnapshot.expires_at > now,
        )
        .order_by(RecommendationCandidateSnapshot.created_at.desc())
        .options(
            selectinload(RecommendationCandidateSnapshot.items).selectinload(
                RecommendationCandidateSnapshotItem.candidate
            )
        )
    )
    if reusable is not None and not fallback:
        return reusable
    coverage = {
        "total": len(candidates),
        "with_identity": sum(
            bool(row.catalog_item.provider_source and row.catalog_item.provider_id)
            for row in candidates
        ),
        "with_artwork": sum(bool(row.catalog_item.poster_url) for row in candidates),
        "with_genres": sum(
            bool(row.catalog_item.normalized_genres or row.catalog_item.provider_genres)
            for row in candidates
        ),
        "stale": sum(
            row.expires_at is None
            or (
                row.expires_at.replace(tzinfo=UTC)
                if row.expires_at.tzinfo is None
                else row.expires_at.astimezone(UTC)
            )
            <= now
            for row in candidates
        ),
        "provider_freshness": max(
            (
                row.fetched_at.replace(tzinfo=UTC)
                if row.fetched_at.tzinfo is None
                else row.fetched_at.astimezone(UTC)
                for row in candidates
            ),
            default=now,
        ).isoformat()
        if candidates
        else None,
    }
    snapshot = RecommendationCandidateSnapshot(
        user_id=user_id,
        preference_revision=preferences.version,
        signal_snapshot_id=signals.id,
        source_hash=source_hash,
        coverage=coverage,
        fallback_used=fallback,
        warning_codes=warning_codes,
        expires_at=now + CATALOG_SNAPSHOT_TTL,
    )
    session.add(snapshot)
    session.flush()
    for position, candidate in enumerate(candidates, start=1):
        item = candidate.catalog_item
        snapshot.items.append(
            RecommendationCandidateSnapshotItem(
                candidate_id=candidate.id,
                position=position,
                identity_quality=1.0 if item.provider_source and item.provider_id else 0.55,
                metadata_quality=_metadata_quality(item),
                artwork_available=bool(item.poster_url),
                eligibility={
                    "media_type": item.media_type,
                    "excluded_at_snapshot": False,
                },
                scoring_payload=_scoring_payload(item, candidate),
                provenance_snapshot={
                    "provider_source": item.provider_source,
                    "provider_id": item.provider_id,
                    "canonical_title": item.canonical_title,
                    "release_year": item.release_year,
                    "source": candidate.source,
                    "fetched_at": candidate.fetched_at.isoformat()
                    if candidate.fetched_at
                    else None,
                    "taste_projection_version": RECOMMENDATION_TASTE_PROJECTION_VERSION,
                },
            )
        )
    session.flush()
    return snapshot
