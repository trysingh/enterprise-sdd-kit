"""The landing page. Feature pages live in their own packages."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from app.web import render, web_router

router = web_router(tags=["pages"])


@router.get("/")
def home(request: Request) -> HTMLResponse:
    return render(request, "home.html")
