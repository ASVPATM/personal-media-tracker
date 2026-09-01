from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from watchtracker.recommendations.contract import (
    ENGINE_CONTRACT_VERSION,
    SCORE_SCALE_VERSION,
    STANDARD_ENGINE_VERSION,
    STANDARD_WEIGHT_VERSION,
    EngineCandidate,
    EngineRequest,
    EngineResponse,
    EngineResultItem,
    EvidenceAnchor,
    PreferenceSignal,
    clamp01,
)

WEIGHT_VERSION = STANDARD_WEIGHT_VERSION
FEATURE_WEIGHTS = {
    "genre_affinity": 3.0,
    "subgenre_affinity": 1.4,
    "keyword_affinity": 1.0,
    "language_affinity": 0.6,
    "country_affinity": 0.5,
    "format_affinity": 0.7,
    "media_type_affinity": 0.7,
    "confirmed_refinement_fit": 1.2,
    "public_quality": 0.8,
    "discovery_quality": 0.3,
}


@dataclass(frozen=True)
class AffinityValue:
    value: float
    support: float
    anchors: tuple[str, ...]


def _values(values: list[str] | None) -> list[str]:
    return [str(value).casefold() for value in (values or []) if str(value).strip()]


def engine_candidates(rows: list[Any]) -> list[EngineCandidate]:
    return [EngineCandidate.model_validate(row.scoring_payload) for row in rows]


