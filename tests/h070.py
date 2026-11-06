"""Shared fixtures for the ekit 0.7.0 tests (not collected: no test_ prefix)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from ekit import checks, kitsource
from ekit.project import Project, dump_yaml

BRD = """# BRD
| ID | Requirement | Source |
|----|-------------|--------|
| BR-001 | Colleagues exchange messages | q1 |
| BR-002 | Messages are kept | q2 |
| BR-003 | Colleagues see who has unread messages | q3 |
"""
PRD = """# PRD

## 3. Features

### FEAT-01: Messaging

**Satisfies**: BR-001, BR-002

- **AC-001** (BR-001): Given two users, when one sends, then the other sees it.

### FEAT-02: Unread overview

**Satisfies**: BR-003

- **AC-002** (BR-003): Given unread messages, when a user opens the overview, then counts show.

## 4. Out of scope
"""
HAPPY = """# Happy path

## 1. Features

### FEAT-01: Messaging

- **Key**: yes

### FEAT-02: Unread overview

- **Key**: yes

## 2. Journeys

### J-01: Two colleagues exchange messages

- **Features**: FEAT-01, FEAT-02
"""
ARCH = "# Architecture\n\n" + "\n\n".join(
    f"## {i}. {t}\n\ntext" for i, t in enumerate(
        ["Topology", "Ports", "Core data model", "Interface", "Day-0 seams", "Slices", "Decisions"], 1)) + "\n"
PORTS_PY = '''from typing import Protocol


class MessageStore(Protocol):
    def append(self, sender: str, body: str) -> int: ...
    def history(self, peer: str) -> list[str]: ...


class SqlMessageStore:
    def append(self, sender: str, body: str) -> int:
        return 1

    def history(self, peer: str) -> list[str]:
        return []


class InMemoryMessageStore:
    def append(self, sender: str, body: str) -> int:
        return 1

    def history(self, peer: str) -> list[str]:
        return []


def get_message_store() -> MessageStore:
    return SqlMessageStore()
'''


def design_data() -> dict[str, Any]:
    return {
        "topology": "central-server",
        "ports": [{"name": "MessageStore", "methods": ["append", "history"], "dependency": "get_message_store"}],
        "seams": {"principal": {"impl": "dev-users", "file": "config/dev-users.yaml"}, "audit": {"impl": "log"},
                  "request_id": {"impl": "middleware"}, "config": {"impl": "env"}, "data_owner": {"field": "owner_id"}},
        "features": {
            "FEAT-01": {"brs": ["BR-001", "BR-002"], "operations": ["send_message", "list_messages"], "pages": ["GET /chat/{peer}"]},
            "FEAT-02": {"brs": ["BR-003"], "operations": ["list_unread"]},
        },
        "slices": [{"id": "S0", "features": ["FEAT-01", "FEAT-02"], "journeys": ["J-01"]}],
        "decisions": [{"id": "D1", "title": "Topology", "status": "accepted", "adr": "ADR-0002"}],
    }


def journeys_report() -> dict[str, Any]:
    def call(op, method, route, who, status, j="J-01"):
        return {"journey": j, "operation_id": op, "method": method, "route": route, "path": route.replace("{peer}", "ravi"),
                "principal": who, "status": status}
    return {"version": 1,
            "journeys": [{"id": "J-01", "scenario": "asha writes to ravi", "features": ["FEAT-01", "FEAT-02"], "outcome": "passed"}],
            "calls": [call("send_message", "POST", "/api/v1/messages", "asha", 201),
                      call("list_unread", "GET", "/api/v1/unread", "ravi", 200),
                      call("list_messages", "GET", "/api/v1/messages/{peer}", "ravi", 200),
                      call(None, "GET", "/chat/{peer}", "ravi", 200)]}


def openapi_doc() -> dict[str, Any]:
    def op(oid, params=(), body=False):
        d: dict[str, Any] = {"operationId": oid, "parameters": [{"name": n, "in": w, "required": True} for n, w in params]}
        if body:
            d["requestBody"] = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Msg"}}}}
        return d
    return {"openapi": "3.1.0", "paths": {
        "/api/v1/messages": {"post": op("send_message", body=True)},
        "/api/v1/messages/{peer}": {"get": op("list_messages", [("peer", "path")])},
        "/api/v1/unread": {"get": op("list_unread")}},
        "components": {"schemas": {"Msg": {"type": "object", "properties": {"peer": {"type": "string"}, "body": {"type": "string"}}}}}}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_project(tmp_path, stack: str = "fastapi-jinja", lane: str | None = "happy-path", slug: str = "chat") -> Project:
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    cfg: dict[str, Any] = {"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": stack}
    if lane:
        cfg["lane"] = lane
    dump_yaml(cfg, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    d = root / "docs/requirements" / slug
    d.mkdir(parents=True)
    (d / "brd.md").write_text(BRD, encoding="utf-8")
    (d / "prd.md").write_text(PRD, encoding="utf-8")
    (d / "open-questions.yaml").write_text("questions: []\n", encoding="utf-8")
    (d / "happy-path.md").write_text(HAPPY, encoding="utf-8")
    return Project.load(root)


def write_design(root: Path, data: dict[str, Any] | None = None, adr: bool = True) -> dict[str, Any]:
    data = data or design_data()
    (root / "docs/design").mkdir(parents=True, exist_ok=True)
    (root / "docs/design/design.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    (root / "docs/design/architecture.md").write_text(ARCH, encoding="utf-8")
    if adr:
        (root / "docs/adr").mkdir(parents=True, exist_ok=True)
        (root / "docs/adr/0002-topology.md").write_text("# ADR-0002: Topology\n\nRecords decision D1.\n", encoding="utf-8")
    return data


def write_reports(root: Path, journeys: dict[str, Any] | None = None, openapi: dict[str, Any] | None = None) -> None:
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports/journeys.json").write_text(json.dumps(journeys or journeys_report()), encoding="utf-8")
    (root / "reports/openapi.json").write_text(json.dumps(openapi or openapi_doc()), encoding="utf-8")


def write_ports(root: Path, text: str = PORTS_PY) -> None:
    (root / "src/app").mkdir(parents=True, exist_ok=True)
    (root / "src/app/ports.py").write_text(text, encoding="utf-8")


def run(project: Project, check_type: str, **params: Any):
    """Run one registered check directly: list of (level, message)."""
    ctx = checks.GateContext(project=Project.load(project.root))
    return [(f.level, f.message) for f in checks.REGISTRY[check_type](ctx, params)]


def errors(project: Project, check_type: str, **params: Any) -> list[str]:
    return [m for lv, m in run(project, check_type, **params) if lv == "error"]
