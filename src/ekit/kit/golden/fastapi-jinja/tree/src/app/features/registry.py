"""Seam: the one place feature routers are registered. Editable (not frozen).

Add one import and one list entry per feature, e.g.:

    from app.features.f003_conversation_history import api as conversation_history_api
    ...
        conversation_history_api.router,
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.settings import Settings


def api_routers(settings: Settings) -> list[APIRouter]:
    """JSON routers, mounted under /api/v1."""
    return []


def web_routers(settings: Settings) -> list[APIRouter]:
    """Page routers built with `app.web.web_router()`."""
    return []
