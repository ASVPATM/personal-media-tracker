from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from dataclasses import dataclass
from typing import Protocol

import httpx


class NotificationAdapterError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class DeliveryResult:
    receipt_hash: str


class NotificationAdapter(Protocol):
    slug: str

    async def send(
        self, destination: str, *, title: str, body: str, dedupe_key: str
    ) -> DeliveryResult: ...


class EmbeddedAppriseAdapter:
    slug = "apprise"

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("apprise") is not None

    def validate_destination(self, destination: str) -> bool:
        if not self.available():
            return False
        import apprise

        try:
            client = apprise.Apprise()
            return bool(client.add(destination))
        except Exception:
            return False

    async def send(
        self, destination: str, *, title: str, body: str, dedupe_key: str
    ) -> DeliveryResult:
        if not self.available():
            raise NotificationAdapterError(
                "adapter_unavailable",
                "Embedded Apprise is not installed in this PMT build.",
            )

        def notify() -> bool:
            import apprise

            client = apprise.Apprise()
            if not client.add(destination):
                raise NotificationAdapterError(
                    "destination_invalid", "The Apprise destination is not valid."
                )
            return bool(client.notify(title=title, body=body))

        try:
            accepted = await asyncio.wait_for(asyncio.to_thread(notify), timeout=20)
        except NotificationAdapterError:
            raise
        except TimeoutError as exc:
            raise NotificationAdapterError(
                "delivery_timeout", "The notification destination timed out.", retryable=True
            ) from exc
        except Exception as exc:
            raise NotificationAdapterError(
                "delivery_failed",
                "The notification destination could not be reached.",
                retryable=True,
            ) from exc
        if not accepted:
            raise NotificationAdapterError(
                "delivery_rejected",
                "The notification destination rejected the message.",
                retryable=True,
            )
        return DeliveryResult(hashlib.sha256(dedupe_key.encode()).hexdigest())


class AppriseApiAdapter:
    slug = "apprise_api"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def send(
        self, destination: str, *, title: str, body: str, dedupe_key: str
    ) -> DeliveryResult:
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(15, connect=5), follow_redirects=False
        )
        close = self.client is None
        try:
            response = await client.post(
                destination,
                json={"title": title, "body": body, "type": "info", "tag": "pmt"},
                headers={"Idempotency-Key": dedupe_key},
            )
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("retry-after")
                raise NotificationAdapterError(
                    "destination_unavailable",
                    "The Apprise API is temporarily unavailable.",
                    retryable=True,
                    retry_after_seconds=(
                        int(retry_after) if retry_after and retry_after.isdigit() else None
                    ),
                )
            if response.status_code >= 400:
                raise NotificationAdapterError(
                    "destination_rejected", "The Apprise API rejected the message."
                )
        except NotificationAdapterError:
            raise
        except httpx.TimeoutException as exc:
            raise NotificationAdapterError(
                "delivery_timeout", "The Apprise API timed out.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise NotificationAdapterError(
                "destination_unavailable",
                "The Apprise API could not be reached.",
                retryable=True,
            ) from exc
        finally:
            if close:
                await client.aclose()
        return DeliveryResult(hashlib.sha256(dedupe_key.encode()).hexdigest())


class NotificationAdapterRegistry:
    def __init__(self, adapters: tuple[NotificationAdapter, ...] = ()):
        self._adapters = {adapter.slug: adapter for adapter in adapters}

    def get(self, slug: str) -> NotificationAdapter | None:
        return self._adapters.get(slug)

    def capabilities(self) -> list[dict[str, object]]:
        embedded = self.get("apprise")
        return [
            {
                "adapter": "apprise",
                "available": bool(embedded and getattr(embedded, "available", lambda: True)()),
                "external_network": True,
            },
            {
                "adapter": "apprise_api",
                "available": self.get("apprise_api") is not None,
                "external_network": True,
            },
        ]


def default_notification_adapters() -> NotificationAdapterRegistry:
    return NotificationAdapterRegistry((EmbeddedAppriseAdapter(), AppriseApiAdapter()))
