from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from watchtracker.build_manifest import BuildManifest
from watchtracker.models import (
    RecommendationCandidateSnapshot,
    RecommendationFeedback,
    RecommendationModelQualification,
    RecommendationPreferenceClaim,
    RecommendationResult,
    RecommendationRun,
    RecommendationSignalSnapshot,
    UserRecommendationPreference,
    WatchEntry,
    utcnow,
)
from watchtracker.recommendations.candidates import (
    TVMazeCatalogSource,
    candidate_snapshot,
    count_owned_unverified_provider_items,
    count_unseen_candidates,
)
from watchtracker.recommendations.contract import (
    ENGINE_CONTRACT_VERSION,
    PHASE_PROGRESS,
    SCORE_SCALE_VERSION,
    SIGNAL_CONTRACT_VERSION,
    STANDARD_ENGINE_VERSION,
    EngineRequest,
    EvidenceAnchor,
    PreferenceSignal,
    RunPhase,
    display_match,
    validate_engine_response,
)
from watchtracker.recommendations.explanations import message_keys
from watchtracker.recommendations.policy import confidence_label, eligible_catalog_item
from watchtracker.recommendations.scalar import engine_candidates, score_candidates
from watchtracker.recommendations.signals import project_signals, signal_snapshot

logger = logging.getLogger(__name__)


class RecommendationNotFound(LookupError):
    pass


class RecommendationConflict(RuntimeError):
    pass


class RecommendationCancelled(RuntimeError):
    pass


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()


