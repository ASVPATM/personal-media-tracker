from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import BigInteger, func, select
from sqlalchemy.exc import IntegrityError

from watchtracker.authorization import Principal, current_user_id
from watchtracker.build_manifest import BUILD_MANIFEST
from watchtracker.imports.service import ImportService
from watchtracker.integrations import IntegrationEventInput
from watchtracker.metadata.http import ProviderError
from watchtracker.models import (
    CatalogItem,
    CatalogMetadataSource,
    ExternalIdentity,
    IntegrationConnection,
    IntegrationRun,
    RatingAssessment,
    RecommendationCandidateSnapshot,
    RecommendationFeedback,
    RecommendationResult,
    RecommendationRun,
    RecommendationSignalSnapshot,
    ScheduledJob,
    UserAccount,
    UserRecommendationPreference,
    WatchEntry,
)
from watchtracker.recommendations.candidates import (
    TVMazeCatalogSource,
    candidate_snapshot,
)
from watchtracker.recommendations.contract import (
    ENGINE_CONTRACT_VERSION,
    EngineCandidate,
    EngineRequest,
    EngineResponse,
    EngineResultItem,
    EvidenceAnchor,
    PreferenceSignal,
    display_match,
    validate_engine_response,
)
from watchtracker.recommendations.evaluation import (
    catalog_coverage,
    genre_coverage,
    intra_list_genre_diversity,
    mean_novelty,
    ndcg_at_k,
    popularity_bias,
    positive_negative_pair_accuracy,
    recall_at_k,
    reciprocal_rank,
    repeated_run_stability,
    result_field_coverage,
)
from watchtracker.recommendations.scalar import engine_candidates, score_candidates
from watchtracker.recommendations.service import RecommendationNotFound
from watchtracker.recommendations.signals import project_signals, signal_snapshot
from watchtracker.schemas import CatalogData, EntryOptions, PortableListTitle
from watchtracker.services.entries import (
    EntryConflict,
    EntryNotFound,
    EntryService,
    refresh_catalog_taxonomy,
)
from watchtracker.services.integrations import IntegrationCoordinator
from watchtracker.services.jobs import DurableJobRunner, DurableJobService
from watchtracker.services.lists import MediaListService
from watchtracker.services.ratings import RUBRIC_VERSION
from watchtracker.taxonomy import INFERENCE_VERSION, infer_taxonomy


def _catalog(
    title: str,
    *,
    provider_id: str,
    genres: list[str],
    public_score: float,
    runtime: int | None = 100,
) -> CatalogItem:
    return CatalogItem(
        canonical_title=title,
        normalized_title=title.casefold(),
        release_year=2025,
        media_type="movie",
        provider_source="tmdb_movie",
        provider_id=provider_id,
        provider_genres=genres,
        normalized_genres=genres,
        inferred_subgenres=[],
        keywords=["character study"],
        language="en",
        country="US",
        runtime_minutes=runtime,
        public_score=public_score,
        poster_url=f"https://images.invalid/{provider_id}.jpg",
        overview=f"Synthetic metadata for {title}.",
        metadata_source="fixture",
        metadata_provenance={
            "source": "synthetic",
            "provider_identity_verified": True,
            "provider_identity_source": "tmdb_movie",
        },
        metadata_field_sources={},
        taste_evidence={},
    )


def _seed_recommendation_fixture(app) -> tuple[str, list[str]]:
    with app.state.session_factory() as session:
        user_id = current_user_id(session)
        anchors = [
            _catalog("Loved Drama", provider_id="owned-1", genres=["Drama"], public_score=8),
            _catalog(
                "Liked Mystery", provider_id="owned-2", genres=["Mystery"], public_score=7
            ),
            _catalog(
                "Disliked Comedy", provider_id="owned-3", genres=["Comedy"], public_score=6
            ),
        ]
        candidates = [
            _catalog(
                "Drama Match", provider_id="candidate-1", genres=["Drama"], public_score=8
            ),
            _catalog(
                "Mystery Match", provider_id="candidate-2", genres=["Mystery"], public_score=7
            ),
            _catalog(
                "Comedy Risk", provider_id="candidate-3", genres=["Comedy"], public_score=9
            ),
        ]
        session.add_all([*anchors, *candidates])
        session.flush()
        for item, rating, favorite in zip(
            anchors, (9.5, 8.0, 2.0), (True, False, False), strict=True
        ):
            session.add(
                WatchEntry(
                    user_id=user_id,
                    catalog_item_id=item.id,
                    status="watched",
                    personal_rating=rating,
                    view_count=1,
                    is_favorite=favorite,
                )
            )
        session.commit()
        return user_id, [item.id for item in candidates]


def _finish(app, user_id: str, run_id: str) -> None:
    asyncio.run(app.state.recommendations.generate(run_id, user_id))


def _model_versions() -> dict[str, str | None]:
    return {
        "scalar": "scalar-v1",
        "weights": "scalar-weights-v1",
        "score_scale": "bounded-affinity-v1",
        "tower": None,
        "llm": None,
    }


def _request_from_snapshots(
    signal: RecommendationSignalSnapshot,
    candidates: RecommendationCandidateSnapshot,
    *,
    request_id: str = "snapshot-request",
) -> EngineRequest:
    return EngineRequest(
        request_id=request_id,
        engine="scalar",
        input_revision=signal.source_revision,
        deterministic_seed=0,
        signals=[PreferenceSignal.model_validate(value) for value in signal.signals],
        evidence_anchors=[
            EvidenceAnchor.model_validate(value) for value in signal.evidence_anchors
        ],
        candidates=engine_candidates(list(candidates.items)),
        limit=40,
    )


def test_standard_manifest_and_strict_contract_bounds():
    manifest = BUILD_MANIFEST.as_dict()
    assert manifest["distribution_flavor"] == "standard"
    assert manifest["recommendation_capabilities"] == ["scalar-v1"]
    assert manifest["base_version"]
    assert isinstance(RecommendationSignalSnapshot.__table__.c.source_revision.type, BigInteger)
    assert isinstance(RecommendationRun.__table__.c.input_revision.type, BigInteger)
    assert display_match(0.845) == 85
    with pytest.raises(ValidationError, match="unregistered signal dimension"):
        PreferenceSignal(
            dimension="arbitrary_database_key",
            value=0.5,
            strength=0.5,
            confidence=0.5,
            polarity="neutral",
            source="confirmed_claim",
            source_catalog_ids=[],
            user_confirmed=True,
            source_revision=1,
        )

    response = EngineResponse(
        contract_version=ENGINE_CONTRACT_VERSION,
        request_id="request-1",
        engine="scalar",
        model_versions=_model_versions(),
        input_revision=2,
        results=[
            EngineResultItem(
                catalog_id="candidate-1",
                rank=1,
                match=0.8,
                confidence=0.7,
                contributions={"scalar": 0.8},
                reason_codes=["genre_affinity"],
                anchor_catalog_ids=["private-anchor"],
            )
        ],
    )
    with pytest.raises(ValueError, match="unpermitted evidence anchor"):
        validate_engine_response(
            response,
            permitted_catalog_ids={"candidate-1"},
            permitted_anchor_ids=set(),
            input_revision=2,
            request_id="request-1",
            engine="scalar",
        )


