from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def test_prod_refuses_dev_authentication() -> None:
    with pytest.raises(ValidationError, match="APP_AUTH_MODE"):
        Settings(env="prod", auth_mode="dev")


def test_prod_requires_the_identity_provider() -> None:
    with pytest.raises(ValidationError, match="APP_OIDC"):
        Settings(env="prod", auth_mode="oidc")


def test_reference_slice_is_never_mounted_in_prod() -> None:
    s = Settings(
        env="prod", auth_mode="oidc", oidc_issuer="i", oidc_audience="a", oidc_jwks_url="https://idp/jwks"
    )
    assert s.reference_slice_mounted is False
    assert Settings(env="test").reference_slice_mounted is True
