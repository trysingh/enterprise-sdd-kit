"""Application factory (golden core). Wires settings, logging, errors, middleware and routers.

Feature routers are not added here: list them in `app.features.registry`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import API_PREFIX, health
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.http import close_http
from app.core.logging import configure_logging
from app.core.middleware import install_middleware
from app.core.settings import Settings, get_settings
from app.features import registry
from app.web import STATIC_DIR, pages


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_http()  # REL-03: release pools on graceful shutdown
    dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title=settings.app_name,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    install_middleware(app, settings)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(health.router)
    app.include_router(pages.router)
    if settings.reference_slice_mounted:
        from app.features.f000_reference import api as reference_api
        from app.features.f000_reference import web as reference_web

        app.include_router(reference_api.router, prefix=API_PREFIX)
        app.include_router(reference_web.router)
    for router in registry.api_routers(settings):
        app.include_router(router, prefix=API_PREFIX)
    for router in registry.web_routers(settings):
        app.include_router(router)

    if settings.otel_enabled:  # OBS-04: exporter configured through OTEL_* environment variables
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