def test_standard_ignores_unsupported_advanced_state_without_destroying_it(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    now = datetime.now(UTC)
    with client.app.state.session_factory() as session:
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        preferences.engine = "advanced_hybrid"
        preferences.local_llm_enabled = True
        advanced_completed = RecommendationRun(
            user_id=user_id,
            distribution_flavor="recommendations-beta",
            engine="advanced_hybrid",
            engine_version="advanced-hybrid-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={"tower": "two-tower-v1", "llm": "local-v1"},
            input_revision=1,
            deterministic_seed=1,
            idempotency_key="advanced:completed",
            state="completed",
            phase="ready",
            progress_percent=100,
            progress_indeterminate=False,
            message_key="recommendations.progress.ready",
            retryable=False,
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(minutes=1),
            completed_at=now - timedelta(minutes=1),
        )
        advanced_queued = RecommendationRun(
            user_id=user_id,
            distribution_flavor="recommendations-beta",
            engine="advanced_hybrid",
            engine_version="advanced-hybrid-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={"tower": "two-tower-v1", "llm": "local-v1"},
            input_revision=1,
            deterministic_seed=2,
            idempotency_key="advanced:queued",
            state="queued",
            phase="llm_reranking",
            progress_percent=60,
            progress_indeterminate=True,
            message_key="recommendations.progress.llm_reranking",
            retryable=True,
            created_at=now,
            updated_at=now,
        )
        session.add_all([advanced_completed, advanced_queued])
        session.commit()
        completed_id = advanced_completed.id
        queued_id = advanced_queued.id

    effective = client.get("/api/v1/recommendations/preferences")
    assert effective.status_code == 200
    assert effective.json()["engine"] == "scalar"
    assert effective.json()["local_llm_enabled"] is False
    changed = client.put("/api/v1/recommendations/preferences", json={"use_rewatches": True})
    assert changed.status_code == 200
    assert changed.json()["engine"] == "scalar"
    with client.app.state.session_factory() as session:
        stored = session.get(UserRecommendationPreference, user_id)
        assert stored.engine == "advanced_hybrid"
        assert stored.local_llm_enabled is True

    readiness = client.get("/api/v1/recommendations/readiness").json()
    assert readiness["active_run"] is None
    assert readiness["latest_run"] is None
    assert readiness["latest_completed_run"] is None
    assert (queued_id, user_id) not in client.app.state.recommendations.recover_pending()
    asyncio.run(client.app.state.recommendations.generate(queued_id, user_id))
    with client.app.state.session_factory() as session:
        assert session.get(RecommendationRun, queued_id).state == "queued"

    standard = client.post("/api/v1/recommendation-runs", json={})
    assert standard.status_code == 202
    assert standard.json()["engine"] == "scalar"
    _finish(client.app, user_id, standard.json()["id"])
    assert (
        client.get(f"/api/v1/recommendation-runs/{standard.json()['id']}").json()["state"]
        == "completed"
    )
    assert client.get(f"/api/v1/recommendation-runs/{completed_id}").status_code == 404
    with client.app.state.session_factory() as session:
        assert session.get(RecommendationRun, completed_id) is not None
        assert session.get(RecommendationRun, queued_id).state == "failed"
        assert session.get(RecommendationRun, queued_id).retryable is True


def test_standard_filters_scalar_shaped_hybrid_rows_on_every_selection_path(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        now = datetime.now(UTC)
        completed = RecommendationRun(
            user_id=user_id,
            distribution_flavor="recommendations-beta",
            engine="scalar",
            engine_version="scalar-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={
                "scalar": "scalar-v1",
                "tower": "two-tower-v1",
                "llm": None,
            },
            input_revision=1,
            deterministic_seed=11,
            idempotency_key="hybrid-shaped:completed",
            state="completed",
            phase="ready",
            progress_percent=100,
            progress_indeterminate=False,
            message_key="recommendations.progress.ready",
            retryable=False,
            completed_at=now,
        )
        active = RecommendationRun(
            user_id=user_id,
            distribution_flavor="recommendations-beta",
            engine="scalar",
            engine_version="scalar-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={"scalar": "scalar-v1", "adapter": "private-adapter"},
            input_revision=1,
            deterministic_seed=12,
            idempotency_key="hybrid-shaped:queued",
            state="queued",
            phase="checking_readiness",
            progress_percent=0,
            progress_indeterminate=False,
            message_key="recommendations.progress.checking_readiness",
            retryable=True,
        )
        session.add_all([completed, active])
        session.commit()
        completed_id = completed.id
        active_id = active.id

    readiness = client.get("/api/v1/recommendations/readiness").json()
    assert readiness["active_run"] is None
    assert readiness["latest_run"] is None
    assert readiness["latest_completed_run"] is None
    assert active_id not in client.app.state.recommendations.compatible_pending_run_ids()
    assert (active_id, user_id) not in client.app.state.recommendations.recover_pending()
    standard = client.post("/api/v1/recommendation-runs", json={})
    assert standard.status_code == 202
    assert standard.json()["id"] not in {completed_id, active_id}
    with client.app.state.session_factory() as session:
        assert session.get(RecommendationRun, active_id).state == "failed"


def test_database_enforces_one_active_recommendation_run_per_user_across_engines(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        standard = RecommendationRun(
            user_id=user_id,
            distribution_flavor="standard",
            engine="scalar",
            engine_version="scalar-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={"scalar": "scalar-v1"},
            input_revision=1,
            deterministic_seed=1,
            idempotency_key="one-active:standard",
            state="queued",
            phase="checking_readiness",
            progress_percent=0,
            progress_indeterminate=False,
            message_key="recommendations.progress.checking_readiness",
            retryable=True,
        )
        advanced = RecommendationRun(
            user_id=user_id,
            distribution_flavor="recommendations-beta",
            engine="advanced_hybrid",
            engine_version="advanced-hybrid-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={"tower": "two-tower-v1"},
            input_revision=1,
            deterministic_seed=2,
            idempotency_key="one-active:advanced",
            state="running",
            phase="scoring",
            progress_percent=55,
            progress_indeterminate=True,
            message_key="recommendations.progress.scoring",
            retryable=False,
        )
        session.add(standard)
        session.flush()
        session.add(advanced)
        with pytest.raises(IntegrityError):
            session.flush()


def test_capability_paused_job_resumes_only_for_a_compatible_scope(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        run = RecommendationRun(
            user_id=user_id,
            distribution_flavor="standard",
            engine="scalar",
            engine_version="scalar-v1",
            signal_contract_version="preference-signal-v1",
            score_scale_version="bounded-affinity-v1",
            model_versions={"scalar": "scalar-v1"},
            input_revision=1,
            deterministic_seed=3,
            idempotency_key="capability-resume:run",
            state="failed",
            phase="scoring",
            progress_percent=55,
            progress_indeterminate=False,
            message_key="recommendations.failure.generation_failed",
            failure_code="generation_failed",
            retryable=True,
            safe_failure_detail="Different capability required.",
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()
    paused = client.app.state.durable_jobs.enqueue(
        "recommendation.generate",
        idempotency_key="capability-resume:job",
        user_id=user_id,
        scope_type="recommendation_run",
        scope_id=run_id,
        payload={"run_id": run_id, "user_id": user_id},
    )
    ordinary = client.app.state.durable_jobs.enqueue(
        "recommendation.generate",
        idempotency_key="capability-resume:ordinary",
        user_id=user_id,
        scope_type="recommendation_run",
        scope_id="00000000-0000-0000-0000-000000009997",
        payload={"safe": True},
    )
    with client.app.state.session_factory() as session:
        paused_row = session.get(ScheduledJob, paused.id)
        paused_row.state = "paused"
        paused_row.last_error_code = "capability_unavailable"
        ordinary_row = session.get(ScheduledJob, ordinary.id)
        ordinary_row.state = "paused"
        ordinary_row.last_error_code = "retryable_failure"
        session.commit()
    resumed = client.app.state.durable_jobs.resume_capability_scopes(
        kind="recommendation.generate",
        scope_type="recommendation_run",
        scope_ids=client.app.state.recommendations.compatible_recoverable_run_ids(),
    )
    assert resumed == {run_id}
    recovered = client.app.state.recommendations.recover_pending(capability_resumed_ids=resumed)
    assert recovered == [(run_id, user_id)]
    with client.app.state.session_factory() as session:
        assert session.get(RecommendationRun, run_id).state == "queued"
        assert session.get(ScheduledJob, paused.id).state == "scheduled"
        assert session.get(ScheduledJob, ordinary.id).state == "paused"


def test_engine_contract_rejects_unfrozen_unknown_and_oversized_values():
    signal = PreferenceSignal(
        dimension="item_preference",
        value=0.8,
        strength=0.8,
        confidence=0.9,
        polarity="positive",
        source="personal_rating",
        source_catalog_ids=["anchor-1"],
        user_confirmed=True,
        source_revision=1,
    )
    candidate = EngineCandidate(
        catalog_id="candidate-1",
        title="Candidate",
        media_type="movie",
        genres=["drama"],
    )
    with pytest.raises(ValidationError, match="frozen evidence anchor"):
        EngineRequest(
            request_id="request-1",
            input_revision=1,
            deterministic_seed=0,
            signals=[signal],
            evidence_anchors=[],
            candidates=[candidate],
        )
    with pytest.raises(ValidationError, match="unknown taste-evidence"):
        EngineCandidate(
            catalog_id="candidate-1",
            title="Candidate",
            media_type="movie",
            taste_evidence={"arbitrary": 0.5},
        )
    with pytest.raises(ValidationError):
        EngineCandidate(
            catalog_id="candidate-1",
            title="Candidate",
            media_type="movie",
            genres=["x" * 101],
        )
    with pytest.raises(ValidationError, match="reason codes must be unique"):
        EngineResultItem(
            catalog_id="candidate-1",
            rank=1,
            match=0.8,
            confidence=0.4,
            reason_codes=["genre_affinity", "genre_affinity"],
        )
    with pytest.raises(ValidationError, match="unknown model version key"):
        EngineResponse(
            request_id="request-1",
            engine="scalar",
            model_versions={"unknown": "v1"},
            input_revision=1,
            results=[],
        )

    response = EngineResponse(
        request_id="request-1",
        engine="scalar",
        model_versions={**_model_versions(), "scalar": "scalar-v0"},
        input_revision=1,
        results=[],
    )
    with pytest.raises(ValueError, match="unsupported Standard model versions"):
        validate_engine_response(
            response,
            permitted_catalog_ids=set(),
            permitted_anchor_ids=set(),
            input_revision=1,
            request_id="request-1",
            engine="scalar",
        )

    too_many = EngineResponse(
        request_id="request-1",
        engine="scalar",
        model_versions=_model_versions(),
        input_revision=1,
        results=[
            EngineResultItem(
                catalog_id="candidate-a",
                rank=1,
                match=0.8,
                confidence=0.4,
            ),
            EngineResultItem(
                catalog_id="candidate-b",
                rank=2,
                match=0.7,
                confidence=0.4,
            ),
        ],
    )
    with pytest.raises(ValueError, match="more results than requested"):
        validate_engine_response(
            too_many,
            permitted_catalog_ids={"candidate-a", "candidate-b"},
            permitted_anchor_ids=set(),
            input_revision=1,
            request_id="request-1",
            engine="scalar",
            result_limit=1,
        )


def test_one_button_standard_run_is_deterministic_explained_and_non_mutating(client):
    user_id, candidate_ids = _seed_recommendation_fixture(client.app)
    readiness = client.get("/api/v1/recommendations/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["useful_ratings"] == 3
    assert readiness.json()["candidate_count"] == 3

    queued = client.post("/api/v1/recommendation-runs", json={"result_limit": 3})
    assert queued.status_code == 202
    run_id = queued.json()["id"]
    duplicate = client.post("/api/v1/recommendation-runs", json={"result_limit": 3})
    assert duplicate.json()["id"] == run_id
    _finish(client.app, user_id, run_id)

    completed = client.get(f"/api/v1/recommendation-runs/{run_id}").json()
    assert completed["state"] == "completed"
    assert completed["progress_percent"] == 100
    assert completed["signal_contract_version"] == "preference-signal-v1"
    assert completed["score_scale_version"] == "bounded-affinity-v1"
    assert completed["model_versions"]["result_limit"] == 3
    result = client.get(f"/api/v1/recommendation-runs/{run_id}/results")
    assert result.status_code == 200
    payload = result.json()
    assert payload["personalized"] is True
    assert [row["match"] for row in payload["results"]] == sorted(
        [row["match"] for row in payload["results"]], reverse=True
    )
    assert payload["results"][0]["catalog_id"] == candidate_ids[0]
    assert all(
        row["reason_codes"] and 0 <= row["display_match"] <= 100 for row in payload["results"]
    )
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WatchEntry)) == 3

    second = client.post("/api/v1/recommendation-runs", json={"result_limit": 3}).json()
    _finish(client.app, user_id, second["id"])
    second_rows = client.get(f"/api/v1/recommendation-runs/{second['id']}/results").json()[
        "results"
    ]
    assert [row["catalog_id"] for row in second_rows] == [
        row["catalog_id"] for row in payload["results"]
    ]
    assert [row["match"] for row in second_rows] == [row["match"] for row in payload["results"]]


def test_recommendation_catalog_action_adds_offline_with_full_personal_options(client):
    _user_id, candidate_ids = _seed_recommendation_fixture(client.app)
    custom = client.post(
        f"/api/v1/catalog/{candidate_ids[0]}/library",
        json={
            "status": "watching",
            "personal_rating": 8.5,
            "notes": "offline catalog action",
            "user_tags": ["recommendation"],
            "view_count": 0,
        },
    )
    assert custom.status_code == 201
    assert custom.json()["entry"]["status"] == "watching"
    assert custom.json()["entry"]["personal_rating"] == 8.5
    assert custom.json()["entry"]["notes"] == "offline catalog action"
    assert custom.json()["entry"]["user_tags"] == ["recommendation"]
    plan = client.post(f"/api/v1/catalog/{candidate_ids[1]}/library")
    assert plan.status_code == 201
    assert plan.json()["entry"]["status"] == "plan_to_watch"
    assert plan.json()["entry"]["view_count"] == 0


def test_signal_and_candidate_snapshots_are_immutable_scoring_inputs(client):
    user_id, candidate_ids = _seed_recommendation_fixture(client.app)
    with client.app.state.session_factory() as session:
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        signal = signal_snapshot(session, user_id=user_id, preferences=preferences)
        candidates = asyncio.run(
            candidate_snapshot(
                session,
                user_id=user_id,
                preferences=preferences,
                signals=signal,
                live_source=None,
            )
        )
        signal_id = signal.id
        candidate_snapshot_id = candidates.id
        before_request = _request_from_snapshots(signal, candidates)
        before = score_candidates(request=before_request).model_dump(mode="json")
        anchor_id = signal.evidence_anchors[0]["catalog_id"]
        session.commit()

    with client.app.state.session_factory() as session:
        anchor = session.get(CatalogItem, anchor_id)
        candidate = session.get(CatalogItem, candidate_ids[0])
        anchor.normalized_genres = ["Mutation Sentinel"]
        anchor.provider_genres = ["Mutation Sentinel"]
        candidate.normalized_genres = ["Mutation Sentinel"]
        candidate.provider_genres = ["Mutation Sentinel"]
        candidate.public_score = 1
        session.commit()

    with client.app.state.session_factory() as session:
        signal = session.get(RecommendationSignalSnapshot, signal_id)
        candidates = session.get(RecommendationCandidateSnapshot, candidate_snapshot_id)
        after_request = _request_from_snapshots(signal, candidates)
        after = score_candidates(request=after_request).model_dump(mode="json")
    assert after == before


def test_tvmaze_catalog_is_bounded_sanitized_and_identity_coalesced(client):
    payload = [
        None,
        {"id": None, "name": "Missing identity"},
        {
            "id": 44,
            "name": "Existing Shared Show",
            "type": "Scripted",
            "premiered": "2024-01-01",
            "rating": {"average": 8.2},
            "genres": ["Drama"],
            "language": "English",
            "averageRuntime": 45,
            "url": "https://www.tvmaze.com/shows/44/existing",
        },
        {
            "id": 55,
            "name": "Safe New Show",
            "type": "Scripted",
            "premiered": "9999-01-01",
            "rating": {"average": float("nan")},
            "genres": ["Drama", "Drama", "x" * 200],
            "language": "x" * 100,
            "averageRuntime": 100_000,
            "image": {"original": "http://unsafe.invalid/poster.jpg"},
            "url": "javascript:unsafe",
        },
        {
            "id": 66,
            "name": "Authoritative Live Show",
            "type": "Scripted",
            "premiered": "2023-01-01",
            "rating": {"average": 7.5},
            "genres": ["Thriller"],
            "language": "English",
            "averageRuntime": 50,
            "image": {"original": "https://images.invalid/live-66.jpg"},
            "url": "https://www.tvmaze.com/shows/66/authoritative",
        },
        {
            "id": 67,
            "name": "Rich Existing Anime",
            "type": "Animation",
            "premiered": "2020-01-01",
            "rating": {"average": 9.1},
            "genres": [],
            "image": {"original": "https://images.invalid/refreshed-67.jpg"},
            "url": "https://www.tvmaze.com/shows/67/rich-existing",
        },
    ]

    class MemoryCache:
        def get(self, _key):
            return payload

        def set(self, _key, _value):
            raise AssertionError("cached fixture should not write")

    tvmaze = SimpleNamespace(
        cache=MemoryCache(),
        http=object(),
        headers={"User-Agent": "PMT synthetic test"},
        base_url="https://api.tvmaze.com",
    )
    source = TVMazeCatalogSource(SimpleNamespace(tvmaze=tvmaze))
    with client.app.state.session_factory() as session:
        existing = _catalog(
            "Existing Shared Show",
            provider_id="tmdb-existing",
            genres=["Drama"],
            public_score=8,
        )
        existing.provider_source = "tmdb_tv"
        session.add(existing)
        session.flush()
        session.add(
            ExternalIdentity(
                catalog_item_id=existing.id,
                namespace="tvmaze",
                external_id="44",
                provenance="synthetic",
                confidence=1,
                verified_at=datetime.now(UTC),
            )
        )
        preclaimed = CatalogItem(
            canonical_title="attacker-live-title-sentinel",
            normalized_title="attacker live title sentinel",
            media_type="tv",
            provider_source="tvmaze",
            provider_id="66",
            poster_url="https://private.invalid/live-sentinel.jpg",
            overview="attacker-live-overview-sentinel",
            provider_genres=["Attacker Genre"],
            normalized_genres=["Attacker Genre"],
            inferred_subgenres=["Attacker Subgenre"],
            keywords=["attacker-live-keyword"],
            metadata_source="manual",
            metadata_provenance={},
            metadata_field_sources={},
            taste_evidence={"attacker": 1},
            raw_provider_payload={"attacker": "sentinel"},
        )
        session.add(preclaimed)
        session.flush()
        session.add_all(
            [
                ExternalIdentity(
                    catalog_item_id=preclaimed.id,
                    namespace="anilist",
                    external_id="attacker-live-identity",
                    provenance="catalog",
                    confidence=1,
                ),
                CatalogMetadataSource(
                    catalog_item_id=preclaimed.id,
                    provider="attacker",
                    provider_id="sentinel",
                    normalized_data={"attacker": "sentinel"},
                    external_ids={"anilist": "attacker-live-identity"},
                ),
            ]
        )
        rich = CatalogItem(
            canonical_title="Rich Existing Anime",
            normalized_title="rich existing anime",
            release_year=2020,
            release_date=date(2020, 1, 1),
            media_type="anime",
            provider_format="Anime",
            provider_source="tvmaze",
            provider_id="67",
            poster_url="https://images.invalid/old-67.jpg",
            overview="Rich overview must survive the shallow index refresh.",
            provider_genres=["Drama"],
            normalized_genres=["Drama"],
            inferred_subgenres=["Character Drama"],
            keywords=["rich-keyword"],
            episode_count=24,
            public_score=6.0,
            metadata_source="tvmaze",
            metadata_provenance={
                "provider_identity_verified": True,
                "provider_identity_source": "tvmaze",
            },
            metadata_field_sources={"overview": "tvmaze"},
            taste_evidence={},
        )
        session.add(rich)
        session.flush()
        session.add(
            ExternalIdentity(
                catalog_item_id=rich.id,
                namespace="tvmaze",
                external_id="67",
                provenance="provider_detail",
                confidence=1,
                verified_at=datetime.now(UTC),
            )
        )
        session.commit()
        touched = asyncio.run(source.refresh(session, limit=60))
        session.commit()
        assert touched == 4
        assert (
            session.scalar(
                select(func.count())
                .select_from(CatalogItem)
                .where(
                    CatalogItem.provider_source == "tvmaze",
                    CatalogItem.provider_id == "44",
                )
            )
            == 0
        )
        new = session.scalar(
            select(CatalogItem).where(
                CatalogItem.provider_source == "tvmaze",
                CatalogItem.provider_id == "55",
            )
        )
        assert new is not None
        assert new.release_year is None
        assert new.public_score is None
        assert new.runtime_minutes is None
        assert new.poster_url is None
        assert len(new.language) == 30
        assert new.provider_genres == ["Drama", "x" * 100]
        assert new.metadata_provenance["license_url"].startswith("https://")
        assert new.metadata_provenance["show_url"] is None
        promoted = session.scalar(
            select(CatalogItem).where(
                CatalogItem.provider_source == "tvmaze",
                CatalogItem.provider_id == "66",
            )
        )
        assert promoted.canonical_title == "Authoritative Live Show"
        assert promoted.poster_url == "https://images.invalid/live-66.jpg"
        assert promoted.overview is None
        assert promoted.provider_genres == ["Thriller"]
        assert promoted.keywords == []
        assert promoted.raw_provider_payload is None
        assert promoted.metadata_provenance["provider_identity_verified"] is True
        promoted_identities = list(
            session.scalars(
                select(ExternalIdentity).where(ExternalIdentity.catalog_item_id == promoted.id)
            )
        )
        promoted_sources = list(
            session.scalars(
                select(CatalogMetadataSource).where(
                    CatalogMetadataSource.catalog_item_id == promoted.id
                )
            )
        )
        assert {(row.namespace, row.external_id) for row in promoted_identities} == {
            ("tvmaze", "66")
        }
        assert {(row.provider, row.provider_id) for row in promoted_sources} == {
            ("tvmaze", "66")
        }
        assert (
            "attacker"
            not in str(
                [row.normalized_data for row in promoted_sources]
                + [row.external_ids for row in promoted_sources]
            ).casefold()
        )
        session.refresh(rich)
        assert rich.poster_url == "https://images.invalid/refreshed-67.jpg"
        assert rich.public_score == 9.1
        assert rich.media_type == "anime"
        assert rich.overview == "Rich overview must survive the shallow index refresh."
        assert rich.release_date == date(2020, 1, 1)
        assert rich.episode_count == 24
        assert rich.provider_genres == ["Drama"]
        assert rich.inferred_subgenres == ["Character Drama"]
        assert rich.keywords == ["rich-keyword"]


def test_tvmaze_refresh_reuses_concurrently_inserted_identity_after_stale_read(
    client, monkeypatch
):
    payload = [
        {
            "id": 77,
            "name": "Concurrent Show",
            "type": "Scripted",
            "premiered": "2024-01-01",
            "rating": {"average": 8},
            "genres": ["Drama"],
        }
    ]

    class MemoryCache:
        def get(self, _key):
            return payload

        def set(self, _key, _value):
            return None

    source = TVMazeCatalogSource(
        SimpleNamespace(
            tvmaze=SimpleNamespace(
                cache=MemoryCache(),
                http=object(),
                headers={"User-Agent": "PMT synthetic test"},
                base_url="https://api.tvmaze.com",
            )
        )
    )
    with client.app.state.session_factory() as session:
        winner = CatalogItem(
            canonical_title="Concurrent Show",
            normalized_title="concurrent show",
            media_type="tv",
            provider_source="tmdb_tv",
            provider_id="tmdb-concurrent-77",
            provider_genres=["Drama"],
            normalized_genres=["Drama"],
            inferred_subgenres=[],
            keywords=[],
            metadata_source="tvmaze",
            metadata_provenance={
                "provider_identity_verified": True,
                "provider_identity_source": "tvmaze",
            },
            metadata_field_sources={},
            taste_evidence={},
        )
        session.add(winner)
        session.flush()
        session.add(
            ExternalIdentity(
                catalog_item_id=winner.id,
                namespace="tvmaze",
                external_id="77",
                provenance="recommendation_catalog",
                confidence=1,
            )
        )
        session.commit()
        real_scalar = session.scalar
        stale_reads = 0

        def scalar_with_concurrent_stale_read(statement, *args, **kwargs):
            nonlocal stale_reads
            if stale_reads < 2:
                stale_reads += 1
                return None
            return real_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", scalar_with_concurrent_stale_read)
        assert asyncio.run(source.refresh(session, limit=1)) == 1
        session.commit()
        assert (
            session.scalar(
                select(func.count())
                .select_from(CatalogItem)
                .where(
                    CatalogItem.provider_source == "tvmaze",
                    CatalogItem.provider_id == "77",
                )
            )
            == 0
        )
        assert session.scalar(select(func.count()).select_from(CatalogItem)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExternalIdentity)
                .where(
                    ExternalIdentity.namespace == "tvmaze",
                    ExternalIdentity.external_id == "77",
                )
            )
            == 1
        )


def test_stale_large_catalog_uses_last_good_snapshot_on_provider_outage(client):
    class FailedLiveSource:
        async def refresh(self, _session, *, limit):
            del limit
            raise ProviderError("TVmaze", "synthetic outage", retryable=True)

    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        old = datetime.now(UTC) - timedelta(days=4)
        rows = [
            _catalog(
                f"Stale candidate {index}",
                provider_id=f"stale-{index}",
                genres=[("Drama", "Comedy", "Anime")[index % 3]],
                public_score=6 + index % 3,
            )
            for index in range(30)
        ]
        for row in rows:
            row.media_type = ("movie", "tv", "anime")[int(row.provider_id.split("-")[1]) % 3]
            row.metadata_fetched_at = old
        session.add_all(rows)
        session.flush()
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        signal = signal_snapshot(session, user_id=user_id, preferences=preferences)
        snapshot = asyncio.run(
            candidate_snapshot(
                session,
                user_id=user_id,
                preferences=preferences,
                signals=signal,
                live_source=FailedLiveSource(),
            )
        )
        session.commit()
        assert len(snapshot.items) == 30
        assert snapshot.fallback_used is True
        assert "provider_unavailable" in snapshot.warning_codes
        assert "stale_candidates" in snapshot.warning_codes
        assert snapshot.coverage["stale"] == 30


def test_discovery_only_result_never_claims_supported_personal_match(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        unrelated = _catalog(
            "Unrelated high public score",
            provider_id="unrelated-public",
            genres=["Comedy"],
            public_score=10,
        )
        session.add(unrelated)
        session.flush()
        unrelated_id = unrelated.id
        session.commit()
    run = client.post("/api/v1/recommendation-runs", json={"result_limit": 1}).json()
    _finish(client.app, user_id, run["id"])
    row = client.get(f"/api/v1/recommendation-runs/{run['id']}/results").json()["results"][0]
    assert row["catalog_id"] == unrelated_id
    assert row["score_label"] == "discovery_fit"
    assert row["personalized"] is False
    assert row["confidence"] <= 0.24
    assert row["confidence_label"] == "limited"
    assert "discovery_only" in row["risk_codes"]
    assert row["match"] < 0.75


def test_readiness_respects_disabled_live_and_evidence_sources(client):
    changed = client.put(
        "/api/v1/recommendations/preferences",
        json={
            "use_live_discovery": False,
            "use_ratings": False,
            "use_refinement": False,
        },
    )
    assert changed.status_code == 200
    readiness = client.get("/api/v1/recommendations/readiness").json()
    assert readiness["candidate_count"] == 0
    assert readiness["ready"] is False
    assert readiness["suggestion"]["code"] == "verify_metadata"


def test_neutral_rating_remains_cold_start_discovery(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        neutral = _catalog(
            "Neutral anchor", provider_id="neutral-anchor", genres=["Drama"], public_score=7
        )
        candidate = _catalog(
            "Same genre candidate",
            provider_id="neutral-candidate",
            genres=["Drama"],
            public_score=7,
        )
        session.add_all([neutral, candidate])
        session.flush()
        session.add(
            WatchEntry(
                user_id=user_id,
                catalog_item_id=neutral.id,
                status="watched",
                personal_rating=5.5,
                view_count=1,
            )
        )
        session.commit()
    readiness = client.get("/api/v1/recommendations/readiness").json()
    assert readiness["useful_ratings"] == 0
    assert readiness["confirmed_signals"] == 0
    assert readiness["personalized"] is False
    run = client.post("/api/v1/recommendation-runs", json={"result_limit": 1}).json()
    _finish(client.app, user_id, run["id"])
    row = client.get(f"/api/v1/recommendation-runs/{run['id']}/results").json()["results"][0]
    assert row["score_label"] == "discovery_fit"
    assert row["confidence_label"] == "limited"
    assert "genre_affinity" not in row["reason_codes"]


def test_feedback_excludes_later_candidates_without_mutating_library(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run = client.post("/api/v1/recommendation-runs", json={}).json()
    _finish(client.app, user_id, run["id"])
    first = client.get(f"/api/v1/recommendation-runs/{run['id']}/results").json()["results"][0]
    response = client.post(
        f"/api/v1/recommendation-results/{first['id']}/feedback",
        json={"feedback": "not_interested"},
    )
    assert response.status_code == 200
    reloaded = client.app.state.recommendations.results(user_id, run["id"])
    saved = next(row for row in reloaded["results"] if row["id"] == first["id"])
    assert saved["feedback"] == "not_interested"
    next_run = client.post("/api/v1/recommendation-runs", json={}).json()
    _finish(client.app, user_id, next_run["id"])
    next_ids = {
        item["catalog_id"]
        for item in client.get(f"/api/v1/recommendation-runs/{next_run['id']}/results").json()[
            "results"
        ]
    }
    assert first["catalog_id"] not in next_ids
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WatchEntry)) == 3


def test_preferences_reject_advanced_capabilities_and_delete_requires_confirmation(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    advanced = client.put(
        "/api/v1/recommendations/preferences",
        json={"engine": "advanced_hybrid"},
    )
    assert advanced.status_code == 409
    llm = client.put(
        "/api/v1/recommendations/preferences",
        json={"local_llm_enabled": True},
    )
    assert llm.status_code == 409
    missing = client.request("DELETE", "/api/v1/me/recommendation-data")
    assert missing.status_code == 422
    wrong = client.request(
        "DELETE",
        "/api/v1/me/recommendation-data",
        json={"confirmation": "delete"},
    )
    assert wrong.status_code == 422
    queued = client.post("/api/v1/recommendation-runs", json={}).json()
    deleted = client.request(
        "DELETE",
        "/api/v1/me/recommendation-data",
        json={"confirmation": "DELETE RECOMMENDATIONS"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"]["runs"] == 1
    assert deleted.json()["deleted"]["jobs"] == 1
    asyncio.run(client.app.state.recommendations.generate(queued["id"], user_id))
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WatchEntry)) == 3
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScheduledJob)
                .where(ScheduledJob.scope_id == queued["id"])
            )
            == 0
        )


