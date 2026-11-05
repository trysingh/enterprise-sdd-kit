"""OBS-02 correlation ids, SEC-06 security headers and CORS, SEC-08 CSRF token cookie.

Registered once in `app.main.create_app`. Feature code never adds global middleware here; a
feature that needs one documents why in an ADR and a person changes the core (`ekit baseline unfreeze`).
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.settings import Settings

CORRELATION_HEADER = "X-Correlation-ID"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

Handler = Callable[[Request], Awaitable[Response]]


def correlation_id_for(request: Request) -> str:
    given = request.headers.get(CORRELATION_HEADER, "")
    if _SAFE_ID.match(given):
        return given
    m = _TRACEPARENT.match(request.headers.get("traceparent", ""))
    return m.group(1) if m else uuid.uuid4().hex


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        cid = correlation_id_for(request)
        request.state.correlation_id = cid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=cid, path=request.url.path, method=request.method
        )
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = cid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, hsts: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if self.hsts:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response


class CsrfCookieMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF: every response carries a token cookie; templates render it into forms and
    `app.web.require_csrf` checks it on unsafe methods of cookie-authenticated (web) routes."""

    def __init__(self, app: object, *, cookie_name: str, secure: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.cookie_name, self.secure = cookie_name, secure

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        token = request.cookies.get(self.cookie_name) or secrets.token_urlsafe(32)
        request.state.csrf_token = token
        response = await call_next(request)
        if request.cookies.get(self.cookie_name) != token:
            response.set_cookie(
                self.cookie_name, token, httponly=False, secure=self.secure, samesite="strict"
            )
        return response


def install_middleware(app: FastAPI, settings: Settings) -> None:
    # Starlette runs the last-added middleware first: correlation must wrap everything else.
    app.add_middleware(
        CsrfCookieMiddleware, cookie_name=settings.csrf_cookie_name, secure=settings.session_cookie_secure
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.env == "prod")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", CORRELATION_HEADER, CSRF_HEADER],
    )
    app.add_middleware(CorrelationMiddleware)
