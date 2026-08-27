from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from watchtracker.authorization import local_principal, principal_for_user
from watchtracker.config import Settings
from watchtracker.services.auth import CSRF_COOKIE, SESSION_COOKIE

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
TAILSCALE_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_IPV6_NETWORK = ipaddress.ip_network("fd7a:115c:a1e0::/48")
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://image.tmdb.org https://s4.anilist.co "
    "https://s3.anilist.co https://cdn.myanimelist.net "
    "https://static.tvmaze.com https://media.kitsu.app "
    "https://commons.wikimedia.org https://upload.wikimedia.org; connect-src 'self'; "
    "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)


def _content_security_policy(*, allow_native_bridge: bool = False) -> str:
    """Return the browser policy, relaxing eval only for the local desktop bridge.

    pywebview's macOS and Qt bridges evaluate their generated RPC callbacks. Public
    browser and shared-server responses retain the strict no-eval policy.
    """
    if allow_native_bridge:
        return CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-eval'", 1)
    return CSP


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": None}},
    )


def _host_only(host: str) -> str:
    if host.startswith("["):
        return host.partition("]")[0].lstrip("[")
    return host.partition(":")[0]


def _is_tailscale_proxy_client(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_loopback
        or address in TAILSCALE_IPV4_NETWORK
        or address in TAILSCALE_IPV6_NETWORK
    )


