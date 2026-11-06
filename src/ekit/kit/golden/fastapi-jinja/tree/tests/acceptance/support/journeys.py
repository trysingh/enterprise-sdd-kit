"""Test-only call recording for journeys (golden core, frozen). Never imported by application code.

During a pytest run, `JourneyRecorder` (pure ASGI middleware, added to the app by the `app` fixture)
records every call made while a scenario tagged `@J-nn` runs: operation id, method, route, dev user,
status. At the end of the run `write_reports` writes:

  reports/journeys.json   {"version": 1, "journeys": [...], "calls": [...]}   (read by `ekit gate smoke`)
  reports/openapi.json    the app's OpenAPI document                          (operation ids to check)

Scenario tags become pytest markers, so `@J-01 @FEAT-01` are read from `item.iter_markers()`.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

JOURNEY_TAG = re.compile(r"^J-\d{2,3}$")
FEATURE_TAG = re.compile(r"^FEAT-\d{2}$")
SESSION_COOKIE = re.compile(r"dev_session=([^;]+)")


@dataclass
class Recorder:
    calls: list[dict[str, Any]] = field(default_factory=list)
    journeys: dict[str, dict[str, Any]] = field(default_factory=dict)
    current: str | None = None  # node id of the running journey scenario

    def begin(self, item: Any) -> None:
        names = [m.name for m in item.iter_markers()]
        jid = next((n for n in names if JOURNEY_TAG.match(n)), None)
        self.current = item.nodeid if jid else None
        if jid:
            self.journeys[item.nodeid] = {
                "id": jid,
                "scenario": item.name,
                "features": sorted({n for n in names if FEATURE_TAG.match(n)}),
                "outcome": "unknown",
            }

    def finish(self, item: Any, outcome: str) -> None:
        j = self.journeys.get(item.nodeid)
        if j is not None and (outcome != "passed" or j["outcome"] == "unknown"):
            j["outcome"] = outcome

    def end(self) -> None:
        self.current = None

    def add(self, **call: Any) -> None:
        if self.current is not None:
            self.calls.append({"journey": self.journeys[self.current]["id"], **call})


RECORDER = Recorder()


def _principal(scope: Scope) -> str | None:
    headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            return base64.b64decode(auth[6:]).decode("utf-8").partition(":")[0]
        except ValueError:
            return None
    m = SESSION_COOKIE.search(headers.get("cookie", ""))
    return m.group(1).rpartition(".")[0] if m else None


def _route_of(scope: Scope) -> Any:
    route = scope.get("route")
    if route is not None:
        return route
    for cand in getattr(getattr(scope.get("app"), "router", None), "routes", []):
        match, _ = cand.matches(scope)
        if match == Match.FULL:
            return cand
    return None


class JourneyRecorder:
    def __init__(self, app: ASGIApp, recorder: Recorder = RECORDER) -> None:
        self.app, self.recorder = app, recorder

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = {"code": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = _route_of(scope)
            self.recorder.add(
                operation_id=(getattr(route, "operation_id", None) or getattr(route, "unique_id", None)),
                method=scope["method"],
                route=getattr(route, "path", None),
                path=scope["path"],
                principal=_principal(scope),
                status=status["code"],
            )


def install(app: FastAPI) -> FastAPI:
    app.add_middleware(JourneyRecorder)
    return app


def write_reports(app: FastAPI, reports: Path) -> None:
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "openapi.json").write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    doc = {
        "version": 1,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "journeys": list(RECORDER.journeys.values()),
        "calls": RECORDER.calls,
    }
    (reports / "journeys.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
