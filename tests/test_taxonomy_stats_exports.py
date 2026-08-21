from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

from conftest import manual_payload

from watchtracker.imports.parsers import parse_manual_csv
from watchtracker.taxonomy import effective_values, infer_taxonomy


def test_taxonomy_requires_evidence_and_user_overrides_win():
    inferred = infer_taxonomy(
        ["Drama", "Crime", "Science Fiction"],
        ["psychological", "thriller", "cerebral", "character study"],
        media_type="movie",
    )
    assert inferred.genres == ["Crime", "Drama", "Science Fiction"]
    assert "Psychological Thriller" in inferred.subgenres
    assert "Cerebral Sci-Fi" in inferred.subgenres
    assert "Body Horror" not in inferred.subgenres
    assert effective_values(inferred.genres, ["Mystery"], ["Drama"]) == [
        "Crime",
        "Mystery",
        "Science Fiction",
    ]
    assert inferred.provenance["version"] == "2.0"

    direct = infer_taxonomy([], ["romantic comedy"], media_type="movie")
    loose = infer_taxonomy([], ["romance in an action figure comedy"], media_type="movie")
    assert "Romantic Comedy" in direct.subgenres
    assert "Romantic Comedy" not in loose.subgenres
    assert "Action Comedy" not in loose.subgenres


def test_statistics_formulas_signals_and_tie_breaking(client):
    alpha = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Alpha",
            personal_rating=8,
            provider_genres=["Drama", "Crime"],
            keywords=["character study", "slow burn"],
            provider_format="Feature Film",
            country="US",
            language="en",
            runtime_minutes=110,
            watched_date="2026-07-01",
        ),
    ).json()["entry"]
    client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Beta",
            personal_rating=4,
            provider_genres=["Drama"],
            watched_date="2026-07-02",
        ),
    )
    client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Gamma",
            personal_rating=None,
            media_type="anime",
            provider_genres=["Psychological", "Thriller"],
            watched_date="2026-07-03",
        ),
    )
    client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Dropped",
            personal_rating=3,
            status="dropped",
            view_count=0,
            provider_genres=["Horror"],
        ),
    )
    client.post(
        "/api/entries/manual",
        json=manual_payload("Planned", status="plan_to_watch", view_count=0),
    )
    client.post(f"/api/entries/{alpha['id']}/viewings", json={"viewed_on": "2026-07-04"})

    stats = client.get("/api/stats").json()
    assert stats["summary"] == {
        "library_total": 5,
        "completed_total": 3,
        "completed_movies": 2,
        "completed_tv": 0,
        "completed_anime": 1,
    }
    assert stats["completion"] == {
        "rate": 0.75,
        "completed": 3,
        "dropped_without_completion": 1,
        "denominator": 4,
    }
    assert stats["rewatch"]["rate"] == 0.333
    assert stats["rating_profile"]["average"] == 6
    assert stats["rating_profile"]["median"] == 6
    assert stats["rating_profile"]["rated_count"] == 2
    assert stats["rating_profile"]["unrated_completed_count"] == 1
    assert stats["rating_profile"]["histogram"]["8"] == 1
    assert stats["rating_profile"]["histogram"]["4"] == 1
    drama = next(row for row in stats["genre_affinity"] if row["name"] == "Drama")
    crime = next(row for row in stats["genre_affinity"] if row["name"] == "Crime")
    assert drama["fractional_title_count"] == 1.5
    assert crime["fractional_title_count"] == 0.5
    assert drama["average_personal_rating"] == 6
    assert drama["rated_support_count"] == 2
    assert stats["positive_signals"][0]["title"] == "Alpha"
    negatives = {row["title"]: row["reason"] for row in stats["negative_signals"]}
    assert negatives["Beta"] == ["personal_rating <= 4"]
    assert negatives["Dropped"] == ["personal_rating <= 4", "dropped"]
    assert stats["top_titles"]["overall"][0]["title"] == "Alpha"
    assert stats["activity"]["dated_viewings"] == 4
    monthly = {row["period"]: row["count"] for row in stats["activity"]["monthly"]}
    assert monthly["2026-07"] == 4
    assert sum(monthly.values()) == 4
    assert sum(row["count"] for row in stats["activity"]["by_weekday"]) == 4
    assert stats["activity"]["by_year"] == [{"year": "2026", "count": 4}]
    assert {row["status"]: row["count"] for row in stats["status_distribution"]} == {
        "dropped": 1,
        "plan_to_watch": 1,
        "watched": 3,
    }
    assert stats["provider_tag_affinity"][0]["name"] in {
        "character study",
        "slow burn",
    }
    assert stats["format_preferences"][0]["name"] == "Feature Film"
    assert stats["runtime_preferences"][0]["name"] == "90–119 min"
    assert stats["rewatch_genre_signals"][0]["total_rewatches"] == 1
    identity_coverage = next(
        row for row in stats["metadata_coverage"] if row["name"] == "Verified provider identity"
    )
    assert identity_coverage == {
        "name": "Verified provider identity",
        "known_count": 0,
        "eligible_count": 5,
        "coverage": 0.0,
    }


