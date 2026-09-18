"""Edition identity, honest missing metadata and portable manual tracking."""

from uuid import uuid4

import httpx
import pytest

from watchtracker.books.provider import OpenLibraryProvider, edition_pages, edition_year
from watchtracker.books.schemas import BookInput
from watchtracker.music.provider import MusicBrainzProvider, image_options
from watchtracker.music.schemas import AlbumInput


@pytest.mark.parametrize(
    "domain,schema,endpoint,creator",
    [("books", BookInput, "entries", "author"), ("music", AlbumInput, "albums", "artist")],
)
def test_edition_counts_and_overrides_roundtrip_and_survive_old_clients(
    client, domain, schema, endpoint, creator
):
    extra = {
        "edition_info": {
            "name": "Fixture edition",
            "date": "2020-03",
            "format": "Paperback" if domain == "books" else "CD",
        },
        "completion_count": 3,
        "genre_additions": ["Personal genre"],
        "genre_removals": ["Fiction"],
        "subgenre_additions": ["Personal subgenre"],
        "subgenre_removals": ["Legacy"],
    }
    response = client.post(
        f"/api/{domain}/{endpoint}",
        json={"title": "Edition fixture", creator: "Creator", **extra},
    )
    assert response.status_code == 201, response.text
    row = response.json()
    # A pre-0026 client doesn't know these fields, and must not clear them.
    body = {key: row[key] for key in schema.model_fields if key not in extra}
    body.update(version=row["version"], notes="Edited by older client")
    response = client.put(f"/api/{domain}/{endpoint}/{row['id']}", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    for key in extra:
        assert saved[key] == row[key]
    export = client.get(
        f"/api/exports/{'book' if domain == 'books' else 'music'}-collection.json"
    ).json()
    exported = next(
        item
        for item in export["books" if domain == "books" else "albums"]
        if item["id"] == row["id"]
    )
    for key in extra:
        assert exported[key] == row[key]


@pytest.mark.parametrize(
    "value,expected", [("c2013", 2013), ("June 1, 2009", 2009), ("unknown", None)]
)
def test_edition_year_parsing(value, expected):
    assert edition_year(value) == expected


def test_pagination_is_edition_specific_and_never_guessed():
    assert edition_pages({"pagination": "xii, 368 p."}) == (368, "Selected edition pagination")
    assert edition_pages({"pagination": "unpaged", "work_pages": 320}) == (None, "")
    assert edition_pages({"number_of_pages": -4}) == (None, "")


@pytest.mark.asyncio
async def test_book_work_artwork_does_not_borrow_edition_pages_and_editions_are_explicit():
    requests = []

    def handle(request):
        requests.append(request)
        data = {
            "/books/OL1M.json": {
                "title": "Book",
                "covers": [10],
                "physical_format": "Paperback",
                "works": [{"key": "/works/OL1W"}],
            },
            "/works/OL1W.json": {
                "title": "Book",
                "covers": [20],
                "first_publish_date": "2013",
                "number_of_pages": 999,
            },
            "/works/OL1W/editions.json": {
                "entries": [
                    {"key": "/books/OL1M", "title": "Book", "covers": [10]},
                    {
                        "key": "/books/OL2M",
                        "title": "Book",
                        "number_of_pages": 320,
                        "publish_date": "2014",
                        "covers": [30],
                        "publishers": ["Fixture publisher"],
                    },
                ]
            },
        }
        return httpx.Response(200, json=data[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = OpenLibraryProvider(http)
        row = await provider.detail("OL1M")
        assert row["year"] is None and row["page_count"] is None
        assert row["provider_id"] == "OL1M" and row["book_format"] == "paperback"
        assert row["edition_info"]["original_year"] == 2013
        assert row["edition_info"]["artwork_scope"] == "Work cover"
        assert row["artwork_url"].endswith("20-L.jpg?default=false")
        result = await provider.editions("OL1M")
        assert result["results"][0]["provider_id"] == "OL2M"
        assert result["results"][0]["page_count"] == 320
        assert len(requests) == 3  # one work, one edition, one bounded alternatives lookup


@pytest.mark.asyncio
async def test_short_book_search_is_literal_and_language_aware():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "title": "It",
                        "first_publish_year": 1986,
                        "editions": {
                            "docs": [
                                {
                                    "key": "/books/OL3M",
                                    "title": "It",
                                    "publish_date": "2017",
                                    "publisher": "Press",
                                    "language": ["eng"],
                                }
                            ]
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        rows = await OpenLibraryProvider(http).search("It", language="fr")
    assert seen[0].url.params["q"] == '"It"'
    assert seen[0].url.params["lang"] == "fr"
    assert "title" not in seen[0].url.params
    assert rows["results"][0]["year"] == 2017
    assert "Press" in rows["results"][0]["edition"]


def test_music_front_artwork_prefers_clean_approved_fronts():
    release = str(uuid4())

    def item(number, **values):
        return {
            "image": f"https://coverartarchive.org/release/{release}/{number}.jpg",
            "id": number,
            "front": True,
            "types": ["Front"],
            "approved": True,
            **values,
        }

    options = image_options(
        {
            "images": [
                item(1, comment="jewel case with sticker"),
                item(2, approved=False),
                item(3),
                item(4, front=False, types=["Back"]),
            ]
        }
    )
    assert len(options) == 3
    assert options[0]["url"].endswith("/3-1200.jpg")
    assert options[1]["packaging"] is True


@pytest.mark.asyncio
async def test_album_edition_details_tolerate_absent_label_and_language_records():
    identifier = uuid4()

    def handle(request):
        if request.url.host == "coverartarchive.org":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "title": "Nullable edition",
                "label-info": [{"label": None, "catalog-number": "TEST-001"}, None],
                "text-representation": None,
                "media": [],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        row = await MusicBrainzProvider(http).detail(identifier)
    assert row["title"] == "Nullable edition"
    assert row["edition_info"]["labels"] == []
    assert row["edition_info"]["language"] == ""
    assert row["edition_info"]["catalog_numbers"] == ["TEST-001"]


@pytest.mark.parametrize(
    "domain,endpoint,creator,statuses",
    [
        ("books", "entries", "author", ["reading", "plan_to_read", "read"]),
        ("music", "albums", "artist", ["listening", "plan_to_listen", "listened"]),
    ],
)
def test_active_collection_scope_includes_planned_but_not_finished(
    client, domain, endpoint, creator, statuses
):
    for status in statuses:
        assert (
            client.post(
                f"/api/{domain}/{endpoint}",
                json={"title": status, creator: "Creator", "status": status},
            ).status_code
            == 201
        )
    rows = client.get(f"/api/{domain}/{endpoint}?status=active").json()["items"]
    assert {row["status"] for row in rows} == set(statuses[:2])
    assert all(row["completion_count"] is None for row in rows)
