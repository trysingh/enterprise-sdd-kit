"""OBS-03: liveness and readiness. Readiness checks the database connection."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import get_engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return JSONResponse({"status": "unavailable", "checks": {"database": "down"}}, status_code=503)
    return JSONResponse({"status": "ok", "checks": {"database": "up"}})