class RecommendationService:
    MAX_TERMINAL_RUNS_PER_USER = 100
    _STANDARD_MODEL_VERSION_KEYS = frozenset(
        {"scalar", "weights", "score_scale", "tower", "llm", "result_limit"}
    )

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        metadata_service: Any,
        build_manifest: BuildManifest,
        job_service: Any | None = None,
    ):
        self.session_factory = session_factory
        self.live_source = TVMazeCatalogSource(metadata_service)
        self.build_manifest = build_manifest
        self.job_service = job_service

    @staticmethod
    def preference_row(session: Session, user_id: str) -> UserRecommendationPreference:
        row = session.get(UserRecommendationPreference, user_id)
        if row is None:
            row = UserRecommendationPreference(user_id=user_id)
            session.add(row)
            session.flush()
        return row

    def preference_payload(
        self, row: UserRecommendationPreference, *, effective_for_build: bool = True
    ) -> dict[str, Any]:
        advanced_available = (
            "advanced-hybrid-v1" in self.build_manifest.recommendation_capabilities
        )
        return {
            "engine": (
                row.engine
                if not effective_for_build or row.engine == "scalar" or advanced_available
                else "scalar"
            ),
            "use_ratings": row.use_ratings,
            "use_favorites": row.use_favorites,
            "use_refinement": row.use_refinement,
            "use_rewatches": row.use_rewatches,
            "use_live_discovery": row.use_live_discovery,
            "local_llm_enabled": (
                row.local_llm_enabled
                if not effective_for_build or advanced_available
                else False
            ),
            "excluded_media_types": row.excluded_media_types or [],
            "excluded_genres": row.excluded_genres or [],
            "retention_days": row.retention_days,
            "consent_revision": row.consent_revision,
            "version": row.version,
            "updated_at": _utc_iso(row.updated_at),
        }

    def preferences(self, user_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            row = self.preference_row(session, user_id)
            session.commit()
            return self.preference_payload(row)

    def update_preferences(self, user_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session:
            row = self.preference_row(session, user_id)
            advanced_available = (
                "advanced-hybrid-v1" in self.build_manifest.recommendation_capabilities
            )
            effective_engine = (
                row.engine if row.engine == "scalar" or advanced_available else "scalar"
            )
            engine = values.get("engine", effective_engine)
            if (
                engine != "scalar"
                and "advanced-hybrid-v1" not in self.build_manifest.recommendation_capabilities
            ):
                raise RecommendationConflict(
                    "This PMT build includes the lightweight recommendation engine only."
                )
            if (
                values.get("local_llm_enabled") is True
                and self.build_manifest.distribution_flavor == "standard"
            ):
                raise RecommendationConflict(
                    "Local-model recommendations are available only in the Advanced Recommendations Beta."
                )
            for field in (
                "engine",
                "use_ratings",
                "use_favorites",
                "use_refinement",
                "use_rewatches",
                "use_live_discovery",
                "local_llm_enabled",
                "excluded_media_types",
                "excluded_genres",
                "retention_days",
            ):
                if field in values:
                    setattr(row, field, values[field])
            row.version += 1
            row.updated_at = utcnow()
            session.commit()
            return self.preference_payload(row)

    @staticmethod
    def run_payload(run: RecommendationRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "state": run.state,
            "phase": run.phase,
            "progress_percent": run.progress_percent,
            "progress_indeterminate": run.progress_indeterminate,
            "completed_units": run.completed_units,
            "total_units": run.total_units,
            "message_key": run.message_key,
            "warning_codes": run.warning_codes or [],
            "failure_code": run.failure_code,
            "retryable": run.retryable,
            "safe_failure_detail": run.safe_failure_detail,
            "fallback_used": "provider_unavailable" in (run.warning_codes or []),
            "engine": run.engine,
            "engine_version": run.engine_version,
            "signal_contract_version": run.signal_contract_version,
            "score_scale_version": run.score_scale_version,
            "model_versions": dict(run.model_versions or {}),
            "distribution_flavor": run.distribution_flavor,
            "created_at": _utc_iso(run.created_at),
            "started_at": _utc_iso(run.started_at),
            "completed_at": _utc_iso(run.completed_at),
            "updated_at": _utc_iso(run.updated_at),
        }

    @staticmethod
    def _scalar_compatibility_clause():
        return and_(
            RecommendationRun.engine == "scalar",
            RecommendationRun.engine_version == STANDARD_ENGINE_VERSION,
            RecommendationRun.signal_contract_version == SIGNAL_CONTRACT_VERSION,
            RecommendationRun.score_scale_version == SCORE_SCALE_VERSION,
        )

    def _compatible_run(self, run: RecommendationRun) -> bool:
        if "scalar-v1" not in self.build_manifest.recommendation_capabilities:
            return False
        versions = dict(run.model_versions or {})
        result_limit = versions.get("result_limit")
        return bool(
            run.engine == "scalar"
            and run.engine_version == STANDARD_ENGINE_VERSION
            and run.signal_contract_version == SIGNAL_CONTRACT_VERSION
            and run.score_scale_version == SCORE_SCALE_VERSION
            and set(versions) <= self._STANDARD_MODEL_VERSION_KEYS
            and versions.get("scalar") == STANDARD_ENGINE_VERSION
            and versions.get("weights") in {None, "scalar-weights-v1"}
            and versions.get("score_scale") in {None, SCORE_SCALE_VERSION}
            and versions.get("tower") is None
            and versions.get("llm") is None
            and (
                result_limit is None
                or (
                    isinstance(result_limit, int)
                    and not isinstance(result_limit, bool)
                    and 1 <= result_limit <= 100
                )
            )
        )

    def _first_compatible(self, session: Session, statement: Any) -> RecommendationRun | None:
        return next(
            (run for run in session.scalars(statement) if self._compatible_run(run)),
            None,
        )

    @staticmethod
    def _quarantine_incompatible_active(run: RecommendationRun) -> None:
        """Release the active slot without deleting beta-derived state."""

        now = utcnow()
        run.state = "failed"
        run.retryable = True
        run.failure_code = "generation_failed"
        run.safe_failure_detail = "This run requires a different PMT recommendation capability."
        run.progress_indeterminate = False
        run.completed_at = now
        run.updated_at = now

    @staticmethod
    def _raw_run_for_user(session: Session, user_id: str, run_id: str) -> RecommendationRun:
        run = session.scalar(
            select(RecommendationRun).where(
                RecommendationRun.id == run_id,
                RecommendationRun.user_id == user_id,
            )
        )
        if run is None:
            raise RecommendationNotFound("Recommendation run not found")
        return run

    def _run_for_user(self, session: Session, user_id: str, run_id: str) -> RecommendationRun:
        run = self._raw_run_for_user(session, user_id, run_id)
        if not self._compatible_run(run):
            raise RecommendationNotFound("Recommendation run not found")
        return run

    def run_compatibility(self, user_id: str, run_id: str) -> str:
        """Classify a durable payload without exposing an unsupported run."""

        with self.session_factory() as session:
            try:
                run = self._raw_run_for_user(session, user_id, run_id)
            except RecommendationNotFound:
                return "missing"
            return "compatible" if self._compatible_run(run) else "unsupported"

    def compatible_pending_run_ids(self) -> set[str]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(RecommendationRun).where(
                    RecommendationRun.state.in_(("queued", "running")),
                    self._scalar_compatibility_clause(),
                )
            )
            return {run.id for run in rows if self._compatible_run(run)}

    def compatible_recoverable_run_ids(self) -> set[str]:
        """Scopes whose capability-paused durable job may safely resume."""

        with self.session_factory() as session:
            rows = session.scalars(
                select(RecommendationRun).where(
                    or_(
                        RecommendationRun.state.in_(("queued", "running")),
                        and_(
                            RecommendationRun.state == "failed",
                            RecommendationRun.retryable.is_(True),
                        ),
                    ),
                    self._scalar_compatibility_clause(),
                )
            )
            return {run.id for run in rows if self._compatible_run(run)}

    def readiness(self, user_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            preferences = self.preference_row(session, user_id)
            _signals, _anchors, counts, _revision, _hash = project_signals(
                session, user_id=user_id, preferences=preferences
            )
            candidate_count = count_unseen_candidates(
                session, user_id=user_id, preferences=preferences
            )
            metadata_verification_needed = count_owned_unverified_provider_items(
                session, user_id=user_id
            )
            latest_with_snapshot = self._first_compatible(
                session,
                select(RecommendationRun)
                .where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.candidate_snapshot_id.is_not(None),
                    self._scalar_compatibility_clause(),
                )
                .order_by(RecommendationRun.created_at.desc()),
            )
            latest_snapshot = (
                session.get(
                    RecommendationCandidateSnapshot,
                    latest_with_snapshot.candidate_snapshot_id,
                )
                if latest_with_snapshot
                else None
            )
            active = self._first_compatible(
                session,
                select(RecommendationRun)
                .where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.state.in_(("queued", "running")),
                    self._scalar_compatibility_clause(),
                )
                .order_by(RecommendationRun.created_at.desc()),
            )
            latest = self._first_compatible(
                session,
                select(RecommendationRun)
                .where(
                    RecommendationRun.user_id == user_id,
                    self._scalar_compatibility_clause(),
                )
                .order_by(RecommendationRun.created_at.desc()),
            )
            latest_completed = self._first_compatible(
                session,
                select(RecommendationRun)
                .where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.state == "completed",
                    self._scalar_compatibility_clause(),
                )
                .order_by(RecommendationRun.completed_at.desc()),
            )
            useful = counts["useful_ratings"]
            confirmed = counts["confirmed_signals"]
            if metadata_verification_needed:
                suggestion = {
                    "code": "verify_metadata",
                    "message_key": "recommendations.suggestion.verify_metadata",
                    "target_view": "settings",
                    "remaining": metadata_verification_needed,
                }
            elif preferences.use_ratings and useful < 3:
                suggestion = {
                    "code": "rate_more",
                    "message_key": "recommendations.suggestion.rate_more",
                    "target_view": "rankings",
                    "remaining": 3 - useful,
                }
            elif preferences.use_refinement and counts["completed_refinements"] < 1:
                suggestion = {
                    "code": "refine_rankings",
                    "message_key": "recommendations.suggestion.refine_rankings",
                    "target_view": "rankings",
                    "remaining": 1,
                }
            elif candidate_count < 5:
                suggestion = {
                    "code": "verify_metadata",
                    "message_key": "recommendations.suggestion.verify_metadata",
                    "target_view": "settings",
                    "remaining": 5 - candidate_count,
                }
            else:
                suggestion = None
            session.commit()
            return {
                "useful_ratings": useful,
                "confirmed_signals": confirmed,
                "candidate_count": candidate_count,
                "metadata_verification_needed": metadata_verification_needed,
                "candidate_freshness": (
                    (latest_snapshot.coverage or {}).get("provider_freshness")
                    if latest_snapshot
                    else None
                ),
                "personalized": useful > 0 or confirmed > 0,
                "ready": candidate_count > 0
                or (preferences.use_live_discovery and self.live_source.available),
                "suggestion": suggestion,
                "active_run": self.run_payload(active) if active else None,
                "latest_run": self.run_payload(latest) if latest else None,
                "latest_completed_run": self.run_payload(latest_completed)
                if latest_completed
                else None,
            }

    def start_run(
        self,
        user_id: str,
        *,
        idempotency_key: str | None = None,
        result_limit: int = 40,
    ) -> tuple[dict[str, Any], bool]:
        with self.session_factory() as session:
            preferences = self.preference_row(session, user_id)
            # Retention is enforced before every attempt as well as at terminal
            # transitions. This bounds histories left by older failed/crashed
            # attempts even when the user never reaches a successful run.
            self._prune(
                session,
                user_id,
                preferences.retention_days,
                keep_run_id="",
            )
            session.commit()
            active_rows = list(
                session.scalars(
                    select(RecommendationRun)
                    .where(
                        RecommendationRun.user_id == user_id,
                        RecommendationRun.state.in_(("queued", "running")),
                    )
                    .order_by(RecommendationRun.created_at.desc())
                )
            )
            active = next((run for run in active_rows if self._compatible_run(run)), None)
            if active is not None:
                return self.run_payload(active), False
            for incompatible in active_rows:
                self._quarantine_incompatible_active(incompatible)
            if active_rows:
                session.flush()
            retry_candidates = list(
                session.scalars(
                    select(RecommendationRun)
                    .where(
                        RecommendationRun.user_id == user_id,
                        RecommendationRun.state == "failed",
                        RecommendationRun.retryable.is_(True),
                        self._scalar_compatibility_clause(),
                    )
                    .order_by(RecommendationRun.updated_at.desc())
                    .limit(20)
                )
            )
            retry_run = next(
                (row for row in retry_candidates if self._compatible_run(row)), None
            )
            if retry_run is not None:
                # Reuse the failed run and replace its durable scope. A delayed
                # delivery can then only race on this same CAS-guarded run; it
                # cannot later publish a stale second result beside a new run.
                if self.job_service is not None:
                    self.job_service.delete_scope(
                        kind="recommendation.generate",
                        scope_type="recommendation_run",
                        scope_id=retry_run.id,
                    )
                retry_run.state = "queued"
                retry_run.phase = RunPhase.CHECKING_READINESS.value
                retry_run.progress_percent = 0
                retry_run.progress_indeterminate = False
                retry_run.completed_units = None
                retry_run.total_units = None
                retry_run.message_key = "recommendations.progress.checking_readiness"
                retry_run.warning_codes = []
                retry_run.failure_code = None
                retry_run.safe_failure_detail = None
                retry_run.retryable = True
                retry_run.started_at = None
                retry_run.completed_at = None
                retry_run.updated_at = utcnow()
                session.commit()
                return self.run_payload(retry_run), False
            effective_idempotency_key = (
                f"{STANDARD_ENGINE_VERSION}:{idempotency_key}"
                if idempotency_key
                else f"{STANDARD_ENGINE_VERSION}:manual:{uuid4()}"
            )[:160]
            if idempotency_key:
                existing = session.scalar(
                    select(RecommendationRun).where(
                        RecommendationRun.user_id == user_id,
                        RecommendationRun.idempotency_key == effective_idempotency_key,
                        self._scalar_compatibility_clause(),
                    )
                )
                if existing is not None and self._compatible_run(existing):
                    return self.run_payload(existing), False
                if existing is not None:
                    effective_idempotency_key = (
                        f"{effective_idempotency_key[:149]}:compatible"
                    )[:160]
            run = RecommendationRun(
                user_id=user_id,
                distribution_flavor=self.build_manifest.distribution_flavor,
                engine="scalar",
                engine_version=STANDARD_ENGINE_VERSION,
                signal_contract_version=SIGNAL_CONTRACT_VERSION,
                score_scale_version=SCORE_SCALE_VERSION,
                model_versions={"scalar": STANDARD_ENGINE_VERSION},
                deterministic_seed=secrets.randbelow(2**31),
                idempotency_key=effective_idempotency_key,
                state="queued",
                phase=RunPhase.CHECKING_READINESS.value,
                progress_percent=0,
                progress_indeterminate=False,
                message_key="recommendations.progress.checking_readiness",
            )
            # The limit is bounded at the API and retained in non-private model metadata.
            run.model_versions = {
                "scalar": STANDARD_ENGINE_VERSION,
                "result_limit": result_limit,
            }
            session.add(run)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                active_rows = list(
                    session.scalars(
                        select(RecommendationRun)
                        .where(
                            RecommendationRun.user_id == user_id,
                            RecommendationRun.state.in_(("queued", "running")),
                        )
                        .order_by(RecommendationRun.created_at.desc())
                    )
                )
                active = next((row for row in active_rows if self._compatible_run(row)), None)
                if active is None:
                    raise
                return self.run_payload(active), False
            return self.run_payload(run), True

    def recover_pending(
        self,
        *,
        recoverable_running_ids: set[str] | None = None,
        capability_resumed_ids: set[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Reset interrupted runs so the shared durable queue can resume them."""

        recoverable_running_ids = recoverable_running_ids or set()
        capability_resumed_ids = capability_resumed_ids or set()
        with self.session_factory() as session:
            condition = RecommendationRun.state == "queued"
            resumable_running_ids = recoverable_running_ids | capability_resumed_ids
            if resumable_running_ids:
                condition = or_(
                    condition,
                    and_(
                        RecommendationRun.state == "running",
                        RecommendationRun.id.in_(resumable_running_ids),
                    ),
                )
            if capability_resumed_ids:
                condition = or_(
                    condition,
                    and_(
                        RecommendationRun.state == "failed",
                        RecommendationRun.retryable.is_(True),
                        RecommendationRun.id.in_(capability_resumed_ids),
                    ),
                )
            candidate_rows = list(
                session.scalars(
                    select(RecommendationRun).where(
                        condition,
                        self._scalar_compatibility_clause(),
                    )
                )
            )
            rows = [run for run in candidate_rows if self._compatible_run(run)]
            for run in rows:
                run.state = "queued"
                run.retryable = True
                run.progress_indeterminate = False
                run.warning_codes = sorted(set([*(run.warning_codes or []), "run_recovered"]))
                run.message_key = "recommendations.progress.recovering"
                run.updated_at = utcnow()
            session.commit()
            return [(run.id, run.user_id) for run in rows]

    def recover_run(self, run_id: str, user_id: str) -> bool:
        """Return one run to queued state after its durable lease has expired."""

        with self.session_factory() as session:
            run = self._raw_run_for_user(session, user_id, run_id)
            if not self._compatible_run(run):
                return False
            if run.state != "running":
                return run.state == "queued"
            run.state = "queued"
            run.retryable = True
            run.progress_indeterminate = False
            run.warning_codes = sorted(set([*(run.warning_codes or []), "run_recovered"]))
            run.message_key = "recommendations.progress.recovering"
            run.updated_at = utcnow()
            session.commit()
            return True

    @staticmethod
    def _progress(
        session: Session,
        run: RecommendationRun,
        phase: RunPhase,
        *,
        completed: int | None = None,
        total: int | None = None,
    ) -> None:
        current_state = session.scalar(
            select(RecommendationRun.state).where(RecommendationRun.id == run.id)
        )
        if current_state != "running":
            raise RecommendationCancelled("Recommendation generation was cancelled.")
        run.phase = phase.value
        run.progress_percent = max(run.progress_percent, PHASE_PROGRESS[phase])
        run.progress_indeterminate = total is None and phase not in {
            RunPhase.CHECKING_READINESS,
            RunPhase.READY,
        }
        run.completed_units = completed
        run.total_units = total
        run.message_key = f"recommendations.progress.{phase.value}"
        run.updated_at = utcnow()
        session.commit()

    async def generate(self, run_id: str, user_id: str) -> None:
        """Execute one durable run; all exceptions become safe persisted state."""

        try:
            with self.session_factory() as session:
                try:
                    candidate_run = self._raw_run_for_user(session, user_id, run_id)
                except RecommendationNotFound:
                    return
                if not self._compatible_run(candidate_run):
                    return
                claimed = session.execute(
                    update(RecommendationRun)
                    .where(
                        RecommendationRun.id == run_id,
                        RecommendationRun.user_id == user_id,
                        self._scalar_compatibility_clause(),
                        or_(
                            RecommendationRun.state == "queued",
                            and_(
                                RecommendationRun.state == "failed",
                                RecommendationRun.retryable.is_(True),
                            ),
                        ),
                    )
                    .values(
                        state="running",
                        started_at=func.coalesce(RecommendationRun.started_at, utcnow()),
                        retryable=False,
                        failure_code=None,
                        safe_failure_detail=None,
                        completed_at=None,
                        updated_at=utcnow(),
                    )
                    .execution_options(synchronize_session=False)
                )
                session.commit()
                if not claimed.rowcount:
                    return
                run = self._run_for_user(session, user_id, run_id)
                self._progress(session, run, RunPhase.CHECKING_READINESS)
                preferences = self.preference_row(session, user_id)

                self._progress(session, run, RunPhase.PREPARING_SIGNALS)
                signals = signal_snapshot(session, user_id=user_id, preferences=preferences)
                run.signal_snapshot_id = signals.id
                run.input_revision = signals.source_revision
                session.commit()

                self._progress(session, run, RunPhase.PREPARING_CANDIDATES)
                candidates = await candidate_snapshot(
                    session,
                    user_id=user_id,
                    preferences=preferences,
                    signals=signals,
                    live_source=self.live_source if self.live_source.available else None,
                )
                run.candidate_snapshot_id = candidates.id
                run.warning_codes = sorted(
                    set([*(run.warning_codes or []), *(candidates.warning_codes or [])])
                )
                session.commit()

                self._progress(
                    session,
                    run,
                    RunPhase.CHECKING_METADATA,
                    completed=(candidates.coverage or {}).get("with_identity", 0),
                    total=(candidates.coverage or {}).get("total", 0),
                )
                session.refresh(candidates, attribute_names=["items"])
                rows = list(candidates.items)
                if not rows:
                    raise RecommendationConflict(
                        "No eligible recommendation candidates are available yet."
                    )

                self._progress(
                    session,
                    run,
                    RunPhase.RETRIEVING,
                    completed=len(rows),
                    total=len(rows),
                )
                candidate_contracts = engine_candidates(rows)
                limit = int((run.model_versions or {}).get("result_limit") or 40)
                request = EngineRequest(
                    contract_version=ENGINE_CONTRACT_VERSION,
                    request_id=run.id,
                    engine="scalar",
                    input_revision=signals.source_revision,
                    deterministic_seed=run.deterministic_seed,
                    signals=[
                        PreferenceSignal.model_validate(value) for value in signals.signals
                    ],
                    evidence_anchors=[
                        EvidenceAnchor.model_validate(value)
                        for value in signals.evidence_anchors
                    ],
                    candidates=candidate_contracts,
                    limit=limit,
                )
                self._progress(
                    session,
                    run,
                    RunPhase.SCORING,
                    completed=0,
                    total=len(candidate_contracts),
                )
                catalog_items = {
                    row.candidate.catalog_item.id: row.candidate.catalog_item for row in rows
                }
                response = score_candidates(request=request)
                self._progress(
                    session,
                    run,
                    RunPhase.VALIDATING,
                    completed=len(response.results),
                    total=len(response.results),
                )
                response = validate_engine_response(
                    response,
                    permitted_catalog_ids=set(catalog_items),
                    permitted_anchor_ids={
                        anchor.catalog_id for anchor in request.evidence_anchors
                    },
                    input_revision=signals.source_revision,
                    request_id=request.request_id,
                    engine=request.engine,
                    result_limit=request.limit,
                )
                candidate_by_catalog = {
                    row.candidate.catalog_item_id: row.candidate for row in rows
                }
                # Reapply tenant ownership, feedback, and current exclusions after
                # scoring. A title added/rejected while the job was running cannot
                # leak into the saved result set.
                owned_now = set(
                    session.scalars(
                        select(WatchEntry.catalog_item_id).where(WatchEntry.user_id == user_id)
                    )
                )
                rejected_now = set(
                    session.scalars(
                        select(RecommendationResult.catalog_item_id)
                        .join(
                            RecommendationRun,
                            RecommendationRun.id == RecommendationResult.run_id,
                        )
                        .join(
                            RecommendationFeedback,
                            RecommendationFeedback.result_id == RecommendationResult.id,
                        )
                        .where(
                            RecommendationRun.user_id == user_id,
                            RecommendationFeedback.user_id == user_id,
                            RecommendationFeedback.feedback.in_(
                                ("not_interested", "already_seen")
                            ),
                        )
                    )
                )
                current_preferences = self.preference_row(session, user_id)
                excluded_types = set(current_preferences.excluded_media_types or [])
                excluded_genres = {
                    str(value).casefold()
                    for value in (current_preferences.excluded_genres or [])
                }
                eligible_results = [
                    item
                    for item in response.results
                    if item.catalog_id not in owned_now
                    and item.catalog_id not in rejected_now
                    and eligible_catalog_item(
                        catalog_items[item.catalog_id],
                        excluded_media_types=excluded_types,
                        excluded_genres=excluded_genres,
                    )
                ]
                self._progress(
                    session,
                    run,
                    RunPhase.SAVING,
                    completed=0,
                    total=len(eligible_results),
                )
                session.execute(
                    delete(RecommendationResult).where(RecommendationResult.run_id == run.id)
                )
                for saved_rank, item in enumerate(eligible_results, start=1):
                    candidate = candidate_by_catalog[item.catalog_id]
                    session.add(
                        RecommendationResult(
                            run_id=run.id,
                            catalog_item_id=item.catalog_id,
                            candidate_id=candidate.id,
                            rank=saved_rank,
                            final_match=item.match,
                            display_match=display_match(item.match),
                            confidence=item.confidence,
                            baseline_contribution=item.match,
                            reason_codes=item.reason_codes,
                            risk_codes=item.risk_codes,
                            anchor_catalog_ids=item.anchor_catalog_ids,
                            eligibility_snapshot={
                                "eligible": True,
                                "personalized": "discovery_only" not in item.risk_codes,
                                "score_label": (
                                    "match"
                                    if "discovery_only" not in item.risk_codes
                                    else "discovery_fit"
                                ),
                            },
                            provenance={
                                "engine": STANDARD_ENGINE_VERSION,
                                "source": candidate.source,
                                "reason_message_keys": message_keys(item.reason_codes),
                                "contributions": item.contributions,
                            },
                        )
                    )
                # Preserve the bounded request limit alongside the engine's
                # immutable implementation versions.  The limit is part of the
                # reproducible run contract even though it is not an engine
                # implementation version returned by ``score_candidates``.
                run.model_versions = {
                    **response.model_versions,
                    "result_limit": limit,
                }
                run.retryable = False
                run.failure_code = None
                run.safe_failure_detail = None
                self._progress(
                    session,
                    run,
                    RunPhase.READY,
                    completed=len(eligible_results),
                    total=len(eligible_results),
                )
                run.state = "completed"
                run.completed_at = utcnow()
                run.updated_at = utcnow()
                self._prune(session, user_id, preferences.retention_days, keep_run_id=run.id)
                session.commit()
        except RecommendationCancelled:
            return
        except Exception as exc:
            logger.warning(
                "Recommendation run failed: run=%s type=%s", run_id, type(exc).__name__
            )
            with self.session_factory() as session:
                try:
                    run = self._run_for_user(session, user_id, run_id)
                except RecommendationNotFound:
                    return
                run.state = "failed"
                run.failure_code = (
                    "no_candidates"
                    if isinstance(exc, RecommendationConflict)
                    else "generation_failed"
                )
                run.retryable = not isinstance(exc, RecommendationConflict)
                run.safe_failure_detail = (
                    "Add or refresh candidate metadata, then try again."
                    if isinstance(exc, RecommendationConflict)
                    else "Recommendation generation could not finish. Try again."
                )
                run.progress_indeterminate = False
                run.message_key = f"recommendations.failure.{run.failure_code}"
                run.completed_at = utcnow()
                run.updated_at = utcnow()
                # Publish the terminal transition before pruning. Sessions use
                # autoflush=False, and durable-job cleanup uses its own short
                # transaction; this keeps the terminal row visible without
                # holding a SQLite writer lock across the cleanup transaction.
                session.commit()
                preferences = self.preference_row(session, user_id)
                self._prune(
                    session,
                    user_id,
                    preferences.retention_days,
                    keep_run_id=run.id,
                )
                session.commit()

    def _prune(
        self, session: Session, user_id: str, retention_days: int, *, keep_run_id: str
    ) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=max(30, retention_days))
        old_ids = list(
            session.scalars(
                select(RecommendationRun.id).where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.id != keep_run_id,
                    RecommendationRun.state.in_(("completed", "failed", "cancelled")),
                    RecommendationRun.created_at < cutoff,
                )
            )
        )
        overflow_ids = list(
            session.scalars(
                select(RecommendationRun.id)
                .where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.state.in_(("completed", "failed", "cancelled")),
                )
                .order_by(RecommendationRun.created_at.desc(), RecommendationRun.id.desc())
                .offset(self.MAX_TERMINAL_RUNS_PER_USER)
            )
        )
        old_ids = sorted((set(old_ids) | set(overflow_ids)) - {keep_run_id})
        if old_ids:
            if self.job_service is not None:
                for run_id in old_ids:
                    self.job_service.delete_scope(
                        kind="recommendation.generate",
                        scope_type="recommendation_run",
                        scope_id=run_id,
                    )
            session.execute(delete(RecommendationRun).where(RecommendationRun.id.in_(old_ids)))
            session.flush()
        referenced_candidates = set(
            session.scalars(
                select(RecommendationRun.candidate_snapshot_id).where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.candidate_snapshot_id.is_not(None),
                )
            )
        )
        candidate_snapshots = list(
            session.scalars(
                select(RecommendationCandidateSnapshot.id).where(
                    RecommendationCandidateSnapshot.user_id == user_id,
                )
            )
        )
        stale_candidates = [
            item for item in candidate_snapshots if item not in referenced_candidates
        ]
        if stale_candidates:
            session.execute(
                delete(RecommendationCandidateSnapshot).where(
                    RecommendationCandidateSnapshot.id.in_(stale_candidates)
                )
            )
            session.flush()
        referenced_signals = set(
            session.scalars(
                select(RecommendationRun.signal_snapshot_id).where(
                    RecommendationRun.user_id == user_id,
                    RecommendationRun.signal_snapshot_id.is_not(None),
                )
            )
        )
        referenced_signals.update(
            session.scalars(
                select(RecommendationCandidateSnapshot.signal_snapshot_id).where(
                    RecommendationCandidateSnapshot.user_id == user_id
                )
            )
        )
        signal_snapshots = list(
            session.scalars(
                select(RecommendationSignalSnapshot.id).where(
                    RecommendationSignalSnapshot.user_id == user_id,
                )
            )
        )
        stale_signals = [item for item in signal_snapshots if item not in referenced_signals]
        if stale_signals:
            session.execute(
                delete(RecommendationSignalSnapshot).where(
                    RecommendationSignalSnapshot.id.in_(stale_signals)
                )
            )

    def run(self, user_id: str, run_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            return self.run_payload(self._run_for_user(session, user_id, run_id))

    def results(self, user_id: str, run_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            run = self._run_for_user(session, user_id, run_id)
            rows = list(
                session.scalars(
                    select(RecommendationResult)
                    .where(RecommendationResult.run_id == run.id)
                    .order_by(RecommendationResult.rank)
                    .options(selectinload(RecommendationResult.catalog_item))
                )
            )
            owned = set(
                session.scalars(
                    select(WatchEntry.catalog_item_id).where(WatchEntry.user_id == user_id)
                )
            )
            feedback_by_result = {
                feedback.result_id: feedback.feedback
                for feedback in session.scalars(
                    select(RecommendationFeedback).where(
                        RecommendationFeedback.user_id == user_id,
                        RecommendationFeedback.result_id.in_([row.id for row in rows]),
                    )
                )
            }
            signals = (
                session.get(RecommendationSignalSnapshot, run.signal_snapshot_id)
                if run.signal_snapshot_id
                else None
            )
            personalized = bool(
                signals and (signals.evidence_counts or {}).get("confirmed_signals", 0)
            )
            return {
                "run": self.run_payload(run),
                "personalized": personalized,
                "score_label": "match" if personalized else "discovery_fit",
                "results": [
                    {
                        "id": row.id,
                        "rank": row.rank,
                        "catalog_id": row.catalog_item_id,
                        "title": row.catalog_item.canonical_title,
                        "year": row.catalog_item.release_year,
                        "media_type": row.catalog_item.media_type,
                        "poster_url": row.catalog_item.poster_url,
                        "overview": row.catalog_item.overview,
                        "genres": list(
                            row.catalog_item.normalized_genres
                            or row.catalog_item.provider_genres
                            or []
                        )[:5],
                        "provider_source": row.catalog_item.provider_source,
                        "provider_id": row.catalog_item.provider_id,
                        "match": row.final_match,
                        "display_match": row.display_match,
                        "confidence": row.confidence,
                        "confidence_label": confidence_label(row.confidence),
                        "personalized": bool(
                            (row.eligibility_snapshot or {}).get("personalized")
                        ),
                        "score_label": (
                            (row.eligibility_snapshot or {}).get("score_label")
                            or (
                                "discovery_fit"
                                if "discovery_only" in (row.risk_codes or [])
                                else "match"
                            )
                        ),
                        "reason_codes": row.reason_codes or [],
                        "reason_message_keys": message_keys(row.reason_codes or []),
                        "risk_codes": row.risk_codes or [],
                        "feedback": feedback_by_result.get(row.id),
                        "in_library": row.catalog_item_id in owned,
                    }
                    for row in rows
                ],
            }

    def feedback(self, user_id: str, result_id: str, value: str) -> dict[str, Any]:
        with self.session_factory() as session:
            selected = session.execute(
                select(RecommendationResult, RecommendationRun)
                .join(RecommendationRun, RecommendationRun.id == RecommendationResult.run_id)
                .where(
                    RecommendationResult.id == result_id,
                    RecommendationRun.user_id == user_id,
                    self._scalar_compatibility_clause(),
                )
            ).first()
            if selected is None or not self._compatible_run(selected[1]):
                raise RecommendationNotFound("Recommendation result not found")
            row = session.scalar(
                select(RecommendationFeedback).where(
                    RecommendationFeedback.user_id == user_id,
                    RecommendationFeedback.result_id == result_id,
                )
            )
            if row is None:
                row = RecommendationFeedback(
                    user_id=user_id, result_id=result_id, feedback=value
                )
                session.add(row)
            else:
                row.feedback = value
                row.created_at = utcnow()
            session.commit()
            return {"result_id": result_id, "feedback": value}

    def delete_user_data(self, user_id: str) -> dict[str, int]:
        deleted_jobs = 0
        with self.session_factory() as session:
            run_ids = list(
                session.scalars(
                    select(RecommendationRun.id).where(RecommendationRun.user_id == user_id)
                )
            )
            active_ids = list(
                session.scalars(
                    select(RecommendationRun.id).where(
                        RecommendationRun.id.in_(run_ids),
                        RecommendationRun.state.in_(("queued", "running")),
                    )
                )
            )
            for run_id in run_ids:
                if self.job_service is not None:
                    self.job_service.cancel_scope(
                        kind="recommendation.generate",
                        scope_type="recommendation_run",
                        scope_id=run_id,
                    )
                    delete_scope = getattr(self.job_service, "delete_scope", None)
                    if delete_scope is not None:
                        deleted_jobs += delete_scope(
                            kind="recommendation.generate",
                            scope_type="recommendation_run",
                            scope_id=run_id,
                        )
            if self.job_service is not None:
                delete_user_kind = getattr(self.job_service, "delete_user_kind", None)
                if delete_user_kind is not None:
                    deleted_jobs += delete_user_kind(
                        kind="recommendation.generate", user_id=user_id
                    )
            session.execute(
                update(RecommendationRun)
                .where(RecommendationRun.id.in_(active_ids))
                .values(state="cancelled", completed_at=utcnow(), updated_at=utcnow())
            )
            session.commit()
        with self.session_factory() as session:
            counts = {
                "jobs": deleted_jobs,
                "runs": session.scalar(
                    select(func.count())
                    .select_from(RecommendationRun)
                    .where(RecommendationRun.user_id == user_id)
                )
                or 0,
                "signals": session.scalar(
                    select(func.count())
                    .select_from(RecommendationSignalSnapshot)
                    .where(RecommendationSignalSnapshot.user_id == user_id)
                )
                or 0,
                "claims": session.scalar(
                    select(func.count())
                    .select_from(RecommendationPreferenceClaim)
                    .where(RecommendationPreferenceClaim.user_id == user_id)
                )
                or 0,
                "results": session.scalar(
                    select(func.count())
                    .select_from(RecommendationResult)
                    .join(
                        RecommendationRun,
                        RecommendationRun.id == RecommendationResult.run_id,
                    )
                    .where(RecommendationRun.user_id == user_id)
                )
                or 0,
                "feedback": session.scalar(
                    select(func.count())
                    .select_from(RecommendationFeedback)
                    .where(RecommendationFeedback.user_id == user_id)
                )
                or 0,
                "candidate_snapshots": session.scalar(
                    select(func.count())
                    .select_from(RecommendationCandidateSnapshot)
                    .where(RecommendationCandidateSnapshot.user_id == user_id)
                )
                or 0,
                "preferences": session.scalar(
                    select(func.count())
                    .select_from(UserRecommendationPreference)
                    .where(UserRecommendationPreference.user_id == user_id)
                )
                or 0,
                "qualifications": session.scalar(
                    select(func.count())
                    .select_from(RecommendationModelQualification)
                    .where(RecommendationModelQualification.user_id == user_id)
                )
                or 0,
            }
            for model in (
                RecommendationModelQualification,
                RecommendationPreferenceClaim,
                RecommendationFeedback,
                RecommendationRun,
                RecommendationCandidateSnapshot,
                RecommendationSignalSnapshot,
                UserRecommendationPreference,
            ):
                session.execute(delete(model).where(model.user_id == user_id))
            session.commit()
            return counts

    def export(self, user_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            preference = session.get(UserRecommendationPreference, user_id)
            runs = list(
                session.scalars(
                    select(RecommendationRun)
                    .where(RecommendationRun.user_id == user_id)
                    .order_by(RecommendationRun.created_at)
                )
            )
            results = list(
                session.execute(
                    select(RecommendationResult, RecommendationRun)
                    .join(
                        RecommendationRun, RecommendationRun.id == RecommendationResult.run_id
                    )
                    .where(RecommendationRun.user_id == user_id)
                    .order_by(RecommendationRun.created_at, RecommendationResult.rank)
                )
            )
            feedback = list(
                session.scalars(
                    select(RecommendationFeedback)
                    .where(RecommendationFeedback.user_id == user_id)
                    .order_by(RecommendationFeedback.created_at)
                )
            )
            claims = list(
                session.scalars(
                    select(RecommendationPreferenceClaim)
                    .where(RecommendationPreferenceClaim.user_id == user_id)
                    .order_by(RecommendationPreferenceClaim.created_at)
                )
            )
            return {
                "schema_version": "recommendations-export-v1",
                "generated_at": _utc_iso(utcnow()),
                "preferences": self.preference_payload(preference, effective_for_build=False)
                if preference
                else None,
                "runs": [self.run_payload(run) for run in runs],
                "results": [
                    {
                        "run_id": run.id,
                        "catalog_id": result.catalog_item_id,
                        "provider_source": result.catalog_item.provider_source,
                        "provider_id": result.catalog_item.provider_id,
                        "rank": result.rank,
                        "match": result.final_match,
                        "confidence": result.confidence,
                        "reason_codes": result.reason_codes or [],
                        "risk_codes": result.risk_codes or [],
                    }
                    for result, run in results
                ],
                "feedback": [
                    {
                        "result_id": row.result_id,
                        "feedback": row.feedback,
                        "created_at": _utc_iso(row.created_at),
                    }
                    for row in feedback
                ],
                "confirmed_claims": [
                    {
                        "dimension": row.dimension,
                        "value": row.value,
                        "confidence": row.confidence,
                        "source_revision": row.source_revision,
                        "confirmed_at": _utc_iso(row.confirmed_at),
                        "revoked_at": _utc_iso(row.revoked_at),
                    }
                    for row in claims
                ],
            }
