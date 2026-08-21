from __future__ import annotations

import json
import time
import zipfile
from io import BytesIO

import pytest
from conftest import manual_payload

from watchtracker.models import CatalogItem, WatchEntry
from watchtracker.services.ratings import (
    AdvancedRankingService,
    calculate_rubric,
)


def _rated_entry(client, title: str, rating: float, **overrides):
    return client.post(
        "/api/entries/manual",
        json=manual_payload(title, personal_rating=rating, **overrides),
    ).json()["entry"]


def _enable(client, value: bool = True):
    response = client.put("/api/settings/general", json={"advanced_ratings_enabled": value})
    assert response.status_code == 200


def _core_answers(value: int = 5):
    return {
        "impact": value,
        "distinctiveness": value,
        "formula_freshness": value,
        "engagement": value,
        "coherence": value,
        "lasting_value": value,
    }


@pytest.mark.parametrize(
    ("answers", "score", "coverage", "partial"),
    [
        (_core_answers(1), 1.0, 6 / 8.05, False),
        (_core_answers(3.5), 6.6, 6 / 8.05, False),
        (_core_answers(5), 10.0, 6 / 8.05, False),
        (
            {"impact": 5, "distinctiveness": 4, "formula_freshness": 3, "engagement": 5},
            8.4,
            4.05 / 8.05,
            True,
        ),
        ({"impact": 5, "distinctiveness": 4, "formula_freshness": 3}, None, 3.05 / 8.05, False),
        (
            {
                **_core_answers(3),
                "consistency": "not_applicable",
                "rewatch_desire": "skip",
            },
            5.5,
            6 / 8.05,
            False,
        ),
    ],
)
def test_current_rubric_golden_cases(answers, score, coverage, partial):
    result = calculate_rubric(answers)
    assert result["suggested_rating"] == score
    assert result["rubric_coverage"] == pytest.approx(coverage)
    assert result["partial_suggestion"] is partial


def test_rubric_scale_accepts_only_half_steps():
    with pytest.raises(ValueError, match="0.5 steps"):
        calculate_rubric({"impact": 3.2})


def test_advanced_mode_defaults_off_and_draft_lifecycle_is_optimistic(client):
    entry = _rated_entry(client, "Guided", 7.0)
    assert client.get("/api/settings/general").json()["advanced_ratings_enabled"] is False
    disabled = client.post("/api/ratings/assessments", json={"entry_id": entry["id"]})
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "advanced_ratings_disabled"

    _enable(client)
    created = client.post(
        "/api/ratings/assessments",
        json={
            "entry_id": entry["id"],
            "answers": {"impact": 5},
            "private_reflection": "A private memory",
        },
    ).json()
    resumed = client.post("/api/ratings/assessments", json={"entry_id": entry["id"]}).json()
    assert resumed["id"] == created["id"]
    assert client.get(f"/api/entries/{entry['id']}").json()["personal_rating"] == 7.0

    patched = client.patch(
        f"/api/ratings/assessments/{created['id']}",
        json={"answers": _core_answers(5), "expected_version": created["version"]},
    ).json()
    stale = client.patch(
        f"/api/ratings/assessments/{created['id']}",
        json={"answers": _core_answers(4), "expected_version": created["version"]},
    )
    assert stale.status_code == 409
    assert patched["suggested_rating"] == 10.0

    completed = client.post(
        f"/api/ratings/assessments/{created['id']}/complete",
        json={
            "expected_version": patched["version"],
            "rating_action": "keep_rating",
        },
    ).json()
    assert completed["rating_changed"] is False
    assert completed["entry"]["personal_rating"] == 7.0
    assert completed["assessment"]["final_rating_snapshot"] == 7.0
    assert client.delete(f"/api/ratings/assessments/{created['id']}").status_code == 409

    _enable(client, False)
    retained = client.get(f"/api/ratings/assessments/{created['id']}")
    assert retained.status_code == 200
    assert retained.json()["private_reflection"] == "A private memory"


def test_assessment_can_complete_without_changing_scalar_and_reassessment_supersedes(client):
    entry = _rated_entry(client, "Stable Scalar", 8.2)
    _enable(client)
    first = client.post(
        "/api/ratings/assessments",
        json={"entry_id": entry["id"], "answers": _core_answers(5)},
    ).json()
    completed = client.post(
        f"/api/ratings/assessments/{first['id']}/complete",
        json={
            "expected_version": first["version"],
            "rating_action": "save_without_change",
        },
    ).json()
    assert completed["entry"]["personal_rating"] == 8.2

    second = client.post(
        "/api/ratings/assessments",
        json={"entry_id": entry["id"], "answers": _core_answers(2)},
    ).json()
    client.post(
        f"/api/ratings/assessments/{second['id']}/complete",
        json={"expected_version": second["version"], "rating_action": "keep_rating"},
    )
    assert client.get(f"/api/ratings/assessments/{first['id']}").json()["state"] == (
        "superseded"
    )
    assert client.get(f"/api/entries/{entry['id']}").json()["personal_rating"] == 8.2


