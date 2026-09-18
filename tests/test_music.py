from __future__ import annotations

import base64
import io
import json
import sqlite3
import zipfile
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from watchtracker.authorization import LOCAL_USER_ID, Principal, bind_principal
from watchtracker.models import MusicAlbum, UserAccount
from watchtracker.music.api import create_album, export_music, get_album, validate_members
from watchtracker.music.provider import MusicBrainzProvider
from watchtracker.music.schemas import AlbumInput


def music_payload(**changes):
    return {
        "title": "Synthetic Horizons",
        "artist": "Fixture Ensemble",
        "year": 2026,
        "status": "listening",
        "rating": 8.5,
        "genres": ["Electronic"],
        "tracks": [{"title": "Opening", "position": 1, "duration_ms": 125000}],
        **changes,
    }


def create(client, **changes):
    response = client.post("/api/music/albums", json=music_payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def editable(row):
    return {key: row[key] for key in AlbumInput.model_fields}


def test_new_music_defaults_to_plan_but_legacy_status_survives_unrelated_edits(client):
    response = client.post("/api/music/albums", json={"title": "New album", "artist": "Artist"})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "plan_to_listen"
    legacy = create(client, title="Legacy album", status="collected", notes="Original note")
    legacy = client.get(f"/api/music/albums/{legacy['id']}").json()
    assert legacy["status"] == "collected"
    body = {key: value for key, value in editable(legacy).items() if key != "status"}
    body.update(version=legacy["version"], notes="Only the note changed")
    response = client.put(f"/api/music/albums/{legacy['id']}", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == "collected"
    assert saved["tracks"] == legacy["tracks"]
    assert saved["rating"] == legacy["rating"]
    exported = client.get("/api/exports/music-collection.json").json()["albums"]
    assert next(row for row in exported if row["id"] == legacy["id"])["status"] == "collected"
    # A deliberate choice still changes status; no implicit history was added.
    body.update(version=saved["version"], status="listened")
    assert (
        client.put(f"/api/music/albums/{legacy['id']}", json=body).json()["status"]
        == "listened"
    )


@pytest.mark.parametrize("include_status", [False, True])
def test_legacy_music_imports_do_not_acquire_invented_plans(client, include_status):
    source = {
        "id": str(uuid4()),
        "title": "Legacy imported album",
        "artist": "Artist",
        "notes": "Original tracking notes",
        "rating": 7.5,
        "genres": ["Provider raw genre"],
        "subgenres": ["User subgenre"],
        "tracks": [{"id": str(uuid4()), "position": 1, "title": "Original track"}],
    }
    if include_status:
        source["status"] = "collected"
    document = {"format": "pmt-music-collection", "version": 1, "albums": [source]}
    preview = client.post("/api/music/import/preview", json={"document": document})
    assert preview.status_code == 200, preview.text
    response = client.post(
        "/api/music/import", json={"document": document, "sha256": preview.json()["sha256"]}
    )
    assert response.status_code == 200, response.text
    row = client.get("/api/music/albums").json()["items"][0]
    assert row["status"] == "collected"
    detail = client.get(f"/api/music/albums/{row['id']}").json()
    assert detail["notes"] == source["notes"] and detail["rating"] == source["rating"]
    assert detail["genres"] == source["genres"] and detail["subgenres"] == source["subgenres"]
    assert detail["tracks"][0]["id"] == source["tracks"][0]["id"]


@pytest.mark.parametrize("domain", ["music", "books"])
@pytest.mark.parametrize("sort", ["title", "creator", "rating", "recent"])
def test_collection_sort_direction_and_page_size_preserve_default_order(client, domain, sort):
    route = "/api/music/albums" if domain == "music" else "/api/books/entries"
    creator = "artist" if domain == "music" else "author"
    rows = []
    for title, score in [("Alpha", 2), ("Beta", 5), ("Gamma", 9)]:
        response = client.post(
            route, json={"title": title, creator: title + " creator", "rating": score}
        )
        assert response.status_code == 201, response.text
        rows.append(response.json()["id"])
    field = creator if sort == "creator" else sort
    for direction, expected in [("asc", rows), ("desc", list(reversed(rows)))]:
        response = client.get(
            route, params={"sort": field, "direction": direction, "page_size": 2}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 3 and page["pages"] == 2
        assert [row["id"] for row in page["items"]] == expected[:2]
        page2 = client.get(
            route, params={"sort": field, "direction": direction, "page_size": 2, "page": 2}
        ).json()
        assert [row["id"] for row in page2["items"]] == expected[2:]
    default = client.get(route, params={"sort": field}).json()
    expected_default = list(reversed(rows)) if field in {"recent", "rating"} else rows
    assert [row["id"] for row in default["items"]] == expected_default
    assert client.get(route, params={"direction": "sideways"}).status_code == 422


def test_music_isolation_crud_conflicts_and_lists(client):
    movie = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Screen sentinel",
            "media_type": "movie",
            "personal_rating": 7,
        },
    ).json()["entry"]
    before = client.get(f"/api/entries/{movie['id']}").json()
    album = create(client)
    assert client.get("/api/entries").json()["total"] == 1
    assert client.get("/api/music/albums").json()["total"] == 1
    assert client.post("/api/music/albums", json=music_payload()).status_code == 409
    changed = {**editable(album), "rating": 9, "version": album["version"]}
    saved = client.put(f"/api/music/albums/{album['id']}", json=changed)
    assert saved.status_code == 200
    assert client.put(f"/api/music/albums/{album['id']}", json=changed).status_code == 409
    assert saved.json()["tracks"][0]["id"] == album["tracks"][0]["id"]
    music_list = client.post(
        "/api/music/lists", json={"name": "Evenings", "album_ids": [album["id"]]}
    ).json()
    assert client.get(f"/api/music/albums?list_id={music_list['id']}").json()["total"] == 1
    assert (
        client.post(
            "/api/music/lists", json={"name": "Wrong domain", "album_ids": [movie["id"]]}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/music/albums/{album['id']}?version=1").status_code == 409
    assert client.delete(f"/api/music/albums/{album['id']}?version=2").status_code == 204
    assert client.get("/api/music/albums").json()["total"] == 0
    assert client.get("/api/music/lists").json()["items"][0]["album_ids"] == []
    assert client.get(f"/api/entries/{movie['id']}").json() == before
    # Removing a record must not permanently block adding that album again.
    assert create(client)["id"] != album["id"]


def test_artwork_export_import_and_full_backup(client, tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), "#923949").save(buffer, "PNG")
    artwork = client.post(
        "/api/music/artwork", files={"file": ("cover.png", buffer.getvalue(), "image/png")}
    ).json()["artwork_data"]
    album = create(client, artwork_data=artwork, notes="Private music note")
    book = client.post(
        "/api/books/entries",
        json={"title": "Book backup sentinel", "author": "Fixture", "artwork_data": artwork},
    ).json()
    image = client.get(album["cover_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert "artwork_data" not in client.get("/api/music/albums").json()["items"][0]
    client.post(
        "/api/music/lists", json={"name": "Cover collection", "album_ids": [album["id"]]}
    )
    document = client.get("/api/exports/music-collection.json").json()
    assert document["albums"][0]["artwork_data"].startswith("data:image/jpeg;base64,")
    preview = client.post("/api/music/import/preview", json={"document": document}).json()
    assert preview["new_albums"] == 0
    assert client.post("/api/music/import", json={"document": document}).status_code == 409
    response = client.post(
        "/api/music/import", json={"document": document, "sha256": preview["sha256"]}
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/music/lists").json()["items"].__len__() == 1
    assert client.get("/api/music/albums").json()["total"] == 1
    assert "Synthetic Horizons" not in client.get("/api/exports/watch-log.csv").text
    exported = client.get("/api/exports/portable-library.zip")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        db = tmp_path / "exported.sqlite3"
        db.write_bytes(archive.read("database/watchtracker.sqlite3"))
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT title, notes FROM music_albums").fetchone() == (
            "Synthetic Horizons",
            "Private music note",
        )
        assert connection.execute("SELECT count(*) FROM music_lists").fetchone()[0] == 1
        assert (
            connection.execute("SELECT title FROM book_records").fetchone()[0]
            == "Book backup sentinel"
        )
    preview = client.post(
        "/api/data/portable/inspect",
        files={"file": ("everything.zip", exported.content, "application/zip")},
    ).json()
    assert preview["music_albums"] == 1 and preview["books"] == 1
    create(client, title="After backup")
    restored = client.post(
        "/api/data/portable/import",
        files={"file": ("everything.zip", exported.content, "application/zip")},
        data={"archive_sha256": preview["sha256"]},
    )
    assert restored.status_code == 200, restored.text
    assert client.get("/api/music/albums").json()["total"] == 1
    assert client.get(f"/api/books/entries/{book['id']}").json()["artwork_data"]


def test_music_import_is_additive_and_rejects_invalid_files(client):
    source = create(client)
    document = client.get("/api/exports/music-collection.json").json()
    document["albums"].append(
        {**document["albums"][0], "id": str(uuid4()), "title": "New record", "notes": "new"}
    )
    document["albums"][0]["notes"] = "Must not overwrite"
    preview = client.post("/api/music/import/preview", json={"document": document}).json()
    assert preview["new_albums"] == 1
    result = client.post(
        "/api/music/import", json={"document": document, "sha256": preview["sha256"]}
    )
    assert result.status_code == 200
    assert client.get(f"/api/music/albums/{source['id']}").json()["notes"] == ""
    document["albums"][1]["title"] = "Tampered"
    assert (
        client.post(
            "/api/music/import", json={"document": document, "sha256": preview["sha256"]}
        ).status_code
        == 409
    )
    document["format"] = "unknown"
    assert (
        client.post("/api/music/import/preview", json={"document": document}).status_code == 422
    )
    assert client.get("/api/music/albums").json()["total"] == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"rating": 0},
        {"rating": 11},
        {"status": "watched"},
        {"title": " "},
        {"artwork_url": "javascript:alert(1)"},
        {"artwork_url": "https://covers.openlibrary.org.evil.invalid/a.jpg"},
        {"provider_id": "../../etc/passwd"},
        {"tracks": [{"position": 1, "title": "A"}, {"position": 1, "title": "B"}]},
    ],
)
def test_invalid_music_is_never_stored(client, changes):
    assert client.post("/api/music/albums", json=music_payload(**changes)).status_code == 422
    assert client.get("/api/music/albums").json()["total"] == 0


def test_artwork_sanitization(client):
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert (
        client.post(
            "/api/music/artwork", files={"file": ("cover.svg", bad, "image/svg+xml")}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/music/albums",
            json=music_payload(
                artwork_data="data:image/svg+xml;base64," + base64.b64encode(bad).decode()
            ),
        ).status_code
        == 422
    )


@pytest.mark.parametrize("domain", ["music", "books"])
def test_collection_notes_only_edits_preserve_textured_jpeg_bytes(client, domain):
    from watchtracker.books.schemas import BookInput

    # A textured JPEG exposes repeated lossy encoding; a solid-color fixture
    # can accidentally look byte-identical even with the original regression.
    image = Image.new("RGB", (96, 96))
    image.putdata(
        [
            ((x * 17 + y * 3) % 256, (x * 7 + y * 23) % 256, (x * 29 + y * 11) % 256)
            for y in range(96)
            for x in range(96)
        ]
    )
    exif = Image.Exif()
    exif[315] = "Private original artwork attribution"
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=93, exif=exif)
    incoming = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    schema = AlbumInput if domain == "music" else BookInput
    route = "/api/music/albums" if domain == "music" else "/api/books/entries"
    row_data = (
        music_payload(artwork_data=incoming, subgenres=["Ambient"])
        if domain == "music"
        else {
            "title": "Textured book cover",
            "author": "Author",
            "artwork_data": incoming,
            "page_count": 250,
            "current_page": 45,
            "genres": ["Fiction"],
            "subgenres": ["Mystery"],
        }
    )
    created = client.post(route, json=row_data)
    assert created.status_code == 201, created.text
    row = created.json()
    stored = row["artwork_data"]
    assert stored != incoming
    with Image.open(io.BytesIO(base64.b64decode(stored.split(",", 1)[1]))) as sanitized:
        assert not sanitized.getexif()
    original_fields = {key: row[key] for key in schema.model_fields if key != "notes"}
    for index in range(3):
        body = {key: row[key] for key in schema.model_fields}
        body.update(version=row["version"], notes=f"Updated note {index}")
        saved = client.put(f"{route}/{row['id']}", json=body)
        assert saved.status_code == 200, saved.text
        row = saved.json()
        assert row["artwork_data"] == stored
        assert {key: row[key] for key in original_fields} == original_fields
        assert client.get(row["cover_url"]).content == base64.b64decode(stored.split(",", 1)[1])
    export_path = (
        "/api/exports/music-collection.json"
        if domain == "music"
        else "/api/exports/book-collection.json"
    )
    document = client.get(export_path).json()
    exported = document["albums" if domain == "music" else "books"][0]
    assert exported["artwork_data"] == stored
    assert not any(key.startswith("_") for key in exported)
    # Changed image data still goes through the same sanitizer; unchanged-image
    # preservation is not a bypass for a malformed replacement or explicit clear.
    body = {key: row[key] for key in schema.model_fields}
    body.update(
        version=row["version"],
        artwork_data="data:image/svg+xml;base64,"
        + base64.b64encode(b"<svg><script>alert(1)</script></svg>").decode(),
    )
    assert client.put(f"{route}/{row['id']}", json=body).status_code == 422
    assert client.get(f"{route}/{row['id']}").json()["artwork_data"] == stored
    body.update(artwork_data=None, artwork_url=None)
    cleared = client.put(f"{route}/{row['id']}", json=body)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["artwork_data"] is None