def test_interrupted_run_and_durable_job_are_recoverable(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run = client.post("/api/v1/recommendation-runs", json={}).json()
    with client.app.state.session_factory() as session:
        row = session.get(RecommendationRun, run["id"])
        row.state = "running"
        row.progress_percent = 44
        row.phase = "checking_metadata"
        job = session.scalar(select(ScheduledJob).where(ScheduledJob.scope_id == run["id"]))
        job.state = "running"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    scopes = client.app.state.durable_jobs.recover_interrupted_scopes(
        kinds={"recommendation.generate"}
    )
    recovered = client.app.state.recommendations.recover_pending(
        recoverable_running_ids={
            scope_id
            for _kind, scope_type, scope_id in scopes
            if scope_type == "recommendation_run" and scope_id
        }
    )
    assert (run["id"], user_id) in recovered
    status = client.get(f"/api/v1/recommendation-runs/{run['id']}").json()
    assert status["state"] == "queued"
    assert status["progress_percent"] == 44
    assert "run_recovered" in status["warning_codes"]
    _finish(client.app, user_id, run["id"])
    completed = client.get(f"/api/v1/recommendation-runs/{run['id']}").json()
    assert completed["state"] == "completed"
    assert "run_recovered" in completed["warning_codes"]


def test_graceful_runner_close_requeues_own_lease_and_recovers_immediately(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run, created = client.app.state.recommendations.start_run(user_id)
    assert created is True
    # TestClient owns the application lifespan on its portal event loop.
    client.portal.call(client.app.state.job_runner.close)

    async def scenario() -> None:
        # Simulate a shutdown while a recommendation handler owns a durable lease.
        first_service = DurableJobService(
            client.app.state.session_factory,
            worker_id="graceful-worker-a",
            lease_seconds=600,
        )
        job = first_service.enqueue(
            "recommendation.generate",
            idempotency_key=f"graceful-recommendation:{run['id']}",
            user_id=user_id,
            scope_type="recommendation_run",
            scope_id=run["id"],
            payload={"run_id": run["id"], "user_id": user_id},
        )
        foreign_service = DurableJobService(
            client.app.state.session_factory,
            worker_id="graceful-foreign-worker",
            lease_seconds=600,
        )
        foreign_job = foreign_service.enqueue(
            "foreign.shutdown.fixture",
            idempotency_key="graceful-foreign-lease",
            user_id=user_id,
            payload={"safe": True},
        )
        assert foreign_service.claim(kinds={"foreign.shutdown.fixture"}) is not None
        entered = asyncio.Event()

        async def interrupted_handler(_payload):
            with client.app.state.session_factory() as session:
                row = session.get(RecommendationRun, run["id"])
                row.state = "running"
                row.phase = "scoring"
                row.progress_percent = 55
                session.commit()
            entered.set()
            await asyncio.Event().wait()

        first_runner = DurableJobRunner(
            first_service,
            {"recommendation.generate": interrupted_handler},
            concurrency=1,
            poll_seconds=0.01,
        )
        first_runner.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        await first_runner.close()

        with client.app.state.session_factory() as session:
            released = session.get(ScheduledJob, job.id)
            assert released.state == "scheduled"
            assert released.lease_owner is None
            assert released.lease_expires_at is None
            assert released.payload["_recovered_lease"] is True
            assert session.get(RecommendationRun, run["id"]).state == "running"
            retained_foreign = session.get(ScheduledJob, foreign_job.id)
            assert retained_foreign.state == "running"
            assert retained_foreign.lease_owner == "graceful-foreign-worker"
        foreign_service.relinquish_worker_leases()

        second_service = DurableJobService(
            client.app.state.session_factory,
            worker_id="graceful-worker-b",
            lease_seconds=600,
        )

        async def recovered_handler(payload):
            assert payload["_recovered_lease"] is True
            assert client.app.state.recommendations.recover_run(
                payload["run_id"], payload["user_id"]
            )
            await client.app.state.recommendations.generate(
                payload["run_id"], payload["user_id"]
            )

        second_runner = DurableJobRunner(
            second_service,
            {"recommendation.generate": recovered_handler},
            concurrency=1,
            poll_seconds=0.01,
        )
        assert await second_runner.run_once() is True
        with client.app.state.session_factory() as session:
            assert session.get(ScheduledJob, job.id).state == "completed"
            assert session.get(RecommendationRun, run["id"]).state == "completed"

    asyncio.run(scenario())


def test_explicit_retry_reuses_failed_run_and_delayed_delivery_cannot_publish_stale(
    client,
):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    client.portal.call(client.app.state.job_runner.close)
    first = client.post("/api/v1/recommendation-runs", json={}).json()
    with client.app.state.session_factory() as session:
        row = session.get(RecommendationRun, first["id"])
        row.state = "failed"
        row.failure_code = "generation_failed"
        row.safe_failure_detail = "Synthetic retryable failure."
        row.retryable = True
        row.completed_at = datetime.now(UTC)
        old_job = session.scalar(
            select(ScheduledJob).where(ScheduledJob.scope_id == first["id"])
        )
        old_job.state = "retry"
        old_job.due_at = datetime.now(UTC) + timedelta(minutes=10)
        old_job_id = old_job.id
        session.commit()

    retried = client.post("/api/v1/recommendation-runs", json={})
    assert retried.status_code == 202
    assert retried.json()["id"] == first["id"]
    assert retried.json()["state"] == "queued"
    with client.app.state.session_factory() as session:
        replacement_jobs = list(
            session.scalars(select(ScheduledJob).where(ScheduledJob.scope_id == first["id"]))
        )
        assert len(replacement_jobs) == 1
        assert replacement_jobs[0].id != old_job_id
        assert replacement_jobs[0].state == "scheduled"

    # A handler that already held the deleted delivery may still arrive. It races
    # only on the same run's queued->running CAS, so the replacement becomes a
    # harmless no-op instead of publishing another stale result set.
    asyncio.run(client.app.state.recommendations.generate(first["id"], user_id))
    assert asyncio.run(client.app.state.job_runner.run_once()) is True
    with client.app.state.session_factory() as session:
        assert session.get(RecommendationRun, first["id"]).state == "completed"
        assert replacement_jobs[0].id is not None
        assert session.get(ScheduledJob, replacement_jobs[0].id).state == "completed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(RecommendationRun)
                .where(RecommendationRun.user_id == user_id)
            )
            == 1
        )


