from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from watchtracker.authorization import Principal, current_user_id
from watchtracker.models import (
    RatingAssessment,
    RatingComparison,
    RatingRefinementRun,
    WatchEntry,
    utcnow,
)
from watchtracker.schemas import (
    RatingAssessmentComplete,
    RatingAssessmentCreate,
    RatingAssessmentPatch,
    RatingComparisonUpdate,
)
from watchtracker.services.entries import serialize_entry
from watchtracker.taxonomy import effective_values, normalize_title

RUBRIC_VERSION = "guided-rubric-v3"
RANKING_VERSION = "advanced-ranking-v2"
SKIPPED_ANSWERS = {"skip", "not_applicable"}
V1_RUBRIC_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "enjoyment",
        "group": "core",
        "weight": 1.0,
        "prompt": "How rewarding was the experience for you?",
        "low_label": "Not rewarding",
        "high_label": "Extremely rewarding",
    },
    {
        "key": "execution",
        "group": "core",
        "weight": 1.0,
        "prompt": "How well did it achieve what it seemed to attempt?",
        "low_label": "Poorly achieved",
        "high_label": "Exceptionally achieved",
    },
    {
        "key": "impact",
        "group": "core",
        "weight": 1.0,
        "prompt": "How much emotional or intellectual impact did it have?",
        "low_label": "Very little",
        "high_label": "Lasting impact",
    },
    {
        "key": "memorability",
        "group": "core",
        "weight": 1.0,
        "prompt": "How distinct does it remain in your memory?",
        "low_label": "Fades quickly",
        "high_label": "Unforgettable",
    },
    {
        "key": "consistency",
        "group": "optional",
        "weight": 0.5,
        "prompt": "How consistent were its pacing and quality?",
        "low_label": "Very uneven",
        "high_label": "Consistently strong",
    },
    {
        "key": "personal_significance",
        "group": "optional",
        "weight": 0.5,
        "prompt": "How personally significant is it beyond general craft?",
        "low_label": "Not personal",
        "high_label": "Deeply personal",
    },
    {
        "key": "rewatch_desire",
        "group": "optional",
        "weight": 0.5,
        "prompt": "How much would you like to experience it again?",
        "low_label": "No desire",
        "high_label": "Strong desire",
    },
)
RUBRIC_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "impact",
        "group": "core",
        "weight": 1.15,
        "prompt": "How strong was its emotional or intellectual impact?",
        "low_label": "Little impact",
        "high_label": "Deep, lasting impact",
        "insight_label": "Impact",
    },
    {
        "key": "distinctiveness",
        "group": "core",
        "weight": 1.0,
        "prompt": "Did it have a unique factor or identity you could recognize as its own?",
        "low_label": "Hard to distinguish",
        "high_label": "Singular identity",
        "insight_label": "Distinctiveness",
    },
    {
        "key": "formula_freshness",
        "group": "core",
        "weight": 0.9,
        "prompt": "Did it feel overly formulaic, or did it use familiar ideas in a fresh way?",
        "low_label": "Very formulaic",
        "high_label": "Fresh or inventive",
        "insight_label": "Freshness",
    },
    {
        "key": "engagement",
        "group": "core",
        "weight": 1.0,
        "prompt": "How consistently did it hold your attention and involvement?",
        "low_label": "Frequently disengaging",
        "high_label": "Completely absorbing",
        "insight_label": "Engagement",
    },
    {
        "key": "coherence",
        "group": "core",
        "weight": 0.95,
        "prompt": "How well did its ideas, craft, pacing, and ending work together?",
        "low_label": "Disconnected or uneven",
        "high_label": "Exceptionally cohesive",
        "insight_label": "Coherence",
    },
    {
        "key": "lasting_value",
        "group": "core",
        "weight": 1.0,
        "prompt": "How strongly did it stay with you later?",
        "low_label": "Barely remembered later",
        "high_label": "Stayed with me strongly",
        "insight_label": "Staying power",
    },
    {
        "key": "consistency",
        "group": "optional",
        "weight": 0.55,
        "prompt": "Across its full runtime, how consistent was the quality?",
        "low_label": "Very uneven",
        "high_label": "Consistently strong",
        "insight_label": "Consistency",
    },
    {
        "key": "personal_significance",
        "group": "optional",
        "weight": 0.55,
        "prompt": "How personally meaningful was it beyond general craft?",
        "low_label": "Not personally meaningful",
        "high_label": "Deeply personal",
        "insight_label": "Personal significance",
    },
    {
        "key": "rewatch_desire",
        "group": "optional",
        "weight": 0.45,
        "prompt": "Independent of how often you already watched it, how strong is your desire to return?",
        "low_label": "No desire to return",
        "high_label": "Strong desire to return",
        "insight_label": "Return desire",
    },
    {
        "key": "reward_vs_flaws",
        "group": "optional",
        "weight": 0.5,
        "prompt": "How much did its strengths outweigh the flaws you noticed?",
        "low_label": "Flaws dominated",
        "high_label": "Rewards dominated",
        "insight_label": "Reward over flaws",
    },
)
RUBRICS = {
    "guided-rubric-v1": V1_RUBRIC_DIMENSIONS,
    "guided-rubric-v2": RUBRIC_DIMENSIONS,
    RUBRIC_VERSION: RUBRIC_DIMENSIONS,
}


class RatingFeatureDisabled(RuntimeError):
    pass


class RatingNotFound(LookupError):
    pass


class RatingConflict(RuntimeError):
    pass