def test_music_insights_do_not_invent_listening_history(client):
    create(client)
    create(client, title="Unrated album", rating=None, status="collected", favorite=True)
    data = client.get("/api/music/insights").json()
    assert data["total"] == 2
    assert data["artists"] == 1
    assert data["average_rating"] == 8.5
    assert data["unrated"] == 1
    assert "listening_time" not in data and "play_count" not in data
    assert client.get("/api/music/albums?sort=rating").json()["total"] == 1
    assert client.get("/api/music/albums?favorite=true").json()["total"] == 1
    assert client.get("/api/music/albums?status=listening").json()["total"] == 1


def test_music_ownership_is_enforced(app, client):
    owner_album = create(client)
    other = str(uuid4())
    with app.state.session_factory() as session:
        session.add(
            UserAccount(
                id=other,
                username="music-user",
                normalized_username="music-user",
                display_name="Music user",
                role="member",
                state="active",
            )
        )
        session.commit()
        bind_principal(session, Principal(other, "member", "system"))
        with pytest.raises(HTTPException) as error:
            get_album(session, owner_album["id"])
        assert error.value.status_code == 404
        with pytest.raises(HTTPException):
            validate_members(session, [owner_album["id"]])
        assert json.loads(export_music(session).body)["albums"] == []
        own = create_album(AlbumInput(**music_payload()), session)
        assert own["id"] != owner_album["id"]
        bind_principal(session, Principal(LOCAL_USER_ID, "admin", "system"))
        assert len(list(session.scalars(select(MusicAlbum)))) == 2


