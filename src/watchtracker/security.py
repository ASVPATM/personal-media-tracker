from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from watchtracker.config import Settings
from watchtracker.services.auth import CSRF_COOKIE, SESSION_COOKIE

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://image.tmdb.org https://s4.anilist.co "
    "https://s3.anilist.co https://cdn.myanimelist.net; connect-src 'self'; "
    "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": None}},
    )


def _host_only(host: str) -> str:
    if host.startswith("["):
        return host.partition("]")[0].lstrip("[")
    return host.partition(":")[0]


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

    def _headers(self, response: Response) -> Response:
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        if self.settings.access_mode == "server":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    def _reject(self, status: int, code: str, message: str) -> Response:
        return self._headers(_error(status, code, message))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_host = request.headers.get("host", "")
        host = _host_only(supplied_host).casefold().strip("[]")
        allowed = {item.casefold().strip("[]") for item in self.settings.allowed_hosts}
        if not host or host not in allowed:
            return self._reject(
                400,
                "invalid_host",
                "This local application rejected an unexpected Host header.",
            )

        if request.method in MUTATING_METHODS:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if self.settings.access_mode == "server":
                valid_origin = origin == self.settings.public_origin
                if not origin or not valid_origin:
                    return self._reject(
                        403,
                        "foreign_origin",
                        "This server rejected a request from an untrusted origin.",
                    )
            elif origin and not _same_origin(origin, request, self.settings):
                return self._reject(
                    403,
                    "foreign_origin",
                    "This local application rejected a request from another site.",
                )
            if not origin and referer and not _same_origin(referer, request, self.settings):
                return self._reject(
                    403,
                    "foreign_origin",
                    "This local application rejected a request from another site.",
                )

        if self.settings.access_mode == "server":
            public_path = request.url.path in {
                "/",
                "/health",
                "/ready",
                "/api/auth/status",
                "/api/auth/login",
                "/feeds/upcoming.ics",
            } or request.url.path.startswith("/static/")
            client_host = request.client.host if request.client else ""
            forwarded_proto = (
                request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
            )
            secure_request = request.url.scheme == "https" or (
                client_host in self.settings.trusted_proxy_values and forwarded_proto == "https"
            )
            if not secure_request and request.url.path not in {"/health", "/ready"}:
                return self._reject(426, "https_required", "Shared access requires HTTPS.")

            auth_record = None
            if not public_path:
                auth_record = request.app.state.auth.authenticate(
                    request.cookies.get(SESSION_COOKIE)
                )
                if auth_record is None:
                    return self._reject(401, "authentication_required", "Sign in to continue.")
                request.state.owner_session = auth_record
            if request.method in MUTATING_METHODS and not public_path:
                header_token = request.headers.get("x-csrf-token")
                cookie_token = request.cookies.get(CSRF_COOKIE)
                if (
                    not header_token
                    or not cookie_token
                    or header_token != cookie_token
                    or not request.app.state.auth.valid_csrf(auth_record, header_token)
                ):
                    return self._reject(403, "csrf_failed", "Refresh the page and try again.")

        response = await call_next(request)
        return self._headers(response)
