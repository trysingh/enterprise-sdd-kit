"""ekit 0.7.0: golden fastapi-jinja 1.1.0 (Day-0 seams, generic API step library, call recording).

fastapi, pydantic-settings and pytest-bdd are not dependencies of ekit, so the golden application code is checked
statically (parse, step binding, frozen list, symbols) and its framework-free logic is executed against minimal stubs
of the framework modules. The golden tests themselves run in a generated project, not here."""
from __future__ import annotations

import asyncio
import ast
import base64
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

from ekit import golden, stepbind, stepscan
from ekit.project import Kit, bundled_kit_dir

G = golden.for_stack(Kit.load(bundled_kit_dir()), "fastapi-jinja")
TREE = G.tree

NOTE_JOURNEY = '''@J-01 @FEAT-01 @FEAT-02
Feature: Two colleagues exchange messages and a file
  Scenario Outline: <sender> writes to <receiver> and shares a file
    Given I am signed in as "<sender>"
    When I call "send_message" with peer "<receiver>" and body "<text>"
    Then the call succeeds
    And I remember "id" from the response as "msg"
    Given I am signed in as "<receiver>"
    When I call "list_unread"
    Then the response contains "<sender>" with count 1
    When I call "list_messages" with peer "<sender>"
    Then the response contains the remembered "msg"
    And the call to "list_unread" now shows "<sender>" with count 0
    Examples:
      | sender | receiver | text            |
      | asha   | ravi     | hello           |
      | ravi   | meera    | report attached |
'''


