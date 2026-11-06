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
BACKGROUND_RE = re.compile(r"^\s*Background\s*:")
STEP_KEYWORD_RE = re.compile(r"^\s*(Given|When|Then|And|But|\*)\b\s*(.*)$")


@dataclass
class Scenario:
    name: str
    tags: list[str]
    file: Path
    line: int
    steps: int = 0
    step_lines: list[str] = field(default_factory=list)


@dataclass
class FeatureFile:
    path: Path
    name: str | None
    tags: list[str] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    has_background: bool = False


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
        if BACKGROUND_RE.match(raw):
            ff.has_background = True
            current = None  # steps under Background are not a scenario's own steps
            pending = []
            continue
        m = SCENARIO_RE.match(raw)
        if m:
            current = Scenario(name=m.group(2).strip(), tags=ff.tags + pending, file=path, line=i)
            ff.scenarios.append(current)
            pending = []
            continue
        sm = STEP_KEYWORD_RE.match(raw)
        if sm and current is not None:
            current.steps += 1
            current.step_lines.append(sm.group(2).strip())
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


def _at(tag: str) -> str:
    """Cucumber-JVM / cucumber-js write tag names as '@SCN-001-01'; pytest-bdd strips the '@'.
    Normalise so one reader serves every runner."""
    return tag if tag.startswith("@") else f"@{tag}"


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
            ftags = [_at(t.get("name", "")) for t in feature.get("tags", [])]
            for el in feature.get("elements", []):
                if el.get("type") == "background" or el.get("keyword", "").strip().lower() == "background":
                    continue
                tags = ftags + [_at(t.get("name", "")) for t in el.get("tags", [])]
                for scn in scn_tags(tags, r"SCN-\d{3}-\d{2}"):
                    result.setdefault(scn, []).append(_scenario_status(el))
    return result


def aggregate(statuses: list[str]) -> str:
    """Worst status wins: one failing example fails the scenario."""
    return max(statuses, key=lambda s: STATUS_ORDER.index(s) if s in STATUS_ORDER else 0)


def read_cucumber_elements(paths: list[Path]) -> dict[str, list[dict]]:
    """Return {SCN-id: [element, ...]} merged across reports, same matching as read_cucumber_reports
    but keeping the raw element so a caller can look past the status string (e.g. at error_message)."""
    result: dict[str, list[dict]] = {}
    for p in paths:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            continue
        for feature in data if isinstance(data, list) else []:
            ftags = [_at(t.get("name", "")) for t in feature.get("tags", [])]
            for el in feature.get("elements", []):
                if el.get("type") == "background" or el.get("keyword", "").strip().lower() == "background":
                    continue
                tags = ftags + [_at(t.get("name", "")) for t in el.get("tags", [])]
                for scn in scn_tags(tags, r"SCN-\d{3}-\d{2}"):
                    result.setdefault(scn, []).append(el)
    return result


_EXC_NAME_RE = re.compile(r"\b([A-Za-z_][\w.]*(?:Error|Exception))\s*:")


def failure_exception(element: dict) -> str | None:
    """Best-effort exception class name from the first failed step's error_message. A traceback
    (pytest's own, or the plain 'SomeError: message' line pytest-bdd puts in the cucumber-json
    error_message) ends with 'SomeError: ...'; this takes the last such name in the text (the
    innermost, most specific exception), or None if nothing looks like a Python exception line
    (another language/framework)."""
    for step in element.get("steps", []):
        res = step.get("result") or {}
        if res.get("status") != "failed":
            continue
        names = _EXC_NAME_RE.findall(res.get("error_message") or "")
        return names[-1].rsplit(".", 1)[-1] if names else None
    return None
