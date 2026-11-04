"""Bounded local cache for artwork on owned collection entries, not a URL proxy."""

import asyncio
import base64
import hashlib
import os
import re
import time
from collections import Counter, OrderedDict
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Response

from watchtracker.music.schemas import normalize_artwork
from watchtracker.services.artwork_palette import provider_image_url, public_host

FRESH_SECONDS = 7 * 86400
STALE_SECONDS = 30 * 86400
MEMORY_BYTES = 16 * 1024 * 1024


def artwork_path(row, domain):
    if not (row.artwork_data or row.artwork_url):
        return None
    return artwork_reference(
        row.id, row.version, row.artwork_url, bool(row.artwork_data), domain
    )


def artwork_reference(identifier, version, url, uploaded, domain):
    if not (uploaded or url):
        return None
    path = "entries" if domain == "books" else "albums"
    # Personal edits keep provider-cover URLs stable. Uploaded images use the
    # entry revision, avoiding loading/hashing large blobs in a list query.
    # Both DTOs use this exact path; responses retain content ETags and ownership.
    token = str(version) if uploaded else hashlib.sha256(url.encode()).hexdigest()[:20]
    return f"/api/{domain}/{path}/{identifier}/artwork?v={token}"


def allowed(url):
    return provider_image_url(url) and (
        urlsplit(url).hostname
        in {"coverartarchive.org", "covers.openlibrary.org", "archive.org"}
        or (urlsplit(url).hostname or "").endswith(".archive.org")
    )


class CollectionArtworkCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory) / "collection-artwork-v1"
        self.pending = {}
        self.failures = OrderedDict()
        self.memory = OrderedDict()
        self.memory_bytes = 0
        self.limit = asyncio.Semaphore(4)
        self.client = None
        self.metrics = Counter()
        self.last_elapsed_ms = 0

    async def close(self):
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.client:
            await self.client.aclose()

    async def get(self, urls):
        started = time.perf_counter()
        try:
            return await self._get(urls)
        finally:
            self.last_elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    async def _get(self, urls):
        urls = [url for url in dict.fromkeys(urls) if url and allowed(url)]
        if not urls:
            self.metrics["no_artwork_supplied"] += 1
        now = time.time()
        # Check ALL cached alternatives before doing ANY network work. A failed
        # edition cover must never hold a cached release-group cover hostage.
        for url in urls:
            if item := self.memory.get(url):
                stamp, data = item
                if stamp > now - FRESH_SECONDS:
                    self.memory.move_to_end(url)
                    self.metrics["memory_hit"] += 1
                    self.metrics["fallback_hit"] += int(url != urls[0])
                    return data
        cached = await asyncio.to_thread(self.read_cached, urls, now)
        if cached:
            url, stamp, data = cached
            self.metrics["disk_hit"] += 1
            self.metrics["fallback_hit"] += int(url != urls[0])
            self.remember(url, stamp, data)
            if stamp <= now - FRESH_SECONDS:
                self.metrics["stale_hit"] += 1
                # Provider-only cached bytes remain visible while one bounded,
                # coalesced refresh runs. Ownership is checked by every caller.
                self.start(url)
            return data
        self.metrics["miss"] += 1
        for url in urls:
            if data := await self.one(url):
                return data
        return None

    def read_cached(self, urls, now):
        stale = None
        for url in urls:
            path = self.directory / f"{hashlib.sha256(url.encode()).hexdigest()}.jpg"
            try:
                if self.directory.is_symlink() or path.is_symlink():
                    continue
                stamp = path.stat().st_mtime
                if stamp <= now - STALE_SECONDS:
                    continue
                if path.stat().st_size > 4 * 1024 * 1024:
                    continue
                item = (url, stamp, path.read_bytes())
                if stamp > now - FRESH_SECONDS:
                    return item
                if stale is None:
                    stale = item
            except OSError:
                pass
        return stale

    def remember(self, url, stamp, data):
        previous = self.memory.pop(url, None)
        if previous:
            self.memory_bytes -= len(previous[1])
        self.memory[url] = (stamp, data)
        self.memory_bytes += len(data)
        while self.memory_bytes > MEMORY_BYTES or len(self.memory) > 64:
            _, (_, removed) = self.memory.popitem(last=False)
            self.memory_bytes -= len(removed)

    def start(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.directory / f"{key}.jpg"
        if self.failures.get(key, 0) > time.monotonic():
            return None
        if key not in self.pending:
            if len(self.pending) >= 100:
                return None
            self.pending[key] = asyncio.create_task(self.fetch(url, key, path))
        return self.pending[key]

    async def one(self, url):
        task = self.start(url)
        return await asyncio.shield(task) if task else None

    async def fetch(self, url, key, path):
        try:
            async with asyncio.timeout(20), self.limit:
                data = await self.download(url)
                if data:
                    # A full/read-only cache must not hide a valid cover.
                    with suppress(OSError):
                        writer = asyncio.create_task(asyncio.to_thread(self.store, path, data))
                        try:
                            await asyncio.shield(writer)
                        except asyncio.CancelledError:
                            # Cache clearing waits for an already-running disk
                            # write before removing its generated file.
                            await writer
                            raise
                    self.remember(url, time.time(), data)
                    self.failures.pop(key, None)
                    return data
        except (OSError, ValueError, httpx.HTTPError, TimeoutError):
            pass
        finally:
            self.pending.pop(key, None)
        self.failures[key] = time.monotonic() + 300
        if len(self.failures) > 512:
            self.failures.popitem(last=False)
        return None

    async def download(self, url):
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(8, connect=3),
                follow_redirects=False,
                trust_env=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            )
        for _ in range(5):
            if not allowed(url) or not await public_host(url):
                return None
            async with self.client.stream(
                "GET", url, headers={"Accept": "image/jpeg,image/png,image/webp"}
            ) as response:
                self.metrics["upstream_requests"] += 1
                if response.is_redirect:
                    url = str(response.url.join(response.headers.get("location", "")))
                    continue
                if response.status_code != 200 or not response.headers.get(
                    "content-type", ""
                ).startswith("image/"):
                    self.metrics["provider_unavailable"] += 1
                    return None
                data = bytearray()
                async for part in response.aiter_bytes():
                    data.extend(part)
                    self.metrics["upstream_bytes"] += len(part)
                    if len(data) > 4 * 1024 * 1024:
                        return None
                try:
                    normalized = await asyncio.to_thread(normalize_artwork, bytes(data))
                except (ValueError, OSError):
                    self.metrics["invalid_image"] += 1
                    raise
                self.metrics["decoded_images"] += 1
                return base64.b64decode(normalized.split(",", 1)[1])
        return None

    def store(self, path, data):
        if self.directory.is_symlink():
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        # Only this cache's generated files are eligible for eviction. Personal
        # artwork and database/backup files are never stored in this directory.
        entries = []
        for item in self.directory.iterdir():
            if re.fullmatch(r"[0-9a-f]{64}\.jpg", item.name) and not item.is_symlink():
                try:
                    stat = item.stat()
                    entries.append((stat.st_mtime, stat.st_size, item))
                except OSError:
                    pass
        size, count = sum(item[1] for item in entries), len(entries)
        for _, length, item in sorted(entries):
            if size <= 128 * 1024 * 1024 and count <= 512:
                break
            item.unlink(missing_ok=True)
            size -= length
            count -= 1

    def inventory(self):
        entries = []
        if self.directory.is_dir() and not self.directory.is_symlink():
            for path in self.directory.iterdir():
                if re.fullmatch(r"[0-9a-f]{64}\.jpg", path.name) and not path.is_symlink():
                    with suppress(OSError):
                        entries.append((path, path.stat()))
        return entries

    async def diagnostics(self):
        entries = await asyncio.to_thread(self.inventory)
        return {
            "files": len(entries),
            "bytes": sum(info.st_size for _, info in entries),
            "oldest_age_seconds": round(
                max((time.time() - info.st_mtime for _, info in entries), default=0)
            ),
            "memory_bytes": self.memory_bytes,
            "memory_files": len(self.memory),
            "inflight": len(self.pending),
            "last_elapsed_ms": self.last_elapsed_ms,
            "counts": dict(self.metrics),
        }

    async def clear(self):
        # Cancel writers before clearing expendable downloads; uploads live in
        # owned DB rows and are never traversed here.
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.pending.clear()
        self.memory.clear()
        self.memory_bytes = 0
        self.failures.clear()

        def remove():
            for path, _ in self.inventory():
                if not path.is_symlink():
                    path.unlink(missing_ok=True)

        await asyncio.to_thread(remove)
        return await self.diagnostics()


async def artwork_response(row, request, domain):
    # Caller resolves ownership before consulting either cache or ETag.
    if not (row.artwork_data or row.artwork_url):
        raise HTTPException(404, "No artwork is available for this entry.")
    if row.artwork_data:
        data = base64.b64decode(row.artwork_data.split(",", 1)[1])
    else:
        urls = [row.artwork_url]
        if domain == "music" and row.release_group_id:
            urls.append(
                f"https://coverartarchive.org/release-group/{row.release_group_id}/front-500"
            )
            if row.provider_id:
                urls.append(f"https://coverartarchive.org/release/{row.provider_id}/front-500")
        elif domain == "books" and row.provider_id:
            urls.append(
                f"https://covers.openlibrary.org/b/olid/{row.provider_id}-M.jpg?default=false"
            )
        data = await request.app.state.collection_artwork.get(urls)
    if not data:
        raise HTTPException(
            404, "The catalog artwork is unavailable. You can choose another image."
        )
    # Revalidate the cached bytes, not just the URL: a provider can replace an
    # image at the same URL. Stale bytes may be served during background refresh;
    # the next revalidation receives the new ETag if the content changed.
    etag = f'"{hashlib.sha256(data).hexdigest()}"'
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "Vary": "Cookie, Authorization",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type="image/jpeg", headers=headers)
