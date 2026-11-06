"""Day-0 seam "data_owner": every feature table has an owner or participant column named `owner_id`.

Add `OwnedMixin` to a model (or a second participant column such as `recipient_id`, documented in
design.yaml). Nothing filters on it yet; row-level authorization policies use it in a later wave.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

OWNER_COLUMN = "owner_id"


class OwnedMixin:
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