def _same_origin(value: str, request: Request, settings: Settings) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if not parsed.scheme or not parsed.hostname:
        return False
    if parsed.scheme != request.url.scheme:
        return False
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.hostname.casefold().strip("[]") == (
        request.url.hostname or ""
    ).casefold().strip("[]") and (parsed.port or default_port) == (
        request.url.port or default_port
    )


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    def _headers(self, response: Response, *, native_loopback: bool = False) -> Response:
        response.headers["Content-Security-Policy"] = _content_security_policy(
            allow_native_bridge=(self.settings.native_actions and native_loopback)
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        native_bridge = self.settings.native_actions and native_loopback
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
            if native_bridge
            else "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        if self.settings.access_mode == "server" and not native_loopback:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    def _reject(
        self,
        status: int,
        code: str,
        message: str,
        *,
        native_loopback: bool = False,
    ) -> Response:
        return self._headers(_error(status, code, message), native_loopback=native_loopback)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_host = request.headers.get("host", "")
        host = _host_only(supplied_host).casefold().strip("[]")
        client_host = request.client.host if request.client else ""
        native_loopback = bool(
            self.settings.native_actions
            and Settings.is_loopback_host(host)
            and Settings.is_loopback_host(client_host)
        )
        request.state.native_desktop_loopback = native_loopback
        allowed = {item.casefold().strip("[]") for item in self.settings.allowed_hosts}
        if native_loopback:
            allowed.update({"127.0.0.1", "localhost", "::1"})
        loopback_probe = request.url.path in {
            "/health",
            "/ready",
        } and Settings.is_loopback_host(host)
        if not host or (host not in allowed and not loopback_probe):
            return self._reject(
                400,
                "invalid_host",
                "This local application rejected an unexpected Host header.",
                native_loopback=native_loopback,
            )

        host_is_personal_tailscale = bool(
            self.settings.access_mode == "local"
            and self.settings.personal_tailscale_enabled
            and self.settings.personal_tailscale_hostname == host
        )
        # Personal access intentionally has no PMT account. Tailscale Serve is
        # the private-network boundary, while PMT remains bound to loopback and
        # accepts only the exact ts.net hostname saved with its managed route.
        # Some current macOS/iOS Serve paths omit the optional identity headers,
        # so requiring one rejects legitimate private access without adding a
        # meaningful boundary to this loopback-only proxy path.
        if host_is_personal_tailscale and not _is_tailscale_proxy_client(client_host):
            return self._reject(
                403,
                "tailscale_proxy_required",
                "Personal access must arrive through this computer's private Tailscale Serve route.",
                native_loopback=native_loopback,
            )

        authorization = request.headers.get("authorization", "")
        bearer_token = (
            authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        )
        native_public_path = request.url.path in {
            "/api/v1/setup/bootstrap",
            "/api/v1/auth/invitations/redeem",
            "/api/v1/auth/device/login",
            "/api/v1/auth/device/refresh",
            "/api/v1/auth/browser/adopt",
            "/api/v1/setup/local-host-recovery",
        }

        if request.method in MUTATING_METHODS:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if (
                self.settings.access_mode == "server"
                and not bearer_token
                and not native_public_path
            ):
                valid_origin = origin == self.settings.public_origin or bool(
                    native_loopback and origin and _same_origin(origin, request, self.settings)
                )
                if not origin or not valid_origin:
                    return self._reject(
                        403,
                        "foreign_origin",
                        "This server rejected a request from an untrusted origin.",
                        native_loopback=native_loopback,
                    )
            elif origin and not _same_origin(origin, request, self.settings):
                return self._reject(
                    403,
                    "foreign_origin",
                    "This local application rejected a request from another site.",
                    native_loopback=native_loopback,
                )
            if not origin and referer and not _same_origin(referer, request, self.settings):
                return self._reject(
                    403,
                    "foreign_origin",
                    "This local application rejected a request from another site.",
                    native_loopback=native_loopback,
                )

        if self.settings.access_mode == "local":
            with request.app.state.session_factory() as session:
                request.state.principal = local_principal(session)

        if self.settings.access_mode == "server":
            public_path = request.url.path in {
                "/",
                "/health",
                "/ready",
                "/api/auth/status",
                "/api/auth/login",
                "/api/v1/setup/status",
                "/api/v1/setup/bootstrap",
                "/api/v1/server/capabilities",
                "/api/v1/auth/invitations/redeem",
                "/api/v1/auth/device/login",
                "/api/v1/auth/device/refresh",
                "/api/v1/auth/browser/adopt",
                "/api/v1/setup/local-host-recovery",
                "/feeds/upcoming.ics",
            } or request.url.path.startswith("/static/")
            forwarded_proto = (
                request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
            )
            secure_request = (
                request.url.scheme == "https"
                or native_loopback
                or (
                    client_host in self.settings.trusted_proxy_values
                    and forwarded_proto == "https"
                )
            )
            if not secure_request and request.url.path not in {"/health", "/ready"}:
                return self._reject(
                    426,
                    "https_required",
                    "Shared access requires HTTPS.",
                    native_loopback=native_loopback,
                )

            auth_record = None
            if not public_path:
                auth_record = (
                    request.app.state.auth.authenticate(bearer_token, kind="native")
                    if bearer_token
                    else request.app.state.auth.authenticate(
                        request.cookies.get(SESSION_COOKIE), kind="browser"
                    )
                )
                if auth_record is None:
                    return self._reject(
                        401,
                        "authentication_required",
                        "Sign in to continue.",
                        native_loopback=native_loopback,
                    )
                request.state.user_session = auth_record
                request.state.owner_session = auth_record
                with request.app.state.session_factory() as session:
                    principal = principal_for_user(
                        session,
                        auth_record.user_id,
                        authentication_method=(
                            "device_token"
                            if auth_record.session_kind == "native"
                            else "password"
                        ),
                        session_id=auth_record.id,
                    )
                if principal is None:
                    return self._reject(
                        401,
                        "authentication_required",
                        "This account is not active.",
                        native_loopback=native_loopback,
                    )
                request.state.principal = principal
            if (
                request.method in MUTATING_METHODS
                and not public_path
                and auth_record is not None
                and auth_record.session_kind == "browser"
            ):
                header_token = request.headers.get("x-csrf-token")
                cookie_token = request.cookies.get(CSRF_COOKIE)
                if (
                    not header_token
                    or not cookie_token
                    or header_token != cookie_token
                    or not request.app.state.auth.valid_csrf(auth_record, header_token)
                ):
                    return self._reject(
                        403,
                        "csrf_failed",
                        "Refresh the page and try again.",
                        native_loopback=native_loopback,
                    )

        response = await call_next(request)
        return self._headers(response, native_loopback=native_loopback)
