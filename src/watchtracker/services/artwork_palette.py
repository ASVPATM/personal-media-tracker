"""Bounded, provider-only colour sampling; never an arbitrary image proxy."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import socket
import time
import warnings
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx
from PIL import Image

PROVIDER_HOSTS = frozenset(
    {
        "image.tmdb.org",
        "static.tvmaze.com",
        "media.kitsu.app",
        "cdn.myanimelist.net",
        "s3.anilist.co",
        "s4.anilist.co",
        "upload.wikimedia.org",
        "covers.openlibrary.org",
        "coverartarchive.org",
        "archive.org",
    }
)
MAX_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 12_000_000


def provider_image_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        return bool(
            parsed.scheme == "https"
            and (host in PROVIDER_HOSTS or host.endswith(".archive.org"))
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
    except ValueError:
        return False


async def public_host(url: str) -> bool:
    rows = await asyncio.get_running_loop().getaddrinfo(
        urlsplit(url).hostname, 443, type=socket.SOCK_STREAM
    )
    return bool(rows) and all(ipaddress.ip_address(row[4][0]).is_global for row in rows)


def sample_image(data: bytes) -> list[int] | None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                return None
            if image.width * image.height > MAX_PIXELS:
                return None
            image = image.convert("RGBA")
            image = image.crop((0, int(image.height * 0.45), image.width, image.height))
            image = image.resize((12, 12))
            pixels = [p for p in image.getdata() if p[3] >= 180]
            if not pixels:
                return None
            return [round(sum(p[c] for p in pixels) / len(pixels)) for c in range(3)]


class ArtworkPaletteService:
    def __init__(self):
        self.cache: OrderedDict[str, tuple[float, list[int] | None]] = OrderedDict()
        self.pending: dict[str, asyncio.Task] = {}
        self.limit = asyncio.Semaphore(4)

    async def sample(self, url: str | None) -> list[int] | None:
        if not url or not provider_image_url(url):
            return None
        if url in self.cache:
            expires, value = self.cache[url]
            if expires > time.monotonic():
                self.cache.move_to_end(url)
                return value
            del self.cache[url]
        if url not in self.pending:
            # A crowded library must not create an unbounded download queue.
            if len(self.pending) >= 64:
                return None
            self.pending[url] = asyncio.create_task(self._sample(url))
        return await asyncio.shield(self.pending[url])

    async def _sample(self, url: str) -> list[int] | None:
        value = None
        try:
            async with asyncio.timeout(12), self.limit:
                value = await self._download(url)
        except (
            OSError,
            ValueError,
            httpx.HTTPError,
            TimeoutError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ):
            # An unavailable/unsupported image must never prevent a tile loading.
            pass
        finally:
            self.cache[url] = (time.monotonic() + (86_400 if value else 300), value)
            if len(self.cache) > 256:
                self.cache.popitem(last=False)
            self.pending.pop(url, None)
        return value

    async def _download(self, url: str) -> list[int] | None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=3), follow_redirects=False, trust_env=False
        ) as client:
            for _ in range(3):
                if not provider_image_url(url) or not await public_host(url):
                    return None
                async with client.stream(
                    "GET", url, headers={"Accept": "image/jpeg,image/png,image/webp"}
                ) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers.get("location", "")))
                        continue
                    response.raise_for_status()
                    if response.headers.get("content-type", "").split(";")[0] not in {
                        "image/jpeg",
                        "image/png",
                        "image/webp",
                        "image/gif",
                    }:
                        return None
                    if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                        return None
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            return None
                    return await asyncio.to_thread(sample_image, bytes(data))
        return None

    async def close(self):
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
