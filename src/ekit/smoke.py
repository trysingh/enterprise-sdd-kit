"""Smoke gate (0.7.0): "can a user actually use the features we planned?", proved from files.

The journeys (Gherkin through the HTTP API) run once; the golden test harness writes
`reports/journeys.json` (every call made during a journey) and `reports/openapi.json`. The checks
below only read those two files and `docs/design/design.yaml`, so they are deterministic and testable
without running an app. Non-golden stacks produce the same two files with their own harness.

journeys.json:
  {"version": 1, "journeys": [{"id": "J-01", "scenario": "...", "features": ["FEAT-01"], "outcome": "passed"}],
   "calls": [{"journey": "J-01", "operation_id": "send_message", "method": "POST", "route": "/api/v1/messages",
              "path": "/api/v1/messages", "principal": "asha", "status": 201}]}
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import design as design_mod
from .checks import Finding, GateContext, check
from .project import EkitError, load_yaml
from .runner import run_profile_command

JOURNEYS = "reports/journeys.json"
OPENAPI = "reports/openapi.json"
NO_RUN_ENV = "EKIT_SMOKE_NO_RUN"
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head"}


def read_json(path: Path, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise EkitError(f"missing {what} ({path.name}): run `ekit run journeys` (or your CI journey step) first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EkitError(f"{path.name} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise EkitError(f"{path.name} must be a JSON object")
    return data


def operations_of(openapi: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """operationId -> (METHOD, path template) from an OpenAPI document."""
    out: dict[str, tuple[str, str]] = {}
    for path, item in (openapi.get("paths") or {}).items():
        for method, spec in (item or {}).items():
            if method.lower() in HTTP_METHODS and isinstance(spec, dict) and spec.get("operationId"):
                out[str(spec["operationId"])] = (method.upper(), str(path))
    return out


def ok_status(call: dict[str, Any]) -> bool:
    try:
        return 200 <= int(call.get("status") or 0) < 300
    except (TypeError, ValueError):
        return False


def _path_rx(template: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$")


def parse_page(page: str) -> tuple[str, str]:
    method, _, path = page.strip().partition(" ")
    return method.upper(), path.strip()


def page_reached(calls: list[dict[str, Any]], page: str) -> bool:
    method, template = parse_page(page)
    rx = _path_rx(template)
    return any(str(c.get("method", "")).upper() == method and c.get("principal") and int(c.get("status") or 0) == 200
               and (c.get("route") == template or rx.match(str(c.get("path") or ""))) for c in calls)


def _paths(ctx: GateContext, w: dict[str, Any]) -> tuple[Path, Path]:
    return ctx.path(w.get("journeys", JOURNEYS)), ctx.path(w.get("openapi", OPENAPI))


def _need(fn: Any, *args: Any) -> tuple[Any, list[Finding]]:
    try:
        return fn(*args), []
    except EkitError as exc:
        return None, [Finding("error", str(exc))]


# --------------------------------------------------------------------------- SMOKE-RUN
@check("smoke.run")
def smoke_run(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Run the `journeys` profile command so the report files are fresh (skip with EKIT_SMOKE_NO_RUN=1)."""
    if os.environ.get(NO_RUN_ENV, "").strip().lower() in ("1", "true", "yes"):
        return [Finding("info", f"{NO_RUN_ENV} is set: using the journey reports already on disk")]
    ran = 0
    out: list[Finding] = []
    for prof in list(getattr(ctx.project, "active_profiles", None) or ctx.project.profiles):
        if "journeys" not in prof.commands:
            continue
        for rel in (JOURNEYS, OPENAPI):
            (prof.root / rel).unlink(missing_ok=True)       # never judge a stale report
        res = run_profile_command(prof, "journeys")
        ran += 1
        if res is not None and res.returncode != 0:
            tail = "\n".join(res.output.strip().splitlines()[-12:])
            out.append(Finding("error", f"[{prof.id}] `ekit run journeys` exited {res.returncode}; the journeys did not run to completion "
                                        f"(fix the command first, e.g. `uv sync` when there is no venv / uv.lock). Last output:\n{tail}"))
    if ran == 0:
        out.append(Finding("info", "no profile defines a `journeys` command; using the journey reports already on disk"))
    return out


