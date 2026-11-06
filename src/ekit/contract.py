"""ekit 0.4.0: split freeze. The red tests' *contract* stays frozen; their *glue* may be fixed by the agent.

Why: in red a scenario stops at its first failing step (the 501 from a `not_implemented()` stub), so
step functions after it never run. A logic error in one of them (a method that doesn't exist, the
wrong object, the wrong return shape) only shows in green, when the whole module was frozen and the
agent could not fix it, and a person had to `ekit unfreeze` it, often more than once per feature.

What the governance claim needs frozen is the behaviour the system must show, not the plumbing:

* the Gherkin (`.feature` files): still edit-denied and byte-fingerprinted, as before;
* the binding of each bound pytest-bdd module: step keywords, patterns and parsers, `target_fixture`,
  `scenario()` / `scenarios()` calls (`GREEN-CONTRACT-INTACT`);
* the assertions of every `Then` step: how many there are and the literal values they compare
  against, plus hazards that would let a test pass without checking anything, such as skips,
  `assert True` or a swallowed AssertionError (`GREEN-GLUE-NOT-WEAKENED`).

Everything else in a bound module (Given/When bodies, helpers, parsing, imports) may change. A
change is accepted only if the amended module still fails cleanly against the feature's code as it
was at red (`GREEN-GLUE-STILL-RED`, which re-runs the scenarios with the red-time code restored
from git and puts the current code back afterwards), and it is recorded in the green ledger entry
with a diff under `.ekit/evidence/`.

`freeze.mode: strict` in `.ekit/project.yaml` keeps the 0.3.0 behaviour (the whole module frozen,
`GREEN-TESTS-UNCHANGED` byte-exact). The default is `split` for golden projects and `strict`
otherwise. Only Python (pytest-bdd) modules are split; other bound files stay byte-frozen.
"""
from __future__ import annotations

import ast
import datetime as dt
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .project import EkitError, load_yaml

STEP_KEYWORDS = {"given", "when", "then", "step"}
SCENARIO_FUNCS = {"scenario", "scenarios"}
HAZARDS = ("skip", "xfail_or_skip_mark", "assert_constant", "assert_tautology", "or_true",
           "swallowed_assert", "return_before_assert")
MODES = ("split", "strict")


# ------------------------------------------------------------------------------- mode
def freeze_mode(root: Path) -> str:
    """`freeze.mode` from `.ekit/project.yaml`; default split for golden projects, strict otherwise."""
    p = root / ".ekit" / "project.yaml"
    data = (load_yaml(p) or {}) if p.is_file() else {}
    mode = ((data.get("freeze") or {}) if isinstance(data, dict) else {}).get("mode")
    if mode in MODES:
        return str(mode)
    return "split" if (root / ".ekit" / "golden.lock.yaml").is_file() else "strict"


def is_glue(rel: str, feature: str) -> bool:
    """A bound test module whose glue is editable in split mode (Python only, never a .feature)."""
    return rel.endswith(".py") and not rel.startswith(f"specs/{feature}/")


def frozen_subset(root: Path, feature: str, fingerprints: dict[str, str]) -> dict[str, str]:
    """What `freeze_feature` denies to the agent: everything in strict mode, all but the glue in split."""
    if freeze_mode(root) != "split":
        return dict(fingerprints)
    return {rel: sha for rel, sha in fingerprints.items() if not is_glue(rel, feature)}


# ------------------------------------------------------------------------- AST contract
def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _step_decorator(dec: ast.AST) -> tuple[str, str] | None:
    """(keyword, normalised binding) for a pytest-bdd step decorator, else None."""
    if not isinstance(dec, ast.Call):
        return None
    kw = _name(dec.func)
    if kw not in STEP_KEYWORDS:
        return None
    args = [ast.unparse(a) for a in dec.args]
    kwargs = sorted(f"{k.arg}={ast.unparse(k.value)}" for k in dec.keywords)
    return kw, f"{kw}({', '.join(args + kwargs)})"


