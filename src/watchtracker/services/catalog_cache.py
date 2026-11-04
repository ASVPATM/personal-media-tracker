"""Bounded public catalog responses and fair, interactive-first provider lanes.

No user library payloads or credentials belong here. Cache keys are digests;
only successful, public provider JSON is persisted. This is expendable cache,
not a second database or a source of identity decisions.
"""

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from tempfile import NamedTemporaryFile

background_catalog = ContextVar("background_catalog", default=False)
bypass_negative = ContextVar("bypass_negative", default=False)


@contextmanager
def catalog_work(*, background=False, retry=False):
    background_token = background_catalog.set(background)
    retry_token = bypass_negative.set(retry)
    try:
        yield
    finally:
        bypass_negative.reset(retry_token)
        background_catalog.reset(background_token)


class CatalogLane:
    """One non-preemptive request; let a bulk waiter run after four UI requests."""

    def __init__(self):
        self.condition = asyncio.Condition()
        self.waiters = []
        self.active = False
        self.foreground_streak = 0
        self.metrics = Counter()

    def next_waiter(self):
        bulk = next((item for item in self.waiters if item[1]), None)
        if bulk and self.foreground_streak >= 4:
            return bulk
        return next((item for item in self.waiters if not item[1]), bulk)

    @asynccontextmanager
    async def acquire(self):
        ticket = (object(), background_catalog.get())
        started = time.perf_counter()
        async with self.condition:
            self.waiters.append(ticket)
            try:
                await self.condition.wait_for(
                    lambda: not self.active and self.next_waiter() is ticket
                )
                self.active = True
                self.foreground_streak = 0 if ticket[1] else self.foreground_streak + 1
            finally:
                self.waiters.remove(ticket)
                self.condition.notify_all()
        self.metrics["queue_ms"] += (time.perf_counter() - started) * 1000
        self.metrics["background" if ticket[1] else "foreground"] += 1
        try:
            yield
        finally:
            async with self.condition:
                self.active = False
                self.condition.notify_all()


def negative_payload(data):
    for key in ("releases", "release-groups", "artists", "docs", "images", "search"):
        if key in data and isinstance(data[key], list):
            return not data[key]
    return False


class CatalogDiskCache:
    MAX_BYTES = 32 * 1024 * 1024
    MAX_FILES = 2048
    MAX_ITEM = 4 * 1024 * 1024

    def __init__(self, directory):
        self.directory = Path(directory) / "public-catalog-v1"
        self.metrics = Counter()

    @staticmethod
    def key(provider, path, params):
        raw = json.dumps([1, provider, path, params], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def read(self, key, *, retry=False, stale=False):
        path = self.directory / f"{key}.json"
        try:
            if self.directory.is_symlink() or path.is_symlink():
                return None
            if path.stat().st_size > self.MAX_ITEM:
                return None
            item = json.loads(path.read_text())
            if item["schema"] != 1 or not isinstance(item["data"], dict):
                return None
            if retry and item["negative"]:
                return None
            deadline = item["stale_until"] if stale else item["expires"]
            if deadline < time.time():
                return None
            self.metrics["negative_hit" if item["negative"] else "disk_hit"] += 1
            return item
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write(self, key, data, *, search=False):
        negative = negative_payload(data)
        ttl = 900 if negative else 86400 if search else 7 * 86400
        now = time.time()
        item = {
            "schema": 1,
            "expires": now + ttl,
            "negative": negative,
            "stale_until": now + ttl if negative or search else now + 30 * 86400,
            "data": data,
        }
        encoded = json.dumps(item, ensure_ascii=False).encode()
        if len(encoded) > self.MAX_ITEM or self.directory.is_symlink():
            return item
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with NamedTemporaryFile(dir=self.directory, suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                file.write(encoded)
            os.replace(temporary, self.directory / f"{key}.json")
            self.prune()
        except OSError:
            self.metrics["write_error"] += 1
        finally:
            if temporary:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
        return item

    def prune(self):
        entries = []
        for path in self.directory.iterdir():
            if re.fullmatch(r"[0-9a-f]{64}\.json", path.name) and not path.is_symlink():
                try:
                    info = path.stat()
                    entries.append((info.st_mtime, info.st_size, path))
                except OSError:
                    pass
        size, count = sum(row[1] for row in entries), len(entries)
        for _, length, path in sorted(entries):
            if size <= self.MAX_BYTES and count <= self.MAX_FILES:
                break
            path.unlink(missing_ok=True)
            size -= length
            count -= 1
