"""Independent identities must agree; multilingual titles are not fuzzy guesses."""

from uuid import uuid4

import httpx
import pytest

from watchtracker.music.provider import MusicBrainzProvider
from watchtracker.music.wikidata import WikidataAlbumBridge


def claim(value):
    return {"mainsnak": {"snaktype": "value", "datavalue": {"value": value}}}


def fixtures():
    group, artist = str(uuid4()), str(uuid4())
    work = {
        "labels": {"en": {"value": "Blue Sky"}, "ja": {"value": "青空"}},
        "claims": {"P436": [claim(group)], "P175": [claim({"id": "Q2"})]},
    }
    performer = {
        "labels": {"en": {"value": "Fixture Artist"}},
        "aliases": {"ru": [{"value": "Пример"}]},
        "claims": {"P434": [claim(artist)]},
    }
    return group, artist, work, performer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "match",
        "wrong_artist",
        "partial_artist",
        "wrong_title",
        "missing_id",
        "deprecated",
        "ambiguous",
    ],
)
async def test_bridge_is_bounded_and_requires_performer_and_album_identity(case):
    group, artist, work, performer = fixtures()
    source = {"title": "Blue Sky", "artist": "Пример"}
    if case == "wrong_artist":
        source["artist"] = "Unrelated Artist"
    if case == "partial_artist":
        source["artist"] = "Fixture"
    if case == "wrong_title":
        source["title"] = "Blue Sky Deluxe Live"
    if case == "missing_id":
        work["claims"]["P436"] = []
    if case == "deprecated":
        work["claims"]["P436"][0]["rank"] = "deprecated"
    works = {"Q1": work}
    if case == "ambiguous":
        works["Q3"] = {**work, "claims": {**work["claims"], "P436": [claim(str(uuid4()))]}}
    calls = []

    def handle(request):
        calls.append(request)
        params = request.url.params
        assert params["maxlag"] == "5"
        if params["action"] == "wbsearchentities":
            data = {"search": [{"id": key} for key in works]}
        else:
            data = {"entities": {"Q2": performer} if params["ids"] == "Q2" else works}
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        bridge = WikidataAlbumBridge(client)
        result = await bridge.find(source)
        if case == "match":
            assert result["id"] == group
            assert result["artists"][artist] == ["Fixture Artist", "Пример"]
        else:
            assert result is None
        assert len(calls) <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("conflicting_credit", [False, True])
async def test_bridge_crosschecks_musicbrainz_credit_before_choosing_edition(
    monkeypatch, conflicting_credit
):
    group, artist, work, performer = fixtures()
    release = str(uuid4())
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "www.wikidata.org":
            params = request.url.params
            if params["action"] == "wbsearchentities":
                data = {"search": [{"id": "Q1"}]}
            else:
                data = {
                    "entities": {"Q2": performer} if params["ids"] == "Q2" else {"Q1": work}
                }
        elif request.url.path.endswith(f"release-group/{group}"):
            data = {
                "id": group,
                "title": "青空",
                "primary-type": "Album",
                "artist-credit": [
                    {
                        "artist": {
                            "id": str(uuid4()) if conflicting_credit else artist,
                            "name": "Fixture Artist",
                        }
                    }
                ],
            }
        else:
            assert request.url.params["release-group"] == group
            data = {
                "releases": [
                    {
                        "id": release,
                        "title": "青空",
                        "status": "Official",
                        "media": [{"track-count": 10}],
                    }
                ]
            }
        return httpx.Response(200, json=data)

    async def no_match(_):
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = MusicBrainzProvider(client)
        monkeypatch.setattr(provider, "match_album", no_match)
        result = await provider.match_album_with_aliases(
            {"title": "Blue Sky", "artist": "Пример"}
        )
        assert result == (
            None if conflicting_credit else {"provider_id": release, "release_group_id": group}
        )
        assert len(calls) <= 5


@pytest.mark.asyncio
async def test_successful_primary_match_never_contacts_extra_source(monkeypatch):
    provider = MusicBrainzProvider()

    async def matched(_):
        return {"provider_id": str(uuid4())}

    async def forbidden(_):
        pytest.fail("Do not contact another provider for an already matched album")

    monkeypatch.setattr(provider, "match_album", matched)
    monkeypatch.setattr(provider.alias_client, "find", forbidden)
    assert await provider.match_album_with_aliases({"title": "Fixture", "artist": "Fixture"})
    await provider.close()
