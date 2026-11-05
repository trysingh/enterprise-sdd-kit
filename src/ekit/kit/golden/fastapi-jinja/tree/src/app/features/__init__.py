"""Feature packages: one per Spec Kit feature folder, named `f<NNN>_<slug>` (`ekit feature package`).

Layout of a feature package (see `f000_reference`, the reference slice):
    api.py        APIRouter for JSON routes (mounted under /api/v1 through registry.api_routers)
    web.py        `app.web.web_router()` for pages (through registry.web_routers)
    schemas.py    Pydantic request/response models, `extra="forbid"`
    service.py    use cases; pure functions or classes, no FastAPI imports
    models.py     SQLAlchemy models on `app.core.db.Base` (+ an Alembic revision in migrations/versions/)
    settings.py   the feature's own BaseSettings with its own env prefix, if it needs any
"""
