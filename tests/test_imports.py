from __future__ import annotations

import io
import zipfile

from conftest import manual_payload


def upload_csv(client, text: str):
    return client.post(
        "/api/imports/preview",
        files={"file": ("user_library.csv", text.encode(), "text/csv")},
        data={"import_kind": "canonical"},
    )


def test_canonical_csv_preview_commit_preserves_ratings_ids_and_is_idempotent(client):
    csv_text = """title,year,media_type,watched_status,user_rating,rewatch_count,external_tmdb_id,notes
Legacy Film,2010,movie,watched,8.5,0,123,quiet
Again,2012,movie,rewatched,9,2,124,
"""
    preview = upload_csv(client, csv_text)
    assert preview.status_code == 200
    body = preview.json()
    assert body["counts"]["parsed_rows"] == 2
    assert body["counts"]["new_entries"] == 2
    assert any("total view_count=1" in note for note in body["normalizations"])
    committed = client.post(
        f"/api/imports/{body['preview_id']}/commit", json={"conflict_policy": None}
    )
    assert committed.status_code == 200
    entries = client.get("/api/entries", params={"sort": "title", "direction": "asc"}).json()[
        "items"
    ]
    assert entries[0]["catalog_item"]["canonical_title"] == "Again"
    assert entries[0]["view_count"] == 2
    legacy = next(
        row for row in entries if row["catalog_item"]["canonical_title"] == "Legacy Film"
    )
    assert legacy["personal_rating"] == 8.5
    assert legacy["catalog_item"]["tmdb_movie_id"] == "123"
    second_preview = upload_csv(client, csv_text).json()
    assert second_preview["already_imported"] is True
    second_commit = client.post(
        f"/api/imports/{second_preview['preview_id']}/commit", json={}
    ).json()
    assert second_commit["status"] == "already_imported"
    assert client.get("/api/entries").json()["total"] == 2


def test_conflict_requires_explicit_policy_and_preserves_existing(client):
    existing = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Conflict",
            release_year=2001,
            personal_rating=9,
            notes="my edit",
            provider_source="tmdb_movie",
            provider_id="5",
            tmdb_movie_id="5",
        ),
    ).json()["entry"]
    text = "title,year,media_type,provider_source,provider_id,personal_rating,notes\nConflict,2001,movie,tmdb_movie,5,7,imported\n"
    preview = upload_csv(client, text).json()
    assert preview["counts"]["conflicts"] == 1
    blocked = client.post(f"/api/imports/{preview['preview_id']}/commit", json={})
    assert blocked.status_code == 409
    committed = client.post(
        f"/api/imports/{preview['preview_id']}/commit",
        json={"conflict_policy": "preserve_existing"},
    )
    assert committed.status_code == 200
    after = client.get(f"/api/entries/{existing['id']}").json()
    assert after["personal_rating"] == 9
    assert after["notes"] == "my edit"


def test_invalid_import_does_not_partially_commit(client):
    text = "title,year,personal_rating\nGood,2020,8\nBad,2021,7.25\n"
    preview = upload_csv(client, text).json()
    assert preview["counts"]["invalid_rows"] == 1
    response = client.post(f"/api/imports/{preview['preview_id']}/commit", json={})
    assert response.status_code == 409
    assert client.get("/api/entries").json()["total"] == 0
    accepted = client.post(
        f"/api/imports/{preview['preview_id']}/commit", json={"allow_invalid": True}
    )
    assert accepted.status_code == 200
    assert client.get("/api/entries").json()["total"] == 1


def letterboxd_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "diary.csv",
            "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Watched Date\n"
            "2024-01-03,Film,2020,https://letterboxd.com/film/film/,4.5,No,2024-01-02\n"
            "2025-02-04,Film,2020,https://letterboxd.com/film/film/,,Yes,2025-02-03\n",
        )
        archive.writestr(
            "watchlist.csv",
            "Date,Name,Year,Letterboxd URI\n2023-01-01,Film,2020,https://letterboxd.com/film/film/\n",
        )
        archive.writestr(
            "ratings.csv",
            "Date,Name,Year,Letterboxd URI,Rating\n2025-02-04,Film,2020,https://letterboxd.com/film/film/,4.5\n",
        )
    return output.getvalue()