def _profile(
    evidence_anchors: list[EvidenceAnchor], signals: list[PreferenceSignal]
) -> tuple[dict[str, dict[str, AffinityValue]], dict[str, float], int]:
    items = {item.catalog_id: item for item in evidence_anchors}
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    anchors: dict[str, dict[str, list[tuple[float, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    refinement_sums: dict[str, float] = defaultdict(float)
    refinement_weights: dict[str, float] = defaultdict(float)
    refinement_anchor_weights: dict[str, float] = defaultdict(float)
    refinement_anchor_counts: dict[str, int] = defaultdict(int)
    item_preference_sums: dict[str, float] = defaultdict(float)
    item_preference_weights: dict[str, float] = defaultdict(float)
    evidence = 0
    for signal in signals:
        weight = signal.strength * signal.confidence
        if signal.source in {
            "personal_rating",
            "favorite",
            "rewatch",
            "pairwise_comparison",
        }:
            if not signal.source_catalog_ids:
                continue
            item = items.get(signal.source_catalog_ids[0])
            if item is None:
                continue
            evidence += 1
            item_preference_sums[item.catalog_id] += signal.value * weight
            item_preference_weights[item.catalog_id] += weight
            features = {
                "genre_affinity": _values(item.genres),
                "subgenre_affinity": _values(item.subgenres),
                "keyword_affinity": _values(item.keywords),
                "language_affinity": [item.language.casefold()] if item.language else [],
                "country_affinity": [item.country.casefold()] if item.country else [],
                "format_affinity": [item.provider_format.casefold()]
                if item.provider_format
                else [],
                "media_type_affinity": [item.media_type],
            }
            for dimension, values in features.items():
                for value in values:
                    sums[dimension][value] += signal.value * weight
                    weights[dimension][value] += weight
                    anchors[dimension][value].append((weight, item.catalog_id))
        elif signal.source in {"completed_refinement", "confirmed_claim"}:
            refinement_sums[signal.dimension] += signal.value * weight
            refinement_weights[signal.dimension] += weight
            if signal.source == "completed_refinement" and signal.source_catalog_ids:
                catalog_id = signal.source_catalog_ids[0]
                refinement_anchor_weights[catalog_id] += weight
                refinement_anchor_counts[catalog_id] += 1
            elif signal.source == "confirmed_claim":
                evidence += 1
    # Completion can add bounded support to an explicit title preference, but raw
    # dimension magnitude is never treated as like/dislike. A low "intensity"
    # answer must not turn a 10/10 favourite into negative genre evidence.
    for catalog_id, support in refinement_anchor_weights.items():
        item = items.get(catalog_id)
        preference_support = item_preference_weights[catalog_id]
        if item is None or support <= 0 or preference_support <= 0:
            continue
        value = item_preference_sums[catalog_id] / preference_support
        weight = min(0.45, support / max(1, refinement_anchor_counts[catalog_id]))
        evidence += 1
        features = {
            "genre_affinity": _values(item.genres),
            "subgenre_affinity": _values(item.subgenres),
            "keyword_affinity": _values(item.keywords),
            "language_affinity": [item.language.casefold()] if item.language else [],
            "country_affinity": [item.country.casefold()] if item.country else [],
            "format_affinity": [item.provider_format.casefold()]
            if item.provider_format
            else [],
            "media_type_affinity": [item.media_type],
        }
        for dimension, feature_values in features.items():
            for feature_value in feature_values:
                sums[dimension][feature_value] += value * weight
                weights[dimension][feature_value] += weight
                anchors[dimension][feature_value].append((weight, catalog_id))
    profile: dict[str, dict[str, AffinityValue]] = {}
    for dimension, by_value in sums.items():
        profile[dimension] = {}
        for value, total in by_value.items():
            support = weights[dimension][value]
            # Bayesian shrinkage prevents one extreme rating from becoming certainty.
            affinity = (total + 0.5 * 1.5) / (support + 1.5)
            ordered = sorted(anchors[dimension][value], key=lambda pair: (-pair[0], pair[1]))
            profile[dimension][value] = AffinityValue(
                value=clamp01(affinity),
                support=support,
                anchors=tuple(item_id for _, item_id in ordered[:3]),
            )
    refinement = {
        dimension: refinement_sums[dimension] / support
        for dimension, support in refinement_weights.items()
        if support > 0
    }
    return profile, refinement, evidence


def _feature_score(
    profile: dict[str, dict[str, AffinityValue]], dimension: str, values: list[str]
) -> tuple[float, float, tuple[str, ...]] | None:
    matches = [profile.get(dimension, {}).get(value) for value in values]
    matches = [match for match in matches if match is not None]
    if not matches:
        return None
    best = max(matches, key=lambda item: (item.value, item.support, item.anchors))
    return best.value, best.support, best.anchors


def _conservative_public_quality(public_score: float) -> float:
    """Shrink an unsupported provider rating toward a neutral-positive prior."""

    prior_mean = 0.6
    prior_strength = 4.0
    observed_strength = 1.0
    normalized = clamp01(public_score / 10)
    return (prior_mean * prior_strength + normalized * observed_strength) / (
        prior_strength + observed_strength
    )


def _score(
    candidate: EngineCandidate,
    profile: dict[str, dict[str, AffinityValue]],
    refinement: dict[str, float],
    evidence_count: int,
) -> tuple[float, float, dict[str, float], list[str], list[str], list[str]]:
    available: list[tuple[str, float, float]] = []
    anchors: list[str] = []
    support_total = 0.0
    feature_values = {
        "genre_affinity": candidate.genres,
        "subgenre_affinity": candidate.subgenres,
        "keyword_affinity": candidate.keywords,
        "language_affinity": [candidate.language] if candidate.language else [],
        "country_affinity": [candidate.country] if candidate.country else [],
        "format_affinity": [candidate.provider_format] if candidate.provider_format else [],
        "media_type_affinity": [candidate.media_type],
    }
    for dimension, values in feature_values.items():
        match = _feature_score(profile, dimension, values)
        if match is None:
            continue
        score, support, matched_anchors = match
        available.append((dimension, score, FEATURE_WEIGHTS[dimension]))
        support_total += min(2.0, support)
        anchors.extend(matched_anchors)
    taste = candidate.taste_evidence or {}
    refinement_matches = []
    for dimension, preferred in refinement.items():
        key = dimension.removeprefix("refinement_")
        raw = taste.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            candidate_value = float(raw)
            if candidate_value > 1:
                candidate_value = (candidate_value - 1) / 4
            refinement_matches.append(1 - abs(clamp01(preferred) - clamp01(candidate_value)))
    if refinement_matches:
        available.append(
            (
                "confirmed_refinement_fit",
                sum(refinement_matches) / len(refinement_matches),
                FEATURE_WEIGHTS["confirmed_refinement_fit"],
            )
        )
        support_total += len(refinement_matches) * 0.5
    if candidate.public_score is not None:
        available.append(
            (
                "public_quality",
                _conservative_public_quality(candidate.public_score),
                FEATURE_WEIGHTS["public_quality"],
            )
        )
    available.append(
        ("discovery_quality", candidate.source_score, FEATURE_WEIGHTS["discovery_quality"])
    )
    denominator = sum(weight for _, _, weight in available)
    match = sum(value * weight for _, value, weight in available) / denominator
    personalized_features = [
        row for row in available if row[0] not in {"public_quality", "discovery_quality"}
    ]
    meaningful_features = [
        row
        for row in personalized_features
        if row[0]
        in {
            "genre_affinity",
            "subgenre_affinity",
            "keyword_affinity",
            "confirmed_refinement_fit",
        }
    ]
    if meaningful_features:
        confidence = clamp01(
            0.16
            + min(0.22, evidence_count * 0.025)
            + min(0.30, len(meaningful_features) * 0.075)
            + min(0.22, support_total * 0.018)
        )
    else:
        # Public quality and broad format/language overlap are useful discovery
        # context, but they are not evidence for a strong personal-match claim.
        confidence = clamp01(0.14 + min(0.10, len(personalized_features) * 0.025))
    contributions = {code: clamp01(value) for code, value, _ in available}
    reasons = [
        code
        for code, value, _weight in sorted(
            available,
            key=lambda row: (-(row[1] * row[2]), row[0]),
        )
        if value >= 0.5
    ][:4]
    if not reasons:
        reasons = ["discovery_quality"]
    risks = []
    if evidence_count < 3:
        risks.append("limited_feedback")
    if not candidate.genres and not candidate.keywords:
        risks.append("sparse_metadata")
    if not meaningful_features:
        risks.append("discovery_only")
    return match, confidence, contributions, reasons, sorted(set(anchors))[:5], risks


def score_candidates(*, request: EngineRequest) -> EngineResponse:
    profile, refinement, evidence_count = _profile(request.evidence_anchors, request.signals)
    scored: list[tuple[EngineCandidate, tuple[Any, ...]]] = []
    for candidate in request.candidates:
        scored.append(
            (
                candidate,
                _score(candidate, profile, refinement, evidence_count),
            )
        )
    scored.sort(key=lambda row: (-row[1][0], -row[1][1], row[0].catalog_id))
    results = []
    for rank, (candidate, values) in enumerate(scored[: request.limit], start=1):
        match, confidence, contributions, reasons, anchors, risks = values
        results.append(
            EngineResultItem(
                catalog_id=candidate.catalog_id,
                rank=rank,
                match=match,
                confidence=confidence,
                contributions=contributions,
                reason_codes=reasons,
                anchor_catalog_ids=anchors,
                risk_codes=risks,
            )
        )
    return EngineResponse(
        contract_version=ENGINE_CONTRACT_VERSION,
        request_id=request.request_id,
        engine="scalar",
        model_versions={
            "scalar": STANDARD_ENGINE_VERSION,
            "weights": WEIGHT_VERSION,
            "score_scale": SCORE_SCALE_VERSION,
            "tower": None,
            "llm": None,
        },
        input_revision=request.input_revision,
        results=results,
    )