def rubric_contract() -> dict[str, Any]:
    return {
        "mode": "guided_v2",
        "rubric_version": RUBRIC_VERSION,
        "dimensions": list(RUBRIC_DIMENSIONS),
        "answer_values": [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5],
        "skip_values": sorted(SKIPPED_ANSWERS),
        "minimum_core_answers": 4,
        "formula": "dimension_score = 1 + 9 * ((answer - 1) / 4)",
        "actual_rewatches_policy": "context_only",
        "actual_rewatches_explanation": (
            "Stored rewatch count is shown as context but never adds points automatically. "
            "Your optional return-desire answer is deliberate evidence instead."
        ),
    }


def _rubric(version: str) -> tuple[dict[str, Any], ...]:
    return RUBRICS.get(version, RUBRIC_DIMENSIONS)


def validate_answers(
    answers: dict[str, Any], *, rubric_version: str = RUBRIC_VERSION
) -> dict[str, float | str]:
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object")
    dimensions = {item["key"]: item for item in _rubric(rubric_version)}
    unknown = set(answers) - set(dimensions)
    if unknown:
        raise ValueError(f"unknown rubric dimension: {sorted(unknown)[0]}")
    validated: dict[str, float | str] = {}
    for key, value in answers.items():
        if isinstance(value, bool):
            raise ValueError(f"{key} must be 1–5 in 0.5 steps, skip, or not_applicable")
        if (
            isinstance(value, (int, float))
            and 1 <= float(value) <= 5
            and float(value) * 2 % 1 == 0
        ):
            validated[key] = float(value)
        elif value in SKIPPED_ANSWERS:
            validated[key] = str(value)
        else:
            raise ValueError(f"{key} must be 1–5 in 0.5 steps, skip, or not_applicable")
    return validated


