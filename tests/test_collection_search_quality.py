"""Bounded relevance and work/version identity, without auto-linking a library."""

from uuid import uuid4

import httpx
import pytest

from watchtracker.books.provider import OpenLibraryProvider
from watchtracker.music.provider import MusicBrainzProvider


@pytest.mark.asyncio
async def test_books_rank_original_work_above_notes_and_group_editions():
    def work(number, title, author, year, edition_title=None):
        return {
            "key": f"/works/OL{number}W",
            "title": title,
            "author_name": [author],
            "first_publish_year": year,
            "editions": {
                "docs": [
                    {
                        "key": f"/books/OL{number}M",
                        "title": edition_title or title,
                        "publish_date": [str(year)],
                        "publisher": ["Publisher"],
                    }
                ]
            },
        }

    original = work(
        1, "Преступление и наказание", "Fyodor Dostoevsky", 1866, "Crime and Punishment"
    )
    rows = [
        work(2, "Crime and Punishment notes", "Cliff", 1963),
        work(3, "Crime and Punishment in England", "Other", 1990),
        original,
        original,
    ]
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"docs": rows})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = OpenLibraryProvider(http)
        results = (await provider.search("Crime and punishment"))["results"]
        assert [row["work_id"] for row in results] == ["OL1W", "OL3W", "OL2W"]
        assert "['" not in results[0]["edition"]
        assert len(calls) == 1 and int(calls[0].url.params["limit"]) <= 100


@pytest.mark.asyncio
async def test_edition_scope_language_completeness_and_preferred_membership():
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/books/OL999M.json":
            return httpx.Response(
                200,
                json={
                    "key": "/books/OL999M",
                    "title": "Wrong book",
                    "works": [{"key": "/works/OL2W"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "entries": [
                    {
                        "key": "/books/OL3M",
                        "title": "Crime et châtiment",
                        "number_of_pages": 400,
                        "publish_date": "2003",
                        "languages": [{"key": "/languages/fre"}],
                    },
                    {
                        "key": "/books/OL1M",
                        "title": "Crime and Punishment",
                        "publish_date": "2000",
                        "languages": [{"key": "/languages/eng"}],
                    },
                    {
                        "key": "/books/OL2M",
                        "title": "Crime and Punishment",
                        "number_of_pages": 500,
                        "publish_date": "2001",
                        "languages": [{"key": "/languages/eng"}],
                        "publishers": ["Test Press"],
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = OpenLibraryProvider(http)
        result = await provider.editions("OL1W", "Crime and Punishment", "en", "OL999M")
        assert [row["provider_id"] for row in result["results"]] == ["OL2M", "OL1M", "OL3M"]
        assert all(row["work_id"] == "OL1W" for row in result["results"])
        assert result["results"][0]["edition"] == "Test Press"
        assert calls == ["/works/OL1W/editions.json", "/books/OL999M.json"]
        with pytest.raises(ValueError):
            await provider.editions("../unexpected")


@pytest.mark.asyncio
async def test_music_collapses_country_format_duplicates_but_preserves_deluxe_and_artist():
    original_group, cover_group = str(uuid4()), str(uuid4())

    def release(group, name, date, form, extra="", status="Official"):
        return {
            "id": str(uuid4()),
            "title": "Siamese Dream",
            "artist-credit": [{"name": name}],
            "release-group": {"id": group},
            "date": date,
            "status": status,
            "country": "US",
            "disambiguation": extra,
            "media": [{"format": form, "track-count": 31 if extra else 13}],
        }

    original = release(original_group, "The Smashing Pumpkins", "1993-07-27", "CD")
    deluxe = release(original_group, "The Smashing Pumpkins", "2011", "CD", "deluxe edition")
    rows = [
        release(str(uuid4()), "Another artist", "1980", "CD"),
        release(cover_group, "Fruit Bats", "2020", "Vinyl"),
        release(cover_group, "Fruit Bats", "2021", "Digital Media"),
        release(original_group, "Smashing Pumpkins", "1993-07-27", "Cassette"),
        original,
        release(original_group, "Smashing Pumpkins", "1994", "CD"),
        deluxe,
        release(
            original_group,
            "Smashing Pumpkins",
            "2011",
            "Digital Media",
            "deluxe edition, hi-res download",
        ),
        release(original_group, "Smashing Pumpkins", "1990", "CD", status="Bootleg"),
    ]
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"releases": rows})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        provider = MusicBrainzProvider(http)
        result = (await provider.search("Siamese Dream"))["results"]
        assert len(result) == 4
        assert result[0]["provider_id"] == original["id"]
        assert result[1]["provider_id"] == deluxe["id"]
        assert result[2]["artist"] == "Fruit Bats"
        assert len(calls) == 1 and int(calls[0].url.params["limit"]) == 100
        # Explicit creator beats an older same-name album by someone else.
        result = (await provider.search("Siamese Dream", "Fruit Bats"))["results"]
        assert result[0]["artist"] == "Fruit Bats"


def test_work_endpoint_validates_identifiers(client):
    assert client.get("/api/books/works/not-a-work/editions").status_code == 422
    assert client.get("/api/books/works/OL1W/editions?preferred=OL2W").status_code == 422
