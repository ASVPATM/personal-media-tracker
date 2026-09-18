from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from watchtracker.authorization import Principal, bind_principal
from watchtracker.books.api import export_books, get_book
from watchtracker.books.provider import OpenLibraryProvider
from watchtracker.books.schemas import BookInput
from watchtracker.models import UserAccount


def payload(**changes):
    return {
        "title": "A Synthetic Book",
        "author": "Fixture Author",
        "year": 2024,
        "page_count": 240,
        "current_page": 50,
        "status": "reading",
        "rating": 8,
        "chapters": ["First", "Second"],
        **changes,
    }


def create(client, **changes):
    response = client.post("/api/books/entries", json=payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_new_books_default_to_plan_and_legacy_status_is_not_silently_changed(client):
    response = client.post("/api/books/entries", json={"title": "New book", "author": "Author"})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "plan_to_read"
    legacy = create(client, title="Legacy book", status="collected", notes="Original note")
    body = {key: legacy[key] for key in BookInput.model_fields if key != "status"}
    body.update(version=legacy["version"], notes="Only this note changed")
    response = client.put(f"/api/books/entries/{legacy['id']}", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == "collected"
    assert saved["current_page"] == legacy["current_page"]
    assert saved["chapters"] == legacy["chapters"]
    exported = client.get("/api/exports/book-collection.json").json()["books"]
    assert next(row for row in exported if row["id"] == legacy["id"])["status"] == "collected"
    body.update(version=saved["version"], status="reading")
    assert (
        client.put(f"/api/books/entries/{legacy['id']}", json=body).json()["status"]
        == "reading"
    )


@pytest.mark.parametrize("include_status", [False, True])
def test_legacy_book_imports_do_not_invent_reading_intent(client, include_status):
    source = {
        "id": str(uuid4()),
        "title": "Legacy imported book",
        "author": "Author",
        "notes": "Original notes",
        "rating": 8,
        "page_count": 240,
        "current_page": 70,
        "chapters": ["Original chapter"],
        "genres": ["A long provider subject that must remain unchanged"],
        "subgenres": ["User choice"],
    }
    if include_status:
        source["status"] = "collected"
    document = {"format": "pmt-book-collection", "version": 1, "books": [source]}
    preview = client.post("/api/books/import/preview", json={"document": document})
    assert preview.status_code == 200, preview.text
    response = client.post(
        "/api/books/import", json={"document": document, "sha256": preview.json()["sha256"]}
    )
    assert response.status_code == 200, response.text
    row = client.get("/api/books/entries").json()["items"][0]
    assert row["status"] == "collected"
    detail = client.get(f"/api/books/entries/{row['id']}").json()
    for key in (
        "notes",
        "rating",
        "current_page",
        "page_count",
        "chapters",
        "genres",
        "subgenres",
    ):
        assert detail[key] == source[key]


def test_books_are_persistent_isolated_and_conflict_safe(client):
    row = create(client)
    assert client.get("/api/music/albums").json()["total"] == 0
    assert client.get("/api/entries").json()["total"] == 0
    assert client.post("/api/books/entries", json=payload()).status_code == 409
    edit = {key: row[key] for key in BookInput.model_fields}
    edit.update(version=row["version"], notes="Private book note", current_page=100)
    updated = client.put(f"/api/books/entries/{row['id']}", json=edit)
    assert updated.status_code == 200
    assert client.put(f"/api/books/entries/{row['id']}", json=edit).status_code == 409
    assert updated.json()["current_page"] == 100
    music = client.post(
        "/api/music/albums", json={"title": "Not a book", "artist": "Fixture"}
    ).json()
    assert (
        client.post(
            "/api/books/lists", json={"name": "Wrong domain", "book_ids": [music["id"]]}
        ).status_code
        == 422
    )
    book_list = client.post(
        "/api/books/lists", json={"name": "Reading list", "book_ids": [row["id"]]}
    ).json()
    assert client.get(f"/api/books/entries?list_id={book_list['id']}").json()["total"] == 1
    insights = client.get("/api/books/insights").json()
    assert insights["statuses"] == {"reading": 1}
    assert insights["authors"] == 1
    assert client.delete(f"/api/books/entries/{row['id']}?version=1").status_code == 409
    assert client.delete(f"/api/books/entries/{row['id']}?version=2").status_code == 204
    assert client.get("/api/books/lists").json()["items"][0]["book_ids"] == []
    assert client.get("/api/music/albums").json()["total"] == 1
    assert create(client)["id"] != row["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"current_page": 241},
        {"isbn": "123"},
        {"isbn": "9780140328720"},
        {"page_count": 0},
        {"status": "listening"},
        {"provider_id": "../private"},
        {"rating": 10.1},
        {"author": " "},
    ],
)
def test_invalid_books_are_not_saved(client, changes):
    assert client.post("/api/books/entries", json=payload(**changes)).status_code == 422
    assert client.get("/api/books/entries").json()["total"] == 0


def test_book_export_and_additive_import(client):
    row = create(client, isbn="978-0-14-032872-1")
    assert row["isbn"] == "9780140328721"
    client.post("/api/books/lists", json={"name": "Shelf", "book_ids": [row["id"]]})
    document = client.get("/api/exports/book-collection.json").json()
    assert document["books"][0]["chapters"] == ["First", "Second"]
    assert "A Synthetic Book" not in client.get("/api/exports/watch-log.csv").text
    assert client.get("/api/exports/music-collection.json").json()["albums"] == []
    document["books"].append(
        {**document["books"][0], "id": str(uuid4()), "isbn": None, "title": "Second book"}
    )
    document["books"][0]["rating"] = 1
    preview = client.post("/api/books/import/preview", json={"document": document}).json()
    assert preview["new_books"] == 1
    assert client.post("/api/books/import", json={"document": document}).status_code == 409
    result = client.post(
        "/api/books/import", json={"document": document, "sha256": preview["sha256"]}
    )
    assert result.status_code == 200, result.text
    assert client.get(f"/api/books/entries/{row['id']}").json()["rating"] == 8
    assert len(client.get("/api/books/lists").json()["items"]) == 1
    assert client.get("/api/books/entries").json()["total"] == 2
    assert (
        client.post("/api/music/import/preview", json={"document": document}).status_code == 422
    )


def test_book_owner_boundary(app, client):
    book = create(client)
    with app.state.session_factory() as session:
        other = str(uuid4())
        session.add(
            UserAccount(
                id=other,
                username="book-user",
                normalized_username="book-user",
                display_name="Book user",
                role="member",
                state="active",
            )
        )
        session.commit()
        bind_principal(session, Principal(other, "member", "system"))
        with pytest.raises(HTTPException):
            get_book(session, book["id"])
        assert json.loads(export_books(session).body)["books"] == []


@pytest.mark.asyncio
async def test_openlibrary_edition_covers_and_metadata():
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "openlibrary.org"
        data = {
            "/search.json": {
                "docs": [
                    {
                        "title": "Book",
                        "author_name": ["Author"],
                        "edition_key": ["OL999M"],
                        "editions": {
                            "docs": [{"key": "/books/OL123M", "title": "Book", "cover_i": 42}]
                        },
                        "first_publish_year": 2001,
                        "cover_i": 42,
                    }
                ]
            },
            "/books/OL123M.json": {
                "title": "Book",
                "authors": [{"key": "/authors/OL1A"}],
                "works": [{"key": "/works/OL1W"}],
                "number_of_pages": 300,
                "publish_date": "May 2002",
                "covers": [42],
                "isbn_13": ["9780140328721"],
                "table_of_contents": [{"title": "Chapter One"}],
            },
            "/works/OL1W.json": {
                "subjects": ["Fiction"],
                "description": {"value": "A description"},
            },
            "/authors/OL1A.json": {"name": "Author"},
        }
        return httpx.Response(200, json=data[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = OpenLibraryProvider(http)
        search = await provider.search("Book")
        assert search["results"][0]["provider_id"] == "OL123M"
        assert requests[0].url.params["lang"] == "en"
        provider.next_request = 0
        result = await provider.detail("OL123M")
        assert result["year"] == 2002
        assert result["page_count"] == 300
        assert result["chapters"] == ["Chapter One"]
        assert result["current_page"] is None
        assert (
            result["artwork_url"]
            == "https://covers.openlibrary.org/b/id/42-L.jpg?default=false"
        )
        assert result["author"] == "Author"
        assert result["status"] == "plan_to_read"
        with pytest.raises(ValueError):
            await provider.detail("../../private")


def test_book_subgenres_preserved_on_legacy_update_and_export(client):
    book = create(client, genres=["Fiction"], subgenres=["Historical fiction"])
    body = {key: book[key] for key in BookInput.model_fields if key != "subgenres"}
    body.update(version=book["version"], notes="New note")
    saved = client.put(f"/api/books/entries/{book['id']}", json=body).json()
    assert saved["subgenres"] == ["Historical fiction"]
    document = client.get("/api/exports/book-collection.json").json()
    assert document["books"][0]["subgenres"] == ["Historical fiction"]
    document["books"][0]["title"] = "Imported book"
    document["books"][0]["id"] = str(uuid4())
    preview = client.post("/api/books/import/preview", json={"document": document}).json()
    assert (
        client.post(
            "/api/books/import", json={"document": document, "sha256": preview["sha256"]}
        ).status_code
        == 200
    )
    assert all(
        row["subgenres"] == ["Historical fiction"]
        for row in client.get("/api/books/entries").json()["items"]
    )


@pytest.mark.asyncio
async def test_book_alternate_artwork_uses_related_editions_deduplicates_and_caches():
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "openlibrary.org"
        data = {
            "/books/OL1M.json": {"covers": [100, -1, 101], "works": [{"key": "/works/OL1W"}]},
            "/works/OL1W.json": {"covers": [101, 102]},
            "/works/OL1W/editions.json": {
                "entries": [
                    {
                        "covers": [102, 103],
                        "publish_date": "2005",
                        "publishers": ["Test Press"],
                    },
                    {"covers": [104, 0, "evil.invalid"]},
                ]
            },
        }
        return httpx.Response(200, json=data[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = OpenLibraryProvider(http)
        result = await provider.artwork_options("OL1M")
        assert len(result["options"]) == 5
        assert result["warning"] is None
        assert result["options"][3]["label"] == "2005 · Test Press"
        assert all(
            option["url"].startswith("https://covers.openlibrary.org/b/id/")
            for option in result["options"]
        )
        assert await provider.artwork_options("OL1M") == result
        assert len(requests) == 3
        with pytest.raises(ValueError):
            await provider.artwork_options("../private")


@pytest.mark.asyncio
async def test_book_subjects_survive_optional_work_lookup_failure():
    def handle(request):
        if request.url.path == "/books/OL1M.json":
            return httpx.Response(
                200,
                json={
                    "title": "Book",
                    "subjects": ["History", " History ", " "],
                    "works": [{"key": "/works/OL1W"}],
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await OpenLibraryProvider(http).detail("OL1M")
    assert result["genres"] == ["History"]
    assert result["subgenres"] == []


def test_book_artwork_options_never_change_metadata_and_guard_unlinked_books(
    client, app, monkeypatch
):
    book = create(
        client,
        provider_id="OL1M",
        work_id="OL1W",
        genres=["Fiction"],
        subgenres=["Mystery"],
        notes="Keep",
    )
    book = client.get(f"/api/books/entries/{book['id']}").json()
    calls = []

    async def options(identifier, work):
        calls.append((identifier, work))
        return {
            "options": [
                {
                    "url": "https://covers.openlibrary.org/b/id/123-L.jpg",
                    "thumbnail_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
                    "label": "Alternate",
                    "source": "Open Library",
                }
            ],
            "source": "Open Library",
            "warning": None,
        }

    monkeypatch.setattr(app.state.book_provider, "artwork_options", options)
    response = client.get(f"/api/books/entries/{book['id']}/artwork-options")
    assert response.status_code == 200
    assert calls == [("OL1M", "OL1W")]
    assert client.get(f"/api/books/entries/{book['id']}").json() == book
    assert client.get(f"/api/books/entries/{uuid4()}/artwork-options").status_code == 404
    manual = create(client, title="Unlinked book")
    assert (
        client.get(f"/api/books/entries/{manual['id']}/artwork-options").json()["options"] == []
    )
    assert len(calls) == 1
