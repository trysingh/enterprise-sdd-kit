"""Typed per-scenario state for pytest-bdd steps.

Why this exists (ekit 0.2.2, found on a real project): a step read `scenario_state["ids"]`, a key
no step in *that* scenario ever set. pytest-bdd reported the resulting KeyError exactly like a
genuine assertion failure, so red froze a broken test. Here, state lives on one object per
scenario; reading a value the scenario never set raises `MissingScenarioStateError`, which
`RED-CLEAN-FAILURE` rejects with a precise message instead of freezing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi.testclient import TestClient


class MissingScenarioStateError(LookupError):
    """A step read state that no earlier step of THIS scenario set. Broken test glue, not a red."""


_UNSET = object()


@dataclass
class ScenarioContext:
    """One instance per scenario (the `ctx` fixture). Never shared across scenarios."""

    client: TestClient | None = None
    response: httpx.Response | None = None
    _values: dict[str, Any] = field(default_factory=dict)

    @property
    def http(self) -> TestClient:
        if self.client is None:
            raise MissingScenarioStateError(
                "no client: this scenario (or its Background) needs the step "
                "'Given the application is running'"
            )
        return self.client

    @property
    def last_response(self) -> httpx.Response:
        if self.response is None:
            raise MissingScenarioStateError(
                "no response yet: a When step of this scenario must call the system and set ctx.response"
            )
        return self.response

    def remember(self, key: str, value: Any) -> None:
        self._values[key] = value

    def recall(self, key: str, default: Any = _UNSET) -> Any:
        if key in self._values:
            return self._values[key]
        if default is not _UNSET:
            return default
        known = ", ".join(sorted(self._values)) or "nothing"
        raise MissingScenarioStateError(
            f"'{key}' was never set in this scenario (it has: {known}). "
            f"A Given/When step of THIS scenario must "
            f"call ctx.remember('{key}', ...); steps never share state across scenarios."
        )