# --------------------------------------------------------------------------- the five smoke checks
@check("smoke.journeys_pass")
def journeys_pass(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    jp, _ = _paths(ctx, w)
    rep, err = _need(read_json, jp, "the journey report")
    if err:
        return err
    journeys = rep.get("journeys") or []
    if not journeys:
        return [Finding("error", f"{jp.name} records no journeys: tag journey scenarios @J-01 …")]
    out = [Finding("error", f"journey {j.get('id')} failed ({j.get('outcome')}): {j.get('scenario')}")
           for j in journeys if j.get("outcome") != "passed"]
    ran = {str(j.get("id")) for j in journeys}
    try:
        data = design_mod.load_design(ctx.project.root)
    except EkitError:
        data = {}
    for s in data.get("slices") or []:
        out += [Finding("error", f"slice {s.get('id')}: journey {j} never ran (no scenario tagged @{j} in {jp.name})")
                for j in s.get("journeys") or [] if j not in ran]
    return out


@check("smoke.operation_exists")
def operation_exists(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    _, op = _paths(ctx, w)
    spec, err = _need(read_json, op, "the OpenAPI document")
    if err:
        return err
    data, derr = design_mod._design(ctx)
    if data is None:
        return derr
    have = operations_of(spec)
    return [Finding("error", f"{f}: operation `{o}` is in design.yaml but not in the app's OpenAPI "
                             f"(give the route `operation_id=\"{o}\"`)")
            for f in (data.get("features") or {}) for o in design_mod.feature_ops(data, f) if o not in have]


@check("smoke.operation_exercised")
def operation_exercised(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    jp, _ = _paths(ctx, w)
    rep, err = _need(read_json, jp, "the journey report")
    if err:
        return err
    data, derr = design_mod._design(ctx)
    if data is None:
        return derr
    calls = [c for c in rep.get("calls") or [] if c.get("journey")]
    good = {c.get("operation_id") for c in calls if ok_status(c)}
    seen = {c.get("operation_id") for c in calls}
    out = []
    for f in design_mod.key_features(data):
        for o in design_mod.feature_ops(data, f):
            if o not in good:
                how = "was called but never got a 2xx response" if o in seen else "was never called by any journey"
                out.append(Finding("error", f"{f}: operation `{o}` {how}"))
    return out


@check("smoke.page_reachable")
def page_reachable(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    jp, _ = _paths(ctx, w)
    data, derr = design_mod._design(ctx)
    if data is None:
        return derr
    pages = [(f, p) for f in design_mod.key_features(data) for p in design_mod.feature_pages(data, f)]
    if not pages:
        return []
    rep, err = _need(read_json, jp, "the journey report")
    if err:
        return err
    calls = [c for c in rep.get("calls") or [] if c.get("journey")]
    return [Finding("error", f"{f}: page `{p}` never returned 200 for a signed-in dev user in any journey "
                             "(open it with `When I open the page \"/…\"`)")
            for f, p in pages if not page_reached(calls, p)]


@check("smoke.feature_covered")
def feature_covered(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    jp, _ = _paths(ctx, w)
    rep, err = _need(read_json, jp, "the journey report")
    if err:
        return err
    data, derr = design_mod._design(ctx)
    if data is None:
        return derr
    tagged = {f for j in rep.get("journeys") or [] for f in j.get("features") or []}
    return [Finding("error", f"key feature {f} has no journey tagged @{f}") for f in design_mod.key_features(data) if f not in tagged]


# --------------------------------------------------------------------------- BASE-SEAMS-PRESENT
def _top_level_names(path: Path) -> set[str]:
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    return {n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}


@check("base.seams_present")
def seams_present(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    from . import golden
    g = golden.for_project(ctx.project)
    if g is None:
        return [Finding("info", "no golden core: Day-0 seams come with the stack's golden landing zone")]
    seams = g.manifest.get("day0_seams") or {}
    if not seams:
        return [Finding("error", f"golden {g.stack} {g.version} has no Day-0 seams (needs 1.1.0): `ekit upgrade` to a 0.7.0 kit")]
    out: list[Finding] = []
    for name, spec in seams.items():
        f = ctx.project.root / spec["file"]
        if not f.is_file():
            out.append(Finding("error", f"seam {name}: {spec['file']} is missing from the core"))
            continue
        have = _top_level_names(f)
        out += [Finding("error", f"seam {name}: `{s}` is missing from {spec['file']}") for s in spec.get("symbols") or [] if s not in have]
    return out


# --------------------------------------------------------------------------- GREEN-NO-DUMMY (enterprise rigor)
NON_DEV_ENV_RE = re.compile(r"^\s*(?:export\s+)?APP_ENV\s*[=:]\s*[\"']?(staging|stage|uat|prod|production|preprod)\b", re.M | re.I)


def _env_files(root: Path) -> list[Path]:
    found = [p for p in root.glob(".env.*") if p.is_file() and not p.name.endswith(".example")]
    for d in ("deploy", "deployment", "config", "k8s", "helm", "charts"):
        if (root / d).is_dir():
            found += [p for p in (root / d).rglob("*") if p.is_file() and p.suffix in (".env", ".yaml", ".yml", ".conf", ".properties")]
    return [p for p in found if p.name != "dev-users.yaml"]


@check("green.no_dummy")
def no_dummy(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Enterprise rigor: the Day-0 dummies (DevUserProvider, LogAuditSink) are not what a non-dev environment runs."""
    from . import golden
    root = ctx.project.root
    out: list[Finding] = []
    try:
        seams = (design_mod.load_design(root).get("seams") or {})
    except EkitError:
        seams = {}
    for seam, dummy in (("principal", "dev-users"), ("audit", "log")):
        if isinstance(seams.get(seam), dict) and seams[seam].get("impl") == dummy:
            out.append(Finding("error", f"design.yaml: seam `{seam}` is still the Day-0 dummy `{dummy}`; replace it with the real "
                                        "control and update design.yaml (or override with reason, approver and expiry)"))
    g = golden.for_project(ctx.project)
    dummies = (g.manifest.get("dummies") if g else None) or [
        {"setting": "APP_PRINCIPAL_PROVIDER", "value": "dev-users"}, {"setting": "APP_AUDIT_SINK", "value": "log"}]
    for f in _env_files(root):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not NON_DEV_ENV_RE.search(text):
            continue
        for d in dummies:
            if re.search(rf"{re.escape(d['setting'])}\s*[=:]\s*[\"']?{re.escape(d['value'])}\b", text, re.I):
                out.append(Finding("error", f"{ctx.project.rel(f)}: a non-dev environment sets {d['setting']}={d['value']} (the Day-0 dummy)"))
    if not out:
        out.append(Finding("info", "no Day-0 dummy is wired for a non-dev environment"))
    return out


# --------------------------------------------------------------------------- SMOKE-W0-INTACT
@check("smoke.w0_intact")
def w0_intact(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """After the adoption point the W0 journeys are a fingerprinted regression suite (like red evidence)."""
    from .waves import W0_RECORD, journey_files
    p = ctx.path(W0_RECORD)
    if not p.is_file():
        return [Finding("info", "no adoption point recorded yet (`ekit wave advance` out of W0 records the journeys)")]
    rec = load_yaml(p) or {}
    now = journey_files(ctx.project.root)
    out = []
    for rel, sha in sorted((rec.get("files") or {}).items()):
        if rel not in now:
            out.append(Finding("error", f"{rel}: a W0 journey was deleted after the adoption point ({rec.get('on')}, {rec.get('by')})"))
        elif now[rel] != sha:
            out.append(Finding("error", f"{rel}: a W0 journey changed after the adoption point ({rec.get('on')}, {rec.get('by')}); "
                                        "revert it, or a person re-records it in a reviewed commit with an ADR"))
    return out or [Finding("info", f"{len(rec.get('files') or {})} W0 journey file(s) unchanged since {rec.get('on')}")]