def test_revision_and_manifest():
    assert G.version == "1.1.2"
    seams = G.manifest["day0_seams"]
    assert set(seams) == {"principal", "audit", "request_id", "config", "data_owner"}
    for name, spec in seams.items():
        src = TREE / spec["file"]
        assert src.is_file(), name
        top = {n.name for n in ast.parse(src.read_text(encoding="utf-8")).body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
        assert set(spec["symbols"]) <= top, (name, set(spec["symbols"]) - top)
    for rel in ("src/app/core/principal.py", "src/app/core/audit.py", "src/app/core/requestid.py", "src/app/core/ownership.py",
                "src/app/web/signin.py", "src/app/templates/signin.html", "tests/acceptance/api_steps.py",
                "tests/acceptance/support/journeys.py", "tests/unit/test_core_seams.py", "tests/acceptance/test_000_signin.py",
                ".gitleaks.toml"):
        target = {v: k for k, v in G.manifest["rename"].items()}.get(rel, rel)
        assert (TREE / target).is_file(), rel
        assert golden.matches(rel, G.frozen), rel
    assert not golden.matches("tests/acceptance/journeys/test_journeys.py", G.frozen)     # people add journeys here
    assert not golden.matches("config/dev-users.yaml", G.frozen)                            # and dev users


def test_dev_users_file_follows_the_dev_convention():
    text = (TREE / "config/dev-users.yaml").read_text(encoding="utf-8")
    assert text.startswith("# DEV ONLY. Refused at startup when APP_ENV is not dev|test.")
    users = yaml.safe_load(text)["users"]
    assert {"asha", "ravi", "admin"} <= set(users)
    assert all(u["password"].endswith("-dev") for u in users.values())
    assert "config/dev-users" in (TREE / "dot_gitleaks.toml").read_text(encoding="utf-8")
    assert "config" not in "".join(l for l in (TREE / "Dockerfile").read_text().splitlines() if l.startswith("COPY"))   # never in the image


def test_settings_and_wiring_mention_the_seams():
    settings = (TREE / "src/app/core/settings.py").read_text(encoding="utf-8")
    assert 'principal_provider: Literal["dev-users", "oidc"]' in settings and "dev_users_file" in settings
    main = (TREE / "src/app/main.py").read_text(encoding="utf-8")
    assert "dev_provider(settings.dev_users_file, settings.env)" in main and "signin.router" in main
    assert "RequestIdMiddleware" in (TREE / "src/app/core/middleware.py").read_text(encoding="utf-8")
    assert "operation_id=\"health_live\"" in (TREE / "src/app/api/health.py").read_text(encoding="utf-8")


def test_new_python_parses_and_has_no_empty_steps():
    for rel in ("src/app/core/principal.py", "src/app/core/audit.py", "src/app/core/requestid.py", "src/app/core/ownership.py",
                "src/app/web/signin.py", "tests/acceptance/api_steps.py", "tests/acceptance/support/journeys.py",
                "tests/acceptance/conftest.py", "tests/acceptance/journeys/test_journeys.py", "tests/unit/test_core_seams.py"):
        src = (TREE / rel).read_text(encoding="utf-8")
        ast.parse(src, rel)
        res = stepscan.scan_source(src)
        assert not res.steps and not res.abs_paths and not res.fault_steps, (rel, res)


def _defs():
    module = TREE / "tests/acceptance/journeys/test_journeys.py"
    defs, dynamic = stepbind.visible_definitions(module, TREE, {})
    assert dynamic == 0
    return defs


def test_the_design_notes_example_journey_is_fully_bound_by_the_generic_library():
    unbound = stepbind.unbound(stepbind.feature_steps(NOTE_JOURNEY), _defs())
    assert unbound == [], [(s.keyword, s.text) for s in unbound]


def test_generic_step_patterns_do_not_shadow_each_other():
    defs = _defs()
    samples = ['I am signed in as "asha"', 'I call "list_unread"', 'I call "send_message" with peer "ravi" and body "hi"',
               'I open the page "/chat/ravi"', "the call succeeds", 'I remember "id" from the response as "msg"',
               'the response contains "x"', 'the response contains the remembered "msg"', 'the response contains "x" with count 1',
               "the response has at least 2 items", 'the call to "list_unread" now shows "asha" with count 0',
               'I GET "/x"', 'I GET "/x" with header "A" set to "b"', "the response status is 200", 'the page contains "x"']
    for text in samples:
        hits = [d for d in defs if d.pattern is not None and d.pattern.fullmatch(text)]
        assert len(hits) == 1, (text, [d.source for d in hits])


# ---------------------------------------------------------------- run the framework-free logic against stubs
@pytest.fixture
def stubs(monkeypatch):
    pytest.importorskip("starlette")
    from starlette.requests import Request
    from starlette.responses import Response

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
        return m

    class _Log:
        def info(self, *a, **k):
            pass

    mod("fastapi", Depends=lambda x=None: x, Request=Request, Response=Response, FastAPI=object)
    mod("structlog", get_logger=lambda *a: _Log(), contextvars=types.SimpleNamespace(bind_contextvars=lambda **k: None))
    mod("app")
    mod("app.core")

    class Unauthorized(Exception):
        pass

    mod("app.core.errors", Unauthorized=Unauthorized)
    mod("app.core.settings", Settings=object, get_settings=lambda: None)
    mod("fastapi.testclient", TestClient=object)
    mod("pytest_bdd", given=lambda *a: (lambda f: f), when=lambda *a: (lambda f: f), then=lambda *a: (lambda f: f),
        parsers=types.SimpleNamespace(re=lambda p: p))

    class Ctx:
        def __init__(self):
            self.values, self.response, self.sent = {}, None, []
            self.http = types.SimpleNamespace(request=lambda *a, **k: self.sent.append((a, k)) or "R")

        def remember(self, k, v):
            self.values[k] = v

        def recall(self, k):
            return self.values[k]
    mod("tests")
    mod("tests.acceptance")
    mod("tests.acceptance.support", ScenarioContext=Ctx)
    mod("tests.acceptance.support.paths", REPO_ROOT=TREE)

    def load(name, rel):
        spec = importlib.util.spec_from_file_location(name, TREE / rel)
        m = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, m)
        spec.loader.exec_module(m)
        return m
    return types.SimpleNamespace(load=load, Request=Request, Ctx=Ctx, Unauthorized=Unauthorized)


def _request(stubs, headers):
    return stubs.Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def test_dev_user_provider_logic(stubs):
    principal = stubs.load("app.core.principal", "src/app/core/principal.py")
    principal.ROOT = TREE
    with pytest.raises(RuntimeError, match="dev/test only"):
        principal.DevUserProvider("config/dev-users.yaml", "prod")
    p = principal.DevUserProvider("config/dev-users.yaml", "test")
    basic = lambda u, pw: "Basic " + base64.b64encode(f"{u}:{pw}".encode()).decode()      # noqa: E731
    who = p.authenticate(_request(stubs, {"Authorization": basic("asha", "asha-dev")}))
    assert who == principal.Principal("asha", "Asha", ("user",))
    assert p.authenticate(_request(stubs, {"Authorization": basic("asha", "wrong")})) is None
    assert p.authenticate(_request(stubs, {"Authorization": "Basic !!!"})) is None
    assert p.authenticate(_request(stubs, {})) is None
    token = p.issue_session("ravi")
    assert p.authenticate(_request(stubs, {"Cookie": f"dev_session={token}"})).id == "ravi"
    assert p.authenticate(_request(stubs, {"Cookie": "dev_session=admin." + token.rpartition(".")[2]})) is None


