"""Static scan of pytest-bdd step modules.

Defects the red gate cannot see by running the suite, because a scenario can fail early
(on an API call) while a later step could never fail:

* a step whose body does nothing (`pass`, `...`, a docstring, `assert True`): a `Then` like that
  would let a scenario go green with the wrong behaviour;
* an absolute feature path in `scenarios()` / `scenario()` (breaks on every other machine and CI).
* (0.6.4) a `Given` step whose text describes an outage/failure but whose body only records a flag
  (e.g. `ctx.remember("x_unavailable", True)`) with nothing that actually wires a fault into the app:
  nothing reads the flag, so the step has no effect on the request path, and the gap is usually only
  discovered during implementation, once the file is frozen.

Pure functions over source text so they can be unit tested without pytest-bdd installed.
A deliberate empty step is allowed with the marker `# ekit: allow-empty-step <reason>` anywhere
in the step function (decorators included), which keeps the exception visible in review. A
deliberate unwired fault step is allowed the same way with `# ekit: allow-unwired-fault <reason>`.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

STEP_DECORATORS = {"given", "when", "then", "step"}
SCENARIO_FUNCS = {"scenario", "scenarios"}
ALLOW_MARK = "ekit: allow-empty-step"

# 0.6.4: a Given step that merely *describes* an outage/failure (vocabulary below) but never
# wires one into the app under test (no dependency override, monkeypatch or mock found in its
# own source text) is a step that cannot affect the request path: a flag set with
# `ctx.remember(...)` alone does nothing. Deliberately narrower than business-rule-denial words
# ("denied", "forbidden", "rejected", "invalid"), which are usually real and already exercised
# through the public interface - this only targets infrastructure/outage wording.
FAULT_VOCAB_RE = re.compile(
    r"\b(unavailable|outage|times?\s*out|unreachable|cannot be (?:loaded|reached)|"
    r"fails? to (?:load|respond|connect|send))\b",
    re.IGNORECASE,
)
# Deliberately a substring check on the step function's own source text, not deep AST semantic
# analysis: a heuristic that trusts the presence of real fault-wiring machinery nearby, not that
# it is wired correctly or to the right dependency.
FAULT_WIRING_MARKERS = (
    "dependency_overrides", "monkeypatch", "side_effect", "mock.patch", "Mock(", "MagicMock(", "patch(",
)
ALLOW_FAULT_MARK = "ekit: allow-unwired-fault"


@dataclass
class StepIssue:
    line: int
    name: str
    step: str
    reason: str


@dataclass
class ScanResult:
    steps: list[StepIssue] = field(default_factory=list)
    abs_paths: list[tuple[int, str]] = field(default_factory=list)
    fault_steps: list[StepIssue] = field(default_factory=list)
    error: str | None = None


def _call_name(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def _step_text(deco: ast.expr) -> str:
    """First string argument of @then("text") or @then(parsers.parse("text"))."""
    if not (isinstance(deco, ast.Call) and deco.args):
        return ""
    arg = deco.args[0]
    if isinstance(arg, ast.Call) and arg.args:
        arg = arg.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return ""


def _is_noop(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return isinstance(stmt.value.value, str) or stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Return):
        return stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
    if isinstance(stmt, ast.Assert):
        return isinstance(stmt.test, ast.Constant) and bool(stmt.test.value)
    return False


def _is_absolute(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def scan_source(source: str) -> ScanResult:
    res = ScanResult()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        res.error = f"cannot parse (line {exc.lineno}): {exc.msg}"
        return res
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            step_decos = [d for d in node.decorator_list if _call_name(d) in STEP_DECORATORS]
            if not step_decos:
                continue
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno or node.lineno
            text = "\n".join(lines[start - 1:end])
            if all(_is_noop(s) for s in node.body) and ALLOW_MARK not in text:
                res.steps.append(StepIssue(
                    line=node.lineno, name=node.name, step=_step_text(step_decos[0]),
                    reason="empty body: the step neither sets up nor checks anything",
                ))
            given_decos = [d for d in step_decos if _call_name(d) == "given"]
            if given_decos and ALLOW_FAULT_MARK not in text:
                step_text = _step_text(given_decos[0])
                if (FAULT_VOCAB_RE.search(step_text)
                        and not any(m in text for m in FAULT_WIRING_MARKERS)):
                    res.fault_steps.append(StepIssue(
                        line=node.lineno, name=node.name, step=step_text,
                        reason=(f"the step {step_text!r} describes a fault/outage but its body never wires "
                                "one into the app (no dependency_overrides, monkeypatch, or mock found); a "
                                "flag set with ctx.remember(...) alone has no effect on the request path. "
                                "Wire a scoped dependency override (not the shared session) so only the "
                                f"intended operation fails, or add `# {ALLOW_FAULT_MARK} <reason>` if this "
                                "is deliberate."),
                    ))
        elif isinstance(node, ast.Call) and _call_name(node) in SCENARIO_FUNCS:
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_absolute(arg.value):
                    res.abs_paths.append((node.lineno, arg.value))
    res.steps.sort(key=lambda i: i.line)
    res.fault_steps.sort(key=lambda i: i.line)
    return res
