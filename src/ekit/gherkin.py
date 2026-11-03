"""Minimal, dependency-free Gherkin and Cucumber-JSON readers (enough for gating)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SCENARIO_RE = re.compile(r"^\s*(Scenario Outline|Scenario Template|Scenario|Example)\s*:\s*(.*)$")
FEATURE_RE = re.compile(r"^\s*Feature\s*:\s*(.*)$")
RULE_RE = re.compile(r"^\s*Rule\s*:")
TAG_LINE_RE = re.compile(r"^\s*@")
EXAMPLES_RE = re.compile(r"^\s*(Examples|Scenarios)\s*:")


@dataclass
class Scenario:
    name: str
    tags: list[str]
    file: Path
    line: int
    steps: int = 0


@dataclass
class FeatureFile:
    path: Path
    name: str | None
    tags: list[str] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _tags(line: str) -> list[str]:
    line = line.split("#", 1)[0]
    return [t for t in line.split() if t.startswith("@")]


def parse_feature(path: Path) -> FeatureFile:
    text = path.read_text(encoding="utf-8")
    ff = FeatureFile(path=path, name=None)
    pending: list[str] = []
    current: Scenario | None = None
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if TAG_LINE_RE.match(raw):
            pending.extend(_tags(raw))
            continue
        m = FEATURE_RE.match(raw)
        if m:
            ff.name = m.group(1).strip()
            ff.tags = pending
            pending = []
            continue
        if RULE_RE.match(raw) or EXAMPLES_RE.match(raw):
            pending = []  # tags on Rule/Examples blocks are not scenario-identity tags
            continue
        m = SCENARIO_RE.match(raw)
        if m:
            current = Scenario(name=m.group(2).strip(), tags=ff.tags + pending, file=path, line=i)
            ff.scenarios.append(current)
            pending = []
            continue
        if re.match(r"^\s*(Given|When|Then|And|But|\*)\b", raw) and current is not None:
            current.steps += 1
    if ff.name is None:
        ff.errors.append(f"{path.name}: no 'Feature:' line")
    if not ff.scenarios:
        ff.errors.append(f"{path.name}: no scenarios")
    for s in ff.scenarios:
        if s.steps == 0:
            ff.errors.append(f"{path.name}:{s.line}: scenario '{s.name}' has no steps")
    return ff


def parse_dir(directory: Path) -> list[FeatureFile]:
    if not directory.is_dir():
        return []
    return [parse_feature(p) for p in sorted(directory.rglob("*.feature"))]


def scn_tags(tags: list[str], pattern: str = r"SCN-\d{3}-\d{2}") -> list[str]:
    rx = re.compile(rf"^@({pattern})$")
    return [m.group(1) for t in tags if (m := rx.match(t))]


# --------------------------------------------------------------------- Cucumber JSON
STATUS_ORDER = ["passed", "skipped", "pending", "undefined", "ambiguous", "failed"]


def _scenario_status(element: dict) -> str:
    statuses = []
    for step in element.get("steps", []) + element.get("before", []) + element.get("after", []):
        st = (step.get("result") or {}).get("status", "undefined")
        statuses.append(st)
    if not statuses:
        return "undefined"
    if "failed" in statuses:
        return "failed"
    for st in ("ambiguous", "undefined", "pending"):
        if st in statuses:
            return st
    if all(s == "passed" for s in statuses):
        return "passed"
    return "skipped"


def read_cucumber_reports(paths: list[Path]) -> dict[str, list[str]]:
    """Return {SCN-id: [status per executed example]} merged across reports."""
    result: dict[str, list[str]] = {}
    for p in paths:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            continue
        for feature in data if isinstance(data, list) else []:
            ftags = [t.get("name", "") for t in feature.get("tags", [])]
            for el in feature.get("elements", []):
                if el.get("type") == "background" or el.get("keyword", "").strip().lower() == "background":
                    continue
                tags = ftags + [t.get("name", "") for t in el.get("tags", [])]
                for scn in scn_tags(tags, r"SCN-\d{3}-\d{2}"):
                    result.setdefault(scn, []).append(_scenario_status(el))
    return result


def aggregate(statuses: list[str]) -> str:
    """Worst status wins: one failing example fails the scenario."""
    return max(statuses, key=lambda s: STATUS_ORDER.index(s) if s in STATUS_ORDER else 0)