def test_no_candidates_is_terminal_and_durable_job_does_not_auto_retry(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
    client.app.state.recommendations.update_preferences(user_id, {"use_live_discovery": False})
    client.portal.call(client.app.state.job_runner.close)
    run = client.post("/api/v1/recommendation-runs", json={}).json()
    assert asyncio.run(client.app.state.job_runner.run_once()) is True
    failed = client.get(f"/api/v1/recommendation-runs/{run['id']}").json()
    assert failed["state"] == "failed"
    assert failed["failure_code"] == "no_candidates"
    assert failed["retryable"] is False
    with client.app.state.session_factory() as session:
        job = session.scalar(select(ScheduledJob).where(ScheduledJob.scope_id == run["id"]))
        assert job.state == "completed"
        assert job.last_error_code is None
    next_run = client.post("/api/v1/recommendation-runs", json={}).json()
    assert next_run["id"] != run["id"]


def test_unexpired_job_lease_is_not_stolen_by_second_process(client):
    _user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run = client.post("/api/v1/recommendation-runs", json={}).json()
    with client.app.state.session_factory() as session:
        session.get(RecommendationRun, run["id"]).state = "running"
        job = session.scalar(select(ScheduledJob).where(ScheduledJob.scope_id == run["id"]))
        job.state = "running"
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        session.commit()
    assert not client.app.state.durable_jobs.recover_interrupted_scopes(
        kinds={"recommendation.generate"}
    )
    assert client.app.state.recommendations.recover_pending() == []
    assert client.get(f"/api/v1/recommendation-runs/{run['id']}").json()["state"] == "running"


def test_duplicate_job_delivery_is_single_writer(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run = client.post("/api/v1/recommendation-runs", json={}).json()

    async def duplicate_delivery():
        await asyncio.gather(
            client.app.state.recommendations.generate(run["id"], user_id),
            client.app.state.recommendations.generate(run["id"], user_id),
        )

    asyncio.run(duplicate_delivery())
    assert client.get(f"/api/v1/recommendation-runs/{run['id']}").json()["state"] == (
        "completed"
    )
    with client.app.state.session_factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(RecommendationResult)
            .where(RecommendationResult.run_id == run["id"])
        )
    assert count == 3


def test_duplicate_generate_click_repairs_enqueue_gap(client, monkeypatch):
    _seed_recommendation_fixture(client.app)
    enqueue = client.app.state.durable_jobs.enqueue
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic enqueue interruption")
        return enqueue(*args, **kwargs)

    monkeypatch.setattr(client.app.state.durable_jobs, "enqueue", fail_once)
    with pytest.raises(RuntimeError, match="synthetic enqueue"):
        client.post("/api/v1/recommendation-runs", json={})
    retry = client.post("/api/v1/recommendation-runs", json={})
    assert retry.status_code == 202
    with client.app.state.session_factory() as session:
        job = session.scalar(
            select(ScheduledJob).where(ScheduledJob.scope_id == retry.json()["id"])
        )
        assert job is not None
        assert job.state == "scheduled"


def test_cross_user_run_lookup_is_not_found(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run = client.post("/api/v1/recommendation-runs", json={}).json()
    with pytest.raises(RecommendationNotFound):
        client.app.state.recommendations.run("00000000-0000-0000-0000-999999999999", run["id"])
    assert client.app.state.recommendations.run(user_id, run["id"])["id"] == run["id"]


def test_private_manual_catalog_title_never_crosses_user_boundary(client):
    second_user_id = "00000000-0000-0000-0000-000000000222"
    injected = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Unique private memory title",
            "media_type": "movie",
            "provider_source": "tmdb_movie",
            "provider_id": "private-id-sentinel",
            "provider_genres": ["Drama"],
            "status": "watched",
            "personal_rating": 9,
            "notes": "private-note-sentinel",
            "view_count": 1,
        },
    )
    assert injected.status_code == 201
    private_id = injected.json()["entry"]["catalog_item"]["id"]
    with client.app.state.session_factory() as session:
        session.add(
            UserAccount(
                id=second_user_id,
                username="second-user",
                normalized_username="second-user",
                display_name="Second User",
                role="member",
                state="active",
            )
        )
        public = _catalog(
            "Public candidate", provider_id="public-candidate", genres=["Drama"], public_score=7
        )
        session.add(public)
        session.flush()
        public_id = public.id
        session.commit()
    client.app.state.recommendations.update_preferences(
        second_user_id, {"use_live_discovery": False}
    )
    readiness = client.app.state.recommendations.readiness(second_user_id)
    assert readiness["candidate_count"] == 1
    run, _created = client.app.state.recommendations.start_run(second_user_id, result_limit=10)
    _finish(client.app, second_user_id, run["id"])
    results = client.app.state.recommendations.results(second_user_id, run["id"])
    assert {row["catalog_id"] for row in results["results"]} == {public_id}
    assert private_id not in {row["catalog_id"] for row in results["results"]}
    assert "Unique private memory title" not in str(results)
    assert "private-note-sentinel" not in str(results)


