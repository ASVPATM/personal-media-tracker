from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ENGINE_CONTRACT_VERSION = "recommendation-engine-v1"
SIGNAL_CONTRACT_VERSION = "preference-signal-v1"
STANDARD_ENGINE_VERSION = "scalar-v1"
STANDARD_WEIGHT_VERSION = "scalar-weights-v1"
SCORE_SCALE_VERSION = "bounded-affinity-v1"

MAX_SIGNALS = 2_000
MAX_EVIDENCE_ANCHORS = 500
MAX_CANDIDATES = 500
MAX_RESULTS = 100


class RunPhase(StrEnum):
    CHECKING_READINESS = "checking_readiness"
    PREPARING_SIGNALS = "preparing_signals"
    PREPARING_CANDIDATES = "preparing_candidates"
    CHECKING_METADATA = "checking_metadata"
    RETRIEVING = "retrieving"
    SCORING = "scoring"
    LLM_RERANKING = "llm_reranking"
    VALIDATING = "validating"
    SAVING = "saving"
    READY = "ready"


PHASE_PROGRESS: dict[RunPhase, int] = {
    RunPhase.CHECKING_READINESS: 4,
    RunPhase.PREPARING_SIGNALS: 14,
    RunPhase.PREPARING_CANDIDATES: 30,
    RunPhase.CHECKING_METADATA: 44,
    RunPhase.RETRIEVING: 58,
    RunPhase.SCORING: 76,
    RunPhase.VALIDATING: 88,
    RunPhase.SAVING: 96,
    RunPhase.READY: 100,
}

REGISTERED_REASON_CODES = frozenset(
    {
        "genre_affinity",
        "subgenre_affinity",
        "keyword_affinity",
        "language_affinity",
        "country_affinity",
        "format_affinity",
        "media_type_affinity",
        "public_quality",
        "provider_similarity",
        "confirmed_refinement_fit",
        "positive_rating_anchor",
        "favorite_anchor",
        "discovery_quality",
    }
)
REGISTERED_RISK_CODES = frozenset(
    {
        "limited_feedback",
        "sparse_metadata",
        "stale_candidates",
        "discovery_only",
        "provider_unavailable",
    }
)
REGISTERED_SIGNAL_DIMENSIONS = frozenset(
    {
        "item_preference",
        "favorite_item",
        "rewatch_item",
        "pairwise_preference",
        "refinement_engagement_pacing",
        "refinement_distinctiveness_freshness",
        "refinement_emotional_intellectual_intensity",
        "refinement_consistency_tolerance",
        "refinement_personal_significance",
        "refinement_return_desire",
        "refinement_commitment_fit",
        "pacing_tolerance",
        "freshness_preference",
        "intensity_preference",
        "consistency_preference",
        "personal_significance",
        "return_desire",
        "commitment_tolerance",
    }
)
REGISTERED_CONTRIBUTION_CODES = REGISTERED_REASON_CODES | frozenset({"scalar", "tower", "llm"})


