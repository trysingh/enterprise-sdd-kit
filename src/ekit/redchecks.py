"""ekit 0.4.0: two red-gate checks that catch test-glue logic errors while the test module is still editable.

In red a scenario stops at its first failing step (a 501 from a `not_implemented()` stub), so later
step functions never run. A call to a method that does not exist, the wrong object, a wrong return
shape only shows in green, when the module is frozen. These checks look at what red never executes."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from . import gherkin
from .checks import (
    Finding,
    GateContext,
    _active,
    _feature_bound_tests,
    _feature_scn_ids,
    _golden,
    check,
)
from .project import EkitError
from .runner import build_argv, command_cwd

# mypy error codes that mean "the glue is logically wrong"; strict-mode style noise is left out.
GLUE_LOGIC_CODES = {"attr-defined", "name-defined", "call-arg", "arg-type", "return-value", "union-attr",
                    "index", "operator", "assignment", "call-overload", "func-returns-value", "has-type"}

_MYPY_LINE = re.compile(
    r"^(?P<path>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+)(?::\d+)?: error: (?P<msg>.*?)(?:\s+\[(?P<code>[a-z0-9-]+)\])?$")


def _same_file(path: str, cwd: Path, bound: set[Path]) -> bool:
    p = Path(path)
    if not p.is_absolute():
        p = cwd / p
    try:
        return p.resolve() in bound
    except OSError:
        return False


def parse_mypy(output: str, cwd: Path, bound_files: list[Path], codes: set[str]) -> list[tuple[str, int, str, str]]:
    """(path as printed, line, message, code) for each mypy error in a bound file with a wanted code."""
    bound = {Path(f).resolve() for f in bound_files}
    out: list[tuple[str, int, str, str]] = []
    for raw in output.splitlines():
        m = _MYPY_LINE.match(raw.strip())
        if not m:
            continue
        code = m.group("code") or ""
        if code not in codes or not _same_file(m.group("path"), cwd, bound):
            continue
        out.append((m.group("path").replace("\\", "/"), int(m.group("line")), m.group("msg"), code))
    return out


@check("bdd.glue_typecheck")
def glue_typecheck(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Type-check this feature's test module: steps after the first failure never run in red."""
    codes = set(w.get("codes") or GLUE_LOGIC_CODES)
    profs = [p for p in _active(ctx) if p.runs_bdd and p.commands.get("typecheck_glue")]
    if not profs:
        return [Finding("info", "skipped: no typecheck_glue command in this stack")]
    bound = _feature_bound_tests(ctx, w["dir"])
    out: list[Finding] = []
    for prof in profs:
        root = prof.root.resolve()
        files = [f for f in bound if f.resolve().is_relative_to(root)]
        if not files:
            continue
        spec = prof.commands["typecheck_glue"]
        cwd = command_cwd(spec, prof)
        label = f"{prof.id}:typecheck_glue"
        try:
            argv = build_argv(spec, cwd)
            rels = [f.resolve().relative_to(cwd.resolve()).as_posix() if f.resolve().is_relative_to(cwd.resolve())
                    else str(f.resolve()) for f in files]
            res = subprocess.run(argv + rels, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=w.get("timeout", 300), check=False)
        except subprocess.TimeoutExpired:
            out.append(Finding("warn", f"{label}: `{' '.join(map(str, spec))}` timed out; test glue was not type-checked"))
            continue
        except (OSError, EkitError) as exc:  # EkitError: executable not on PATH
            out.append(Finding("warn", f"{label}: `{' '.join(map(str, spec))}` could not run ({exc}); test glue was not type-checked"))
            continue
        ctx.outputs[label] = (res.stdout or "") + (res.stderr or "")
        for path, line, msg, code in parse_mypy(ctx.outputs[label], cwd, files, codes):
            out.append(Finding("error", f"{path}:{line} {msg} [{code}] — test glue calls something that does not "
                                        "exist or uses the wrong type/return value. Red only executes steps up to "
                                        "the first failure, so this step would only break in green, after the "
                                        "module is frozen. Fix it now."))
    return out


_STATUS_RE = re.compile(r"expected (\d{3}), got (\d{3})\b")


@check("bdd.route_stubbed")
def route_stubbed(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Golden projects: every route of the feature exists at red and answers 501, never 404."""
    if not _golden(ctx):
        return []
    want = _feature_scn_ids(ctx, w["dir"])
    reports = [p.root / p.bdd["report"] for p in _active(ctx) if p.runs_bdd and p.bdd.get("report")]
    elements = gherkin.read_cucumber_elements([r for r in reports if r.is_file()])
    out: list[Finding] = []
    for sid in want:
        for el in elements.get(sid, []):
            if gherkin._scenario_status(el) != "failed":
                continue
            step = next((s for s in el.get("steps", []) if (s.get("result") or {}).get("status") == "failed"), None)
            if step is None:
                continue
            m = _STATUS_RE.search((step["result"].get("error_message")) or "")
            if m and m.group(2) == "404" and m.group(1) != "404":
                name = f"{(step.get('keyword') or '').strip()} {step.get('name') or ''}".strip()
                out.append(Finding("error", f"{sid}: failed with 404 at step '{name}', not 501. In a golden project "
                                            "every route of the feature exists at red and calls not_implemented() "
                                            "(501). A 404 means the test calls a URL the feature's stubs don't define "
                                            "(wrong path or method in the glue) or the router isn't registered in "
                                            "features/registry.py. Fix the glue or add the stub, then rerun "
                                            "`ekit gate red`."))
                break
    return out
