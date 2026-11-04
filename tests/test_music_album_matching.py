"""No live requests: matching must recover real variations without guessing identity."""

import asyncio
import time
from uuid import uuid4

import httpx
import pytest

from watchtracker.music.matching import album_key, choose_group
from watchtracker.music.provider import MusicBrainzProvider


def group(title="Honeymoon", artist="Lana Del Rey", kind="Album", **extra):
    return {
        "id": str(uuid4()),
        "title": title,
        "primary-type": kind,
        "artist-credit": [{"artist": {"id": str(uuid4()), "name": artist}}],
        **extra,
    }


@pytest.mark.parametrize(
    "title,artist,canonical,credit",
    [
        ("Honeymoon", "Lana Del Ray", "Honeymoon", "Lana Del Rey"),
        ("10 000 Hertz Legend", "Air", "10,000 Hz Legend", "Air"),
        (
            "Blade Runner Music From The Original Soundtrack",
            "Vangelis",
            "Blade Runner",
            "Vangelis",
        ),
        ("E·MO·TION", "Carly Rae Jepson", "Emotion", "Carly Rae Jepsen"),
        ("Ju Ju", "Siousxie and the Banshees", "Juju", "Siouxsie and the Banshees"),
        ("Soon Forward", "Gregrory Isaacs", "Soon Forward", "Gregory Isaacs"),
        ("III Communication", "Beastie Boys", "Ill Communication", "Beastie Boys"),
        ("Eco Pack - 浮躁", "王菲", "浮躁", "王菲"),
        (
            "In the Court of the Crimson King",
            "Crimson King",
            "In the Court of the Crimson King",
            "King Crimson",
        ),
    ],
)
def test_safe_normalizations_and_single_artist_typo(title, artist, canonical, credit):
    expected = group(canonical, credit)
    assert choose_group({"title": title, "artist": artist}, [expected]) == expected


def test_collaboration_alias_and_album_not_single():
    album = group("Together", "Canonical Artist")
    album["artist-credit"][0]["artist"]["aliases"] = [{"name": "Имя артиста"}]
    album["artist-credit"].append({"artist": {"name": "Collaborator"}})
    single = {**album, "id": str(uuid4()), "primary-type": "Single"}
    source = {"title": "Together", "artist": "Имя артиста", "release_type": "album"}
    assert choose_group(source, [single, album]) == album
    source["artist"] = "Collaborator"
    assert choose_group(source, [album]) == album


def test_wrong_ambiguous_short_and_double_fuzzy_matches_stay_unlinked():
    album = group()
    assert choose_group({"title": "Honeymoon", "artist": "Lana"}, [album]) is None
    assert choose_group({"title": "Honeymoons", "artist": "Lana Del Ray"}, [album]) is None
    assert choose_group({"title": "Honeymoon", "artist": "Unknown artist"}, [album]) is None
    assert (
        choose_group({"title": "Honeymoon", "artist": "Lana Del Rey"}, [album, group()]) is None
    )
    live = {**album, "secondary-types": ["Live"]}
    assert choose_group({"title": "Honeymoon", "artist": "Lana Del Rey"}, [live]) is None
    assert album_key("Honeymoon Deluxe") != album_key("Honeymoon")
    assert (
        choose_group(
            {"title": "Marcos Valle", "artist": "Marco"},
            [group("Marcos Valle", "Marcos Valle")],
        )
        is None
    )


@pytest.mark.asyncio
async def test_album_first_alias_lookup_is_bounded_and_keeps_edition_identity():
    artist_id, release_id = str(uuid4()), str(uuid4())
    album = group("Synthetic Album", "Actual Artist")
    album["artist-credit"][0]["artist"]["id"] = artist_id
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("artist/"):
            data = {
                "artists": [
                    {
                        "id": artist_id,
                        "name": "Actual Artist",
                        "aliases": [{"name": "Legal Name"}],
                    }
                ]
            }
        elif request.url.path.endswith("release-group/"):
            data = {
                "release-groups": [album]
                if "arid:" in request.url.params.get("query", "")
                else []
            }
        else:
            data = {
                "releases": [
                    {
                        "id": str(uuid4()),
                        "title": "Synthetic Album",
                        "status": "Official",
                        "disambiguation": "deluxe edition",
                        "cover-art-archive": {"front": True},
                    },
                    {
                        "id": release_id,
                        "title": "Synthetic Album",
                        "status": "Official",
                        "media": [{"track-count": 8}],
                    },
                ]
            }
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = MusicBrainzProvider(client)
        result = await provider.match_album(
            {"title": "Synthetic Album", "artist": "Legal Name"}
        )
        assert result == {"provider_id": release_id, "release_group_id": album["id"]}
        assert len(calls) == 5
        assert all(int(call.url.params["limit"]) <= 100 for call in calls)


@pytest.mark.asyncio
async def test_cache_hit_does_not_wait_for_provider_queue_and_bulk_skips_art_chooser():
    release_id, group_id = str(uuid4()), str(uuid4())
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": release_id,
                "title": "Fixture Album",
                "artist-credit": [{"name": "Fixture"}],
                "release-group": {"id": group_id},
                "cover-art-archive": {"front": True},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = MusicBrainzProvider(client)
        result = await provider.fill_detail(release_id)
        assert len(calls) == 1 and result["artwork_url"].endswith("/front-500")
        async with provider.lane.acquire():
            assert await asyncio.wait_for(provider.fill_detail(release_id), 0.1) == result
        provider.cache[("cached", ())] = (time.monotonic() + 60, {"items": [1]})
        first = await provider._get("cached")
        first["items"].append(2)
        assert (await provider._get("cached"))["items"] == [1]
