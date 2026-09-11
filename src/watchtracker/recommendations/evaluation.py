from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any

from watchtracker.recommendations.contract import EngineRequest
from watchtracker.recommendations.scalar import score_candidates

EVALUATION_VERSION = "local-relative-holdout-v2"


def rating_labels(request: EngineRequest, ratings: dict[str, float] | None = None):
    candidates = {item.catalog_id for item in request.candidates}
    labels = (
        ratings
        if ratings is not None
        else {
            signal.source_catalog_ids[0]: signal.value
            for signal in request.signals
            if signal.source == "personal_rating" and len(signal.source_catalog_ids) == 1
        }
    )
    return {identity: value for identity, value in labels.items() if identity in candidates}


def relevance_threshold(labels: dict[str, float]) -> float | None:
    # Compare higher/lower scores within the user's own scale. Lower here does not
    # mean disliked, and does not manufacture negative training signals. Keep equal
    # ratings together; each group needs one training and one held-out example.
    splits = [
        value
        for value in sorted(set(labels.values()))
        if sum(rating < value for rating in labels.values()) >= 2
        and sum(rating >= value for rating in labels.values()) >= 2
    ]
    return (
        min(
            splits,
            key=lambda value: abs(sum(r >= value for r in labels.values()) * 2 - len(labels)),
        )
        if splits
        else None
    )


def holdout_requests(
    request: EngineRequest, *, ratings: dict[str, float] | None = None
) -> list[tuple[EngineRequest, set[str]]]:
    """Two deterministic folds, with *all* held-out title evidence removed.

    A small-library diagnostic, not a population accuracy estimate. A withheld
    title's favorite/refinement/comparison/feedback must not leak into training.
    Unattributed inferred claims are excluded from both folds.
    """
    candidates = {item.catalog_id: item for item in request.candidates}
    labels = rating_labels(request, ratings)
    threshold = relevance_threshold(labels)
    if len(labels) < 8 or threshold is None:
        return []
    groups = [[], []]
    for identity, value in labels.items():
        groups[0 if value >= threshold else 1].append(identity)
    held_out = [set(), set()]
    for group in groups:
        ordered = sorted(
            group,
            key=lambda identity: hashlib.sha256(
                f"{request.deterministic_seed}:{identity}".encode()
            ).digest(),
        )
        for index, identity in enumerate(ordered):
            held_out[index % 2].add(identity)
    folds = []
    for index, test_ids in enumerate(held_out):
        training_signals = [
            signal
            for signal in request.signals
            if signal.source_catalog_ids
            and not test_ids.intersection(signal.source_catalog_ids)
        ]
        train_ids = {
            identity for signal in training_signals for identity in signal.source_catalog_ids
        }
        fold = EngineRequest(
            request_id=f"holdout-{index}",
            input_revision=request.input_revision,
            deterministic_seed=request.deterministic_seed,
            signals=training_signals,
            evidence_anchors=[
                anchor for anchor in request.evidence_anchors if anchor.catalog_id in train_ids
            ],
            candidates=[candidates[identity] for identity in sorted(test_ids)],
            limit=min(5, max(1, len(test_ids) // 2)),
        )
        folds.append(
            (fold, {identity for identity in test_ids if labels[identity] >= threshold})
        )
    return folds


def evaluate_holdout(
    request: EngineRequest, *, ratings: dict[str, float] | None = None
) -> dict[str, Any]:
    labels = rating_labels(request, ratings)
    folds = holdout_requests(request, ratings=labels)
    report = {
        "version": EVALUATION_VERSION,
        "status": "insufficient_ratings" if len(labels) < 8 else "insufficient_variation",
        "rated_titles": len(labels),
        "minimum_rated_titles": 8,
        "missing_ratings": max(0, 8 - len(labels)),
        "distinct_ratings": len(set(labels.values())),
        "relevance_policy": "relative_personal_ratings",
        "tested_titles": 0,
        "folds": 0,
        "personalized": None,
        "public_baseline": None,
    }
    if not folds:
        return report
    personal, baseline = [], []
    for fold, relevant in folds:
        ranking = [row.catalog_id for row in score_candidates(request=fold).results]
        public = sorted(
            fold.candidates,
            key=lambda item: (
                -(item.public_score if item.public_score is not None else 5.0),
                item.catalog_id,
            ),
        )
        public_ranking = [item.catalog_id for item in public[: fold.limit]]
        genres = {item.catalog_id: set(item.genres) for item in fold.candidates}
        for output, ids in ((personal, ranking), (baseline, public_ranking)):
            output.append(
                {
                    "ndcg": ndcg_at_k(ids, relevant, fold.limit),
                    "recall": recall_at_k(ids, relevant, fold.limit),
                    "genre_diversity": intra_list_genre_diversity(
                        [genres[identity] for identity in ids]
                    ),
                }
            )
    return {
        **report,
        "status": "ready",
        "folds": len(folds),
        "tested_titles": sum(len(fold.candidates) for fold, _ in folds),
        "personalized": {
            key: round(sum(row[key] for row in personal) / len(personal), 4)
            for key in personal[0]
        },
        "public_baseline": {
            key: round(sum(row[key] for row in baseline) / len(baseline), 4)
            for key in baseline[0]
        },
    }


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[: max(0, k)]).intersection(relevant)) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for index, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    limit = max(0, k)
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, item in enumerate(ranked[:limit])
        if item in relevant
    )
    ideal_count = min(len(relevant), limit)
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / ideal if ideal else 0.0


