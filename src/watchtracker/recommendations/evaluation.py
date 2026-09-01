from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


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