def _round_tenth(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def calculate_rubric(
    answers: dict[str, Any], *, rubric_version: str = RUBRIC_VERSION
) -> dict[str, Any]:
    rubric = _rubric(rubric_version)
    dimensions = {item["key"]: item for item in rubric}
    core_dimensions = tuple(item["key"] for item in rubric if item["group"] == "core")
    total_weight = sum(item["weight"] for item in rubric)
    minimum_core = 3 if rubric_version == "guided-rubric-v1" else 4
    validated = validate_answers(answers, rubric_version=rubric_version)
    answered = {key: value for key, value in validated.items() if isinstance(value, float)}
    core_answered = sum(key in answered for key in core_dimensions)
    answered_weight = sum(dimensions[key]["weight"] for key in answered)
    coverage = answered_weight / total_weight
    breakdown = {key: 1 + 9 * ((value - 1) / 4) for key, value in answered.items()}
    rubric_score = None
    suggested_rating = None
    if core_answered >= minimum_core and answered_weight:
        rubric_score = (
            sum(dimensions[key]["weight"] * score for key, score in breakdown.items())
            / answered_weight
        )
        suggested_rating = _round_tenth(rubric_score)
    return {
        "answers": validated,
        "core_answered": core_answered,
        "core_total": len(core_dimensions),
        "minimum_core_answers": minimum_core,
        "core_complete": core_answered == len(core_dimensions),
        "answered_weight": answered_weight,
        "total_weight": total_weight,
        "rubric_coverage": coverage,
        "rubric_score": rubric_score,
        "suggested_rating": suggested_rating,
        "partial_suggestion": rubric_score is not None and core_answered < len(core_dimensions),
        "breakdown": breakdown,
    }


def assessment_payload(
    assessment: RatingAssessment, *, include_private: bool = True
) -> dict[str, Any]:
    calculation = calculate_rubric(
        assessment.answers or {}, rubric_version=assessment.rubric_version
    )
    value = {
        "id": assessment.id,
        "entry_id": assessment.entry_id,
        "mode": assessment.mode,
        "rubric_version": assessment.rubric_version,
        "state": assessment.state,
        "answers": assessment.answers or {},
        "rubric_score": assessment.rubric_score,
        "rubric_coverage": assessment.rubric_coverage,
        "suggested_rating": assessment.suggested_rating,
        "final_rating_snapshot": assessment.final_rating_snapshot,
        "version": assessment.version,
        "created_at": assessment.created_at,
        "updated_at": assessment.updated_at,
        "completed_at": assessment.completed_at,
        "core_answered": calculation["core_answered"],
        "core_total": calculation["core_total"],
        "minimum_core_answers": calculation["minimum_core_answers"],
        "core_complete": calculation["core_complete"],
        "partial_suggestion": calculation["partial_suggestion"],
        "breakdown": calculation["breakdown"],
    }
    if include_private:
        value["private_reflection"] = assessment.private_reflection
    return value


class RatingAssessmentService:
    def __init__(
        self,
        session: Session,
        *,
        enabled: bool,
        principal: Principal | None = None,
    ):
        self.session = session
        self.enabled = enabled
        self.user_id = current_user_id(session, principal)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RatingFeatureDisabled(
                "Advanced ratings are disabled. Enable them in Settings → Ratings & Rankings."
            )

    def _entry(self, entry_id: str) -> WatchEntry:
        entry = self.session.scalar(
            select(WatchEntry).where(
                WatchEntry.id == entry_id,
                WatchEntry.user_id == self.user_id,
                WatchEntry.deleted_at.is_(None),
            )
        )
        if not entry:
            raise RatingNotFound("Watch entry not found")
        return entry

    def _assessment(self, assessment_id: str) -> RatingAssessment:
        assessment = self.session.scalar(
            select(RatingAssessment)
            .join(WatchEntry, RatingAssessment.entry_id == WatchEntry.id)
            .where(
                RatingAssessment.id == assessment_id,
                WatchEntry.user_id == self.user_id,
            )
        )
        if not assessment:
            raise RatingNotFound("Rating assessment not found")
        return assessment

    @staticmethod
    def _set_calculation(assessment: RatingAssessment) -> dict[str, Any]:
        calculated = calculate_rubric(
            assessment.answers or {}, rubric_version=assessment.rubric_version
        )
        assessment.rubric_score = calculated["rubric_score"]
        assessment.rubric_coverage = calculated["rubric_coverage"]
        assessment.suggested_rating = calculated["suggested_rating"]
        return calculated

    def create(self, payload: RatingAssessmentCreate) -> dict[str, Any]:
        self._require_enabled()
        self._entry(payload.entry_id)
        existing = self.session.scalar(
            select(RatingAssessment).where(
                RatingAssessment.entry_id == payload.entry_id,
                RatingAssessment.rubric_version == RUBRIC_VERSION,
                RatingAssessment.state == "draft",
            )
        )
        if existing:
            return assessment_payload(existing)
        assessment = RatingAssessment(
            entry_id=payload.entry_id,
            mode="guided_v2",
            rubric_version=RUBRIC_VERSION,
            answers=validate_answers(payload.answers, rubric_version=RUBRIC_VERSION),
            private_reflection=(payload.private_reflection or None),
        )
        self._set_calculation(assessment)
        self.session.add(assessment)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise RatingConflict("An assessment draft already exists for this title") from exc
        return assessment_payload(assessment)

    def get(self, assessment_id: str) -> dict[str, Any]:
        return assessment_payload(self._assessment(assessment_id))

    def patch(self, assessment_id: str, payload: RatingAssessmentPatch) -> dict[str, Any]:
        self._require_enabled()
        assessment = self._assessment(assessment_id)
        if assessment.state != "draft":
            raise RatingConflict("Only a draft assessment can be edited")
        if assessment.version != payload.expected_version:
            raise RatingConflict("This draft changed in another tab. Reload it before saving.")
        if payload.answers is not None:
            assessment.answers = validate_answers(
                payload.answers, rubric_version=assessment.rubric_version
            )
        if "private_reflection" in payload.model_fields_set:
            assessment.private_reflection = payload.private_reflection or None
        self._set_calculation(assessment)
        assessment.version += 1
        assessment.updated_at = utcnow()
        self.session.commit()
        return assessment_payload(assessment)

    def complete(self, assessment_id: str, payload: RatingAssessmentComplete) -> dict[str, Any]:
        self._require_enabled()
        assessment = self._assessment(assessment_id)
        if assessment.state != "draft":
            raise RatingConflict("This assessment has already been completed")
        if assessment.version != payload.expected_version:
            raise RatingConflict(
                "This draft changed in another tab. Reload it before completing."
            )
        entry = self._entry(assessment.entry_id)
        calculated = self._set_calculation(assessment)
        if calculated["rubric_score"] is None:
            raise RatingConflict(
                f"Answer at least {calculated['minimum_core_answers']} core questions before completing"
            )
        if payload.refinement_run_id:
            refinement = RatingRefinementService(self.session, enabled=True).get(
                payload.refinement_run_id
            )
            next_entry = refinement.get("next_entry")
            next_entry_id = getattr(next_entry, "id", None)
            if next_entry_id is None and isinstance(next_entry, dict):
                next_entry_id = next_entry.get("id")
            if (
                refinement["state"] != "active"
                or refinement["stage"] != "assessments"
                or not next_entry
                or next_entry_id != entry.id
            ):
                raise RatingConflict(
                    "This title is no longer the current step in that refinement run"
                )
        if payload.rating_action == "use_suggestion":
            entry.personal_rating = assessment.suggested_rating
        elif payload.rating_action == "set_rating":
            entry.personal_rating = payload.final_rating
        previous = list(
            self.session.scalars(
                select(RatingAssessment).where(
                    RatingAssessment.entry_id == entry.id,
                    RatingAssessment.rubric_version == assessment.rubric_version,
                    RatingAssessment.state == "completed",
                    RatingAssessment.id != assessment.id,
                )
            )
        )
        now = utcnow()
        for item in previous:
            item.state = "superseded"
            item.updated_at = now
        assessment.state = "completed"
        assessment.completed_at = now
        assessment.updated_at = now
        assessment.version += 1
        assessment.final_rating_snapshot = entry.personal_rating
        self.session.commit()
        if payload.refinement_run_id:
            RatingRefinementService(self.session, enabled=True).record_assessment(
                payload.refinement_run_id, entry.id
            )
        return {
            "assessment": assessment_payload(assessment),
            "entry": serialize_entry(entry),
            "rating_changed": payload.rating_action in {"use_suggestion", "set_rating"},
        }

    def discard(self, assessment_id: str) -> None:
        self._require_enabled()
        assessment = self._assessment(assessment_id)
        if assessment.state != "draft":
            raise RatingConflict("Completed assessment history cannot be discarded")
        self.session.delete(assessment)
        self.session.commit()


def _current_assessments(session: Session, user_id: str) -> dict[str, RatingAssessment]:
    assessments = list(
        session.scalars(
            select(RatingAssessment)
            .join(WatchEntry, RatingAssessment.entry_id == WatchEntry.id)
            .where(
                RatingAssessment.state == "completed",
                WatchEntry.user_id == user_id,
            )
            .order_by(RatingAssessment.completed_at.desc(), RatingAssessment.id.desc())
        )
    )
    result: dict[str, RatingAssessment] = {}
    for assessment in assessments:
        result.setdefault(assessment.entry_id, assessment)
    return result


def _score_band(value: float) -> int:
    return min(3, max(0, int((value - 1) // 2.5)))


class AdvancedRankingService:
    def __init__(self, session: Session, principal: Principal | None = None):
        self.session = session
        self.user_id = current_user_id(session, principal)

    def _entries(self) -> list[WatchEntry]:
        return list(
            self.session.scalars(
                select(WatchEntry)
                .where(
                    WatchEntry.user_id == self.user_id,
                    WatchEntry.deleted_at.is_(None),
                    WatchEntry.personal_rating.is_not(None),
                )
                .options(selectinload(WatchEntry.catalog_item))
            )
        )

    def calculate(self) -> list[dict[str, Any]]:
        entries = self._entries()
        by_id = {entry.id: entry for entry in entries}
        assessments = _current_assessments(self.session, self.user_id)
        current_rubric_entry_ids = set(
            self.session.scalars(
                select(RatingAssessment.entry_id).where(
                    RatingAssessment.entry_id.in_(by_id),
                    RatingAssessment.rubric_version == RUBRIC_VERSION,
                    RatingAssessment.state == "completed",
                )
            )
        )
        priors: dict[str, float] = {}
        assessment_data: dict[str, dict[str, Any]] = {}
        for entry in entries:
            rating = float(entry.personal_rating)
            assessment = assessments.get(entry.id)
            if assessment and assessment.rubric_score is not None:
                coverage = float(assessment.rubric_coverage or 0)
                weight = min(0.30, 0.30 * coverage)
                adjustment = max(
                    -0.75,
                    min(0.75, weight * (float(assessment.rubric_score) - rating)),
                )
                calculated = calculate_rubric(
                    assessment.answers or {}, rubric_version=assessment.rubric_version
                )
                assessment_data[entry.id] = {
                    "rubric_score": float(assessment.rubric_score),
                    "rubric_coverage": coverage,
                    "rubric_adjustment": adjustment,
                    "core_complete": calculated["core_complete"],
                }
            else:
                adjustment = 0.0
                assessment_data[entry.id] = {
                    "rubric_score": None,
                    "rubric_coverage": 0.0,
                    "rubric_adjustment": 0.0,
                    "core_complete": False,
                }
            priors[entry.id] = max(1.0, min(10.0, rating + adjustment))

        residuals: dict[str, list[float]] = defaultdict(list)
        opponent_bands: dict[str, set[int]] = defaultdict(set)
        comparisons = list(
            self.session.scalars(
                select(RatingComparison).where(
                    RatingComparison.user_id == self.user_id,
                    RatingComparison.result != "skip",
                )
            )
        )
        for comparison in comparisons:
            low = comparison.entry_low_id
            high = comparison.entry_high_id
            if low not in by_id or high not in by_id:
                continue
            expected_low = 1 / (1 + math.exp(-(priors[low] - priors[high]) / 1.25))
            observed_low = {"low": 1.0, "tie": 0.5, "high": 0.0}[comparison.result]
            residual = observed_low - expected_low
            residuals[low].append(residual)
            residuals[high].append(-residual)
            opponent_bands[low].add(_score_band(priors[high]))
            opponent_bands[high].add(_score_band(priors[low]))

        rows: list[dict[str, Any]] = []
        for entry in entries:
            values = residuals[entry.id]
            count = len(values)
            mean_residual = sum(values) / count if count else 0.0
            reliability = count / (count + 8)
            pair_adjustment = max(-0.75, min(0.75, 1.5 * mean_residual * reliability))
            technical = max(1.0, min(10.0, priors[entry.id] + pair_adjustment))
            evidence = assessment_data[entry.id]
            if (
                evidence["rubric_coverage"] >= 0.75
                and count >= 12
                and len(opponent_bands[entry.id]) > 1
            ):
                level = "well_supported"
            elif evidence["core_complete"] and count >= 5:
                level = "supported"
            elif assessments.get(entry.id) is not None or 1 <= count <= 4:
                level = "developing"
            else:
                level = "base"
            rows.append(
                {
                    "entry": entry,
                    "personal_rating": float(entry.personal_rating),
                    "technical_score": technical,
                    "prior_score": priors[entry.id],
                    "pairwise_adjustment": pair_adjustment,
                    "comparison_count": count,
                    "opponent_band_count": len(opponent_bands[entry.id]),
                    "evidence_level": level,
                    "refined": entry.id in current_rubric_entry_ids,
                    "rewatch_count": entry.rewatch_count,
                    "algorithm_version": RANKING_VERSION,
                    **evidence,
                }
            )
        rows.sort(
            key=lambda row: (
                -row["technical_score"],
                -row["personal_rating"],
                -row["rubric_coverage"],
                row["entry"].catalog_item.normalized_title,
                row["entry"].id,
            )
        )
        return rows

    @staticmethod
    def _matches(
        row: dict[str, Any],
        *,
        media_type: str | None,
        status: str | None,
        genre: str | None,
        year_min: int | None,
        year_max: int | None,
        q: str | None,
    ) -> bool:
        entry: WatchEntry = row["entry"]
        item = entry.catalog_item
        if media_type and item.media_type != media_type:
            return False
        if status and entry.status != status:
            return False
        if year_min is not None and (item.release_year is None or item.release_year < year_min):
            return False
        if year_max is not None and (item.release_year is None or item.release_year > year_max):
            return False
        if q:
            needle = normalize_title(q)
            words = item.normalized_title.split()
            if not (
                item.normalized_title.startswith(needle)
                or any(word.startswith(needle) for word in words)
            ):
                return False
        if genre:
            values = [
                *effective_values(
                    item.normalized_genres or [],
                    entry.genre_additions or [],
                    entry.genre_removals or [],
                ),
                *effective_values(
                    item.inferred_subgenres or [],
                    entry.subgenre_additions or [],
                    entry.subgenre_removals or [],
                ),
            ]
            needle = genre.strip().casefold()
            if not any(needle in value.casefold() for value in values):
                return False
        return True

    def rankings(
        self,
        *,
        advanced: bool,
        page: int,
        page_size: int,
        show_all: bool = False,
        media_type: str | None = None,
        status: str | None = None,
        genre: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        rows = self.calculate()
        if not advanced:
            rows.sort(
                key=lambda row: (
                    -row["personal_rating"],
                    row["entry"].catalog_item.normalized_title,
                    row["entry"].id,
                )
            )
        filtered = [
            row
            for row in rows
            if self._matches(
                row,
                media_type=media_type,
                status=status,
                genre=genre,
                year_min=year_min,
                year_max=year_max,
                q=q,
            )
        ]
        total = len(filtered)
        start = (page - 1) * page_size
        items = []
        page_rows = filtered if show_all else filtered[start : start + page_size]
        rank_start = 1 if show_all else start + 1
        for rank, row in enumerate(page_rows, start=rank_start):
            entry = row.pop("entry")
            items.append(
                {
                    "rank": rank,
                    "entry": serialize_entry(entry, include_events=False),
                    "personal_rating": row["personal_rating"],
                    "technical_score": row["technical_score"] if advanced else None,
                    "prior_score": row["prior_score"] if advanced else None,
                    "rubric_score": row["rubric_score"] if advanced else None,
                    "rubric_coverage": row["rubric_coverage"] if advanced else 0.0,
                    "rubric_adjustment": row["rubric_adjustment"] if advanced else 0.0,
                    "pairwise_adjustment": row["pairwise_adjustment"] if advanced else 0.0,
                    "comparison_count": row["comparison_count"] if advanced else 0,
                    "opponent_band_count": row["opponent_band_count"] if advanced else 0,
                    "evidence_level": row["evidence_level"] if advanced else "base",
                    "refined": row["refined"] if advanced else False,
                    "rewatch_count": row["rewatch_count"],
                    "rewatch_policy": "context_only" if advanced else None,
                    "algorithm_version": RANKING_VERSION if advanced else None,
                    "explanation_reason_codes": [
                        "canonical_anchor",
                        *(
                            ["rubric_blend"]
                            if advanced and row["rubric_score"] is not None
                            else []
                        ),
                        *(
                            ["pairwise_residual"]
                            if advanced and row["comparison_count"]
                            else []
                        ),
                        "stable_tie_break",
                    ],
                }
            )
        return {
            "mode": "technical" if advanced else "personal",
            "advanced_ratings_enabled": advanced,
            "algorithm_version": RANKING_VERSION if advanced else None,
            "items": items,
            "total": total,
            "page": page,
            "page_size": total if show_all else page_size,
            "pages": 1 if show_all and total else math.ceil(total / page_size) if total else 0,
        }


class RatingRefinementService:
    """Persist a bounded, resumable calibration followed by title evidence."""

    def __init__(
        self,
        session: Session,
        *,
        enabled: bool,
        principal: Principal | None = None,
    ):
        self.session = session
        self.enabled = enabled
        self.user_id = current_user_id(session, principal)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RatingFeatureDisabled(
                "Advanced ratings are disabled. Enable them in Settings → Ratings & Rankings."
            )

    def _run(self, run_id: str) -> RatingRefinementRun:
        run = self.session.scalar(
            select(RatingRefinementRun).where(
                RatingRefinementRun.id == run_id,
                RatingRefinementRun.user_id == self.user_id,
            )
        )
        if not run:
            raise RatingNotFound("Rating refinement run not found")
        return run

    def active(self) -> dict[str, Any] | None:
        run = self.session.scalar(
            select(RatingRefinementRun)
            .where(
                RatingRefinementRun.user_id == self.user_id,
                RatingRefinementRun.state == "active",
            )
            .order_by(RatingRefinementRun.updated_at.desc())
        )
        return self.payload(run) if run else None

    def _available_comparisons(self, rows: list[dict[str, Any]]) -> int:
        by_type: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            entry: WatchEntry = row["entry"]
            by_type[entry.catalog_item.media_type].append(entry.id)
        possible = sum(len(ids) * (len(ids) - 1) // 2 for ids in by_type.values())
        eligible = {row["entry"].id for row in rows}
        existing = sum(
            1
            for item in self.session.scalars(
                select(RatingComparison).where(
                    RatingComparison.user_id == self.user_id,
                    RatingComparison.result != "skip",
                )
            )
            if item.entry_low_id in eligible and item.entry_high_id in eligible
        )
        return max(0, possible - existing)

    def start(self, scope: str, *, entry_id: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        existing = self.session.scalar(
            select(RatingRefinementRun)
            .where(
                RatingRefinementRun.user_id == self.user_id,
                RatingRefinementRun.state == "active",
            )
            .order_by(RatingRefinementRun.updated_at.desc())
        )
        if existing:
            if entry_id and entry_id not in set(existing.target_entry_ids or []):
                raise RatingConflict(
                    "Finish or end the current refinement before starting another title"
                )
            return self.payload(existing)
        rows = AdvancedRankingService(self.session).calculate()
        if not rows:
            raise RatingConflict("Add a personal rating to at least one title first")
        evidence_order = {"base": 0, "developing": 1, "supported": 2, "well_supported": 3}
        rows.sort(
            key=lambda row: (
                evidence_order.get(row["evidence_level"], 0),
                row["comparison_count"],
                row["rubric_coverage"],
                row["entry"].catalog_item.normalized_title,
            )
        )
        if entry_id:
            selected = [row for row in rows if row["entry"].id == entry_id]
            if not selected:
                raise RatingConflict("Add a personal rating to this title before refining it")
        else:
            selected = rows if scope == "full" else rows[: min(3, len(rows))]
        target_ids = [row["entry"].id for row in selected]
        completed_v2 = set(
            self.session.scalars(
                select(RatingAssessment.entry_id).where(
                    RatingAssessment.entry_id.in_(target_ids),
                    RatingAssessment.rubric_version == RUBRIC_VERSION,
                    RatingAssessment.state == "completed",
                )
            )
        )
        available = self._available_comparisons(rows)
        if entry_id:
            entry_type = selected[0]["entry"].catalog_item.media_type
            available = min(
                available,
                sum(
                    row["entry"].id != entry_id
                    and row["entry"].catalog_item.media_type == entry_type
                    for row in rows
                ),
            )
            desired = 3
        elif scope == "full":
            # A logarithmic, capped sample captures useful close calls without
            # turning refinement into an exhausting all-pairs exercise.
            desired = min(12, max(6, math.ceil(math.log2(len(rows) + 1) * 2)))
        else:
            desired = 3
        comparison_target = min(desired, available)
        stage = "comparisons" if comparison_target else "assessments"
        if len(completed_v2) == len(target_ids) and not comparison_target:
            stage = "complete"
        now = utcnow()
        run = RatingRefinementRun(
            user_id=self.user_id,
            scope=scope,
            state="completed" if stage == "complete" else "active",
            stage=stage,
            rubric_version=RUBRIC_VERSION,
            ranking_version=RANKING_VERSION,
            target_entry_ids=target_ids,
            completed_entry_ids=sorted(completed_v2),
            completed_pair_keys=[],
            comparison_target=comparison_target,
            comparisons_completed=0,
            assessment_target=len(target_ids),
            assessments_completed=len(completed_v2),
            completed_at=now if stage == "complete" else None,
        )
        self.session.add(run)
        self.session.commit()
        return self.payload(run)

    def get(self, run_id: str) -> dict[str, Any]:
        return self.payload(self._run(run_id))

    def _advance(self, run: RatingRefinementRun) -> None:
        if run.state != "active":
            return
        if run.stage == "comparisons" and run.comparisons_completed >= run.comparison_target:
            run.stage = "assessments"
        if run.stage == "assessments" and run.assessments_completed >= run.assessment_target:
            run.stage = "complete"
            run.state = "completed"
            run.completed_at = utcnow()
        run.updated_at = utcnow()

    def finish_comparisons_early(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run.state != "active" or run.stage != "comparisons":
            return self.payload(run)
        run.comparison_target = run.comparisons_completed
        self._advance(run)
        self.session.commit()
        return self.payload(run)

    def record_comparison(self, run_id: str, pair_key: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run.state != "active" or run.stage != "comparisons":
            raise RatingConflict("This refinement run is no longer accepting comparisons")
        completed = list(run.completed_pair_keys or [])
        if pair_key not in completed:
            completed.append(pair_key)
            run.completed_pair_keys = completed
            run.comparisons_completed = len(completed)
        self._advance(run)
        self.session.commit()
        return self.payload(run)

    def record_assessment(self, run_id: str, entry_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run.state != "active" or run.stage != "assessments":
            raise RatingConflict("This refinement run is not in its title-reflection stage")
        if entry_id not in set(run.target_entry_ids or []):
            raise RatingConflict("This title is not part of the selected refinement scope")
        completed = list(run.completed_entry_ids or [])
        if entry_id not in completed:
            completed.append(entry_id)
            run.completed_entry_ids = completed
            run.assessments_completed = len(completed)
        self._advance(run)
        self.session.commit()
        return self.payload(run)

    def skip_assessment(self, run_id: str, entry_id: str) -> dict[str, Any]:
        """Advance without inventing evidence when the title is not remembered."""
        self._require_enabled()
        return self.record_assessment(run_id, entry_id)

    def undo_last_comparison(self, run_id: str) -> dict[str, Any]:
        """Remove the most recent run comparison so it can be answered again."""
        self._require_enabled()
        run = self._run(run_id)
        if run.state != "active" or run.stage not in {"comparisons", "assessments"}:
            raise RatingConflict("This refinement run cannot go back to a comparison")
        if run.stage == "assessments" and run.assessments_completed:
            raise RatingConflict(
                "Finish or pause the current title before revisiting comparisons"
            )
        completed = list(run.completed_pair_keys or [])
        if not completed:
            raise RatingConflict("There is no earlier comparison in this run")
        pair_key = completed.pop()
        low, high = parse_pair_key(pair_key)
        comparison = self.session.scalar(
            select(RatingComparison).where(
                RatingComparison.user_id == self.user_id,
                RatingComparison.entry_low_id == low,
                RatingComparison.entry_high_id == high,
            )
        )
        if comparison:
            self.session.delete(comparison)
        run.completed_pair_keys = completed
        run.comparisons_completed = len(completed)
        run.stage = "comparisons"
        run.updated_at = utcnow()
        self.session.commit()
        payload = self.payload(run)
        payload["undone_pair_key"] = pair_key
        return payload

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run.state == "active":
            run.state = "cancelled"
            run.updated_at = utcnow()
            self.session.commit()
        return self.payload(run)

    def payload(self, run: RatingRefinementRun) -> dict[str, Any]:
        target_ids = list(run.target_entry_ids or [])
        completed_ids = set(run.completed_entry_ids or [])
        next_id = next((item for item in target_ids if item not in completed_ids), None)
        next_entry = None
        if next_id and run.stage == "assessments":
            entry = self.session.scalar(
                select(WatchEntry)
                .where(
                    WatchEntry.id == next_id,
                    WatchEntry.user_id == self.user_id,
                    WatchEntry.deleted_at.is_(None),
                )
                .options(selectinload(WatchEntry.catalog_item))
            )
            if entry:
                next_entry = serialize_entry(entry, include_events=False)
        total = run.comparison_target + run.assessment_target
        done = min(run.comparisons_completed, run.comparison_target) + min(
            run.assessments_completed, run.assessment_target
        )
        return {
            "id": run.id,
            "scope": run.scope,
            "state": run.state,
            "stage": run.stage,
            "rubric_version": run.rubric_version,
            "ranking_version": run.ranking_version,
            "comparison_target": run.comparison_target,
            "comparisons_completed": run.comparisons_completed,
            "assessment_target": run.assessment_target,
            "assessments_completed": run.assessments_completed,
            "overall_completed": done,
            "overall_target": total,
            "overall_percent": round(100 * done / total) if total else 100,
            "next_entry": next_entry,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "completed_at": run.completed_at,
            "rewatch_policy": "context_only",
            "target_entry_ids": target_ids,
            "can_undo_comparison": bool(run.completed_pair_keys),
        }


def canonical_pair(first: str, second: str) -> tuple[str, str, str]:
    if first == second:
        raise RatingConflict("A title cannot be compared with itself")
    low, high = sorted((first, second))
    return low, high, f"{low}~{high}"


def parse_pair_key(pair_key: str) -> tuple[str, str]:
    parts = pair_key.split("~")
    if len(parts) != 2 or any(len(part) != 36 for part in parts):
        raise RatingNotFound("Comparison pair not found")
    low, high, canonical = canonical_pair(parts[0], parts[1])
    if canonical != pair_key:
        raise RatingNotFound("Comparison pair not found")
    return low, high


class RatingComparisonService:
    def __init__(
        self,
        session: Session,
        *,
        enabled: bool,
        principal: Principal | None = None,
    ):
        self.session = session
        self.enabled = enabled
        self.user_id = current_user_id(session, principal)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RatingFeatureDisabled(
                "Advanced ratings are disabled. Enable them in Settings → Ratings & Rankings."
            )

    def _valid_entries(self, ids: tuple[str, str]) -> dict[str, WatchEntry]:
        entries = list(
            self.session.scalars(
                select(WatchEntry)
                .where(
                    WatchEntry.id.in_(ids),
                    WatchEntry.user_id == self.user_id,
                    WatchEntry.deleted_at.is_(None),
                    WatchEntry.personal_rating.is_not(None),
                )
                .options(selectinload(WatchEntry.catalog_item))
            )
        )
        if len(entries) != 2:
            raise RatingConflict("Both comparison titles must be rated and active")
        return {entry.id: entry for entry in entries}

    def next(
        self,
        *,
        cross_media: bool = False,
        session_size: int = 5,
        refinement_run_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        refinement = None
        if refinement_run_id:
            refinement = RatingRefinementService(self.session, enabled=True).get(
                refinement_run_id
            )
            if refinement["state"] != "active" or refinement["stage"] != "comparisons":
                return {"pair": None, "session_size": session_size, "refinement": refinement}
            refinement_targets = set(refinement.get("target_entry_ids") or [])
        else:
            refinement_targets = set()
        rows = AdvancedRankingService(self.session).calculate()
        if len(rows) < 2:
            return {
                "pair": None,
                "session_size": session_size,
                "refinement": refinement,
            }
        comparisons = list(
            self.session.scalars(
                select(RatingComparison).where(RatingComparison.user_id == self.user_id)
            )
        )
        existing = {(item.entry_low_id, item.entry_high_id): item for item in comparisons}
        counts: dict[str, int] = defaultdict(int)
        left_counts: dict[str, int] = defaultdict(int)
        for item in comparisons:
            left_counts[item.displayed_left_entry_id] += 1
            if item.result != "skip":
                counts[item.entry_low_id] += 1
                counts[item.entry_high_id] += 1
        now = datetime.now(UTC)
        candidates: list[tuple[Any, ...]] = []
        window = 8
        for index, row in enumerate(rows):
            for other in rows[index + 1 : index + 1 + window]:
                first: WatchEntry = row["entry"]
                second: WatchEntry = other["entry"]
                if len(refinement_targets) == 1 and not (
                    first.id in refinement_targets or second.id in refinement_targets
                ):
                    continue
                if (
                    not cross_media
                    and first.catalog_item.media_type != second.catalog_item.media_type
                ):
                    continue
                low, high, pair_key = canonical_pair(first.id, second.id)
                previous = existing.get((low, high))
                if previous and previous.result != "skip":
                    continue
                if previous and previous.skipped_until:
                    until = previous.skipped_until
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=UTC)
                    if until > now:
                        continue
                disagreement = max(
                    abs(row["rubric_adjustment"]), abs(other["rubric_adjustment"])
                )
                candidates.append(
                    (
                        abs(row["technical_score"] - other["technical_score"]),
                        counts[first.id] + counts[second.id],
                        -disagreement,
                        pair_key,
                        first,
                        second,
                    )
                )
        if not candidates:
            return {
                "pair": None,
                "session_size": session_size,
                "refinement": refinement,
            }
        _, _, disagreement, pair_key, first, second = min(candidates)
        if left_counts[first.id] < left_counts[second.id]:
            left, right = first, second
        elif left_counts[second.id] < left_counts[first.id]:
            left, right = second, first
        else:
            left, right = (first, second) if pair_key[-1] < "8" else (second, first)
        return {
            "pair": {
                "pair_key": pair_key,
                "left": serialize_entry(left, include_events=False),
                "right": serialize_entry(right, include_events=False),
                "selection_reason": (
                    "rubric_disagreement" if disagreement < 0 else "nearby_score"
                ),
            },
            "session_size": session_size,
            "refinement": refinement,
        }

    def put(self, pair_key: str, payload: RatingComparisonUpdate) -> dict[str, Any]:
        self._require_enabled()
        low, high = parse_pair_key(pair_key)
        self._valid_entries((low, high))
        if payload.refinement_run_id:
            refinement = RatingRefinementService(self.session, enabled=True).get(
                payload.refinement_run_id
            )
            if refinement["state"] != "active" or refinement["stage"] != "comparisons":
                raise RatingConflict("This refinement run is no longer accepting comparisons")
        if payload.displayed_left_entry_id not in {low, high}:
            raise RatingConflict("The displayed-left title must belong to this pair")
        comparison = self.session.scalar(
            select(RatingComparison).where(
                RatingComparison.user_id == self.user_id,
                RatingComparison.entry_low_id == low,
                RatingComparison.entry_high_id == high,
            )
        )
        now = utcnow()
        if comparison is None:
            comparison = RatingComparison(
                user_id=self.user_id,
                entry_low_id=low,
                entry_high_id=high,
                displayed_left_entry_id=payload.displayed_left_entry_id,
                result=payload.result,
                selection_reason="nearby_score",
            )
            self.session.add(comparison)
        else:
            comparison.displayed_left_entry_id = payload.displayed_left_entry_id
            comparison.result = payload.result
            comparison.updated_at = now
        comparison.skipped_until = (
            now + timedelta(days=30) if payload.result == "skip" else None
        )
        self.session.commit()
        refinement = None
        if payload.refinement_run_id:
            refinement = RatingRefinementService(self.session, enabled=True).record_comparison(
                payload.refinement_run_id, pair_key
            )
        return {
            "id": comparison.id,
            "pair_key": pair_key,
            "entry_low_id": low,
            "entry_high_id": high,
            "displayed_left_entry_id": comparison.displayed_left_entry_id,
            "result": comparison.result,
            "selection_reason": comparison.selection_reason,
            "algorithm_version": comparison.algorithm_version,
            "created_at": comparison.created_at,
            "updated_at": comparison.updated_at,
            "refinement": refinement,
        }

    def delete(self, pair_key: str) -> None:
        self._require_enabled()
        low, high = parse_pair_key(pair_key)
        comparison = self.session.scalar(
            select(RatingComparison).where(
                RatingComparison.user_id == self.user_id,
                RatingComparison.entry_low_id == low,
                RatingComparison.entry_high_id == high,
            )
        )
        if not comparison:
            raise RatingNotFound("Comparison pair not found")
        self.session.delete(comparison)
        self.session.commit()


def advanced_rating_export(
    session: Session, principal: Principal | None = None
) -> dict[str, Any]:
    """Return the deliberate private structured export, including reflections."""
    user_id = current_user_id(session, principal)
    assessments = list(
        session.scalars(
            select(RatingAssessment)
            .join(WatchEntry, RatingAssessment.entry_id == WatchEntry.id)
            .where(WatchEntry.user_id == user_id)
            .order_by(RatingAssessment.created_at, RatingAssessment.id)
        )
    )
    comparisons = list(
        session.scalars(
            select(RatingComparison)
            .where(RatingComparison.user_id == user_id)
            .order_by(RatingComparison.created_at, RatingComparison.id)
        )
    )
    runs = list(
        session.scalars(
            select(RatingRefinementRun)
            .order_by(RatingRefinementRun.created_at, RatingRefinementRun.id)
            .where(RatingRefinementRun.user_id == user_id)
        )
    )
    return {
        "format": "personal-media-tracker-advanced-ratings",
        "format_version": 1,
        "private_data_notice": (
            "This export contains guided answers and may contain private reflections."
        ),
        "rubric": rubric_contract(),
        "ranking_algorithm": RANKING_VERSION,
        "assessments": [assessment_payload(item) for item in assessments],
        "comparisons": [
            {
                "id": item.id,
                "pair_key": f"{item.entry_low_id}~{item.entry_high_id}",
                "entry_low_id": item.entry_low_id,
                "entry_high_id": item.entry_high_id,
                "displayed_left_entry_id": item.displayed_left_entry_id,
                "dimension": item.dimension,
                "result": item.result,
                "selection_reason": item.selection_reason,
                "algorithm_version": item.algorithm_version,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in comparisons
        ],
        "refinement_runs": [
            {
                "id": item.id,
                "scope": item.scope,
                "state": item.state,
                "stage": item.stage,
                "rubric_version": item.rubric_version,
                "ranking_version": item.ranking_version,
                "target_entry_ids": item.target_entry_ids,
                "completed_entry_ids": item.completed_entry_ids,
                "completed_pair_keys": item.completed_pair_keys,
                "comparison_target": item.comparison_target,
                "comparisons_completed": item.comparisons_completed,
                "assessment_target": item.assessment_target,
                "assessments_completed": item.assessments_completed,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in runs
        ],
    }
