from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from conftest import manual_payload
from sqlalchemy import func, select

from watchtracker.models import ProviderProgressClaim, ViewingCycle, ViewingEvent, WatchEntry
from watchtracker.services.viewing_policy import (
    PlaybackObservation,
    ViewingReducer,
    evaluate_playback_observation,
)


def test_golden_playback_timelines_have_deterministic_policy_decisions():
    fixture = json.loads(
        (Path(__file__).parents[1] / "contracts/viewing-policy/v1/timelines.json").read_text()
    )
    evaluated = 0
    for scenario in fixture["scenarios"]:
        raw = scenario.get("observation")
        if raw is None or scenario["id"] in {"exact_provider_retry", "two_provider_duplicate"}:
            continue
        decision = evaluate_playback_observation(
            PlaybackObservation(
                event=raw["event"],
                position_seconds=raw.get("position_seconds", 0),
                duration_seconds=raw.get("duration_seconds", 0),
                active_seconds=raw.get("active_seconds"),
                strong_completion=raw.get("strong_completion", False),
            )
        )
        assert decision == scenario["expected"]["decision"]
        evaluated += 1
    assert evaluated >= 5


def test_reducer_merges_cross_provider_completion_and_requires_explicit_rewatch(app, client):
    entry_id = client.post(
        "/api/entries/manual",
        json=manual_payload("Reducer fixture", status="plan_to_watch", view_count=0),
    ).json()["entry"]["id"]
    first_time = datetime(2026, 8, 27, 12, tzinfo=UTC)
    with app.state.session_factory() as session:
        entry = session.get(WatchEntry, entry_id)
        reducer = ViewingReducer(session, user_id=entry.user_id)
        first, outcome = reducer.record_title_completion(
            entry,
            viewed_on=date(2026, 8, 27),
            source="integration",
            source_key="plex:delivery-1",
            source_event_key="plex:event-1",
            occurred_at=first_time,
        )
        assert outcome == "created"
        merged, outcome = reducer.record_title_completion(
            entry,
            viewed_on=date(2026, 8, 27),
            source="integration",
            source_key="jellyfin:delivery-1",
            source_event_key="jellyfin:event-9",
            occurred_at=first_time + timedelta(hours=2),
        )
        assert outcome == "merged"
        assert merged.id == first.id
        assert entry.view_count == 1
        cycle = reducer.start_rewatch(entry, target_episode_ids=[], initiated_by="ui")
        second, outcome = reducer.record_title_completion(
            entry,
            viewed_on=None,
            source="ui",
            source_key="manual-rewatch-1",
            occurred_at=first_time + timedelta(days=10),
        )
        assert outcome == "created"
        assert second.cycle_id == cycle.id
        assert entry.view_count == 2
        assert cycle.state == "completed"
        session.commit()
        assert (
            session.scalar(
                select(func.count(ViewingEvent.id)).where(ViewingEvent.deleted_at.is_(None))
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(ViewingCycle.id)).where(ViewingCycle.kind == "rewatch")
            )
            == 1
        )


def test_aggregate_provider_progress_is_a_claim_not_synthetic_history(app, client):
    entry_id = client.post(
        "/api/entries/manual",
        json=manual_payload("Claim fixture", status="watching", view_count=0, media_type="tv"),
    ).json()["entry"]["id"]
    with app.state.session_factory() as session:
        entry = session.get(WatchEntry, entry_id)
        reducer = ViewingReducer(session, user_id=entry.user_id)
        reducer.accept_progress_claim(
            entry,
            provider="simkl",
            source_key="snapshot-1",
            episode_progress_count=6,
            repeat_count=1,
            completed_status=False,
        )
        session.commit()
        assert entry.episode_progress_count == 6
        assert session.scalar(select(func.count(ViewingEvent.id))) == 0
        assert session.scalar(select(func.count(ProviderProgressClaim.id))) == 1
