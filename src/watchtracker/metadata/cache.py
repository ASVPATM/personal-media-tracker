from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


def cache_key(namespace: str, operation: str, parameters: dict[str, Any]) -> str:
    """Return a stable, order-independent key without exposing query contents in filenames."""
    canonical = json.dumps(
        {"namespace": namespace, "operation": operation, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class TTLCache:
    def __init__(self, directory: Path, ttl_seconds: int = 21_600, max_entries: int = 500):
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if float(record["expires_at"]) <= time.time():
                path.unlink(missing_ok=True)
                return None
            return record["value"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set(self, key: str, value: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"expires_at": time.time() + self.ttl_seconds, "value": value}),
            encoding="utf-8",
        )
        temporary.replace(path)
        self.prune()

    def prune(self) -> None:
        try:
            paths = sorted(
                self.directory.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in paths[self.max_entries :]:
                path.unlink(missing_ok=True)
        except OSError:
            # A cache failure must never prevent tracking a title.
            return