def _assert_literals(node: ast.Assert) -> list[str]:
    return sorted(repr(n.value) for n in ast.walk(node.test) if isinstance(n, ast.Constant))


def _contains_assert(nodes: list[ast.stmt]) -> bool:
    return any(isinstance(n, ast.Assert) for stmt in nodes for n in ast.walk(stmt))


def _hazards(tree: ast.Module, then_funcs: list[ast.FunctionDef | ast.AsyncFunctionDef]) -> dict[str, int]:
    h = dict.fromkeys(HAZARDS, 0)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _name(n.func) in {"skip", "xfail"} and \
                isinstance(n.func, ast.Attribute) and _name(n.func.value) == "pytest":
            h["skip"] += 1
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in n.decorator_list:
                target = d.func if isinstance(d, ast.Call) else d
                if isinstance(target, ast.Attribute) and target.attr in {"skip", "skipif", "xfail"} \
                        and _name(target.value) == "mark":
                    h["xfail_or_skip_mark"] += 1
        # pytestmark = pytest.mark.skip / [pytest.mark.xfail, ...]
        if isinstance(n, ast.Assign) and any(_name(t) == "pytestmark" for t in n.targets) and \
                any(m in ast.unparse(n.value) for m in ("mark.skip", "mark.xfail")):
            h["xfail_or_skip_mark"] += 1
        if isinstance(n, ast.Assert):
            t = n.test
            if isinstance(t, ast.Constant) and bool(t.value):
                h["assert_constant"] += 1
            if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], (ast.Eq, ast.Is)) and \
                    ast.dump(t.left) == ast.dump(t.comparators[0]):
                h["assert_tautology"] += 1
            if isinstance(t, ast.BoolOp) and isinstance(t.op, ast.Or) and \
                    any(isinstance(v, ast.Constant) and bool(v.value) for v in t.values):
                h["or_true"] += 1
        if isinstance(n, ast.Try) and _contains_assert(n.body):
            for handler in n.handlers:
                names = {_name(x) for x in (handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type])} \
                    if handler.type is not None else {None}
                if names & {None, "Exception", "BaseException", "AssertionError"}:
                    h["swallowed_assert"] += 1
    for fn in then_funcs:
        for stmt in fn.body:
            if isinstance(stmt, ast.Assert) or _contains_assert([stmt]):
                break
            if any(isinstance(n, ast.Return) for n in ast.walk(stmt)) and _contains_assert(fn.body):
                h["return_before_assert"] += 1
                break
    return h


