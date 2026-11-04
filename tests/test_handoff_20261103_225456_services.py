"""Edition completeness and representative artwork without invented facts."""

from uuid import UUID, uuid4

import pytest

from watchtracker.books.provider import OpenLibraryProvider, edition_pages
from watchtracker.metadata.http import ProviderError
from watchtracker.music.provider import MusicBrainzProvider, image_options


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"number_of_pages": "281"}, 281),
        ({"pagination": "xiv, 281"}, 281),
        ({"pagination": "[281 pages]"}, 281),
        ({"pagination": "(281 p.)"}, 281),
        ({"number_of_pages": True}, None),
        ({"number_of_pages": "unknown", "pagination": "3 volumes"}, None),
        ({"pagination": "audio, 9 hours"}, None),
        ({"number_of_pages": "200001"}, None),
    ],
)
def test_pages_only_come_from_a_real_edition_count(record, expected):
    assert edition_pages(record)[0] == expected


@pytest.mark.asyncio
async def test_automatic_book_matching_selects_complete_same_title_language_and_format(
    monkeypatch,
):
    provider = OpenLibraryProvider()
    candidate = {
        "provider_id": "OL1M",
        "work_id": "OL1W",
        "title": "The Ocean",
        "author": "Original Author",
    }
    good = {
        "provider_id": "OL5M",
        "title": "The Ocean",
        "page_count": 281,
        "year": 2013,
        "language": "eng",
        "edition": "Paperback",
        "isbn": "9780062255655",
    }
    rows = [
        {**good, "provider_id": "OL2M", "language": "fre"},
        {**good, "provider_id": "OL3M", "edition": "Large print paperback"},
        {**good, "provider_id": "OL4M", "title": "The Ocean Study Guide"},
        good,
    ]

    async def editions(*args, **kwargs):
        return {"results": rows}

    monkeypatch.setattr(provider, "editions", editions)
    try:
        result = await provider.preferred_edition(
            candidate, {"title": "Ocean", "book_format": "paperback"}
        )
        assert result["provider_id"] == "OL5M" and result["page_count"] == 281
        assert result["isbn"] == good["isbn"]
        # Explicit identifiers, years and formats cannot be silently replaced.
        for source in (
            {"provider_id": "OL1M"},
            {"isbn": "9780062255655"},
            {"year": 2020},
            {"book_format": "hardcover"},
        ):
            assert (
                await provider.preferred_edition(candidate, {"title": "Ocean", **source})
                == candidate
            )
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_edition_lookup_failure_keeps_original_candidate(monkeypatch):
    provider = OpenLibraryProvider()
    candidate = {"provider_id": "OL1M", "work_id": "OL1W"}

    async def unavailable(*args, **kwargs):
        raise ProviderError("unavailable", "Open Library is unavailable")

    monkeypatch.setattr(provider, "editions", unavailable)
    try:
        assert await provider.preferred_edition(candidate, {"title": "Ocean"}) == candidate
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_default_album_match_chooses_standard_release_over_test_pressing(monkeypatch):
    provider = MusicBrainzProvider()
    group_id, pressing, regular = str(uuid4()), str(uuid4()), str(uuid4())

    async def editions(*args, **kwargs):
        return {
            "releases": [
                {
                    "id": pressing,
                    "title": "Promises",
                    "status": "Official",
                    "date": "2020-11-24",
                    "disambiguation": "test pressing",
                    "cover-art-archive": {"front": True},
                    "media": [{"track-count": 2}],
                },
                {
                    "id": regular,
                    "title": "Promises",
                    "status": "Official",
                    "date": "2021-03-26",
                    "media": [{"track-count": 9}],
                },
            ]
        }

    monkeypatch.setattr(provider, "_get", editions)
    try:
        result = await provider._edition_for_group({"title": "Promises"}, {"id": group_id})
        assert result == {"provider_id": regular, "release_group_id": group_id}
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_unavailable_cover_catalog_keeps_group_cover_endpoint(monkeypatch):
    provider = MusicBrainzProvider()
    release_id, group_id = str(uuid4()), str(uuid4())

    async def metadata(*args, **kwargs):
        return {
            "id": release_id,
            "title": "Promises",
            "date": "2020-11-24",
            "disambiguation": "test pressing",
            "artist-credit": [{"name": "Floating Points"}],
            "release-group": {"id": group_id, "title": "Promises", "primary-type": "Album"},
            "cover-art-archive": {"front": True},
            "media": [],
        }

    async def unavailable(*args, **kwargs):
        raise ProviderError("unavailable", "Cover Art Archive is unavailable")

    monkeypatch.setattr(provider, "_get", metadata)
    monkeypatch.setattr(provider.artwork_client, "_artwork_get", unavailable)
    try:
        result = await provider.detail(UUID(release_id))
        assert result["provider_id"] == release_id  # an explicit edition stays intact
        assert f"release-group/{group_id}/front" in result["artwork_url"]
        assert result["edition_info"]["artwork_scope"] == "Release group"
    finally:
        await provider.close()


def test_test_pressing_sleeves_are_secondary_artwork():
    release_id = str(uuid4())
    options = image_options(
        {
            "images": [
                {
                    "id": str(i),
                    "image": f"https://coverartarchive.org/release/{release_id}/{i}.jpg",
                    "approved": True,
                    "front": True,
                    "types": ["Front"],
                    "comment": label,
                }
                for i, label in [(1, "Test pressing white label"), (2, "Front cover")]
            ]
        }
    )
    assert options[0]["url"].endswith("/2-1200.jpg")
    assert options[1]["packaging"] is True
