from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from watchtracker.authorization import Principal
from watchtracker.integrations.playback import parse_playback_event
from watchtracker.models import (
    IntegrationConnection,
    IntegrationUserBinding,
    UserAccount,
    WebhookCredential,
    utcnow,
)
from watchtracker.services.integrations import IntegrationCoordinator, IntegrationError


class PlaybackIntegrationService:
    def __init__(self, session: Session, principal: Principal):
        self.session = session
        self.principal = principal

    def _connection(self, connection_id: str) -> IntegrationConnection:
        if not self.principal.is_local_mode and not self.principal.is_admin:
            raise IntegrationError(
                "Media-server connections are managed by the dedicated server account."
            )
        connection = self.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.user_id == self.principal.user_id,
                IntegrationConnection.provider_slug.in_(("jellyfin", "plex", "emby")),
            )
        )
        if connection is None:
            raise IntegrationError("Playback connection not found.")
        return connection

    def issue_webhook(self, connection_id: str, *, base_url: str) -> dict[str, str]:
        connection = self._connection(connection_id)
        for row in self.session.scalars(
            select(WebhookCredential).where(
                WebhookCredential.connection_id == connection.id,
                WebhookCredential.revoked_at.is_(None),
            )
        ):
            row.revoked_at = utcnow()
        token = secrets.token_urlsafe(40)
        public_id = secrets.token_urlsafe(15)[:20]
        row = WebhookCredential(
            connection_id=connection.id,
            public_id=public_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        self.session.add(row)
        self.session.commit()
        callback_url = (
            f"{base_url.rstrip('/')}/api/v1/webhooks/{connection.provider_slug}/{public_id}"
        )
        transport = "header"
        response_token = token
        token_header = "X-PMT-Webhook-Token"
        if connection.provider_slug in {"plex", "emby"}:
            # These provider webhook forms accept a URL but do not reliably provide a
            # custom-header control. Keep the credential in the one-time setup URL and
            # retain only its hash in PMT.
            callback_url = f"{callback_url}?token={quote(token, safe='')}"
            transport = "query"
            response_token = ""
            token_header = ""
        return {
            "provider": connection.provider_slug,
            "callback_url": callback_url,
            "token": response_token,
            "token_header": token_header,
            "credential_transport": transport,
        }

    def bindings(self, connection_id: str) -> list[dict[str, Any]]:
        connection = self._connection(connection_id)
        rows = self.session.execute(
            select(IntegrationUserBinding, UserAccount)
            .join(UserAccount, IntegrationUserBinding.pmt_user_id == UserAccount.id)
            .where(IntegrationUserBinding.connection_id == connection.id)
            .order_by(IntegrationUserBinding.remote_user_label)
        )
        return [
            {
                "id": binding.id,
                "remote_user_id": binding.remote_user_id,
                "remote_user_label": binding.remote_user_label,
                "pmt_user_id": user.id,
                "pmt_display_name": user.display_name,
            }
            for binding, user in rows
        ]

    def bind(
        self,
        connection_id: str,
        *,
        remote_user_id: str,
        remote_user_label: str | None,
        pmt_user_id: str,
    ) -> dict[str, Any]:
        connection = self._connection(connection_id)
        if not self.principal.is_admin and pmt_user_id != self.principal.user_id:
            raise IntegrationError("You can map only your own PMT account.")
        user = self.session.scalar(
            select(UserAccount).where(
                UserAccount.id == pmt_user_id,
                UserAccount.state == "active",
            )
        )
        if user is None:
            raise IntegrationError("PMT user not found.")
        row = IntegrationUserBinding(
            connection_id=connection.id,
            remote_user_id=remote_user_id.strip()[:200],
            remote_user_label=(remote_user_label or "").strip()[:120] or None,
            pmt_user_id=user.id,
            created_by_user_id=self.principal.user_id,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise IntegrationError(
                "That remote user or PMT user is already mapped on this connection."
            ) from exc
        return {
            "id": row.id,
            "remote_user_id": row.remote_user_id,
            "remote_user_label": row.remote_user_label,
            "pmt_user_id": user.id,
            "pmt_display_name": user.display_name,
        }


def authenticate_webhook(
    session: Session, *, provider: str, public_id: str, token: str
) -> tuple[WebhookCredential, IntegrationConnection] | None:
    credential = session.scalar(
        select(WebhookCredential).where(
            WebhookCredential.public_id == public_id,
            WebhookCredential.revoked_at.is_(None),
        )
    )
    if credential is None:
        return None
    connection = session.get(IntegrationConnection, credential.connection_id)
    digest = hashlib.sha256(token.encode()).hexdigest()
    if (
        connection is None
        or connection.provider_slug != provider
        or not hmac.compare_digest(credential.token_hash, digest)
    ):
        return None
    credential.last_used_at = utcnow()
    session.commit()
    return credential, connection


def ingest_playback(
    session: Session,
    coordinator: IntegrationCoordinator,
    connection: IntegrationConnection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    threshold = float(connection.configuration.get("completion_threshold") or 0.9)
    envelope = parse_playback_event(
        connection.provider_slug, payload, completion_threshold=max(0.5, min(threshold, 1.0))
    )
    binding = session.scalar(
        select(IntegrationUserBinding).where(
            IntegrationUserBinding.connection_id == connection.id,
            IntegrationUserBinding.remote_user_id == envelope.remote_user_id,
        )
    )
    if binding is None:
        return {"accepted": True, "applied": False, "reason": "remote_user_unbound"}
    if envelope.event is None:
        return {"accepted": True, "applied": False, "reason": envelope.ignored_reason}
    result = coordinator.ingest(connection.id, envelope.event, user_id=binding.pmt_user_id)
    return {"accepted": True, "applied": True, "run": result}