def test_manual_payload_cannot_poison_verified_shared_catalog_by_id_or_title(client):
    with client.app.state.session_factory() as session:
        public = _catalog(
            "Verified shared title",
            provider_id="verified-shared-id",
            genres=["Drama"],
            public_score=7,
        )
        public.poster_url = None
        public.overview = None
        public.language = None
        public.keywords = ["provider fact"]
        session.add(public)
        session.commit()
        public_id = public.id
    hostile_fields = {
        "media_type": "movie",
        "release_year": 2025,
        "poster_url": "https://private.invalid/sentinel.jpg",
        "overview": "private overview sentinel",
        "provider_genres": ["Private Genre"],
        "keywords": ["private keyword sentinel"],
        "language": "private-language",
        "status": "plan_to_watch",
        "view_count": 0,
    }
    by_id = client.post(
        "/api/entries/manual",
        json={
            **hostile_fields,
            "canonical_title": "Hostile provider alias",
            "provider_source": "tmdb_movie",
            "provider_id": "verified-shared-id",
        },
    )
    assert by_id.status_code == 201
    by_title = client.post(
        "/api/entries/manual",
        json={
            **hostile_fields,
            "canonical_title": "Verified shared title",
            "provider_source": None,
            "provider_id": None,
        },
    )
    assert by_title.status_code == 201
    with client.app.state.session_factory() as session:
        retained = session.get(CatalogItem, public_id)
        assert retained.canonical_title == "Verified shared title"
        assert retained.poster_url is None
        assert retained.overview is None
        assert retained.language is None
        assert retained.provider_genres == ["Drama"]
        assert retained.keywords == ["provider fact"]

        # Import reconciliation calls the lower-level merge helper directly.
        EntryService(session, today=date(2026, 8, 31))._merge_catalog(
            retained,
            CatalogData(
                canonical_title="Verified shared title",
                release_year=2025,
                media_type="movie",
                overview="import-private-sentinel",
                provider_genres=["Import Private Genre"],
                keywords=["import-private-keyword"],
            ),
        )
        session.flush()
        assert retained.overview is None
        assert retained.provider_genres == ["Drama"]
        assert retained.keywords == ["provider fact"]


def test_trusted_detail_replaces_unverified_preclaim_and_purges_untrusted_sources(client):
    created = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "attacker-title-sentinel",
            # An untrusted caller may preclaim a real provider identity with a
            # false anime classification. Trusted detail must replace it too.
            "media_type": "anime",
            "provider_source": "tmdb_movie",
            "provider_id": "real-provider-id",
            "tmdb_movie_id": "real-provider-id",
            "poster_url": "https://private.invalid/attacker-poster.jpg",
            "overview": "attacker-overview-sentinel",
            "provider_genres": ["Attacker Genre"],
            "keywords": ["attacker-keyword-sentinel"],
            "external_ids": {
                "tmdb_movie": "real-provider-id",
                "tvmaze": "attacker-tvmaze-sentinel",
            },
            "status": "plan_to_watch",
            "view_count": 0,
        },
    )
    assert created.status_code == 201
    entry_id = created.json()["entry"]["id"]
    catalog_id = created.json()["entry"]["catalog_item"]["id"]
    with client.app.state.session_factory() as session:
        entry = session.get(WatchEntry, entry_id)
        service = EntryService(session, today=date(2026, 8, 31))
        service._merge_catalog(
            entry.catalog_item,
            CatalogData(
                canonical_title="Authoritative Provider Title",
                original_title="Authoritative Original",
                release_year=2024,
                media_type="movie",
                provider_source="tmdb_movie",
                provider_id="real-provider-id",
                tmdb_movie_id="real-provider-id",
                poster_url="https://images.invalid/authoritative.jpg",
                overview="Authoritative provider overview.",
                provider_genres=["Drama"],
                keywords=["character study"],
                language="en",
                country="US",
                public_score=8.2,
                external_ids={"tmdb_movie": "real-provider-id"},
            ),
            trusted_metadata=True,
        )
        session.commit()
        promoted = session.get(CatalogItem, catalog_id)
        assert promoted.canonical_title == "Authoritative Provider Title"
        assert promoted.media_type == "movie"
        assert promoted.poster_url == "https://images.invalid/authoritative.jpg"
        assert promoted.overview == "Authoritative provider overview."
        assert promoted.provider_genres == ["Drama"]
        assert promoted.keywords == ["character study"]
        assert promoted.metadata_provenance["provider_identity_verified"] is True
        identities = list(
            session.scalars(
                select(ExternalIdentity).where(ExternalIdentity.catalog_item_id == catalog_id)
            )
        )
        assert {(row.namespace, row.external_id) for row in identities} == {
            ("tmdb_movie", "real-provider-id")
        }
        sources = list(
            session.scalars(
                select(CatalogMetadataSource).where(
                    CatalogMetadataSource.catalog_item_id == catalog_id
                )
            )
        )
        assert {(row.provider, row.provider_id) for row in sources} == {
            ("tmdb_movie", "real-provider-id")
        }
        assert (
            "attacker"
            not in str(
                [row.normalized_data for row in sources] + [row.external_ids for row in sources]
            ).casefold()
        )


