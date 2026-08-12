from __future__ import annotations

from typing import Any

import httpx
from packaging.version import InvalidVersion, Version


class UpdateCheckError(RuntimeError):
    pass


class UpdateService:
    def __init__(self, repository_url: str, current_version: str, *, client=None):
        self.repository_url = repository_url.rstrip("/")
        self.current_version = current_version
        self.client = client

    @property
    def endpoint(self) -> str:
        parts = self.repository_url.split("/")
        if len(parts) < 2:
            raise UpdateCheckError("The update source is not configured correctly.")
        owner, repository = parts[-2:]
        return f"https://api.github.com/repos/{owner}/{repository}/releases/latest"

    async def check(self) -> dict[str, Any]:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False
        )
        try:
            response = await client.get(
                self.endpoint,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"personal-media-tracker/{self.current_version}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("response is not an object")
            tag = str(payload.get("tag_name") or "").lstrip("v")
            release_url = str(payload.get("html_url") or "")
            if not tag or not release_url.startswith("https://github.com/"):
                raise ValueError("release fields are missing")
            current = Version(self.current_version)
            latest = Version(tag)
            return {
                "current_version": str(current),
                "latest_version": str(latest),
                "update_available": latest > current and not latest.is_prerelease,
                "release_url": release_url,
            }
        except (httpx.HTTPError, ValueError, InvalidVersion) as exc:
            raise UpdateCheckError(
                "Updates could not be checked. Check your connection and try again."
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