def test_profile_json_markdown_agree_and_insufficient_data_is_honest(client):
    client.post(
        "/api/entries/manual",
        json=manual_payload(
            "One",
            personal_rating=9,
            provider_genres=["Drama"],
            watched_date=date.today().isoformat(),
        ),
    )
    profile_response = client.get("/api/exports/preference-profile.json")
    markdown_response = client.get("/api/exports/preference-profile.md")
    profile = profile_response.json()
    markdown = markdown_response.text
    assert profile["schema_version"] == "1.1"
    assert profile["scope"] == {"ratings_are_personal": True, "dated_activity_only": True}
    assert profile["rating_profile"]["average"] == 9
    assert "Average / median: 9.0 / 9.0" in markdown
    assert "One" in markdown
    assert all(
        "support_count" in row and "confidence" in row for row in profile["genre_affinity"]
    )
    assert all(row["state"] == "insufficient_data" for row in profile["taste_dimensions"])
    assert 'filename="preference-profile-' in profile_response.headers["content-disposition"]


def test_csv_export_is_safe_and_round_trippable(client):
    client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Formula Test",
            personal_rating=7.5,
            notes='=HYPERLINK("bad")',
            provider_source="tmdb_movie",
            provider_id="88",
            tmdb_movie_id="88",
            user_tags=["private", "+tag"],
            watched_date="2024-01-02",
            view_count=2,
            provider_genres=["Drama", "Crime"],
        ),
    )
    response = client.get("/api/exports/watch-log.csv")
    row = next(csv.DictReader(io.StringIO(response.text)))
    assert row["personal_rating"] == "7.5"
    assert row["provider_id"] == "88"
    assert row["view_count"] == "2"
    assert row["rewatch_count"] == "1"
    assert row["viewing_dates"] == "2024-01-02"
    assert row["notes"].startswith("'=")
    assert row["tags"].startswith("'+tag")
    imported, invalid, _warnings = parse_manual_csv(response.content)
    assert invalid == []
    assert imported[0]["notes"] == '=HYPERLINK("bad")'
    assert imported[0]["tags"] == ["+tag", "private"]
    assert imported[0]["viewing_events"][0]["viewed_on"] == "2024-01-02"
    assert 'filename="watch-log-' in response.headers["content-disposition"]


def test_obsidian_export_is_a_safe_vault_ready_markdown_snapshot(client):
    created = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "A/B: Memory",
            personal_rating=8.5,
            notes="A private **Markdown** note.",
            user_tags=["favorite", "slow burn"],
            watched_date="2026-08-20",
            poster_url="https://images.invalid/poster.jpg",
        ),
    ).json()["entry"]

    response = client.get("/api/exports/obsidian-vault.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "personal-media-tracker-obsidian-" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        title_notes = [name for name in names if "/Titles/" in name]
        assert names[0] == "Personal Media Tracker/Media Library.md"
        assert len(title_notes) == 1
        assert "A/B" not in title_notes[0]
        assert ".." not in title_notes[0]
        index = archive.read(names[0]).decode("utf-8")
        note = archive.read(title_notes[0]).decode("utf-8")
        readme = archive.read("Personal Media Tracker/README.md").decode("utf-8")

    assert f'pmt_id: "{created["id"]}"' in note
    assert "personal_rating: 8.5" in note
    assert (
        'tags: ["favorite","media/movie","personal-media-tracker","slow burn","status/watched"]'
        in note
    )
    assert "A private **Markdown** note." in note
    assert "2026-08-20" in note
    assert "[[Titles/A B Memory" in index
    assert "one-way snapshot" in readme
    assert "Private PMT notes are included" in readme