def clamp01(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("score must be finite")
    return min(1.0, max(0.0, float(value)))


def display_match(value: float) -> int:
    bounded = clamp01(value)
    return int(
        (Decimal(str(bounded)) * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


BoundedFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
CatalogId = Annotated[str, Field(min_length=1, max_length=80)]
FeatureValue = Annotated[str, Field(min_length=1, max_length=100)]
REGISTERED_TASTE_EVIDENCE = frozenset(
    {
        "engagement_pacing",
        "distinctiveness_freshness",
        "emotional_intellectual_intensity",
        "consistency_tolerance",
        "personal_significance",
        "return_desire",
        "commitment_fit",
    }
)


class PreferenceSignal(ContractModel):
    signal_contract: Literal["preference-signal-v1"] = SIGNAL_CONTRACT_VERSION
    dimension: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    value: BoundedFloat
    strength: BoundedFloat
    confidence: BoundedFloat
    polarity: Literal["positive", "negative", "neutral"]
    source: Literal[
        "personal_rating",
        "favorite",
        "rewatch",
        "completed_refinement",
        "pairwise_comparison",
        "confirmed_claim",
    ]
    source_catalog_ids: list[CatalogId] = Field(default_factory=list, max_length=20)
    user_confirmed: bool
    source_revision: int = Field(ge=1)
    model_id: str | None = Field(default=None, max_length=160)

    @field_validator("dimension")
    @classmethod
    def registered_dimension(cls, value: str) -> str:
        if value not in REGISTERED_SIGNAL_DIMENSIONS:
            raise ValueError("unregistered signal dimension")
        return value

    @model_validator(mode="after")
    def require_confirmation(self):
        if self.source == "confirmed_claim" and not self.user_confirmed:
            raise ValueError("durable inferred claims require confirmation")
        return self


class EngineCandidate(ContractModel):
    catalog_id: CatalogId
    title: str = Field(min_length=1, max_length=500)
    media_type: Literal["movie", "tv", "anime"]
    genres: list[FeatureValue] = Field(default_factory=list, max_length=30)
    subgenres: list[FeatureValue] = Field(default_factory=list, max_length=30)
    keywords: list[FeatureValue] = Field(default_factory=list, max_length=50)
    language: str | None = Field(default=None, max_length=30)
    country: str | None = Field(default=None, max_length=100)
    provider_format: str | None = Field(default=None, max_length=50)
    public_score: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    source_score: BoundedFloat = 0.5
    taste_evidence: dict[str, BoundedFloat] = Field(default_factory=dict, max_length=30)

    @field_validator("taste_evidence")
    @classmethod
    def known_taste_dimensions(cls, value: dict[str, float]) -> dict[str, float]:
        if unknown := set(value) - REGISTERED_TASTE_EVIDENCE:
            raise ValueError(f"unknown taste-evidence dimension: {sorted(unknown)[0]}")
        return value


class EvidenceAnchor(ContractModel):
    """Frozen, non-display metadata used to interpret one evidence catalog ID.

    Titles, notes, reflections, and other private/free-form fields are deliberately
    absent.  Engines must not resolve these identifiers against the mutable catalog.
    """

    catalog_id: CatalogId
    media_type: Literal["movie", "tv", "anime"]
    genres: list[FeatureValue] = Field(default_factory=list, max_length=30)
    subgenres: list[FeatureValue] = Field(default_factory=list, max_length=30)
    keywords: list[FeatureValue] = Field(default_factory=list, max_length=50)
    language: str | None = Field(default=None, max_length=30)
    country: str | None = Field(default=None, max_length=100)
    provider_format: str | None = Field(default=None, max_length=50)


class EngineRequest(ContractModel):
    contract_version: Literal["recommendation-engine-v1"] = ENGINE_CONTRACT_VERSION
    request_id: str = Field(min_length=1, max_length=80)
    engine: Literal["scalar", "advanced_hybrid"] = "scalar"
    input_revision: int = Field(ge=1)
    deterministic_seed: int = Field(ge=0, le=2**31 - 1)
    signals: list[PreferenceSignal] = Field(max_length=MAX_SIGNALS)
    evidence_anchors: list[EvidenceAnchor] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ANCHORS
    )
    candidates: list[EngineCandidate] = Field(max_length=MAX_CANDIDATES)
    limit: int = Field(default=40, ge=1, le=MAX_RESULTS)

    @field_validator("candidates")
    @classmethod
    def unique_candidates(cls, value: list[EngineCandidate]) -> list[EngineCandidate]:
        identifiers = [item.catalog_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate catalog IDs must be unique")
        return value

    @model_validator(mode="after")
    def valid_evidence_anchors(self):
        anchor_ids = [item.catalog_id for item in self.evidence_anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("evidence anchor catalog IDs must be unique")
        permitted = set(anchor_ids)
        referenced = {
            catalog_id for signal in self.signals for catalog_id in signal.source_catalog_ids
        }
        if not referenced.issubset(permitted):
            raise ValueError("every signal catalog ID requires a frozen evidence anchor")
        return self


class EngineResultItem(ContractModel):
    catalog_id: CatalogId
    rank: int = Field(ge=1, le=MAX_RESULTS)
    match: BoundedFloat
    confidence: BoundedFloat
    contributions: dict[str, BoundedFloat] = Field(default_factory=dict, max_length=20)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)
    anchor_catalog_ids: list[CatalogId] = Field(default_factory=list, max_length=10)
    risk_codes: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("reason_codes")
    @classmethod
    def known_reasons(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("reason codes must be unique")
        if unknown := set(value) - REGISTERED_REASON_CODES:
            raise ValueError(f"unknown reason code: {sorted(unknown)[0]}")
        return value

    @field_validator("risk_codes")
    @classmethod
    def known_risks(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("risk codes must be unique")
        if unknown := set(value) - REGISTERED_RISK_CODES:
            raise ValueError(f"unknown risk code: {sorted(unknown)[0]}")
        return value

    @field_validator("anchor_catalog_ids")
    @classmethod
    def unique_anchors(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("anchor catalog IDs must be unique")
        return value

    @field_validator("contributions")
    @classmethod
    def known_contributions(cls, value: dict[str, float]) -> dict[str, float]:
        if unknown := set(value) - REGISTERED_CONTRIBUTION_CODES:
            raise ValueError(f"unknown contribution code: {sorted(unknown)[0]}")
        return value


class EngineResponse(ContractModel):
    contract_version: Literal["recommendation-engine-v1"] = ENGINE_CONTRACT_VERSION
    request_id: str = Field(min_length=1, max_length=80)
    engine: Literal["scalar", "advanced_hybrid"] = "scalar"
    model_versions: dict[str, str | None] = Field(max_length=12)
    input_revision: int = Field(ge=1)
    results: list[EngineResultItem] = Field(max_length=MAX_RESULTS)

    @model_validator(mode="after")
    def valid_result_set(self):
        ids = [item.catalog_id for item in self.results]
        ranks = [item.rank for item in self.results]
        if len(ids) != len(set(ids)) or ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("engine results require unique IDs and contiguous ranks")
        return self

    @field_validator("model_versions")
    @classmethod
    def known_model_versions(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        allowed = {"scalar", "weights", "score_scale", "tower", "llm", "adapter", "prompt"}
        if unknown := set(value) - allowed:
            raise ValueError(f"unknown model version key: {sorted(unknown)[0]}")
        for key, version in value.items():
            if version is not None and not 1 <= len(version) <= 160:
                raise ValueError(f"invalid model version for {key}")
        return value


def validate_engine_response(
    response: EngineResponse,
    *,
    permitted_catalog_ids: set[str],
    permitted_anchor_ids: set[str],
    input_revision: int,
    request_id: str,
    engine: str,
    result_limit: int = MAX_RESULTS,
) -> EngineResponse:
    if response.request_id != request_id or response.engine != engine:
        raise ValueError("engine response does not match its request")
    if response.input_revision != input_revision:
        raise ValueError("engine response uses a stale input revision")
    if response.contract_version != ENGINE_CONTRACT_VERSION:
        raise ValueError("engine response uses an unsupported contract version")
    if response.engine == "scalar":
        expected_versions = {
            "scalar": STANDARD_ENGINE_VERSION,
            "weights": STANDARD_WEIGHT_VERSION,
            "score_scale": SCORE_SCALE_VERSION,
            "tower": None,
            "llm": None,
        }
        if response.model_versions != expected_versions:
            raise ValueError("engine response uses unsupported Standard model versions")
    if len(response.results) > result_limit:
        raise ValueError("engine returned more results than requested")
    if any(item.catalog_id not in permitted_catalog_ids for item in response.results):
        raise ValueError("engine returned an unknown candidate")
    if any(
        anchor not in permitted_anchor_ids
        for item in response.results
        for anchor in item.anchor_catalog_ids
    ):
        raise ValueError("engine returned an unpermitted evidence anchor")
    ordered = sorted(
        response.results,
        key=lambda item: (-item.match, -item.confidence, item.catalog_id),
    )
    if [item.catalog_id for item in ordered] != [item.catalog_id for item in response.results]:
        raise ValueError("engine results are not in stable descending order")
    return response


def canonical_json_value(value: Any) -> Any:
    """Normalize JSON-compatible values before stable hashing/export."""

    if isinstance(value, dict):
        return {str(key): canonical_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_json_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite contract value")
        return round(value, 8)
    return value