def test_advanced_ranking_v2_pair_update_filter_invariance_and_undo(client):
    high = _rated_entry(client, "High", 9.0, media_type="movie")
    low = _rated_entry(client, "Low", 8.8, media_type="movie")
    _rated_entry(client, "Anime", 8.9, media_type="anime")
    _enable(client)

    draft = client.post(
        "/api/ratings/assessments",
        json={"entry_id": low["id"], "answers": _core_answers(5)},
    ).json()
    client.post(
        f"/api/ratings/assessments/{draft['id']}/complete",
        json={"expected_version": draft["version"], "rating_action": "keep_rating"},
    )
    before = client.get("/api/rankings").json()
    low_before = next(item for item in before["items"] if item["entry"]["id"] == low["id"])
    assert low_before["rubric_adjustment"] <= 0.75
    assert low_before["algorithm_version"] == "advanced-ranking-v2"

    candidate = client.get("/api/ratings/comparisons/next").json()["pair"]
    assert candidate is not None
    assert {candidate["left"]["id"], candidate["right"]["id"]} == {high["id"], low["id"]}
    result = "low" if low["id"] == candidate["pair_key"].split("~")[0] else "high"
    saved = client.put(
        f"/api/ratings/comparisons/{candidate['pair_key']}",
        json={"result": result, "displayed_left_entry_id": candidate["left"]["id"]},
    )
    assert saved.status_code == 200
    after = client.get("/api/rankings").json()
    low_after = next(item for item in after["items"] if item["entry"]["id"] == low["id"])
    assert low_after["comparison_count"] == 1
    assert 1 <= low_after["technical_score"] <= 10
    assert abs(low_after["pairwise_adjustment"]) <= 0.75

    filtered = client.get("/api/rankings", params={"media_type": "movie"}).json()
    filtered_low = next(item for item in filtered["items"] if item["entry"]["id"] == low["id"])
    assert filtered_low["technical_score"] == low_after["technical_score"]
    assert client.delete(f"/api/ratings/comparisons/{candidate['pair_key']}").status_code == 204
    assert (
        next(
            item
            for item in client.get("/api/rankings").json()["items"]
            if item["entry"]["id"] == low["id"]
        )["comparison_count"]
        == 0
    )


def test_focused_refinement_is_resumable_staged_and_keeps_scalar_ratings(client):
    entries = [
        _rated_entry(
            client, f"Refinement {index}", 7.0 + index / 10, view_count=8 if index == 0 else 1
        )
        for index in range(4)
    ]
    _enable(client)
    run = client.post("/api/ratings/refinement-runs", json={"scope": "focused"}).json()
    assert run["stage"] == "comparisons"
    assert run["comparison_target"] == 3
    assert run["assessment_target"] == 3
    assert run["rewatch_policy"] == "context_only"
    assert client.get("/api/ratings/refinement-runs/active").json()["run"]["id"] == run["id"]

    while run["stage"] == "comparisons":
        pair = client.get(
            "/api/ratings/comparisons/next", params={"refinement_run_id": run["id"]}
        ).json()["pair"]
        assert pair is not None
        response = client.put(
            f"/api/ratings/comparisons/{pair['pair_key']}",
            json={
                "result": "tie",
                "displayed_left_entry_id": pair["left"]["id"],
                "refinement_run_id": run["id"],
            },
        )
        assert response.status_code == 200
        run = response.json()["refinement"]

    assert run["stage"] == "assessments"
    while run["state"] == "active":
        entry = run["next_entry"]
        draft = client.post(
            "/api/ratings/assessments",
            json={"entry_id": entry["id"], "answers": _core_answers(4)},
        ).json()
        completed = client.post(
            f"/api/ratings/assessments/{draft['id']}/complete",
            json={
                "expected_version": draft["version"],
                "rating_action": "keep_rating",
                "refinement_run_id": run["id"],
            },
        )
        assert completed.status_code == 200
        run = client.get(f"/api/ratings/refinement-runs/{run['id']}").json()

    assert run["state"] == "completed"
    assert run["overall_percent"] == 100
    assert [
        client.get(f"/api/entries/{entry['id']}").json()["personal_rating"] for entry in entries
    ] == [
        7.0,
        7.1,
        7.2,
        7.3,
    ]
    technical = client.get("/api/rankings").json()["items"]
    rewatched = next(item for item in technical if item["entry"]["id"] == entries[0]["id"])
    assert rewatched["rewatch_count"] == 7
    assert rewatched["rewatch_policy"] == "context_only"