def test_historical_provider_row_is_diagnosed_and_reverified_without_blind_backfill(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        legacy = _catalog(
            "Historical provider title",
            provider_id="historical-provider-id",
            genres=["Drama"],
            public_score=7,
        )
        legacy.metadata_provenance = {"source": "pre-marker-library"}
        session.add(legacy)
        session.flush()
        entry = WatchEntry(
            user_id=user_id,
            catalog_item_id=legacy.id,
            status="watched",
            personal_rating=8,
            view_count=1,
        )
        session.add(entry)
        session.flush()
        session.add(
            ExternalIdentity(
                catalog_item_id=legacy.id,
                namespace="tmdb_movie",
                external_id="historical-provider-id",
                provenance="legacy",
                confidence=1.0,
            )
        )
        entry_id = entry.id
        session.commit()
    client.app.state.recommendations.update_preferences(user_id, {"use_live_discovery": False})
    readiness = client.get("/api/v1/recommendations/readiness")
    assert readiness.status_code == 200
    assert isinstance(readiness.json()["candidate_count"], int)
    assert readiness.json()["metadata_verification_needed"] == 1
    assert readiness.json()["suggestion"]["code"] == "verify_metadata"
    review = client.get("/api/metadata/review").json()
    assert review["total"] == 1
    assert review["entry"]["id"] == entry_id
    with client.app.state.session_factory() as session:
        EntryService(session, today=date(2026, 8, 31)).apply_metadata(
            entry_id,
            CatalogData(
                canonical_title="Historical provider title",
                release_year=2025,
                media_type="movie",
                provider_source="tmdb_movie",
                provider_id="historical-provider-id",
                tmdb_movie_id="historical-provider-id",
                poster_url="https://images.invalid/historical.jpg",
                overview="Verified historical metadata.",
                provider_genres=["Drama"],
                keywords=["character study"],
            ),
            trusted_metadata=True,
        )
    refreshed = client.get("/api/v1/recommendations/readiness").json()
    assert refreshed["metadata_verification_needed"] == 0


def test_taxonomy_refresh_preserves_verified_provider_and_attribution_provenance(client):
    with client.app.state.session_factory() as session:
        item = _catalog(
            "Taxonomy provenance",
            provider_id="taxonomy-provenance",
            genres=["Drama"],
            public_score=7,
        )
        item.inference_version = "legacy-taxonomy"
        item.metadata_provenance = {
            "provider_identity_verified": True,
            "provider_identity_source": "tmdb_movie",
            "attribution": "Provider attribution",
            "license_url": "https://example.invalid/terms",
        }
        session.add(item)
        session.commit()
        item_id = item.id
        assert refresh_catalog_taxonomy(session) == 1
        refreshed = session.get(CatalogItem, item_id)
        assert refreshed.metadata_provenance["provider_identity_verified"] is True
        assert refreshed.metadata_provenance["provider_identity_source"] == "tmdb_movie"
        assert refreshed.metadata_provenance["attribution"] == "Provider attribution"
        assert refreshed.metadata_provenance["license_url"].startswith("https://")


def test_private_catalog_uuid_cannot_cross_tenants_into_library_or_list(client):
    second_user_id = "00000000-0000-0000-0000-000000000776"
    second_principal = Principal(
        user_id=second_user_id,
        role="member",
        authentication_method="password",
    )
    with client.app.state.session_factory() as session:
        owner_id = current_user_id(session)
        private = CatalogItem(
            canonical_title="Owner private UUID sentinel",
            normalized_title="owner private uuid sentinel",
            media_type="movie",
            provider_source=None,
            provider_id=None,
            provider_genres=[],
            normalized_genres=[],
            inferred_subgenres=[],
            keywords=[],
            metadata_source="manual",
            metadata_provenance={},
            metadata_field_sources={},
            taste_evidence={},
        )
        session.add_all(
            [
                UserAccount(
                    id=second_user_id,
                    username="catalog-uuid-second",
                    normalized_username="catalog-uuid-second",
                    display_name="Catalog UUID Second",
                    role="member",
                    state="active",
                ),
                private,
            ]
        )
        session.flush()
        session.add(
            WatchEntry(
                user_id=owner_id,
                catalog_item_id=private.id,
                status="watched",
                view_count=1,
            )
        )
        private_id = private.id
        session.commit()
        list_service = MediaListService(session, principal=second_principal)
        list_id = list_service.create("Second user's list").id
        with pytest.raises(EntryNotFound):
            EntryService(
                session,
                today=date(2026, 8, 31),
                principal=second_principal,
            ).add_existing_catalog(private_id)
        with pytest.raises(EntryNotFound):
            MediaListService(session, principal=second_principal).add_catalog_item(
                list_id, private_id
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WatchEntry)
                .where(
                    WatchEntry.user_id == second_user_id,
                    WatchEntry.catalog_item_id == private_id,
                )
            )
            == 0
        )


def test_untrusted_ingest_never_reuses_another_tenants_private_catalog(client):
    exact_owner = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Tenant exact-title sentinel",
            "release_year": 2024,
            "media_type": "movie",
            "overview": "owner exact overview secret",
            "status": "watched",
        },
    ).json()["entry"]
    claimed_owner = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Tenant claimed-provider sentinel",
            "release_year": 2025,
            "media_type": "movie",
            "provider_source": "tmdb_movie",
            "provider_id": "tenant-unverified-provider-id",
            "overview": "owner provider overview secret",
            "status": "watched",
        },
    ).json()["entry"]
    import_owner = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Tenant import sentinel",
            "release_year": 2023,
            "media_type": "tv",
            "overview": "owner import overview secret",
            "status": "watched",
        },
    ).json()["entry"]
    portable_owner = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Tenant portable-title sentinel",
            "release_year": 2022,
            "media_type": "movie",
            "overview": "owner portable overview secret",
            "status": "watched",
        },
    ).json()["entry"]

    second_user_id = "00000000-0000-0000-0000-000000000778"
    with client.app.state.session_factory() as session:
        owner_id = current_user_id(session)
        session.add(
            UserAccount(
                id=second_user_id,
                username="ingest-isolation-second",
                normalized_username="ingest-isolation-second",
                display_name="Ingest Isolation Second",
                role="member",
                state="active",
            )
        )
        session.commit()
        second_principal = Principal(
            user_id=second_user_id,
            role="member",
            authentication_method="password",
        )
        second_entries = EntryService(
            session,
            today=date(2026, 8, 31),
            principal=second_principal,
        )

        exact_second = second_entries.create_or_handle_duplicate(
            CatalogData(
                canonical_title="Tenant exact-title sentinel",
                release_year=2024,
                media_type="movie",
                overview="second user's own exact overview",
            ),
            EntryOptions(status="plan_to_watch"),
        ).entry
        assert exact_second.catalog_item.id != exact_owner["catalog_item"]["id"]
        assert exact_second.catalog_item.overview == "second user's own exact overview"
        assert "owner exact overview secret" not in str(exact_second.model_dump(mode="json"))

        claimed_second = second_entries.create_or_handle_duplicate(
            CatalogData(
                canonical_title="Second user's claimed-provider copy",
                release_year=2025,
                media_type="movie",
                provider_source="tmdb_movie",
                provider_id="tenant-unverified-provider-id",
                overview="second user's provider overview",
            ),
            EntryOptions(status="plan_to_watch"),
        ).entry
        assert claimed_second.catalog_item.id != claimed_owner["catalog_item"]["id"]
        assert claimed_second.catalog_item.provider_source is None
        assert claimed_second.catalog_item.provider_id is None
        assert "owner provider overview secret" not in str(
            claimed_second.model_dump(mode="json")
        )

        import_service = ImportService(
            session,
            today=date(2026, 8, 31),
            principal=second_principal,
        )
        import_match, media_correction = import_service._find_import_catalog(
            second_entries,
            CatalogData(
                canonical_title="Tenant import sentinel",
                release_year=2023,
                media_type="anime",
            ),
        )
        assert import_match is None
        assert media_correction is False

        list_service = MediaListService(session, principal=second_principal)
        portable_by_provider = list_service._portable_catalog(
            PortableListTitle(
                canonical_title="Portable caller provider copy",
                release_year=2025,
                media_type="movie",
                provider_source="tmdb_movie",
                provider_id="tenant-unverified-provider-id",
                overview="portable caller overview",
                external_ids={"tmdb_movie": "tenant-unverified-provider-id"},
            )
        )
        assert portable_by_provider.id != claimed_owner["catalog_item"]["id"]
        assert portable_by_provider.provider_source is None
        assert portable_by_provider.provider_id is None
        portable_by_title = list_service._portable_catalog(
            PortableListTitle(
                canonical_title="Tenant portable-title sentinel",
                release_year=2022,
                media_type="movie",
                overview="portable caller title overview",
            )
        )
        assert portable_by_title.id != portable_owner["catalog_item"]["id"]
        assert portable_by_title.overview == "portable caller title overview"

        connection = IntegrationConnection(
            user_id=second_user_id,
            provider_slug="fixture",
            label="Tenant-isolated fixture",
            enabled=True,
            configuration={},
            remote_profile={},
            capabilities={"pull_history": "pull"},
            schedule={},
        )
        session.add(connection)
        session.flush()
        run = IntegrationRun(
            connection_id=connection.id,
            trigger="manual",
            direction="pull",
            capability="pull_history",
            state="running",
            dry_run=False,
            counts={},
        )
        session.add(run)
        session.flush()
        identity_outcome, identity_catalog_id, _entry = IntegrationCoordinator._resolve_event(
            session,
            run,
            second_user_id,
            IntegrationEventInput(
                event_kind="history",
                safe_summary="Tenant identity isolation fixture",
                payload_hash="a" * 64,
                identities={"tmdb_movie": "tenant-unverified-provider-id"},
                title="Integration caller provider copy",
                year=2025,
                media_type="movie",
                changes={"status": "plan_to_watch"},
            ),
        )
        assert identity_outcome == "created"
        assert identity_catalog_id != claimed_owner["catalog_item"]["id"]
        assert session.get(CatalogItem, identity_catalog_id).overview is None

        title_outcome, title_catalog_id, _entry = IntegrationCoordinator._resolve_event(
            session,
            run,
            second_user_id,
            IntegrationEventInput(
                event_kind="history",
                safe_summary="Tenant title isolation fixture",
                payload_hash="b" * 64,
                identities={"fixture": "tenant-title-new-identity"},
                title="Tenant import sentinel",
                year=2023,
                media_type="tv",
                changes={"status": "plan_to_watch"},
            ),
        )
        assert title_outcome == "created"
        assert title_catalog_id != import_owner["catalog_item"]["id"]
        assert session.get(CatalogItem, title_catalog_id).overview is None
        assert owner_id != second_user_id


