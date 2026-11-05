"""Server-rendered pages (frontend/jinja profile): one template engine, CSRF on unsafe methods.

Feature pages are routers created with `web_router()` so they get CSRF protection by default, and
render with `render(request, "features/<slug>/page.html", {...})`.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.errors import Forbidden
from app.core.i18n import t
from app.core.middleware import CSRF_HEADER

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))  # autoescape on for .html (SEC-07)
templates.env.globals["t"] = t

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def require_csrf(request: Request) -> None:
    if request.method not in UNSAFE:
        return
    expected = getattr(request.state, "csrf_token", None)
    sent = request.headers.get(CSRF_HEADER)
    if sent is None and "form" in request.headers.get("content-type", ""):
        sent = str((await request.form()).get("csrf_token") or "")
    # `expected` is the cookie value (or a fresh token when there is no cookie, which nothing can match).
    if not expected or not sent or not secrets.compare_digest(sent, expected):
        raise Forbidden("CSRF token missing or invalid")


def web_router(**kwargs: Any) -> APIRouter:
    deps = list(kwargs.pop("dependencies", []))
    return APIRouter(
        dependencies=[Depends(require_csrf), *deps], default_response_class=HTMLResponse, **kwargs
    )


def render(
    request: Request, template: str, context: dict[str, Any] | None = None, status_code: int = 200
) -> HTMLResponse:
    ctx = {"csrf_token": getattr(request.state, "csrf_token", ""), **(context or {})}
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