@pytest.mark.asyncio
async def test_musicbrainz_lookup_tracks_artwork_caching_and_fixed_hosts():
    release_id, group_id, recording_id = str(uuid4()), str(uuid4()), str(uuid4())
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "coverartarchive.org":
            return httpx.Response(404)
        assert request.url.host == "musicbrainz.org"
        assert "PersonalMediaTracker/" in request.headers["User-Agent"]
        if request.url.path == "/ws/2/release/":
            return httpx.Response(
                200,
                json={
                    "releases": [
                        {
                            "id": release_id,
                            "title": "Test album",
                            "artist-credit": [{"name": "Test artist"}],
                            "date": "2024-03",
                            "release-group": {"id": group_id},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": release_id,
                "title": "Test album",
                "artist-credit": [{"name": "Test artist"}],
                "date": "2024-03",
                "release-group": {"id": group_id, "primary-type": "Album"},
                "cover-art-archive": {"front": True},
                "genres": [{"name": "ambient"}],
                "media": [
                    {
                        "tracks": [
                            {
                                "title": "Test track",
                                "recording": {"id": recording_id},
                                "length": 65000,
                            }
                        ]
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = MusicBrainzProvider(http)
        result = await provider.search('Test "album"')
        assert len(result["results"]) == 1
        assert await provider.search('Test "album"') == result
        assert len(requests) == 1
        provider.next_request = 0
        from uuid import UUID

        album = await provider.detail(UUID(release_id))
        assert album["tracks"][0]["duration_ms"] == 65000
        assert album["tracks"][0]["recording_id"] == recording_id
        assert (
            album["artwork_url"]
            == f"https://coverartarchive.org/release/{release_id}/front-1200"
        )
        assert album["genres"] == ["ambient"]
        assert album["status"] == "plan_to_listen"


def test_music_subgenres_survive_legacy_updates_and_collection_exports(client):
    album = create(client, genres=["Electronic"], subgenres=["Ambient techno"])
    assert album["subgenres"] == ["Ambient techno"]
    body = {key: value for key, value in editable(album).items() if key != "subgenres"}
    body.update(version=album["version"], notes="Only this note changed")
    saved = client.put(f"/api/music/albums/{album['id']}", json=body).json()
    assert saved["subgenres"] == ["Ambient techno"]
    document = client.get("/api/exports/music-collection.json").json()
    assert document["albums"][0]["genres"] == ["Electronic"]
    assert document["albums"][0]["subgenres"] == ["Ambient techno"]
    document["albums"][0]["id"] = str(uuid4())
    document["albums"][0]["title"] = "Imported album"
    preview = client.post("/api/music/import/preview", json={"document": document}).json()
    assert (
        client.post(
            "/api/music/import", json={"document": document, "sha256": preview["sha256"]}
        ).status_code
        == 200
    )
    assert all(
        row["subgenres"] == ["Ambient techno"]
        for row in client.get("/api/music/albums").json()["items"]
    )


@pytest.mark.asyncio
async def test_musicbrainz_track_positions_keep_provider_order_and_valid_disc_numbers():
    def handle(request):
        return httpx.Response(
            200,
            json={
                "title": "Several discs",
                "artist-credit": [{"name": "Artist"}],
                "media": [
                    {
                        "position": 1,
                        "tracks": [
                            {"position": 2, "title": "Second"},
                            {"position": 1, "title": "First"},
                        ],
                    },
                    {
                        "position": 2,
                        "tracks": [
                            {"position": 1, "title": "Disc two opening"},
                            {"position": 1, "title": "Provider duplicate repaired"},
                        ],
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await MusicBrainzProvider(http).detail(uuid4())
    assert [(row["disc"], row["position"]) for row in result["tracks"]] == [
        (1, 2),
        (1, 1),
        (2, 1),
        (2, 2),
    ]
    assert result["subgenres"] == []


@pytest.mark.asyncio
async def test_musicbrainz_typeahead_uses_one_safe_partial_term_fallback():
    identifier = str(uuid4())
    queries = []

    def handle(request):
        query = request.url.params["query"]
        queries.append(query)
        if len(queries) == 1:
            return httpx.Response(200, json={"releases": []})
        return httpx.Response(
            200,
            json={
                "releases": [
                    {
                        "id": identifier,
                        "title": "Kind of Blue",
                        "artist-credit": [{"name": "Miles Davis"}],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await MusicBrainzProvider(http).search("Kind of Blu", "Miles Davis")
    assert result["results"][0]["provider_id"] == identifier
    assert result["search_strategy"] == "broader_terms"
    assert queries == [
        'release:"Kind of Blu" AND artist:"Miles Davis"',
        'release:("kind" AND "of" AND blu*) AND artist:"Miles Davis"',
    ]


@pytest.mark.asyncio
async def test_musicbrainz_search_failure_does_not_fan_out_to_other_services():
    from watchtracker.metadata.http import ProviderError

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(503, headers={"Retry-After": "60"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(ProviderError):
            await MusicBrainzProvider(http).search("Unavailable album")
    assert len(requests) == 1
    assert requests[0].url.host == "musicbrainz.org"


@pytest.mark.asyncio
async def test_music_artwork_options_redirect_validation_deduplication_and_cache():
    release_id, group_id, alternate_id = uuid4(), uuid4(), uuid4()
    requests = []
    front = {
        "id": "100",
        "image": f"http://coverartarchive.org/release/{release_id}/100.jpg",
        "front": True,
        "approved": True,
        "types": ["Front"],
    }

    def handle(request):
        requests.append(request)
        if request.url.host == "musicbrainz.org":
            assert request.url.params["release-group"] == str(group_id)
            return httpx.Response(
                200,
                json={
                    "releases": [
                        {
                            "id": str(alternate_id),
                            "date": "2001",
                            "country": "GB",
                            "cover-art-archive": {"front": True},
                        }
                    ]
                },
            )
        if request.url.host == "archive.org":
            return httpx.Response(
                200,
                json={
                    "images": [front, {"id": "101", "image": "https://evil.invalid/steal.jpg"}]
                },
            )
        if request.url.path == f"/release/{release_id}/":
            return httpx.Response(
                307,
                headers={
                    "Location": f"https://archive.org/download/mbid-{release_id}/index.json"
                },
            )
        assert request.url.path == f"/release-group/{group_id}/"
        return httpx.Response(
            200,
            json={
                "images": [
                    front,
                    {
                        "id": "102",
                        "image": f"https://coverartarchive.org/release/{release_id}/102.jpg",
                        "types": ["Back"],
                        "approved": True,
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = MusicBrainzProvider(http)
        result = await provider.artwork_options(release_id, group_id)
        assert len(result["options"]) == 3
        assert result["warning"] is None
        assert (
            result["options"][0]["url"]
            == f"https://coverartarchive.org/release/{release_id}/100-1200.jpg"
        )
        assert result["options"][2]["label"] == "Back"
        assert (
            result["options"][1]["url"]
            == f"https://coverartarchive.org/release/{alternate_id}/front-1200"
        )
        assert all("evil.invalid" not in option["url"] for option in result["options"])
        count = len(requests)
        assert await provider.artwork_options(release_id, group_id) == result
        assert len(requests) == count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "redirect",
    [
        "https://example.com/image",
        "http://archive.org/index.json",
        "https://archive.org.evil.invalid/index.json",
        "https://127.0.0.1/private",
        "file:///etc/passwd",
    ],
)
async def test_music_artwork_redirects_cannot_access_unapproved_hosts(redirect):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": redirect})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await MusicBrainzProvider(http).artwork_options(uuid4())
    assert result["options"] == [] and result["warning"]
    assert len(requests) == 1


def test_music_artwork_options_are_read_only_and_guard_missing_records(
    client, app, monkeypatch
):
    album = create(
        client,
        provider_id=str(uuid4()),
        release_group_id=str(uuid4()),
        notes="Keep",
        subgenres=["Downtempo"],
    )
    album = client.get(f"/api/music/albums/{album['id']}").json()
    calls = []

    async def options(identifier, group):
        calls.append((identifier, group))
        return {
            "options": [
                {
                    "url": "https://coverartarchive.org/release/cover.jpg",
                    "thumbnail_url": "https://coverartarchive.org/release/thumb.jpg",
                    "label": "Front",
                    "source": "Cover Art Archive",
                }
            ],
            "source": "Cover Art Archive",
            "warning": None,
        }

    monkeypatch.setattr(app.state.music_provider, "artwork_options", options)
    response = client.get(f"/api/music/albums/{album['id']}/artwork-options")
    assert response.status_code == 200
    assert calls == [(UUID(album["provider_id"]), UUID(album["release_group_id"]))]
    assert client.get(f"/api/music/albums/{album['id']}").json() == album
    assert client.get(f"/api/music/albums/{uuid4()}/artwork-options").status_code == 404
    assert len(calls) == 1
    manual = create(client, title="Manual artwork")
    response = client.get(f"/api/music/albums/{manual['id']}/artwork-options")
    assert response.json()["options"] == []
    assert len(calls) == 1
