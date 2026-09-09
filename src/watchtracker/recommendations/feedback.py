"""Tenant-scoped feedback semantics, shared by discovery and final validation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from watchtracker.models import RecommendationFeedback, RecommendationResult, RecommendationRun

SNOOZE_DAYS = 7


def latest_feedback(session: Session, user_id: str) -> dict[str, RecommendationFeedback]:
    rows = session.execute(
        select(RecommendationResult.catalog_item_id, RecommendationFeedback)
        .join(RecommendationRun, RecommendationRun.id == RecommendationResult.run_id)
        .join(
            RecommendationFeedback, RecommendationFeedback.result_id == RecommendationResult.id
        )
        .where(RecommendationRun.user_id == user_id, RecommendationFeedback.user_id == user_id)
        .order_by(RecommendationFeedback.created_at.desc(), RecommendationFeedback.id.desc())
    )
    latest = {}
    for catalog_id, feedback in rows:
        latest.setdefault(catalog_id, feedback)
    return latest


def suppressed_catalog_ids(
    session: Session, user_id: str, *, now: datetime | None = None
) -> set[str]:
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    suppressed = set()
    for catalog_id, feedback in latest_feedback(session, user_id).items():
        created = feedback.created_at
        created = (
            created.replace(tzinfo=UTC) if created.tzinfo is None else created.astimezone(UTC)
        )
        if feedback.feedback in {"not_interested", "already_seen"} or (
            feedback.feedback == "wrong_mood" and created + timedelta(days=SNOOZE_DAYS) > now
        ):
            suppressed.add(catalog_id)
    return suppressed
