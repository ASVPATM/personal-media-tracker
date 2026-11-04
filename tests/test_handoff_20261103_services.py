"""Artwork provenance, retired network integrations and preference preservation."""

from uuid import UUID, uuid4

import httpx
import pytest

from watchtracker.music.provider import MusicBrainzProvider, image_options
from watchtracker.services.preferences import PreferenceStore


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("variant", [False, True])
async def test_detail_and_fill_keep_curated_album_cover_but_preserve_named_editions(
    bulk, variant
):
    release_id, group_id, cover_id = str(uuid4()), str(uuid4()), str(uuid4())
    requests = []

    def handle(request):
        requests.append(str(request.url))
        if request.url.host == "musicbrainz.org":
            return httpx.Response(
                200,
                json={
                    "id": release_id,
                    "title": "The Dark Side of the Moon",
                    "artist-credit": [{"name": "Pink Floyd"}],
                    "date": "1973",
                    "disambiguation": "deluxe edition" if variant else "",
                    "release-group": {
                        "id": group_id,
                        "title": "The Dark Side of the Moon",
                        "primary-type": "Album",
                    },
                    "cover-art-archive": {"front": True},
                    "media": [
                        {
                            "format": "Cassette",
                            "tracks": [{"title": "Speak to Me", "length": 70000}],
                        }
                    ],
                },
            )
        group = "release-group" in request.url.path
        return httpx.Response(
            200,
            json={
                "images": [
                    {
                        "id": "123" if group else "456",
                        "approved": True,
                        "front": True,
                        "types": ["Front"],
                        "comment": "" if group or variant else "Cassette case",
                        "image": f"https://coverartarchive.org/release/{cover_id if group else release_id}/{123 if group else 456}.jpg",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await MusicBrainzProvider(http).detail(
            UUID(release_id), artwork_choices=not bulk
        )
    assert result["provider_id"] == release_id
    assert result["tracks"][0]["title"] == "Speak to Me"
    assert result["edition_info"]["artwork_scope"] == (
        "Selected edition" if variant else "Release group"
    )
    if bulk:
        assert len(requests) == 1  # No per-image lookup added to bulk fill.
        assert (
            f"{'release' if variant else 'release-group'}/{release_id if variant else group_id}/front-500"
            in result["artwork_url"]
        )
    else:
        assert len(requests) == 2
        assert (
            f"{release_id if variant else cover_id}/{456 if variant else 123}-1200.jpg"
            in result["artwork_url"]
        )


def test_packaging_scans_do_not_beat_clean_front():
    identifier = uuid4()
    rows = [
        {
            "id": str(i),
            "image": f"https://coverartarchive.org/release/{identifier}/{i}.jpg",
            "front": True,
            "approved": True,
            "types": ["Front"],
            "comment": comment,
        }
        for i, comment in [(1, "Cassette case"), (2, ""), (3, "Box with sticker")]
    ]
    choices = image_options({"images": rows})
    assert choices[0]["url"].endswith("/2-1200.jpg")
    assert all(choice["packaging"] for choice in choices[1:])


def test_shipped_app_cannot_contact_account_integrations(client):
    for method, path in [
        ("get", "/api/integrations/catalog"),
        ("post", "/api/integrations/connections"),
        ("post", "/api/v1/integrations/connections/old/runs"),
        ("get", "/api/v1/integrations/oauth/trakt/callback"),
        ("post", "/api/v1/webhooks/plex/old"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "integrations_unavailable"
    assert "integration_sync" not in client.app.state.job_runner.handlers
    assert client.get("/api/metadata/providers").status_code == 200
    assert client.get("/api/music/albums").status_code == 200


def test_icon_default_follows_accent_without_overwriting_explicit_choice(settings):
    store = PreferenceStore(settings)
    assert store.load()["icon_follow_accent"] is True
    store.update(icon_follow_accent=False, icon_text_color="#f034ad")
    reopened = PreferenceStore(settings).load()
    assert reopened["icon_follow_accent"] is False
    assert reopened["icon_text_color"] == "#f034ad"
