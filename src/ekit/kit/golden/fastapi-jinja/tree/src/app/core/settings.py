"""CFG-01: typed, twelve-factor settings. Read once at startup; a missing or invalid value fails fast.

Every value comes from the environment (prefix APP_) or a git-ignored `.env`. Nothing else in the
application reads `os.environ`. A feature that needs its own settings declares its own
`BaseSettings` class with its own prefix in its package (see the reference slice).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore", frozen=True)

    app_name: str = "__PROJECT_NAME__"
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # Data (DATA-01)
    database_url: str = "sqlite:///./app.db"
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0)

    # Outbound HTTP (REL-01)
    http_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    http_read_timeout_seconds: float = Field(default=5.0, gt=0)

    # Authentication (SEC-01). "oidc" validates bearer JWTs against the enterprise IdP.
    # "dev" accepts a fixed developer identity and is refused when env == "prod".
    auth_mode: Literal["oidc", "dev"] = "dev"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    # Browser security (SEC-06, SEC-08)
    cors_origins: list[str] = Field(default_factory=list)
    csrf_cookie_name: str = "csrftoken"
    session_cookie_secure: bool = True

    # Observability (OBS-04)
    otel_enabled: bool = False

    # The reference slice (app.features.f000_reference) is mounted outside production only.
    reference_slice_enabled: bool = True

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.env == "prod":
            if self.auth_mode != "oidc":
                raise ValueError("APP_AUTH_MODE must be 'oidc' when APP_ENV=prod")
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError(
                    "APP_OIDC_ISSUER, APP_OIDC_AUDIENCE and APP_OIDC_JWKS_URL are required in prod"
                )
        return self

    @property
    def reference_slice_mounted(self) -> bool:
        return self.reference_slice_enabled and self.env != "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
