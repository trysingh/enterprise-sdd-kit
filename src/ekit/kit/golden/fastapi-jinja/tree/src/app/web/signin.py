"""Day-0 sign-in page for the dev-user seam: a minimal form that sets a session cookie.

Pages call `get_principal` like the API does; the cookie is only another way for `DevUserProvider`
to learn who is calling. Replaced together with the provider.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.errors import Unauthorized
from app.core.principal import SESSION_COOKIE, dev_provider
from app.core.settings import Settings, get_settings
from app.web import render, web_router

router = web_router(tags=["signin"])


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


@router.get("/signin", include_in_schema=False)
def signin_form(request: Request, next: str = "/") -> HTMLResponse:
    return render(request, "signin.html", {"next": _safe_next(next)})


@router.post("/signin", include_in_schema=False)
def signin(
    settings: Annotated[Settings, Depends(get_settings)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    provider = dev_provider(settings.dev_users_file, settings.env)
    if provider.verify(username, password) is None:
        raise Unauthorized("Unknown user or wrong password")
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(SESSION_COOKIE, provider.issue_session(username), httponly=True,
                        secure=settings.session_cookie_secure, samesite="strict")
    return response


@router.get("/signout", include_in_schema=False)
def signout() -> Response:
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