def test_letterboxd_diary_events_rating_and_watchlist_no_downgrade(client):
    content = letterboxd_zip()
    preview = client.post(
        "/api/imports/preview",
        files={"file": ("letterboxd-export.zip", content, "application/zip")},
        data={"import_kind": "letterboxd"},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["counts"]["parsed_rows"] == 1
    committed = client.post(f"/api/imports/{body['preview_id']}/commit", json={})
    assert committed.status_code == 200
    assert committed.json()["viewing_events_added"] == 2
    entry = client.get("/api/entries").json()["items"][0]
    detail = client.get(f"/api/entries/{entry['id']}").json()
    assert detail["status"] == "watched"
    assert detail["personal_rating"] == 9
    assert detail["view_count"] == 2
    assert [event["viewed_on"] for event in detail["viewing_events"]] == [
        "2024-01-02",
        "2025-02-03",
    ]


def test_reference_canonical_shape_maps_types_status_counts_and_context(client):
    text = """record_id,media_type,title,source_title,rating,rating_label,rank_position,rank_status,view_status,times_watched,release_year,season_scope,progress,notes,source_occurrences,source_sections,source_order
show-beef,show,Beef,BEEF x2,10,Amazing,,,completed,2,,,,,1,Show rating 10,168
anime-example,anime,Example Anime,Example Anime,8,Great,,,partial,0,,Season 1,4 of 12,,1,Anime rating 8,169
movie-example,movie,Example Film,Example Film,7,Good,,,completed,0,2022,,,,1,Movie rating 7,170
"""
    preview = upload_csv(client, text)
    assert preview.status_code == 200
    body = preview.json()
    assert body["counts"]["invalid_rows"] == 0
    assert body["media_type_breakdown"] == {"anime": 1, "movie": 1, "tv": 1}
    assert body["status_breakdown"] == {"watched": 2, "watching": 1}

    committed = client.post(f"/api/imports/{body['preview_id']}/commit", json={})
    assert committed.status_code == 200
    entries = client.get("/api/entries", params={"page_size": 10}).json()["items"]
    beef = next(item for item in entries if item["catalog_item"]["canonical_title"] == "Beef")
    assert beef["catalog_item"]["media_type"] == "tv"
    assert beef["status"] == "watched"
    assert beef["view_count"] == 2
    assert beef["personal_rating"] == 10
    assert beef["import_context"]["record_id"] == "show-beef"
    assert beef["import_context"]["source_title"] == "BEEF x2"
    anime = next(
        item for item in entries if item["catalog_item"]["canonical_title"] == "Example Anime"
    )
    assert anime["catalog_item"]["media_type"] == "anime"
    assert anime["status"] == "watching"
    movie = next(
        item for item in entries if item["catalog_item"]["canonical_title"] == "Example Film"
    )
    assert movie["view_count"] == 1
    assert any("completed status" in note for note in body["normalizations"])

    summary = client.get("/api/stats").json()["summary"]
    assert summary["completed_movies"] == 1
    assert summary["completed_tv"] == 1
    assert summary["completed_anime"] == 0


def test_reimport_repairs_old_unresolved_movie_classification_without_duplicate(client):
    original = client.post(
        "/api/entries/manual",
        json=manual_payload(
            "Beef",
            release_year=None,
            media_type="movie",
            personal_rating=None,
            provider_genres=[],
        ),
    ).json()["entry"]
    text = """record_id,media_type,title,rating,view_status,times_watched
show-beef,show,Beef,10,completed,2
"""
    preview = upload_csv(client, text).json()
    assert preview["counts"]["new_entries"] == 0
    assert preview["counts"]["updates"] == 1
    assert preview["counts"]["media_type_corrections"] == 1

    committed = client.post(f"/api/imports/{preview['preview_id']}/commit", json={})
    assert committed.status_code == 200
    assert client.get("/api/entries").json()["total"] == 1
    repaired = client.get(f"/api/entries/{original['id']}").json()
    assert repaired["catalog_item"]["media_type"] == "tv"
    assert repaired["view_count"] == 2
    assert repaired["personal_rating"] == 10
