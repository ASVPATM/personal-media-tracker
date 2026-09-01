from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from watchtracker.models import (
    RatingComparison,
    RecommendationPreferenceClaim,
    RecommendationSignalSnapshot,
    UserRecommendationPreference,
    WatchEntry,
)
from watchtracker.recommendations.contract import (
    MAX_EVIDENCE_ANCHORS,
    MAX_SIGNALS,
    SIGNAL_CONTRACT_VERSION,
    EvidenceAnchor,
    PreferenceSignal,
    canonical_json_value,
)


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.timestamp()


def _polarity(value: float) -> str:
    if value >= 0.58:
        return "positive"
    if value <= 0.42:
        return "negative"
    return "neutral"


def _catalog_map(entries: list[WatchEntry]) -> dict[str, str]:
    return {entry.id: entry.catalog_item_id for entry in entries}


def _bounded_values(values: list[Any] | None, *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = " ".join(str(raw).split()).casefold()[:100]
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _evidence_anchor(entry: WatchEntry) -> EvidenceAnchor:
    item = entry.catalog_item
    return EvidenceAnchor(
        catalog_id=item.id,
        media_type=item.media_type,
        genres=_bounded_values(item.normalized_genres or item.provider_genres, limit=30),
        subgenres=_bounded_values(item.inferred_subgenres, limit=30),
        keywords=_bounded_values(item.keywords, limit=50),
        language=(item.language or "").casefold()[:30] or None,
        country=(item.country or "").casefold()[:100] or None,
        provider_format=(item.provider_format or "").casefold()[:50] or None,
    )


def project_signals(
    session: Session,
    *,
    user_id: str,
    preferences: UserRecommendationPreference,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int], int, str]:
    """Project only explicit/confirmed evidence into a bounded immutable contract."""

    entries = list(
        session.scalars(
            select(WatchEntry)
            .where(WatchEntry.user_id == user_id, WatchEntry.deleted_at.is_(None))
            .options(
                selectinload(WatchEntry.catalog_item),
                selectinload(WatchEntry.rating_assessments),
            )
            .order_by(WatchEntry.id)
        )
    )
    comparisons = list(
        session.scalars(
            select(RatingComparison)
            .where(RatingComparison.user_id == user_id)
            .order_by(RatingComparison.updated_at, RatingComparison.id)
        )
    )
    claims = list(
        session.scalars(
            select(RecommendationPreferenceClaim)
            .where(
                RecommendationPreferenceClaim.user_id == user_id,
                RecommendationPreferenceClaim.revoked_at.is_(None),
            )
            .order_by(
                RecommendationPreferenceClaim.confirmed_at, RecommendationPreferenceClaim.id
            )
        )
    )
    latest = max(
        [
            *(_timestamp(entry.updated_at) for entry in entries),
            *(_timestamp(entry.catalog_item.updated_at) for entry in entries),
            *(
                _timestamp(assessment.updated_at or assessment.completed_at)
                for entry in entries
                for assessment in entry.rating_assessments
                if assessment.state == "completed"
                and assessment.rubric_version == "guided-rubric-v4"
            ),
            *(_timestamp(item.updated_at) for item in comparisons),
            *(_timestamp(item.confirmed_at) for item in claims),
            _timestamp(preferences.updated_at),
        ],
        default=1.0,
    )
    revision = max(1, int(latest * 1_000_000))
    entries.sort(
        key=lambda entry: (
            -int(bool(entry.is_favorite)),
            -abs(
                ((float(entry.personal_rating) - 1) / 9) - 0.5
                if entry.personal_rating is not None
                else 0
            ),
            -int(
                any(
                    assessment.state == "completed"
                    and assessment.rubric_version == "guided-rubric-v4"
                    for assessment in entry.rating_assessments
                )
            ),
            -_timestamp(entry.updated_at),
            entry.id,
        )
    )
    signals: list[PreferenceSignal] = []

    for entry in entries:
        if preferences.use_ratings and entry.personal_rating is not None:
            value = min(1.0, max(0.0, (float(entry.personal_rating) - 1.0) / 9.0))
            polarity = _polarity(value)
            if polarity != "neutral":
                signals.append(
                    PreferenceSignal(
                        dimension="item_preference",
                        value=value,
                        strength=max(0.12, abs(value - 0.5) * 2),
                        confidence=0.9,
                        polarity=polarity,
                        source="personal_rating",
                        source_catalog_ids=[entry.catalog_item_id],
                        user_confirmed=True,
                        source_revision=revision,
                    )
                )
        if preferences.use_favorites and entry.is_favorite:
            signals.append(
                PreferenceSignal(
                    dimension="favorite_item",
                    value=1.0,
                    strength=0.85,
                    confidence=0.95,
                    polarity="positive",
                    source="favorite",
                    source_catalog_ids=[entry.catalog_item_id],
                    user_confirmed=True,
                    source_revision=revision,
                )
            )
        rewatch_count = max(0, int(entry.view_count or 0) - 1)
        if preferences.use_rewatches and rewatch_count:
            value = min(1.0, 0.55 + 0.09 * min(rewatch_count, 5))
            signals.append(
                PreferenceSignal(
                    dimension="rewatch_item",
                    value=value,
                    strength=min(0.65, 0.3 + 0.07 * min(rewatch_count, 5)),
                    confidence=0.78,
                    polarity="positive",
                    source="rewatch",
                    source_catalog_ids=[entry.catalog_item_id],
                    user_confirmed=True,
                    source_revision=revision,
                )
            )
        if not preferences.use_refinement:
            continue
        completed = [
            assessment
            for assessment in entry.rating_assessments
            if assessment.state == "completed"
            and assessment.rubric_version in {"guided-rubric-v3", "guided-rubric-v4"}
        ]
        if not completed:
            continue
        assessment = max(completed, key=lambda item: (_timestamp(item.completed_at), item.id))
        if assessment.rubric_version != "guided-rubric-v4":
            # Historical v3 remains portable and understandable, but the direct
            # recommendation projection begins at v4 to avoid changing old meaning.
            continue
        for dimension, raw in sorted((assessment.answers or {}).items()):
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                continue
            value = min(1.0, max(0.0, (float(raw) - 1.0) / 4.0))
            signals.append(
                PreferenceSignal(
                    dimension=f"refinement_{dimension}"[:80],
                    value=value,
                    strength=0.62,
                    confidence=min(0.95, 0.55 + 0.4 * float(assessment.rubric_coverage or 0)),
                    polarity=_polarity(value),
                    source="completed_refinement",
                    source_catalog_ids=[entry.catalog_item_id],
                    user_confirmed=True,
                    source_revision=revision,
                )
            )

    entry_catalog = _catalog_map(entries)
    if preferences.use_refinement:
        for comparison in comparisons:
            if comparison.result in {"skip", "tie"}:
                continue
            preferred_entry = (
                comparison.entry_low_id
                if comparison.result == "low"
                else comparison.entry_high_id
            )
            other_entry = (
                comparison.entry_high_id
                if comparison.result == "low"
                else comparison.entry_low_id
            )
            preferred = entry_catalog.get(preferred_entry)
            other = entry_catalog.get(other_entry)
            if not preferred or not other:
                continue
            signals.append(
                PreferenceSignal(
                    dimension="pairwise_preference",
                    value=0.75,
                    strength=0.45,
                    confidence=0.7,
                    polarity="positive",
                    source="pairwise_comparison",
                    source_catalog_ids=[preferred, other],
                    user_confirmed=True,
                    source_revision=revision,
                )
            )

    owned_catalog_ids = {entry.catalog_item_id for entry in entries}
    for claim in claims:
        raw_value = claim.value.get("value") if isinstance(claim.value, dict) else None
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            continue
        value = min(1.0, max(0.0, float(raw_value)))
        provenance_ids = [
            str(value)
            for value in (claim.provenance.get("source_catalog_ids") or [])
            if str(value) in owned_catalog_ids
        ][:20]
        signals.append(
            PreferenceSignal(
                dimension=claim.dimension,
                value=value,
                strength=min(1.0, max(0.0, float(claim.value.get("strength", 0.5)))),
                confidence=min(1.0, max(0.0, float(claim.confidence))),
                polarity=_polarity(value),
                source="confirmed_claim",
                source_catalog_ids=provenance_ids,
                user_confirmed=True,
                source_revision=revision,
                model_id=claim.model_id,
            )
        )

    signal_priority = {
        "favorite": 0,
        "personal_rating": 1,
        "rewatch": 2,
        "confirmed_claim": 3,
        "completed_refinement": 4,
        "pairwise_comparison": 5,
    }
    signals.sort(key=lambda signal: signal_priority[signal.source])
    # Keep both contracts bounded together: no retained signal may reference an
    # anchor omitted from the immutable snapshot.
    bounded_signals: list[PreferenceSignal] = []
    referenced_ids: set[str] = set()
    for signal in signals:
        candidate_ids = set(signal.source_catalog_ids)
        if len(referenced_ids | candidate_ids) > MAX_EVIDENCE_ANCHORS:
            continue
        bounded_signals.append(signal)
        referenced_ids.update(candidate_ids)
        if len(bounded_signals) >= MAX_SIGNALS:
            break
    signals = bounded_signals
    entries_by_catalog = {entry.catalog_item_id: entry for entry in entries}
    anchors = [
        _evidence_anchor(entries_by_catalog[catalog_id])
        for catalog_id in sorted(referenced_ids)
        if catalog_id in entries_by_catalog
    ]
    payload = [signal.model_dump(mode="json") for signal in signals]
    anchor_payload = [anchor.model_dump(mode="json") for anchor in anchors]
    counts = {
        "library_titles": len(entries),
        "useful_ratings": sum(
            signal.source == "personal_rating" and signal.polarity != "neutral"
            for signal in signals
        ),
        "favorites": sum(signal.source == "favorite" for signal in signals),
        "rewatches": sum(signal.source == "rewatch" for signal in signals),
        "completed_refinements": len(
            {
                signal.source_catalog_ids[0]
                for signal in signals
                if signal.source == "completed_refinement" and signal.source_catalog_ids
            }
        ),
        "confirmed_signals": len(signals),
    }
    hash_material = canonical_json_value(
        {
            "contract": SIGNAL_CONTRACT_VERSION,
            "preferences_version": preferences.version,
            "signals": payload,
            "evidence_anchors": anchor_payload,
        }
    )
    source_hash = hashlib.sha256(
        json.dumps(hash_material, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return payload, anchor_payload, counts, revision, source_hash


def signal_snapshot(
    session: Session,
    *,
    user_id: str,
    preferences: UserRecommendationPreference,
) -> RecommendationSignalSnapshot:
    signals, evidence_anchors, counts, revision, source_hash = project_signals(
        session, user_id=user_id, preferences=preferences
    )
    existing = session.scalar(
        select(RecommendationSignalSnapshot).where(
            RecommendationSignalSnapshot.user_id == user_id,
            RecommendationSignalSnapshot.source_hash == source_hash,
        )
    )
    if existing is not None:
        return existing
    row = RecommendationSignalSnapshot(
        user_id=user_id,
        source_revision=revision,
        source_hash=source_hash,
        signal_contract_version=SIGNAL_CONTRACT_VERSION,
        evidence_counts=counts,
        signals=signals,
        evidence_anchors=evidence_anchors,
        evidence_sufficient=counts["useful_ratings"] >= 3 or counts["confirmed_signals"] >= 5,
    )
    session.add(row)
    session.flush()
    return row
