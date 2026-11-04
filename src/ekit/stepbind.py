"""Static check that every Gherkin step is bound to a pytest-bdd step definition.

Why this exists: `ekit gate red` proves each scenario FAILS, but pytest-bdd only looks a step
definition up when it reaches that step. A scenario that fails at an early step (a 501 from a stub)
is recorded as failed even if a later `Then` has no definition at all. Red then freezes a test that
can never pass, and the gap only shows at green. This scan finds such steps before the freeze.

What it understands (pytest-bdd 6+):
* step decorators `given` / `when` / `then` / `step`, used directly or as `pytest_bdd.given`;
* patterns as a plain string (exact match), `parsers.parse(...)`, `parsers.cfparse(...)`,
  `parsers.re(...)` (full match) and `parsers.string(...)`;
* keyword types: a `Given` definition does not bind a `Then` step; `And` / `But` / `*` take the
  type of the previous step; `step` binds any type;
* Background steps (prepended to every scenario) and Scenario Outline placeholders, substituted
  from each Examples row;
* where definitions are visible to a test module: the module itself, `conftest.py` files from its
  directory up to the acceptance root, and modules it imports from the acceptance tree.

A pattern that is not a string literal (built at runtime) cannot be checked; when a module has one,
unbound steps are reported as warnings instead of errors.

Pure functions over text so they can be unit tested without pytest-bdd installed.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

DECORATOR_TYPES = {"given": "given", "when": "when", "then": "then", "step": "any"}
KEYWORDS = {"given": "given", "when": "when", "then": "then", "and": None, "but": None, "*": None}
STEP_RE = re.compile(r"^\s*(Given|When|Then|And|But|\*)\s+(.*?)\s*$")
SCENARIO_RE = re.compile(r"^\s*(Scenario Outline|Scenario Template|Scenario|Example)\s*:\s*(.*)$")
BACKGROUND_RE = re.compile(r"^\s*Background\s*:")
EXAMPLES_RE = re.compile(r"^\s*(Examples|Scenarios)\s*:")
RULE_RE = re.compile(r"^\s*Rule\s*:")
PARSE_FIELD_RE = re.compile(r"\{([^{}]*)\}")


# --------------------------------------------------------------------------- step definitions
@dataclass
class StepDef:
    kind: str            # given | when | then | any
    pattern: re.Pattern[str] | None
    source: str          # the pattern text as written, for messages
    line: int
    file: str


@dataclass
class ModuleDefs:
    defs: list[StepDef] = field(default_factory=list)
    dynamic: int = 0     # patterns that are not string literals (cannot be checked)
    imports: list[str] = field(default_factory=list)
    error: str | None = None


def _parse_to_regex(fmt: str) -> str:
    """parse/cfparse format -> regex. `{name}`, `{name:d}`, `{:w}`; `{{` / `}}` are literal braces."""
    out, i = [], 0
    fmt = fmt.replace("{{", "\0LB\0").replace("}}", "\0RB\0")
    for m in PARSE_FIELD_RE.finditer(fmt):
        out.append(re.escape(fmt[i:m.start()]))
        spec = m.group(1).split(":", 1)[1] if ":" in m.group(1) else ""
        conv = spec.strip()[-1:] if spec.strip() else ""
        out.append({"d": r"[-+]?\d+", "n": r"[-+]?[\d,]+", "f": r"[-+]?\d*\.?\d+", "w": r"\w+"}.get(conv, r".+?"))
        i = m.end()
    out.append(re.escape(fmt[i:]))
    rx = "".join(out)
    return rx.replace(re.escape("\0LB\0"), r"\{").replace(re.escape("\0RB\0"), r"\}")


def _decorator_kind(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else None
    return DECORATOR_TYPES.get(name or "")


def _pattern(arg: ast.expr) -> tuple[re.Pattern[str] | None, str, bool]:
    """(compiled full-match regex, text for messages, is_dynamic)."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return re.compile(re.escape(arg.value)), arg.value, False
    if isinstance(arg, ast.Call) and arg.args and isinstance(arg.args[0], ast.Constant) and isinstance(arg.args[0].value, str):
        func = arg.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        text = arg.args[0].value
        try:
            if name == "re":
                return re.compile(text), text, False
            if name in ("parse", "cfparse"):
                return re.compile(_parse_to_regex(text)), text, False
            if name == "string":
                return re.compile(re.escape(text)), text, False
        except re.error:
            return None, text, True
    return None, ast.unparse(arg) if hasattr(ast, "unparse") else "?", True


def scan_definitions(source: str, filename: str = "") -> ModuleDefs:
    res = ModuleDefs()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        res.error = f"cannot parse (line {exc.lineno}): {exc.msg}"
        return res
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                kind = _decorator_kind(deco)
                if kind is None or not isinstance(deco, ast.Call) or not deco.args:
                    continue
                rx, text, dynamic = _pattern(deco.args[0])
                if dynamic:
                    res.dynamic += 1
                    continue
                res.defs.append(StepDef(kind, rx, text, deco.lineno, filename))
        elif isinstance(node, ast.ImportFrom) and node.module:
            res.imports.append(("." * node.level) + node.module)
        elif isinstance(node, ast.ImportFrom) and node.level:
            res.imports += ["." * node.level + a.name for a in node.names]
        elif isinstance(node, ast.Import):
            res.imports += [a.name for a in node.names]
    return res


