"""Test-wide settings and the database fixtures (golden core). Tests never talk to real infrastructure."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# A temp SQLite *file* (not `sqlite://`: an in-memory database is a new, empty database per connection).
_DB_DIR = Path(tempfile.mkdtemp(prefix="app-test-db-"))
atexit.register(shutil.rmtree, _DB_DIR, ignore_errors=True)

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DATABASE_URL", f"sqlite:///{(_DB_DIR / 'test.db').as_posix()}")
os.environ.setdefault("APP_AUTH_MODE", "dev")
os.environ.setdefault("APP_LOG_JSON", "false")
os.environ.setdefault("APP_SESSION_COOKIE_SECURE", "false")


@pytest.fixture(scope="session")
def db_schema() -> Iterator[None]:
    """Create every table of `Base.metadata` once per run (migrations are for deployments, not for tests).

    Feature models register on `Base` when their package is imported; the feature registry imports them.
    """
    from app.core.db import Base, dispose_engine, get_engine

    import app.features.registry  # noqa: F401  (imports the registered features, hence their models)

    Base.metadata.create_all(get_engine())
    yield
    dispose_engine()


@pytest.fixture
def db_session(db_schema: None) -> Iterator[Any]:
    """A session on the temp database; rolled back at the end of the test."""
    from sqlalchemy.orm import sessionmaker

    from app.core.db import get_engine

    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        yield session
        session.rollback()