def test_refinement_can_undo_a_comparison_and_skip_uncertain_title_evidence(client):
    entries = [_rated_entry(client, f"Memory {index}", 7.0 + index / 10) for index in range(4)]
    _enable(client)
    run = client.post("/api/ratings/refinement-runs", json={"scope": "focused"}).json()
    pair = client.get(
        "/api/ratings/comparisons/next", params={"refinement_run_id": run["id"]}
    ).json()["pair"]
    run = client.put(
        f"/api/ratings/comparisons/{pair['pair_key']}",
        json={
            "result": "tie",
            "displayed_left_entry_id": pair["left"]["id"],
            "refinement_run_id": run["id"],
        },
    ).json()["refinement"]
    assert run["can_undo_comparison"] is True

    undone = client.post(
        f"/api/ratings/refinement-runs/{run['id']}/undo-comparison", json={}
    ).json()
    assert undone["comparisons_completed"] == 0
    assert undone["undone_pair_key"] == pair["pair_key"]

    while undone["stage"] == "comparisons":
        candidate = client.get(
            "/api/ratings/comparisons/next",
            params={"refinement_run_id": undone["id"]},
        ).json()["pair"]
        undone = client.put(
            f"/api/ratings/comparisons/{candidate['pair_key']}",
            json={
                "result": "skip",
                "displayed_left_entry_id": candidate["left"]["id"],
                "refinement_run_id": undone["id"],
            },
        ).json()["refinement"]

    skipped_id = undone["next_entry"]["id"]
    advanced = client.post(
        f"/api/ratings/refinement-runs/{undone['id']}/skip-entry",
        json={"entry_id": skipped_id},
    ).json()
    assert advanced["assessments_completed"] == 1
    assert client.get(f"/api/entries/{skipped_id}").json()["personal_rating"] in {
        entry["personal_rating"] for entry in entries
    }


def test_single_title_refinement_keeps_every_comparison_on_that_title(client):
    target = _rated_entry(client, "Single target", 8.0)
    neighbors = []
    for index in range(4):
        neighbors.append(
            _rated_entry(client, f"Single neighbor {index}", round(7.8 + index / 10, 1))
        )
    _enable(client)
    run = client.post(
        "/api/ratings/refinement-runs",
        json={"scope": "focused", "entry_id": target["id"]},
    ).json()
    assert run["target_entry_ids"] == [target["id"]]
    assert run["assessment_target"] == 1
    conflict = client.post(
        "/api/ratings/refinement-runs",
        json={"scope": "focused", "entry_id": neighbors[0]["id"]},
    )
    assert conflict.status_code == 409
    while run["stage"] == "comparisons":
        pair = client.get(
            "/api/ratings/comparisons/next", params={"refinement_run_id": run["id"]}
        ).json()["pair"]
        assert target["id"] in {pair["left"]["id"], pair["right"]["id"]}
        run = client.put(
            f"/api/ratings/comparisons/{pair['pair_key']}",
            json={
                "result": "tie",
                "displayed_left_entry_id": pair["left"]["id"],
                "refinement_run_id": run["id"],
            },
        ).json()["refinement"]
    assert run["next_entry"]["id"] == target["id"]


def test_advanced_export_is_deliberately_private_and_backup_counts_evidence(client):
    entry = _rated_entry(client, "Private Evidence", 8.0)
    _enable(client)
    draft = client.post(
        "/api/ratings/assessments",
        json={
            "entry_id": entry["id"],
            "answers": _core_answers(4),
            "private_reflection": "never flatten this",
        },
    ).json()
    client.post(
        f"/api/ratings/assessments/{draft['id']}/complete",
        json={"expected_version": draft["version"], "rating_action": "keep_rating"},
    )
    csv_value = client.get("/api/exports/watch-log.csv").text
    rankings_value = client.get("/api/rankings").text
    assert "never flatten this" not in csv_value
    assert "never flatten this" not in rankings_value
    exported = client.get("/api/exports/advanced-ratings.json")
    assert "advanced-ratings-private-" in exported.headers["content-disposition"]
    assert exported.json()["assessments"][0]["private_reflection"] == "never flatten this"

    archive = client.get("/api/exports/portable-library.zip")
    with zipfile.ZipFile(BytesIO(archive.content)) as source:
        manifest = json.loads(source.read("manifest.json"))
    assert manifest["database"]["rating_assessments"] == 1
    assert manifest["database"]["rating_comparisons"] == 0


def test_thousand_title_ranking_is_bounded_and_interactive(app, client):
    assert client.get("/health").status_code == 200
    with app.state.session_factory() as session:
        entries = []
        for index in range(1_000):
            catalog = CatalogItem(
                canonical_title=f"Synthetic {index:04d}",
                normalized_title=f"synthetic {index:04d}",
                media_type=("movie", "tv", "anime")[index % 3],
            )
            entries.append(
                WatchEntry(
                    catalog_item=catalog,
                    status="watched",
                    personal_rating=1 + (index % 91) / 10,
                    view_count=1,
                )
            )
        session.add_all(entries)
        session.commit()
        started = time.perf_counter()
        rows = AdvancedRankingService(session).rankings(advanced=True, page=1, page_size=100)
        elapsed = time.perf_counter() - started
    assert rows["total"] == 1_000
    assert len(rows["items"]) == 100
    assert elapsed < 2.0
