"""Request principals and the fail-closed tenant ownership boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from watchtracker.models import UserAccount

LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"
AuthenticationMethod = Literal["local", "password", "device_token", "system"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Literal["admin", "member"]
    authentication_method: AuthenticationMethod
    session_id: str | None = None
    is_local_mode: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def principal_for_user(
    session: Session,
    user_id: str,
    *,
    authentication_method: AuthenticationMethod,
    session_id: str | None = None,
    is_local_mode: bool = False,
) -> Principal | None:
    user = session.scalar(
        select(UserAccount).where(
            UserAccount.id == user_id,
            UserAccount.state == "active",
        )
    )
    if user is None:
        return None
    return Principal(
        user_id=user.id,
        role="admin" if user.role == "admin" else "member",
        authentication_method=authentication_method,
        session_id=session_id,
        is_local_mode=is_local_mode,
    )


def local_principal(session: Session) -> Principal:
    users = list(
        session.scalars(
            select(UserAccount)
            .where(UserAccount.state == "active")
            .order_by(UserAccount.created_at, UserAccount.id)
            .limit(2)
        )
    )
    if not users:
        raise RuntimeError("The local data profile is missing.")
    if len(users) > 1:
        raise RuntimeError(
            "Local-only mode cannot choose between multiple users; start Shared Server mode."
        )
    user = users[0]
    return Principal(
        user_id=user.id,
        role="admin" if user.role == "admin" else "member",
        authentication_method="local",
        is_local_mode=True,
    )


def bind_principal(session: Session, principal: Principal) -> None:
    session.info["principal"] = principal
    session.info["user_id"] = principal.user_id


def current_principal(session: Session, principal: Principal | None = None) -> Principal:
    resolved = principal or session.info.get("principal")
    if isinstance(resolved, Principal):
        return resolved
    # This fallback exists for internal scripts and older unit tests. It is safe only
    # when the database has exactly one active user; ambiguous access fails closed.
    resolved = local_principal(session)
    bind_principal(session, resolved)
    return resolved


def current_user_id(session: Session, principal: Principal | None = None) -> str:
    return current_principal(session, principal).user_id


def request_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(401, "Sign in to continue.")
    return principal


def require_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise HTTPException(403, "Administrator access is required.")