def test_trusted_metadata_repoints_one_user_without_mutating_shared_catalog(client):
    second_user_id = "00000000-0000-0000-0000-000000000777"
    with client.app.state.session_factory() as session:
        owner_id = current_user_id(session)
        second = UserAccount(
            id=second_user_id,
            username="metadata-second",
            normalized_username="metadata-second",
            display_name="Metadata Second",
            role="member",
            state="active",
        )
        shared = _catalog(
            "Shared Provider A",
            provider_id="provider-a",
            genres=["Drama"],
            public_score=8,
        )
        session.add_all([second, shared])
        session.flush()
        owner_entry = WatchEntry(
            user_id=owner_id,
            catalog_item_id=shared.id,
            status="watching",
            view_count=0,
        )
        second_entry = WatchEntry(
            user_id=second_user_id,
            catalog_item_id=shared.id,
            status="watching",
            view_count=0,
        )
        session.add_all([owner_entry, second_entry])
        session.commit()
        shared_id = shared.id
        owner_entry_id = owner_entry.id
        second_entry_id = second_entry.id

        owner_service = EntryService(
            session,
            today=date(2026, 8, 31),
            principal=Principal(
                user_id=owner_id,
                role="admin",
                authentication_method="local",
                is_local_mode=True,
            ),
        )
        changed = owner_service.apply_metadata(
            owner_entry_id,
            CatalogData(
                canonical_title="Different Provider B",
                release_year=2026,
                media_type="movie",
                provider_source="tmdb_movie",
                provider_id="provider-b",
                tmdb_movie_id="provider-b",
                poster_url="https://images.invalid/provider-b.jpg",
                overview="Provider B overview.",
                provider_genres=["Mystery"],
            ),
            trusted_metadata=True,
        )
        assert changed.catalog_item.id != shared_id
        provider_b_id = changed.catalog_item.id
        retained = session.get(CatalogItem, shared_id)
        assert retained.canonical_title == "Shared Provider A"
        assert session.get(WatchEntry, second_entry_id).catalog_item_id == shared_id
        assert session.get(WatchEntry, owner_entry_id).catalog_item_id == provider_b_id

        # A same-identity refresh remains a safe shared metadata refresh.
        second_service = EntryService(
            session,
            today=date(2026, 8, 31),
            principal=Principal(
                user_id=second_user_id,
                role="member",
                authentication_method="password",
            ),
        )
        refreshed = second_service.apply_metadata(
            second_entry_id,
            CatalogData(
                canonical_title="Shared Provider A Refreshed",
                release_year=2025,
                media_type="movie",
                provider_source="tmdb_movie",
                provider_id="provider-a",
                tmdb_movie_id="provider-a",
                overview="Fresh provider A overview.",
                provider_genres=["Drama"],
            ),
            trusted_metadata=True,
        )
        assert refreshed.catalog_item.id == shared_id
        assert session.get(CatalogItem, shared_id).canonical_title == (
            "Shared Provider A Refreshed"
        )

        # If that user already tracks B, the usual duplicate conflict is retained.
        session.add(
            WatchEntry(
                user_id=second_user_id,
                catalog_item_id=provider_b_id,
                status="plan_to_watch",
                view_count=0,
            )
        )
        session.commit()
        with pytest.raises(EntryConflict, match="already attached"):
            second_service.apply_metadata(
                second_entry_id,
                CatalogData(
                    canonical_title="Different Provider B",
                    release_year=2026,
                    media_type="movie",
                    provider_source="tmdb_movie",
                    provider_id="provider-b",
                    tmdb_movie_id="provider-b",
                    provider_genres=["Mystery"],
                ),
                trusted_metadata=True,
            )


def test_feedback_is_tenant_scoped_on_reload(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    run = client.post("/api/v1/recommendation-runs", json={}).json()
    _finish(client.app, user_id, run["id"])
    result = client.get(f"/api/v1/recommendation-runs/{run['id']}/results").json()["results"][0]
    other_user_id = "00000000-0000-0000-0000-000000000333"
    with client.app.state.session_factory() as session:
        session.add(
            UserAccount(
                id=other_user_id,
                username="feedback-other",
                normalized_username="feedback-other",
                display_name="Feedback Other",
                role="member",
                state="active",
            )
        )
        session.flush()
        session.add(
            RecommendationFeedback(
                user_id=other_user_id,
                result_id=result["id"],
                feedback="useful",
            )
        )
        session.commit()
    reloaded = client.app.state.recommendations.results(user_id, run["id"])
    assert reloaded["results"][0]["feedback"] is None


def test_rewatch_signal_is_default_off_and_explicitly_opt_in(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    with client.app.state.session_factory() as session:
        entry = session.scalar(
            select(WatchEntry).where(WatchEntry.user_id == user_id).order_by(WatchEntry.id)
        )
        entry.view_count = 4
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        payload, _anchors, counts, _revision, _hash = project_signals(
            session, user_id=user_id, preferences=preferences
        )
        assert counts["rewatches"] == 0
        assert not any(signal["source"] == "rewatch" for signal in payload)
        preferences.use_rewatches = True
        preferences.version += 1
        payload, _anchors, counts, _revision, _hash = project_signals(
            session, user_id=user_id, preferences=preferences
        )
    rewatches = [signal for signal in payload if signal["source"] == "rewatch"]
    assert counts["rewatches"] == 1
    assert rewatches[0]["dimension"] == "rewatch_item"
    assert rewatches[0]["source_catalog_ids"] == [entry.catalog_item_id]


def test_completed_v4_reflection_changes_affinity_but_skips_add_no_signal(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        anchor = _catalog(
            "Refined drama", provider_id="refined-anchor", genres=["Drama"], public_score=7
        )
        skipped_anchor = _catalog(
            "Skipped title", provider_id="skipped-anchor", genres=["Comedy"], public_score=7
        )
        session.add_all([anchor, skipped_anchor])
        session.flush()
        skipped_anchor_id = skipped_anchor.id
        entry = WatchEntry(
            user_id=user_id,
            catalog_item_id=anchor.id,
            status="watched",
            personal_rating=9,
            view_count=1,
        )
        skipped_entry = WatchEntry(
            user_id=user_id,
            catalog_item_id=skipped_anchor.id,
            status="watched",
            personal_rating=5.5,
            view_count=1,
        )
        session.add_all([entry, skipped_entry])
        session.flush()
        session.add_all(
            [
                RatingAssessment(
                    entry_id=entry.id,
                    mode="guided_v4",
                    rubric_version="guided-rubric-v4",
                    state="completed",
                    answers={
                        "engagement_pacing": 1,
                        "distinctiveness_freshness": 1,
                        "emotional_intellectual_intensity": 1,
                        "consistency_tolerance": 1,
                    },
                    question_order=[],
                    rubric_coverage=1,
                    version=1,
                    completed_at=datetime.now(UTC),
                ),
                RatingAssessment(
                    entry_id=skipped_entry.id,
                    mode="guided_v4",
                    rubric_version="guided-rubric-v4",
                    state="completed",
                    answers={"engagement_pacing": "skip"},
                    question_order=[],
                    rubric_coverage=0,
                    version=1,
                    completed_at=datetime.now(UTC),
                ),
            ]
        )
        session.flush()
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        preferences.use_refinement = False
        off_signals, off_anchors, _counts, revision, _hash = project_signals(
            session, user_id=user_id, preferences=preferences
        )
        candidates = [
            EngineCandidate(
                catalog_id="drama-candidate",
                title="Drama candidate",
                media_type="movie",
                genres=["drama"],
                public_score=7,
            ),
            EngineCandidate(
                catalog_id="comedy-candidate",
                title="Comedy candidate",
                media_type="movie",
                genres=["comedy"],
                public_score=7,
            ),
        ]
        off = score_candidates(
            request=EngineRequest(
                request_id="refinement-off",
                input_revision=revision,
                deterministic_seed=0,
                signals=[PreferenceSignal.model_validate(value) for value in off_signals],
                evidence_anchors=[
                    EvidenceAnchor.model_validate(value) for value in off_anchors
                ],
                candidates=candidates,
            )
        )
        preferences.use_refinement = True
        preferences.version += 1
        on_signals, on_anchors, counts, revision, _hash = project_signals(
            session, user_id=user_id, preferences=preferences
        )
        on = score_candidates(
            request=EngineRequest(
                request_id="refinement-on",
                input_revision=revision,
                deterministic_seed=0,
                signals=[PreferenceSignal.model_validate(value) for value in on_signals],
                evidence_anchors=[EvidenceAnchor.model_validate(value) for value in on_anchors],
                candidates=candidates,
            )
        )
    off_by_id = {row.catalog_id: row for row in off.results}
    on_by_id = {row.catalog_id: row for row in on.results}
    assert on_by_id["drama-candidate"].match > off_by_id["drama-candidate"].match
    assert counts["completed_refinements"] == 1
    assert not any(
        signal["source"] == "completed_refinement"
        and signal["source_catalog_ids"] == [skipped_anchor_id]
        for signal in on_signals
    )


def test_refinement_only_completion_advances_signal_revision(client):
    user_id, _candidate_ids = _seed_recommendation_fixture(client.app)
    with client.app.state.session_factory() as session:
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        session.commit()
        _signals, _anchors, _counts, before_revision, _hash = project_signals(
            session, user_id=user_id, preferences=preferences
        )
        entry_id = session.scalar(
            select(WatchEntry.id).where(WatchEntry.user_id == user_id).order_by(WatchEntry.id)
        )
    assert (
        client.put("/api/settings/general", json={"advanced_ratings_enabled": True}).status_code
        == 200
    )
    time.sleep(0.002)
    assessment = client.post(
        "/api/ratings/assessments",
        json={
            "entry_id": entry_id,
            "answers": {
                "engagement_pacing": 4,
                "distinctiveness_freshness": 4,
                "emotional_intellectual_intensity": 4,
                "consistency_tolerance": 4,
            },
        },
    ).json()
    completed = client.post(
        f"/api/ratings/assessments/{assessment['id']}/complete",
        json={
            "expected_version": assessment["version"],
            "rating_action": "keep_rating",
        },
    )
    assert completed.status_code == 200
    with client.app.state.session_factory() as session:
        preferences = client.app.state.recommendations.preference_row(session, user_id)
        signals, _anchors, _counts, after_revision, _hash = project_signals(
            session, user_id=user_id, preferences=preferences
        )
    assert after_revision > before_revision
    refinement = [row for row in signals if row["source"] == "completed_refinement"]
    assert refinement
    assert {row["source_revision"] for row in refinement} == {after_revision}


def test_verified_taxonomy_projects_v4_intensity_into_real_candidate_ranking(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        anchor = _catalog(
            "Intensity anchor",
            provider_id="intensity-anchor",
            genres=["Drama"],
            public_score=7,
        )
        intense = _catalog(
            "Intense candidate",
            provider_id="intense-candidate",
            genres=["Drama"],
            public_score=7,
        )
        comforting = _catalog(
            "Comforting candidate",
            provider_id="comforting-candidate",
            genres=["Drama"],
            public_score=7,
        )
        for item, keywords in (
            (intense, ["tense", "cerebral"]),
            (comforting, ["wholesome"]),
        ):
            taxonomy = infer_taxonomy(["Drama"], keywords, media_type="movie")
            item.keywords = keywords
            item.normalized_genres = taxonomy.genres
            item.inferred_subgenres = taxonomy.subgenres
            item.taste_evidence = taxonomy.taste_evidence
            item.metadata_provenance = {
                **taxonomy.provenance,
                "provider_identity_verified": True,
                "provider_identity_source": "tmdb_movie",
            }
            item.inference_version = INFERENCE_VERSION
        session.add_all([anchor, intense, comforting])
        session.flush()
        entry = WatchEntry(
            user_id=user_id,
            catalog_item_id=anchor.id,
            status="watched",
            personal_rating=9,
            view_count=1,
        )
        session.add(entry)
        session.flush()
        session.add(
            RatingAssessment(
                entry_id=entry.id,
                mode="guided_v4",
                rubric_version="guided-rubric-v4",
                state="completed",
                answers={"emotional_intellectual_intensity": 5},
                question_order=["emotional_intellectual_intensity"],
                rubric_coverage=0.2,
                version=1,
                completed_at=datetime.now(UTC),
            )
        )
        intense_id = intense.id
        comforting_id = comforting.id
        session.commit()
    run = client.post("/api/v1/recommendation-runs", json={"result_limit": 2}).json()
    _finish(client.app, user_id, run["id"])
    rows = client.get(f"/api/v1/recommendation-runs/{run['id']}/results").json()["results"]
    assert [row["catalog_id"] for row in rows] == [intense_id, comforting_id]
    assert "confirmed_refinement_fit" in rows[0]["reason_codes"]


def test_terminal_run_retention_is_age_and_count_bounded(client):
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        created = datetime.now(UTC) - timedelta(days=1)
        rows = []
        for index in range(102):
            row = RecommendationRun(
                user_id=user_id,
                distribution_flavor="standard",
                engine="scalar",
                engine_version="scalar-v1",
                signal_contract_version="preference-signal-v1",
                score_scale_version="bounded-affinity-v1",
                model_versions={"scalar": "scalar-v1"},
                input_revision=1,
                deterministic_seed=index,
                idempotency_key=f"retention:{index}",
                state="completed",
                phase="ready",
                progress_percent=100,
                progress_indeterminate=False,
                message_key="recommendations.progress.ready",
                retryable=False,
                created_at=created + timedelta(seconds=index),
                updated_at=created + timedelta(seconds=index),
                completed_at=created + timedelta(seconds=index),
            )
            rows.append(row)
            session.add(row)
        session.flush()
        oldest_id = rows[0].id
        keep_id = rows[-1].id
        session.commit()
    client.app.state.durable_jobs.enqueue(
        "recommendation.generate",
        idempotency_key="retention-old-run",
        user_id=user_id,
        scope_type="recommendation_run",
        scope_id=oldest_id,
        payload={"run_id": oldest_id, "user_id": user_id},
    )
    client.app.state.durable_jobs.enqueue(
        "recommendation.generate",
        idempotency_key="retention-orphan",
        user_id=user_id,
        scope_type="recommendation_run",
        scope_id="00000000-0000-0000-0000-000000009999",
        payload={"run_id": "orphan", "user_id": user_id},
    )
    client.app.state.durable_jobs.enqueue(
        "integration_sync",
        idempotency_key="retention-unrelated",
        user_id=user_id,
        scope_type="integration_connection",
        scope_id="unrelated",
        payload={"safe": True},
    )
    with client.app.state.session_factory() as session:
        client.app.state.recommendations._prune(session, user_id, 365, keep_run_id=keep_id)
        session.commit()
        remaining = list(
            session.scalars(
                select(RecommendationRun).where(RecommendationRun.user_id == user_id)
            )
        )
    assert len(remaining) == 100
    assert keep_id in {row.id for row in remaining}
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScheduledJob)
                .where(
                    ScheduledJob.kind == "recommendation.generate",
                    ScheduledJob.scope_id == oldest_id,
                )
            )
            == 0
        )
    deleted = client.app.state.recommendations.delete_user_data(user_id)
    assert deleted["jobs"] == 1
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScheduledJob)
                .where(
                    ScheduledJob.kind == "recommendation.generate",
                    ScheduledJob.user_id == user_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScheduledJob)
                .where(
                    ScheduledJob.kind == "integration_sync",
                    ScheduledJob.user_id == user_id,
                )
            )
            == 1
        )


