from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.public_message = f"{provider} is temporarily unavailable."
        self.retryable = retryable


def redact_secrets(value: str, secrets: list[str | None] | None = None) -> str:
    redacted = value
    for secret in secrets or []:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)\S+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"(?i)(api_key|token)=([^&\s]+)", r"\1=[REDACTED]", redacted)
    return redacted


class ResilientHttpClient:
    RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        attempts: int = 3,
        base_delay: float = 0.2,
        timeout: float = 8.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout,
                connect=min(timeout, 4.0),
                read=timeout,
                write=timeout,
                pool=min(timeout, 4.0),
            ),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self.attempts = max(1, attempts)
        self.base_delay = max(0, base_delay)
        self.sleep = sleep

    async def request_json(
        self,
        provider: str,
        method: str,
        url: str,
        *,
        secrets: list[str | None] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = await self.client.request(method, url, **kwargs)
                if response.status_code in self.RETRYABLE_STATUS:
                    if attempt + 1 < self.attempts:
                        header = response.headers.get("Retry-After", "")
                        delay = (
                            min(float(header), 3.0)
                            if header.replace(".", "", 1).isdigit()
                            else self.base_delay * (2**attempt)
                        )
                        await self.sleep(delay)
                        continue
                    raise ProviderError(
                        provider, f"HTTP {response.status_code}", retryable=True
                    )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ProviderError(provider, "Unexpected provider response")
                return data
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    await self.sleep(self.base_delay * (2**attempt))
                    continue
            except (httpx.HTTPStatusError, ValueError) as exc:
                message = redact_secrets(str(exc), secrets)
                logger.warning(
                    "Provider %s request failed: type=%s",
                    provider,
                    type(exc).__name__,
                )
                raise ProviderError(provider, message) from exc
        safe = redact_secrets(str(last_error or "request failed"), secrets)
        logger.warning(
            "Provider %s exhausted retries: type=%s",
            provider,
            type(last_error).__name__ if last_error else "unknown",
        )
        raise ProviderError(provider, safe, retryable=True) from last_error

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
