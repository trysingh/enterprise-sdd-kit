from __future__ import annotations

from typing import Annotated

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse

from app.features.f000_reference.service import greet
from app.features.f000_reference.settings import get_reference_settings
from app.web import render, web_router

router = web_router(tags=["reference"])  # CSRF is checked on POST by web_router's dependency


def _page(request: Request, name: str) -> HTMLResponse:
    message = greet(name, get_reference_settings().greeting_word) if name.strip() else ""
    return render(request, "features/reference/greeting.html", {"message": message})


@router.get("/reference")
def greeting_page(request: Request, name: Annotated[str, Query(max_length=40)] = "") -> HTMLResponse:
    return _page(request, name)


@router.post("/reference")
def greeting_form(request: Request, name: Annotated[str, Form(max_length=40)]) -> HTMLResponse:
    return _page(request, name)