def test_audit_and_request_id_logic(stubs):
    audit = stubs.load("app.core.audit", "src/app/core/audit.py")
    sink = audit.InMemoryAuditSink()
    sink.record("asha", "send", "message:1", {"to": "ravi"})
    audit.LogAuditSink().record("asha", "send", "message:1")
    assert sink.events == [("asha", "send", "message:1", {"to": "ravi"})]
    rid = stubs.load("app.core.requestid", "src/app/core/requestid.py")
    assert rid.request_id_for(_request(stubs, {"X-Request-Id": "req-12345678"})) == "req-12345678"
    assert len(rid.request_id_for(_request(stubs, {"X-Request-Id": "bad id"}))) == 32


def test_api_step_library_helpers(stubs):
    steps = stubs.load("api_steps", "tests/acceptance/api_steps.py")
    ctx = stubs.Ctx()
    ctx.remember("msg", 7)
    assert steps.parse_args(ctx, 'peer "ravi" and body "hi there" and limit 5 and id "{msg}"') == {
        "peer": "ravi", "body": "hi there", "limit": 5, "id": 7}
    assert steps.parse_args(ctx, None) == {}
    data = {"unread": [{"from": "asha", "count": 1}, {"from": "meera", "count": 0}], "ravi": 2}
    assert steps.shows(data, "asha", "count", "1") and not steps.shows(data, "asha", "count", "0")
    assert steps.shows(data, "meera", "count", "0") and steps.shows(data, "ravi", "count", "2")      # {"name": n} form

    spec = {"paths": {"/api/v1/messages/{peer}": {"get": {"operationId": "list_messages", "parameters": [
                {"name": "peer", "in": "path"}, {"name": "limit", "in": "query"}]}},
            "/api/v1/messages": {"post": {"operationId": "send_message", "requestBody": {}}}}}
    app = types.SimpleNamespace(openapi=lambda: spec)
    steps.call_operation(ctx, app, "list_messages", {"peer": "a b", "limit": 3})
    assert ctx.sent[-1] == (("GET", "/api/v1/messages/a%20b"), {"params": {"limit": 3}, "json": None})
    steps.call_operation(ctx, app, "send_message", {"peer": "ravi", "body": "hi"})
    assert ctx.sent[-1] == (("POST", "/api/v1/messages"), {"params": None, "json": {"peer": "ravi", "body": "hi"}})
    with pytest.raises(AssertionError, match="needs the path parameter"):
        steps.call_operation(ctx, app, "list_messages", {})
    with pytest.raises(AssertionError, match="no operation"):
        steps.call_operation(ctx, app, "nope", {})
    with pytest.raises(AssertionError, match="takes no argument"):
        steps.call_operation(ctx, app, "list_messages", {"peer": "x", "extra": 1})


def test_call_recorder_writes_the_report_the_smoke_gate_reads(stubs, tmp_path):
    j = stubs.load("tests_journeys", "tests/acceptance/support/journeys.py")
    rec = j.Recorder()

    class Item:
        def __init__(self, tags):
            self.nodeid, self.name, self._t = "t::a" + "".join(tags), "scenario", tags

        def iter_markers(self):
            return [types.SimpleNamespace(name=t) for t in self._t]

    class Route:
        path, operation_id, unique_id = "/api/v1/m", "send_message", "u"

    async def app(scope, receive, send):
        scope["route"] = Route()
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def call(item, headers):
        async def send(_): pass
        await j.JourneyRecorder(app, rec)({"type": "http", "method": "POST", "path": "/api/v1/m", "headers": headers}, None, send)

    basic = "Basic " + base64.b64encode(b"asha:asha-dev").decode()
    outside = Item(["SCN-1"])
    rec.begin(outside)
    asyncio.run(call(outside, []))                                   # not a journey: nothing recorded
    item = Item(["J-01", "FEAT-01", "SCN-2"])
    rec.begin(item)
    asyncio.run(call(item, [(b"authorization", basic.encode())]))
    rec.finish(item, "passed")
    rec.end()
    assert rec.calls == [{"journey": "J-01", "operation_id": "send_message", "method": "POST", "route": "/api/v1/m",
                          "path": "/api/v1/m", "principal": "asha", "status": 201}]
    assert list(rec.journeys.values()) == [{"id": "J-01", "scenario": "scenario", "features": ["FEAT-01"], "outcome": "passed"}]
    j.RECORDER.calls, j.RECORDER.journeys = rec.calls, rec.journeys
    app_obj = types.SimpleNamespace(openapi=lambda: {"paths": {}})
    j.write_reports(app_obj, tmp_path / "reports")
    import json
    from ekit import smoke
    doc = json.loads((tmp_path / "reports/journeys.json").read_text())
    assert doc["version"] == 1 and doc["calls"][0]["status"] == 201 and (tmp_path / "reports/openapi.json").is_file()
    assert smoke.read_json(tmp_path / "reports/journeys.json", "x")["journeys"][0]["outcome"] == "passed"
