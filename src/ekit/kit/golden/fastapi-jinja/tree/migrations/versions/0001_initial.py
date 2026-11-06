"""Initial (empty) revision: the chain every slice's revision hangs from (golden core, frozen).

Convention (DATA-01): ONE revision per slice, in this directory, created when the slice adds or changes tables:

    uv run alembic revision --rev-id 0002 -m "S0 vehicles and bookings"      # then fill upgrade()/downgrade()

Name it `<rev-id>_<slice>_<what>.py`, make `down_revision` the previous revision (alembic does this), keep
models on `app.core.db.Base`, and add the `owner_id` column to every owned table. Tests do not run migrations:
the `db_schema` fixture (tests/conftest.py) creates the schema from `Base.metadata` in a temp SQLite file.
"""
from __future__ import annotations

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing yet: the golden core has no tables of its own."""


def downgrade() -> None:
    """Nothing to undo."""