def test_failed_run_attempts_enforce_count_and_job_retention(client, monkeypatch):
    monkeypatch.setattr(
        client.app.state.recommendations,
        "MAX_TERMINAL_RUNS_PER_USER",
        3,
    )
    created = datetime.now(UTC) - timedelta(days=1)
    prior_ids: list[str] = []
    with client.app.state.session_factory() as session:
        user_id = current_user_id(session)
        for index in range(3):
            run = RecommendationRun(
                user_id=user_id,
                distribution_flavor="standard",
                engine="scalar",
                engine_version="scalar-v1",
                signal_contract_version="preference-signal-v1",
                score_scale_version="bounded-affinity-v1",
                model_versions={"scalar": "scalar-v1"},
                input_revision=1,
                deterministic_seed=index,
                idempotency_key=f"failed-retention:{index}",
                state="failed",
                phase="preparing_candidates",
                progress_percent=25,
                progress_indeterminate=False,
                message_key="recommendations.failure.no_candidates",
                failure_code="no_candidates",
                # A no-candidate outcome is terminal until candidate state
                # changes; it must not be selected by the explicit retry path.
                retryable=False,
                created_at=created + timedelta(seconds=index),
                updated_at=created + timedelta(seconds=index),
                completed_at=created + timedelta(seconds=index),
            )
            session.add(run)
            session.flush()
            prior_ids.append(run.id)
        session.commit()
    for index, run_id in enumerate(prior_ids):
        client.app.state.durable_jobs.enqueue(
            "recommendation.generate",
            idempotency_key=f"failed-retention-job:{index}",
            user_id=user_id,
            scope_type="recommendation_run",
            scope_id=run_id,
            payload={"run_id": run_id, "user_id": user_id},
        )

    payload, created_run = client.app.state.recommendations.start_run(user_id)
    assert created_run is True
    current_id = payload["id"]
    client.app.state.durable_jobs.enqueue(
        "recommendation.generate",
        idempotency_key="failed-retention-job:current",
        user_id=user_id,
        scope_type="recommendation_run",
        scope_id=current_id,
        payload={"run_id": current_id, "user_id": user_id},
    )
    asyncio.run(client.app.state.recommendations.generate(current_id, user_id))

    with client.app.state.session_factory() as session:
        remaining_runs = list(
            session.scalars(
                select(RecommendationRun).where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.state == "failed",
                )
            )
        )
        remaining_jobs = list(
            session.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.user_id == user_id,
                    ScheduledJob.kind == "recommendation.generate",
                )
            )
        )
    assert len(remaining_runs) == 3
    assert current_id in {run.id for run in remaining_runs}
    assert prior_ids[0] not in {run.id for run in remaining_runs}
    assert len(remaining_jobs) == 3
    assert prior_ids[0] not in {job.scope_id for job in remaining_jobs}


def test_standard_evaluation_golden_values_are_hand_checkable():
    ranked = ["a", "b", "c"]
    assert recall_at_k(ranked, {"b", "d"}, 2) == 0.5
    assert reciprocal_rank(ranked, {"b"}) == 0.5
    assert ndcg_at_k(ranked, {"a", "c"}, 3) == pytest.approx(
        (1 + 1 / 2) / (1 + 1 / 1.584962500721156)
    )
    assert positive_negative_pair_accuracy({"a": 0.8, "b": 0.4}, [("a", "b")]) == 1
    assert catalog_coverage(ranked, {"a", "b", "c", "d"}) == 0.75
    genres = [{"Drama"}, {"Drama", "Mystery"}, {"Comedy"}]
    assert genre_coverage(genres, {"Drama", "Mystery", "Comedy", "Action"}) == 0.75
    assert intra_list_genre_diversity([{"Drama"}, {"Drama"}, {"Comedy"}]) == pytest.approx(
        2 / 3
    )
    assert mean_novelty([0.2, 0.8]) == pytest.approx(0.5)
    assert popularity_bias([0.8, 0.6], [0.2, 0.4, 0.6]) == pytest.approx(0.3)
    coverage = result_field_coverage(
        [
            {
                "provider_source": "fixture",
                "provider_id": "1",
                "genres": ["Drama"],
                "poster_url": "https://images.invalid/1.jpg",
                "reason_codes": ["genre_affinity"],
            },
            {},
        ]
    )
    assert coverage == {
        "identity": 0.5,
        "metadata": 0.5,
        "artwork": 0.5,
        "explanation": 0.5,
    }
    assert repeated_run_stability(ranked, ranked) == {
        "exact_order": True,
        "overlap": 1.0,
        "mean_rank_shift": 0.0,
    }
    assert repeated_run_stability([], ranked) == {
        "exact_order": False,
        "overlap": 0.0,
        "mean_rank_shift": 3.0,
    }
    unequal = repeated_run_stability(["a", "b", "c"], ["a"])
    assert unequal["exact_order"] is False
    assert unequal["overlap"] == pytest.approx(1 / 3)
    assert unequal["mean_rank_shift"] == pytest.approx(2.0)


def test_v4_contract_is_current():
    assert RUBRIC_VERSION == "guided-rubric-v4"
