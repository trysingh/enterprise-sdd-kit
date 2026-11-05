"""SEC-01 authentication against the enterprise IdP (OIDC bearer JWT); SEC-02 building blocks.

`current_user` is the only way a route learns who is calling. In `auth_mode=dev` (never allowed in
prod, see settings) it returns a fixed developer identity so local work and tests need no IdP.
Authorisation per route: `Depends(require("scope:action"))`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request

from app.core.errors import Forbidden, Unauthorized
from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class User:
    subject: str
    name: str = ""
    permissions: frozenset[str] = field(default_factory=frozenset)


DEV_USER = User(subject="dev-user", name="Developer", permissions=frozenset({"*"}))


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, timeout=5)


def _decode(token: str, settings: Settings) -> dict[str, Any]:
    assert settings.oidc_jwks_url and settings.oidc_audience and settings.oidc_issuer
    key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token).key
    claims: dict[str, Any] = jwt.decode(
        token,
        key,
        algorithms=["RS256", "ES256"],
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
    )
    return claims


def current_user(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> User:
    if settings.auth_mode == "dev":
        return DEV_USER
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("A bearer token is required")
    try:
        claims = _decode(token, settings)
    except jwt.PyJWTError as exc:
        raise Unauthorized("The token is not valid") from exc
    perms = claims.get("permissions") or str(claims.get("scope", "")).split()
    return User(subject=str(claims["sub"]), name=str(claims.get("name", "")), permissions=frozenset(perms))


CurrentUser = Annotated[User, Depends(current_user)]


def require(permission: str) -> Callable[[User], User]:
    """Route dependency: `Depends(require("chat:send"))`. Deny unless the caller holds the permission."""

    def _check(user: CurrentUser) -> User:
        if "*" not in user.permissions and permission not in user.permissions:
            raise Forbidden(f"Missing permission {permission}")
        return user

    return _check
