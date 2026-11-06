"""Traceability (0.7.0): BR -> FEAT -> operation / page -> journey -> last result.

`ekit trace matrix` is the single artifact a reviewer reads; `ekit trace postman` exports a Postman v2.1
collection (OpenAPI + journeys, HTTP Basic dev-user preset) so anyone can call each feature by hand.
Both read `docs/design/design.yaml`, `reports/journeys.json` and `reports/openapi.json`.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import yaml

from . import design as design_mod
from . import smoke
from .project import EkitError

COLUMNS = ("br", "feature", "kind", "item", "journeys", "result")
POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def _report(root: Path, journeys: str) -> dict[str, Any]:
    p = root / journeys
    return smoke.read_json(p, "the journey report") if p.is_file() else {"journeys": [], "calls": []}


def matrix(root: Path, journeys: str = smoke.JOURNEYS) -> list[dict[str, Any]]:
    data = design_mod.load_design(root)
    rep = _report(root, journeys)
    outcome = {str(j.get("id")): j.get("outcome") for j in rep.get("journeys") or []}
    calls = [c for c in rep.get("calls") or [] if c.get("journey")]
    rows: list[dict[str, Any]] = []
    for feat, spec in (data.get("features") or {}).items():
        spec = spec or {}
        items = [("operation", o) for o in design_mod.feature_ops(data, feat)] + \
                [("page", p) for p in design_mod.feature_pages(data, feat)]
        for kind, item in items or [("-", "-")]:
            if kind == "operation":
                hit = [c for c in calls if c.get("operation_id") == item]
            elif kind == "page":
                hit = [c for c in calls if smoke.page_reached([c], item)]
            else:
                hit = []
            js = sorted({str(c["journey"]) for c in hit})
            if not hit:
                result = "not run"
            elif any((smoke.ok_status(c) or kind == "page") and outcome.get(str(c["journey"])) == "passed" for c in hit):
                result = f"pass ({hit[-1].get('status')})"
            else:
                result = f"FAIL ({hit[-1].get('status')})"
            for br in spec.get("brs") or ["-"]:
                rows.append({"br": br, "feature": feat, "kind": kind, "item": item, "journeys": js, "result": result})
    return rows


def render(rows: list[dict[str, Any]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([", ".join(r[c]) if c == "journeys" else r[c] for c in COLUMNS])
        return buf.getvalue().rstrip("\n")
    head = "| BR | Feature | Kind | Operation / page | Journeys | Last result |\n|----|---------|------|------------------|----------|-------------|"
    body = [f"| {r['br']} | {r['feature']} | {r['kind']} | `{r['item']}` | {', '.join(r['journeys']) or '-'} | {r['result']} |"
            for r in rows]
    return "\n".join([head, *body])


# --------------------------------------------------------------------------- postman
def _resolve(schema: dict[str, Any], spec: dict[str, Any], depth: int = 0) -> Any:
    if depth > 4 or not isinstance(schema, dict):
        return None
    if "$ref" in schema:
        node: Any = spec
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            node = (node or {}).get(part)
        return _resolve(node or {}, spec, depth + 1)
    if "example" in schema:
        return schema["example"]
    for key in ("allOf", "anyOf", "oneOf"):
        if schema.get(key):
            return _resolve(schema[key][0], spec, depth + 1)
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: _resolve(v, spec, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_resolve(schema.get("items") or {}, spec, depth + 1)]
    if "default" in schema:
        return schema["default"]
    return {"integer": 0, "number": 0, "boolean": True}.get(t, "string")


def dev_users(root: Path) -> dict[str, str]:
    p = root / "config" / "dev-users.yaml"
    if not p.is_file():
        return {}
    users = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("users") or {}
    return {str(n): str((u or {}).get("password", "")) for n, u in users.items()}


def _auth(user: str, password: str) -> dict[str, Any]:
    return {"type": "basic", "basic": [{"key": "username", "value": user, "type": "string"},
                                        {"key": "password", "value": password, "type": "string"}]}


def _request(method: str, path: str, op: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    segs = [":" + s[1:-1] if s.startswith("{") else s for s in path.strip("/").split("/")]
    params = op.get("parameters") or []
    req: dict[str, Any] = {
        "method": method,
        "header": [{"key": "Accept", "value": "application/json"}],
        "url": {"raw": "{{baseUrl}}/" + "/".join(segs), "host": ["{{baseUrl}}"], "path": segs,
                "variable": [{"key": p["name"], "value": "example"} for p in params if p.get("in") == "path"],
                "query": [{"key": p["name"], "value": "", "disabled": not p.get("required")} for p in params if p.get("in") == "query"]},
    }
    body = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if body is not None:
        req["header"].append({"key": "Content-Type", "value": "application/json"})
        req["body"] = {"mode": "raw", "raw": json.dumps(_resolve(body.get("schema") or {}, spec), indent=2),
                       "options": {"raw": {"language": "json"}}}
    return req


def postman(root: Path, openapi: str = smoke.OPENAPI, journeys: str = smoke.JOURNEYS, base_url: str = "http://localhost:8000",
            name: str | None = None) -> dict[str, Any]:
    spec = smoke.read_json(root / openapi, "the OpenAPI document")
    rep = _report(root, journeys)
    users = dev_users(root)
    first = next(iter(users), "asha")
    by_op: dict[str, dict[str, Any]] = {}
    ops_items: list[dict[str, Any]] = []
    for path, item in (spec.get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method.lower() in smoke.HTTP_METHODS and isinstance(op, dict) and op.get("operationId"):
                req = _request(method.upper(), path, op, spec)
                by_op[op["operationId"]] = req
                ops_items.append({"name": op["operationId"], "request": req})
    folders: list[dict[str, Any]] = [{"name": "Operations", "item": sorted(ops_items, key=lambda i: i["name"])}]
    jr: dict[str, list[dict[str, Any]]] = {}
    for c in rep.get("calls") or []:
        if c.get("journey") and c.get("operation_id") in by_op:
            who = str(c.get("principal") or first)
            jr.setdefault(str(c["journey"]), []).append({
                "name": f"{len(jr.get(str(c['journey']), [])) + 1}. {c['operation_id']} as {who}",
                "request": {**by_op[c["operation_id"]], "auth": _auth(who, users.get(who, "<dev password>"))}})
    meta = {str(j.get("id")): j for j in rep.get("journeys") or []}
    if jr:
        folders.append({"name": "Journeys", "item": [
            {"name": f"{jid} {meta.get(jid, {}).get('scenario', '')}".strip(), "item": items} for jid, items in sorted(jr.items())]})
    return {
        "info": {"name": name or f"{root.name} API", "schema": POSTMAN_SCHEMA,
                 "description": "Generated by `ekit trace postman` from OpenAPI and the journey report. Dev users only (HTTP Basic)."},
        "auth": _auth("{{dev_user}}", "{{dev_password}}"),
        "variable": [{"key": "baseUrl", "value": base_url}, {"key": "dev_user", "value": first},
                     {"key": "dev_password", "value": users.get(first, "")}],
        "item": folders,
    }