# --------------------------------------------------------------------------- feature steps
@dataclass
class FeatureStep:
    kind: str            # given | when | then
    keyword: str         # as written (And, But, …)
    text: str
    line: int
    scenario: str


def _examples(lines: list[str], start: int) -> list[dict[str, str]]:
    """Rows of every Examples table after `start` until the next scenario."""
    rows: list[dict[str, str]] = []
    i = start
    while i < len(lines):
        raw = lines[i]
        if SCENARIO_RE.match(raw) or RULE_RE.match(raw):
            break
        if EXAMPLES_RE.match(raw):
            header: list[str] | None = None
            i += 1
            while i < len(lines):
                cell_line = lines[i].strip()
                if not cell_line or cell_line.startswith("#") or cell_line.startswith("@"):
                    i += 1
                    if header is not None and not cell_line:
                        break
                    continue
                if not cell_line.startswith("|"):
                    break
                cells = [c.strip() for c in cell_line.strip("|").split("|")]
                if header is None:
                    header = cells
                else:
                    rows.append(dict(zip(header, cells)))
                i += 1
            continue
        i += 1
    return rows


def feature_steps(text: str) -> list[FeatureStep]:
    """Every step a scenario runs, Background included, outlines expanded per Examples row."""
    lines = text.splitlines()
    background: list[tuple[str, str, str, int]] = []
    out: list[FeatureStep] = []
    in_doc = False
    section: str | None = None       # background | scenario
    current: list[tuple[str, str, str, int]] = []
    name = ""
    outline = False
    outline_start = 0

    def flush() -> None:
        if section != "scenario":
            return
        rows = _examples(lines, outline_start) if outline else [{}]
        for row in rows or [{}]:
            for kind, kw, txt, ln in background + current:
                for k, v in row.items():
                    txt = txt.replace(f"<{k}>", v)
                out.append(FeatureStep(kind, kw, txt, ln, name))

    prev_kind = "given"
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith('"""') or stripped.startswith("```"):
            in_doc = not in_doc
            continue
        if in_doc or not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("@"):
            continue
        if BACKGROUND_RE.match(raw):
            flush()
            section, current, prev_kind = "background", background, "given"
            continue
        m = SCENARIO_RE.match(raw)
        if m:
            flush()
            section, current, name, prev_kind = "scenario", [], m.group(2).strip(), "given"
            outline = m.group(1) in ("Scenario Outline", "Scenario Template")
            outline_start = idx + 1
            continue
        if RULE_RE.match(raw):
            flush()
            section, background, current = None, [], []
            continue
        if EXAMPLES_RE.match(raw):
            continue
        s = STEP_RE.match(raw)
        if s and section in ("background", "scenario"):
            kw = s.group(1)
            kind = KEYWORDS.get(kw.lower()) or prev_kind
            prev_kind = kind
            current.append((kind, kw, s.group(2), idx + 1))
    flush()
    return out


# --------------------------------------------------------------------------- visibility and matching
def visible_definitions(module: Path, stop: Path, cache: dict[Path, ModuleDefs]) -> tuple[list[StepDef], int]:
    """Definitions pytest-bdd can see from `module`: itself, every conftest.py from its folder up to
    `stop` (the profile root), and the modules it imports (recursively) that live under `stop`."""
    seen: set[Path] = set()
    defs: list[StepDef] = []
    dynamic = 0
    module, stop = module.resolve(), stop.resolve()

    def scan(p: Path) -> ModuleDefs:
        if p not in cache:
            cache[p] = scan_definitions(p.read_text(encoding="utf-8", errors="replace"), p.as_posix())
        return cache[p]

    def visit(p: Path) -> None:
        nonlocal dynamic
        p = p.resolve()
        if p in seen or not p.is_file():
            return
        seen.add(p)
        md = scan(p)
        defs.extend(md.defs)
        dynamic += md.dynamic
        for imp in md.imports:
            for cand in _resolve_import(imp, p, stop):
                visit(cand)

    visit(module)
    d = module.parent
    while True:
        visit(d / "conftest.py")
        if d == stop or stop not in d.parents:
            break
        d = d.parent
    return defs, dynamic


def _resolve_import(name: str, importer: Path, stop: Path) -> list[Path]:
    """Map an import to files under `stop`: `.steps`, `..common.steps`, `tests.acceptance.steps`."""
    level = len(name) - len(name.lstrip("."))
    parts = [p for p in name.lstrip(".").split(".") if p]
    if level:
        bases = [importer.parents[level - 1]] if len(importer.parents) >= level else []
    else:
        bases = [stop, importer.parent]
    out = []
    for base in bases:
        target = base.joinpath(*parts) if parts else base
        for cand in (target.with_suffix(".py"), target / "__init__.py"):
            if cand.is_file() and (cand.resolve() == stop or stop in cand.resolve().parents):
                out.append(cand)
    return out


def unbound(steps: list[FeatureStep], defs: list[StepDef]) -> list[FeatureStep]:
    out = []
    for st in steps:
        if not any(d.pattern is not None and d.kind in (st.kind, "any") and d.pattern.fullmatch(st.text) for d in defs):
            out.append(st)
    return out


def near_miss(st: FeatureStep, defs: list[StepDef]) -> str | None:
    """A hint: a definition whose text matches but under another keyword type."""
    for d in defs:
        if d.pattern is not None and d.kind not in (st.kind, "any") and d.pattern.fullmatch(st.text):
            return f"a @{d.kind} definition matches ({Path(d.file).name}:{d.line}) but this is a {st.kind.capitalize()} step"
    return None
