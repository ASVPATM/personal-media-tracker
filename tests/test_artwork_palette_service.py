import asyncio
import io
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from watchtracker.services import artwork_palette as palettes


def png(color="#db963b"):
    output = io.BytesIO()
    Image.new("RGB", (40, 60), color).save(output, "PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    "url",
    [
        "http://image.tmdb.org/a",
        "https://localhost/a",
        "https://127.0.0.1/a",
        "https://image.tmdb.org.evil.invalid/a",
        "https://image.tmdb.org:444/a",
        "https://user:pass@image.tmdb.org/a",
        "file:///tmp/image.png",
        "https://[::1/a",
    ],
)
def test_untrusted_image_urls_rejected(url):
    assert not palettes.provider_image_url(url)


@pytest.mark.asyncio
async def test_bounded_download_cache_and_redirect_safety(monkeypatch):
    calls = []
    original_client = httpx.AsyncClient

    async def public(_url):
        return True

    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})
        if request.url.path == "/huge":
            return httpx.Response(
                200,
                headers={
                    "content-type": "image/png",
                    "content-length": str(palettes.MAX_BYTES + 1),
                },
            )
        return httpx.Response(200, content=png(), headers={"content-type": "image/png"})

    monkeypatch.setattr(palettes, "public_host", public)
    monkeypatch.setattr(
        palettes.httpx,
        "AsyncClient",
        lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw),
    )
    service = palettes.ArtworkPaletteService()
    url = "https://image.tmdb.org/poster.png"
    assert (
        await asyncio.gather(service.sample(url), service.sample(url)) == [[219, 150, 59]] * 2
    )
    assert await service.sample(url) == [219, 150, 59]
    assert calls == [url]
    assert await service.sample("https://image.tmdb.org/redirect") is None
    assert await service.sample("https://image.tmdb.org/huge") is None
    assert not any("127.0.0.1" in value for value in calls)
    await service.close()


@pytest.mark.asyncio
async def test_dns_private_address_rejected(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    assert not await palettes.public_host("https://image.tmdb.org/a")


def test_endpoint_uses_owned_entry_and_selected_artwork(client, monkeypatch):
    from watchtracker.models import WatchEntry

    calls = []

    async def sample(_self, url):
        calls.append(url)
        return [219, 150, 59]

    monkeypatch.setattr(palettes.ArtworkPaletteService, "sample", sample)
    row = client.post(
        "/api/entries/manual",
        json={
            "canonical_title": "Palette fixture",
            "media_type": "movie",
            "poster_url": "https://image.tmdb.org/original.png",
        },
    ).json()
    entry_id = row["entry"]["id"]
    with client.app.state.session_factory() as session:
        entry = session.get(WatchEntry, entry_id)
        entry.poster_override_url = "https://static.tvmaze.com/override.png"
        session.commit()
    response = client.get(f"/api/entries/{entry_id}/artwork-palette")
    assert response.status_code == 200
    assert response.json() == {
        "url": "https://static.tvmaze.com/override.png",
        "rgb": [219, 150, 59],
    }
    with client.app.state.session_factory() as session:
        entry = session.get(WatchEntry, entry_id)
        entry.user_id = str(uuid4())
        # Keep the foreign key valid, but outside this local user's library.
        from watchtracker.models import UserAccount

        session.add(
            UserAccount(
                id=entry.user_id,
                username="other",
                normalized_username="other",
                display_name="Other",
                role="member",
                state="disabled",
            )
        )
        session.commit()
    assert client.get(f"/api/entries/{entry_id}/artwork-palette").status_code == 404
    assert calls == ["https://static.tvmaze.com/override.png"]
