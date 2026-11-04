"""Static scan of pytest-bdd step modules.

Two defects the red gate cannot see by running the suite, because a scenario can fail early
(on an API call) while a later step could never fail:

* a step whose body does nothing (`pass`, `...`, a docstring, `assert True`): a `Then` like that
  would let a scenario go green with the wrong behaviour;
* an absolute feature path in `scenarios()` / `scenario()` (breaks on every other machine and CI).

Pure functions over source text so they can be unit tested without pytest-bdd installed.
A deliberate empty step is allowed with the marker `# ekit: allow-empty-step <reason>` anywhere
in the step function (decorators included), which keeps the exception visible in review.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

STEP_DECORATORS = {"given", "when", "then", "step"}
SCENARIO_FUNCS = {"scenario", "scenarios"}
ALLOW_MARK = "ekit: allow-empty-step"


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
            if not step_decos or not all(_is_noop(s) for s in node.body):
                continue
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno or node.lineno
            if ALLOW_MARK in "\n".join(lines[start - 1:end]):
                continue
            res.steps.append(StepIssue(
                line=node.lineno, name=node.name, step=_step_text(step_decos[0]),
                reason="empty body: the step neither sets up nor checks anything",
            ))
        elif isinstance(node, ast.Call) and _call_name(node) in SCENARIO_FUNCS:
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_absolute(arg.value):
                    res.abs_paths.append((node.lineno, arg.value))
    res.steps.sort(key=lambda i: i.line)
    return res
