"""A feature's own settings: its own BaseSettings class and env prefix, never the core Settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReferenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_REFERENCE_", env_file=".env", extra="ignore", frozen=True
    )

    greeting_word: str = Field(default="Hello", min_length=1, max_length=20)


@lru_cache(maxsize=1)
def get_reference_settings() -> ReferenceSettings:
    return ReferenceSettings()
