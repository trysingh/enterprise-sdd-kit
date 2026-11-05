"""DATA-01 data access: one SQLAlchemy engine with pool timeouts; schema changes only via Alembic."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base for every feature's models (import it, never declare another)."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    s = get_settings()
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if s.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_timeout"] = s.db_pool_timeout_seconds
    return create_engine(s.database_url, **kwargs)  # type: ignore[arg-type]


def get_session() -> Iterator[Session]:
    """Route dependency: one session per request, committed by the service that owns the transaction."""
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        yield session


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