def module_contract(source: str) -> dict[str, Any]:
    """The frozen part of one pytest-bdd test module. Raises SyntaxError for unparsable source."""
    tree = ast.parse(source)
    bindings: list[str] = []
    then_funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    then_steps: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                sd = _step_decorator(dec)
                if sd:
                    bindings.append(sd[1])
                    if sd[0] == "then":
                        then_funcs.append(node)
                        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
                        lits = sorted(x for a in asserts for x in _assert_literals(a))
                        then_steps[sd[1]] = {
                            "asserts": len(asserts),
                            "literals_sha256": hashlib.sha256(json.dumps(lits).encode()).hexdigest(),
                        }
                elif isinstance(dec, ast.Call) and _name(dec.func) in SCENARIO_FUNCS:
                    bindings.append(ast.unparse(dec))
        elif isinstance(node, ast.Call) and _name(node.func) in SCENARIO_FUNCS:
            bindings.append(ast.unparse(node))
    imports = sorted({
        (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    } - {""})
    bindings = sorted(set(bindings))
    return {
        "bindings": bindings,
        "bindings_sha256": hashlib.sha256(json.dumps(bindings).encode()).hexdigest(),
        "then_steps": then_steps,
        "hazards": _hazards(tree, then_funcs),
        "imports": imports,
    }


def defines_steps(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(_step_decorator(d) for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for d in n.decorator_list)


def project_contract(root: Path, feature: str, files: dict[str, str], known_test_files: list[str]) -> dict[str, Any]:
    """`files`: rel path -> current text. Recorded in the red ledger entry under `contract`."""
    modules: dict[str, Any] = {}
    for rel, text in sorted(files.items()):
        if not is_glue(rel, feature):
            continue
        try:
            modules[rel] = module_contract(text)
        except SyntaxError as exc:
            modules[rel] = {"unparsable": f"line {exc.lineno}: {exc.msg}"}
    return {"version": 1, "modules": modules, "known_test_files": sorted(known_test_files)}


# ------------------------------------------------------------------------- comparisons
def compare_contract(red: dict[str, Any], now_sources: dict[str, str]) -> list[str]:
    """Errors for GREEN-CONTRACT-INTACT: bindings changed, a module deleted or unparsable."""
    out: list[str] = []
    for rel, rc in sorted((red.get("modules") or {}).items()):
        if rel not in now_sources:
            out.append(f"{rel}: deleted since red (its bindings are part of the frozen contract)")
            continue
        try:
            now = module_contract(now_sources[rel])
        except SyntaxError as exc:
            out.append(f"{rel}: does not parse (line {exc.lineno}: {exc.msg})")
            continue
        if "bindings" not in rc or now["bindings_sha256"] == rc.get("bindings_sha256"):
            continue
        removed = sorted(set(rc["bindings"]) - set(now["bindings"]))
        added = sorted(set(now["bindings"]) - set(rc["bindings"]))
        detail = "; ".join(x for x in (
            ("removed: " + ", ".join(removed)) if removed else "",
            ("added: " + ", ".join(added)) if added else "") if x)
        out.append(f"{rel}: step bindings changed since red ({detail}). Step keywords, patterns, parsers, "
                   "target_fixture and scenario() calls are the frozen contract; only step BODIES may change. "
                   "If the binding really is wrong, run `ekit blocked` and a person decides on `ekit unfreeze`")
    return out


def compare_weakening(red: dict[str, Any], now_sources: dict[str, str]) -> list[str]:
    """Errors for GREEN-GLUE-NOT-WEAKENED."""
    out: list[str] = []
    for rel, rc in sorted((red.get("modules") or {}).items()):
        if rel not in now_sources or "then_steps" not in rc:
            continue
        try:
            now = module_contract(now_sources[rel])
        except SyntaxError:
            continue  # GREEN-CONTRACT-INTACT reports it
        for key, before in sorted(rc["then_steps"].items()):
            after = now["then_steps"].get(key)
            if after is None:
                continue  # a binding change; GREEN-CONTRACT-INTACT reports it
            if after["asserts"] < before["asserts"]:
                out.append(f"{rel}: `{key}` has {after['asserts']} assert(s), {before['asserts']} at red. "
                           "A Then step may not lose assertions")
            if after["literals_sha256"] != before["literals_sha256"]:
                out.append(f"{rel}: `{key}` compares against different expected values than at red. "
                           "Expected values in Then assertions are part of the contract")
        for hz, n in sorted(now["hazards"].items()):
            was = (rc.get("hazards") or {}).get(hz, 0)
            if n > was:
                out.append(f"{rel}: new {hz.replace('_', ' ')} ({was} -> {n}). A test that can pass without "
                           "checking anything is not allowed")
    return out


# ------------------------------------------------------------------------------ git
def _git(root: Path, *args: str, binary: bool = False) -> Any:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if proc.returncode != 0:
        raise EkitError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", errors="replace")


def red_evidence_commit(root: Path, feature: str, red_entry: dict[str, Any]) -> str | None:
    """The commit that committed this red entry (tests, stubs, ledger). Red's own `git_head` is the
    HEAD *before* that commit, where the feature's stubs usually did not exist yet."""
    head = red_entry.get("git_head")
    ledger = f".ekit/ledger/{feature}.yaml"
    at = str(red_entry.get("at") or "")
    try:
        rng = f"{head}..HEAD" if head else "HEAD"
        revs = _git(root, "rev-list", "--reverse", rng, "--", ledger).split()
    except EkitError:
        revs = []
    for rev in revs:
        try:
            text = _git(root, "show", f"{rev}:{ledger}")
        except EkitError:
            continue
        if at and at in text:
            return rev
    return head


def file_at(root: Path, rev: str, rel: str) -> bytes | None:
    try:
        return _git(root, "show", f"{rev}:{rel}", binary=True)
    except EkitError:
        return None


def contract_from_commit(root: Path, feature: str, red_entry: dict[str, Any]) -> dict[str, Any]:
    """`ekit freeze --recontract`: compute the contract from the red-time content (committed), not the
    working tree, for features recorded red before 0.4.0."""
    rev = red_evidence_commit(root, feature, red_entry)
    if not rev:
        raise EkitError("The red entry has no git_head; the red-time test content cannot be found.")
    files: dict[str, str] = {}
    for rel, sha in (red_entry.get("fingerprints") or {}).items():
        blob = file_at(root, rev, rel)
        if blob is None or hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest() != sha:
            if is_glue(rel, feature):
                raise EkitError(f"{rel}: the red-time content (sha {sha[:12]}) is not in commit {rev[:12]}. "
                                 "Commit the red evidence first (REDREC-COMMITTED), then retry.")
            continue
        files[rel] = blob.decode("utf-8", errors="replace")
    return project_contract(root, feature, files, sorted(files))


# ------------------------------------------------------------------------- replay red
def replay_red(project: Any, feature: str, red_entry: dict[str, Any], run: Any) -> tuple[str, list[str]]:
    """Put the feature's code back as it was when red was committed, call `run()` (which runs the
    feature's acceptance scenarios and returns findings), then restore the current code exactly,
    including uncommitted work. Never touches the git index. Returns (red commit, run's result).

    The current code is copied to `.ekit/replay-backup/<ts>/` first and removed only after a
    successful restore, so an interrupted run leaves a copy to restore from."""
    from .fixred import _revert_scope
    root = project.root
    rev = red_evidence_commit(root, feature, red_entry)
    if not rev:
        raise EkitError("The last red entry has no git_head; cannot replay red.")
    dirs = [d for d in _revert_scope(project, feature) if d]
    if not dirs:
        raise EkitError("No feature package or source directory to revert for the replay.")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / ".ekit" / "replay-backup" / stamp
    backup.mkdir(parents=True)
    for d in dirs:
        if (root / d).exists():
            shutil.copytree(root / d, backup / d, symlinks=True)
    try:
        for d in dirs:
            shutil.rmtree(root / d, ignore_errors=True)
            names = _git(root, "ls-tree", "-r", "--name-only", rev, "--", d).splitlines()
            for rel in names:
                blob = file_at(root, rev, rel)
                if blob is None:
                    continue
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
        result = run()
    finally:
        for d in dirs:
            shutil.rmtree(root / d, ignore_errors=True)
            if (backup / d).exists():
                shutil.copytree(backup / d, root / d, symlinks=True)
        shutil.rmtree(backup, ignore_errors=True)
        try:
            (root / ".ekit" / "replay-backup").rmdir()
        except OSError:
            pass
    return rev, result


def write_glue_diff(root: Path, feature: str, rel: str, before: str, after: str) -> str:
    """Save the glue change as evidence; returns the diff's repo-relative path."""
    ev = root / ".ekit" / "evidence" / feature
    ev.mkdir(parents=True, exist_ok=True)
    n = 1 + sum(1 for _ in ev.glob("glue-*.diff"))
    path = ev / f"glue-{n}.diff"
    diff = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                fromfile=f"red/{rel}", tofile=f"green/{rel}")
    path.write_text("".join(diff), encoding="utf-8", newline="\n")
    return path.relative_to(root).as_posix()
