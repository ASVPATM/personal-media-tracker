from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from watchtracker.config import Settings

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_host = request.headers.get("host", "")
        host = _host_only(supplied_host).casefold().strip("[]")
        allowed = {item.casefold().strip("[]") for item in self.settings.allowed_hosts}
        if not host or host not in allowed:
            return _error(
                400,
                "invalid_host",
                "This local application rejected an unexpected Host header.",
            )

        if request.method in MUTATING_METHODS:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if origin and not _same_origin(origin, request, self.settings):
                return _error(
                    403,
                    "foreign_origin",
                    "This local application rejected a request from another site.",
                )
            if not origin and referer and not _same_origin(referer, request, self.settings):
                return _error(
                    403,
                    "foreign_origin",
                    "This local application rejected a request from another site.",
                )

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://image.tmdb.org https://s4.anilist.co "
            "https://s3.anilist.co https://cdn.myanimelist.net; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        return response
