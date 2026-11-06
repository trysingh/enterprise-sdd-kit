"""Day-0 seam "principal": who is calling. A seam with a dummy implementation, not a control.

`get_principal` is the only way a route learns who is calling. `DevUserProvider` reads fixed users
from `config/dev-users.yaml`: HTTP Basic for the API (works in Postman and in journeys) and a
signed session cookie for pages (see `app.web.signin`). It refuses to exist unless APP_ENV is dev or
test. A later wave replaces it with the OIDC provider; business code keeps calling `get_principal`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Request

from app.core.errors import Unauthorized
from app.core.settings import Settings, get_settings

SESSION_COOKIE = "dev_session"
DEV_ENVS = frozenset({"dev", "test"})
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Principal:
    id: str
    display: str
    roles: tuple[str, ...] = ()


class DevUserProvider:
    def __init__(self, users_file: str, env: str) -> None:
        if env not in DEV_ENVS:
            raise RuntimeError(f"DevUserProvider is for dev/test only and is refused when APP_ENV={env}")
        path = Path(users_file)
        data: dict[str, Any] = yaml.safe_load((path if path.is_absolute() else ROOT / path).read_text("utf-8")) or {}
        self._users: dict[str, dict[str, Any]] = dict(data.get("users") or {})
        self._key = secrets.token_bytes(32)  # sessions die with the process; fine for a dev seam

    def _principal(self, name: str) -> Principal:
        u = self._users[name]
        return Principal(name, str(u.get("display") or name), tuple(u.get("roles") or ()))

    def verify(self, name: str, password: str) -> Principal | None:
        u = self._users.get(name)
        if u is None or not hmac.compare_digest(str(u.get("password", "")).encode(), password.encode()):
            return None
        return self._principal(name)

    def issue_session(self, name: str) -> str:
        return f"{name}.{hmac.new(self._key, name.encode(), hashlib.sha256).hexdigest()}"

    def from_session(self, token: str) -> Principal | None:
        name, _, sig = token.rpartition(".")
        good = hmac.new(self._key, name.encode(), hashlib.sha256).hexdigest()
        return self._principal(name) if name in self._users and hmac.compare_digest(sig, good) else None

    def authenticate(self, request: Request) -> Principal | None:
        scheme, _, value = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "basic" and value:
            try:
                name, _, password = base64.b64decode(value).decode("utf-8").partition(":")
            except (binascii.Error, UnicodeDecodeError):
                return None
            return self.verify(name, password)
        token = request.cookies.get(SESSION_COOKIE)
        return self.from_session(token) if token else None


@lru_cache(maxsize=4)
def dev_provider(users_file: str, env: str) -> DevUserProvider:
    return DevUserProvider(users_file, env)


def get_principal(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Principal:
    if settings.principal_provider == "dev-users":
        found = dev_provider(settings.dev_users_file, settings.env).authenticate(request)
    else:  # "oidc": the bearer-JWT path of app.core.security, mapped to a Principal
        from app.core.security import current_user

        user = current_user(request, settings)
        found = Principal(user.subject, user.name or user.subject, ("user",))
    if found is None:
        raise Unauthorized("Sign in (HTTP Basic with a dev user, or the /signin page)")
    request.state.principal = found
    return found


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
