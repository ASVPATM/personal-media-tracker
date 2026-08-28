from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from watchtracker.authorization import Principal, current_user_id
from watchtracker.integrations import ProviderRegistry
from watchtracker.models import (
    IntegrationConnection,
    IntegrationOAuthGrant,
    IntegrationOAuthState,
    utcnow,
)
from watchtracker.services.secrets import SecretStore


class IntegrationAuthorizationError(RuntimeError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class IntegrationAuthorizationService:
    def __init__(
        self,
        session: Session,
        registry: ProviderRegistry,
        secret_store: SecretStore,
        principal: Principal | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.session = session
        self.registry = registry
        self.secrets = secret_store
        self.user_id = current_user_id(session, principal) if principal else None
        self.client = client

    def start(self, connection_id: str, *, redirect_uri: str) -> dict[str, Any]:
        connection = self.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.user_id == self.user_id,
            )
        )
        if connection is None:
            raise IntegrationAuthorizationError("Integration connection not found.")
        definition = self.registry.definition(connection.provider_slug)
        if not definition.oauth_authorize_url or not definition.oauth_token_url:
            raise IntegrationAuthorizationError(
                "This provider uses manual credentials instead of browser authorization."
            )
        client_id = self._credential(connection, "client_id") or str(
            connection.configuration.get("client_id") or ""
        )
        if not client_id:
            raise IntegrationAuthorizationError(
                "Add the provider application's client ID before authorizing."
            )
        state = secrets.token_urlsafe(40)
        verifier = secrets.token_urlsafe(64)
        verifier_reference = f"integration.oauth.{secrets.token_hex(12)}"
        self.secrets.save_named(verifier_reference, "pkce_verifier", verifier)
        now = utcnow()
        row = IntegrationOAuthState(
            connection_id=connection.id,
            user_id=connection.user_id,
            provider_slug=connection.provider_slug,
            state_hash=_hash(state),
            verifier_reference=verifier_reference,
            redirect_uri=redirect_uri,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        self.session.add(row)
        self.session.commit()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if definition.oauth_scopes:
            params["scope"] = " ".join(definition.oauth_scopes)
        if definition.authorization_type == "oauth2_pkce":
            if connection.provider_slug == "myanimelist":
                challenge = verifier
                method = "plain"
            else:
                challenge = _b64(hashlib.sha256(verifier.encode()).digest())
                method = "S256"
            params.update(
                {
                    "code_challenge": challenge,
                    "code_challenge_method": method,
                }
            )
        return {
            "authorization_url": f"{definition.oauth_authorize_url}?{urlencode(params)}",
            "callback_url": redirect_uri,
            "expires_at": _aware(row.expires_at).isoformat(),
        }

    async def callback(self, provider: str, *, state: str, code: str) -> dict[str, Any]:
        row = self.session.scalar(
            select(IntegrationOAuthState).where(
                IntegrationOAuthState.state_hash == _hash(state),
                IntegrationOAuthState.provider_slug == provider,
            )
        )
        now = utcnow()
        if row is None or row.used_at is not None or _aware(row.expires_at) < now:
            raise IntegrationAuthorizationError(
                "This authorization link expired or was already used. Start again."
            )
        connection = self.session.get(IntegrationConnection, row.connection_id)
        if connection is None:
            raise IntegrationAuthorizationError("Integration connection not found.")
        definition = self.registry.definition(provider)
        verifier, _ = self.secrets.get_named(
            row.verifier_reference, "pkce_verifier", refresh=True
        )
        if not verifier:
            raise IntegrationAuthorizationError("Authorization verifier is unavailable.")
        client_id = self._credential(connection, "client_id") or str(
            connection.configuration.get("client_id") or ""
        )
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": row.redirect_uri,
        }
        if definition.authorization_type == "oauth2_pkce":
            payload["code_verifier"] = verifier
        if client_secret := self._credential(connection, "client_secret"):
            payload["client_secret"] = client_secret
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=7), follow_redirects=False
        )
        close = self.client is None
        try:
            if provider in {"trakt", "simkl", "anilist"}:
                response = await client.post(definition.oauth_token_url, json=payload)
            else:
                response = await client.post(definition.oauth_token_url, data=payload)
        except httpx.HTTPError as exc:
            raise IntegrationAuthorizationError(
                "The provider could not complete authorization."
            ) from exc
        finally:
            if close:
                await client.aclose()
        if response.status_code >= 400:
            raise IntegrationAuthorizationError(
                "The provider rejected authorization. Check the exact callback URL and try again."
            )
        try:
            tokens = response.json()
        except ValueError as exc:
            raise IntegrationAuthorizationError(
                "The provider returned an invalid authorization response."
            ) from exc
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            raise IntegrationAuthorizationError("The provider did not return an access token.")
        namespace = connection.secret_reference or f"integration.{connection.id}"
        token_values = {"access_token": access_token}
        if tokens.get("refresh_token"):
            token_values["refresh_token"] = str(tokens["refresh_token"])
        self.secrets.save_many_named(
            namespace,
            token_values,
            storage=connection.credential_storage,
        )
        connection.secret_reference = namespace
        connection.configuration = {
            **(connection.configuration or {}),
            "oauth_redirect_uri": row.redirect_uri,
        }
        row.used_at = now
        grant = self.session.scalar(
            select(IntegrationOAuthGrant).where(
                IntegrationOAuthGrant.connection_id == connection.id
            )
        )
        if grant is None:
            grant = IntegrationOAuthGrant(connection_id=connection.id)
            self.session.add(grant)
        expires_in = tokens.get("expires_in")
        grant.expires_at = (
            now + timedelta(seconds=max(0, int(expires_in))) if expires_in else None
        )
        grant.token_type = str(tokens.get("token_type") or "Bearer")[:30]
        scope = tokens.get("scope") or definition.oauth_scopes
        grant.scopes = str(scope).split() if isinstance(scope, str) else list(scope or [])
        grant.reconnect_reason = None
        grant.authorized_at = now
        self.session.commit()
        self.secrets.clear_namespace(row.verifier_reference, ["pkce_verifier"])
        return {
            "connected": True,
            "connection_id": connection.id,
            "provider": provider,
        }

    def status(self, connection_id: str) -> dict[str, Any]:
        connection = self.session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.user_id == self.user_id,
            )
        )
        if connection is None:
            raise IntegrationAuthorizationError("Integration connection not found.")
        grant = self.session.scalar(
            select(IntegrationOAuthGrant).where(
                IntegrationOAuthGrant.connection_id == connection.id
            )
        )
        return {
            "authorized": grant is not None and not grant.reconnect_reason,
            "expires_at": (
                _aware(grant.expires_at).isoformat() if grant and grant.expires_at else None
            ),
            "reconnect_reason": grant.reconnect_reason if grant else None,
        }

    def _credential(self, connection: IntegrationConnection, key: str) -> str | None:
        if not connection.secret_reference:
            return None
        value, _ = self.secrets.get_named(connection.secret_reference, key)
        return value