def positive_negative_pair_accuracy(
    scores: dict[str, float], pairs: Sequence[tuple[str, str]]
) -> float:
    usable = [
        (positive, negative)
        for positive, negative in pairs
        if positive in scores and negative in scores
    ]
    if not usable:
        return 0.0
    return sum(scores[positive] > scores[negative] for positive, negative in usable) / len(
        usable
    )


def catalog_coverage(ranked: Sequence[str], eligible_catalog_ids: set[str]) -> float:
    if not eligible_catalog_ids:
        return 0.0
    return len(set(ranked).intersection(eligible_catalog_ids)) / len(eligible_catalog_ids)


def genre_coverage(ranked_genres: Sequence[set[str]], candidate_genres: set[str]) -> float:
    if not candidate_genres:
        return 0.0
    represented = set().union(*ranked_genres) if ranked_genres else set()
    return len(represented.intersection(candidate_genres)) / len(candidate_genres)


def intra_list_genre_diversity(ranked_genres: Sequence[set[str]]) -> float:
    pairs: list[float] = []
    for index, first in enumerate(ranked_genres):
        for second in ranked_genres[index + 1 :]:
            union = first | second
            pairs.append(1 - (len(first & second) / len(union) if union else 0.0))
    return sum(pairs) / len(pairs) if pairs else 0.0


def mean_novelty(popularity: Sequence[float]) -> float:
    bounded = [min(1.0, max(0.0, float(value))) for value in popularity]
    return sum(1 - value for value in bounded) / len(bounded) if bounded else 0.0


def popularity_bias(
    ranked_popularity: Sequence[float], candidate_popularity: Sequence[float]
) -> float:
    if not ranked_popularity or not candidate_popularity:
        return 0.0
    ranked_mean = sum(ranked_popularity) / len(ranked_popularity)
    candidate_mean = sum(candidate_popularity) / len(candidate_popularity)
    return ranked_mean - candidate_mean


def result_field_coverage(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {
            "identity": 0.0,
            "metadata": 0.0,
            "artwork": 0.0,
            "explanation": 0.0,
        }
    total = len(rows)
    return {
        "identity": sum(
            bool(row.get("provider_source") and row.get("provider_id")) for row in rows
        )
        / total,
        "metadata": sum(bool(row.get("genres") or row.get("overview")) for row in rows) / total,
        "artwork": sum(bool(row.get("poster_url")) for row in rows) / total,
        "explanation": sum(bool(row.get("reason_codes")) for row in rows) / total,
    }


def repeated_run_stability(
    first: Sequence[str], second: Sequence[str], *, k: int | None = None
) -> dict[str, float | bool]:
    limit = max(0, k) if k is not None else max(len(first), len(second))
    first_slice = list(first[:limit])
    second_slice = list(second[:limit])
    if not first_slice and not second_slice:
        return {"exact_order": True, "overlap": 1.0, "mean_rank_shift": 0.0}
    overlap_ids = set(first_slice).intersection(second_slice)
    # Missing positions are instability, not a reason to shorten the evaluation
    # window. This keeps an empty/truncated rerun from appearing perfectly stable.
    overlap = len(overlap_ids) / max(1, limit)
    first_rank = {item: index for index, item in enumerate(first_slice)}
    second_rank = {item: index for index, item in enumerate(second_slice)}
    missing_penalty = float(limit)
    rank_shifts = [
        abs(first_rank[item] - second_rank[item])
        if item in first_rank and item in second_rank
        else missing_penalty
        for item in set(first_slice).union(second_slice)
    ]
    mean_shift = sum(rank_shifts) / len(rank_shifts) if rank_shifts else 0.0
    return {
        "exact_order": first_slice == second_slice,
        "overlap": overlap,
        "mean_rank_shift": mean_shift,
    }
