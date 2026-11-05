from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Greeting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
