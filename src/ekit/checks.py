"""Check implementations. Each check is a pure function of repo files / test reports.

A check receives a GateContext and its `with:` params (placeholders already resolved) and
returns a list of Findings. Severity of a finding is "error", "warn" or "info"; the gate
engine downgrades "error" to "warn" when the policy (or an override) sets severity: warn.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import gherkin, stepscan
from .project import EkitError, Project, dump_yaml, git, load_yaml
from .runner import run_profile_command


@dataclass
class Finding:
    level: str  # error | warn | info
    message: str


@dataclass
class GateContext:
    project: Project
    feature_dir: Path | None = None
    prd_dir: Path | None = None
    verbose: bool = False
    outputs: dict[str, str] = field(default_factory=dict)  # captured command output per check
    pending_records: list[dict[str, Any]] = field(default_factory=list)  # queued by bdd.run; see flush_pending_records

    def path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else self.project.root / q

    @property
    def feature_number(self) -> str | None:
        if not self.feature_dir:
            return None
        m = re.match(r"^(\d{3})-", self.feature_dir.name)
        return m.group(1) if m else None


CheckFn = Callable[[GateContext, dict[str, Any]], list[Finding]]
REGISTRY: dict[str, CheckFn] = {}


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    def deco(fn: CheckFn) -> CheckFn:
        REGISTRY[name] = fn
        return fn
    return deco


def _read(ctx: GateContext, p: str) -> str | None:
    f = ctx.path(p)
    return f.read_text(encoding="utf-8") if f.is_file() else None


def _active(ctx: GateContext) -> list[Any]:
    """Profiles whose checks run now: all of them, unless a wave plan makes some inactive."""
    return list(getattr(ctx.project, "active_profiles", None) or ctx.project.profiles)


def _missing(ctx: GateContext, p: str) -> list[Finding]:
    return [Finding("error", f"missing file: {ctx.project.rel(ctx.path(p))}")]


# ------------------------------------------------------------------------- files / text
ADR_FILE_RE = re.compile(r"^(\d{4})-.+\.md$")


@check("adr.unique")
def adr_unique(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """ADR numbers are unique, so `ADR-0003` in a Waived row points at exactly one decision."""
    d = ctx.path(w.get("dir", "docs/adr"))
    if not d.is_dir():
        return []  # BASE-ADR-DIR reports a missing folder
    by_num: dict[str, list[str]] = {}
    for f in sorted(d.glob("*.md")):
        m = ADR_FILE_RE.match(f.name)
        if m:
            by_num.setdefault(m.group(1), []).append(f.name)
    taken = {int(n) for n in by_num}
    nxt = f"{(max(taken) + 1) if taken else 1:04d}"
    return [Finding("error", f"ADR number {n} is used by {len(names)} files ({', '.join(names)}): renumber all but one "
                             f"(next free number: {nxt}) and update any `ADR-{n}` reference")
            for n, names in sorted(by_num.items()) if len(names) > 1]


@check("files.exist")
def files_exist(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    return [
        Finding("error", f"missing: {ctx.project.rel(ctx.path(p))}")
        for p in w.get("paths", [])
        if not ctx.path(p).exists()
    ]


@check("text.absent")
def text_absent(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    out = []
    for pat in w.get("patterns", []):
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pat, line):
                out.append(Finding("error", f"{ctx.project.rel(ctx.path(w['file']))}:{i}: unresolved marker: {line.strip()[:120]}"))
    return out


@check("text.present")
def text_present(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    return [
        Finding("error", f"{ctx.project.rel(ctx.path(w['file']))}: expected to contain /{pat}/")
        for pat in w.get("patterns", [])
        if not re.search(pat, text)
    ]


# ------------------------------------------------------------------------- ids / trace
@check("ids.present")
def ids_present(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    found = set(re.findall(w["pattern"], text))
    if len(found) < int(w.get("min", 1)):
        return [Finding("error", f"{ctx.project.rel(ctx.path(w['file']))}: expected ≥{w.get('min', 1)} ids matching {w['pattern']}, found {len(found)}")]
    return []


def _definitions(text: str, regex: str) -> list[str]:
    rx = re.compile(regex)
    out = []
    for line in text.splitlines():
        m = rx.match(line)
        if m:
            out.append(m.group(1))
    return out


@check("ids.unique")
def ids_unique(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    defs = _definitions(text, w["definition_regex"])
    if not defs:
        return [Finding("error", f"{ctx.project.rel(ctx.path(w['file']))}: no definitions of {w['pattern']} found")]
    dupes = sorted({d for d in defs if defs.count(d) > 1})
    return [Finding("error", f"duplicate id defined more than once: {d}") for d in dupes]


def br_definitions(text: str) -> list[str]:
    return _definitions(text, r"^\s*\|\s*\**(BR-\d{3})\**\s*\|")


def ac_definitions(text: str) -> list[str]:
    return _definitions(text, r"^\s*[-*|]?\s*\**(AC-\d{3})")


@check("trace.br_covered")
def br_covered(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    brd, prd = _read(ctx, w["brd"]), _read(ctx, w["prd"])
    if brd is None:
        return _missing(ctx, w["brd"])
    if prd is None:
        return _missing(ctx, w["prd"])
    brs = br_definitions(brd)
    if not brs:
        return [Finding("error", "brd.md defines no BR-### rows in its requirements table")]
    return [
        Finding("error", f"{b} is neither cited by an acceptance criterion nor listed as out of scope in prd.md")
        for b in brs
        if not re.search(rf"\b{re.escape(b)}\b", prd)
    ]


@check("trace.valid")
def trace_valid(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    p = ctx.path(w["trace"])
    if not p.is_file():
        return [Finding("error", f"missing {ctx.project.rel(p)} (written by /speckit.specify)")]
    t = load_yaml(p) or {}
    out = []
    for key in ("feature", "prd", "acceptance_criteria"):
        if not t.get(key):
            out.append(Finding("error", f"trace.yaml: '{key}' is required"))
    if ctx.feature_dir and t.get("feature") and t["feature"] != ctx.feature_dir.name:
        out.append(Finding("error", f"trace.yaml feature '{t['feature']}' != directory '{ctx.feature_dir.name}'"))
    prd_dir = ctx.path(t.get("prd", "")) if t.get("prd") else None
    if prd_dir and not (prd_dir / "prd.md").is_file():
        out.append(Finding("error", f"trace.yaml prd '{t['prd']}' has no prd.md"))
    elif prd_dir:
        defined = set(ac_definitions((prd_dir / "prd.md").read_text(encoding="utf-8")))
        for ac in t.get("acceptance_criteria") or []:
            if ac not in defined:
                out.append(Finding("error", f"trace.yaml lists {ac}, which prd.md does not define"))
    return out


@check("trace.acs_in_file")
def acs_in_file(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    tp = ctx.path(w["trace"])
    if not tp.is_file():
        return []  # reported by trace.valid
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    acs = (load_yaml(tp) or {}).get("acceptance_criteria") or []
    return [
        Finding("error", f"{ac} from trace.yaml is not referenced in {ctx.project.rel(ctx.path(w['file']))}")
        for ac in acs
        if not re.search(rf"\b{re.escape(ac)}\b", text)
    ]


# ------------------------------------------------------------------------- questions
Q_STATUSES = {"open", "answered", "deferred", "withdrawn"}


def load_questions(path: Path) -> list[dict[str, Any]]:
    data = load_yaml(path) or {}
    return list(data.get("questions") or [])


@check("questions.valid")
def questions_valid(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    p = ctx.path(w["file"])
    if not p.is_file():
        return _missing(ctx, w["file"])
    out, seen = [], set()
    for i, q in enumerate(load_questions(p), 1):
        qid = str(q.get("id", ""))
        where = qid or f"question #{i}"
        if not re.fullmatch(r"OQ-\d{3}", qid):
            out.append(Finding("error", f"{where}: id must look like OQ-001"))
        if qid in seen:
            out.append(Finding("error", f"{where}: duplicate id"))
        seen.add(qid)
        if not str(q.get("question") or "").strip():
            out.append(Finding("error", f"{where}: question text is empty"))
        if q.get("status") not in Q_STATUSES:
            out.append(Finding("error", f"{where}: status must be one of {sorted(Q_STATUSES)}"))
        if not isinstance(q.get("blocking"), bool):
            out.append(Finding("error", f"{where}: blocking must be true or false"))
        if q.get("status") == "answered" and not str(q.get("answer") or "").strip():
            out.append(Finding("error", f"{where}: answered but no answer recorded"))
        if q.get("status") == "answered" and not str(q.get("answered_by") or "").strip():
            # a blocking answer changes scope or acceptance criteria: the accountable owner must be named
            level = "error" if q.get("blocking") is True else "warn"
            out.append(Finding(level, f"{where}: answered_by is empty (who decided?)"))
    return out


@check("questions.no_open_blocking")
def no_open_blocking(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    p = ctx.path(w["file"])
    if not p.is_file():
        return _missing(ctx, w["file"])
    out = []
    for q in load_questions(p):
        if q.get("blocking") and q.get("status") in ("open", "deferred"):
            owner = q.get("owner") or "unassigned"
            out.append(Finding("error", f"{q.get('id')} [{q.get('status')}, owner: {owner}] {str(q.get('question', '')).strip()[:140]}"))
        elif q.get("blocking") and q.get("status") == "answered" and not str(q.get("answered_by") or "").strip():
            out.append(Finding("error", f"{q.get('id')}: blocking question answered without `answered_by`; record who decided"))
        elif q.get("status") == "open":
            out.append(Finding("info", f"{q.get('id')} open (non-blocking)"))
    return out


# ------------------------------------------------------------------------- NFR conformance
# An ADR reference: "ADR-0007", "ADR 7" or a file under docs/adr/ ("docs/adr/0007-x.md", "adr/0007-x.md").
# A bare date such as "2026-12" is NOT an ADR reference.
ADR_REF_RE = re.compile(r"\bADR[- ]?\d+\b|\badr/\d{4}-", re.IGNORECASE)
ROW_RE = re.compile(r"^\s*\|\s*`?([A-Z]{2,5}-\d{2})`?\s*\|(.*)\|\s*$")


def parse_conformance(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        cells += [""] * (4 - len(cells))
        rows[m.group(1)] = {"title": cells[0], "status": cells[1], "evidence": cells[2], "adr": cells[3]}
    return rows


DEFERRED_STATUS_RE = re.compile(r"^Deferred\s*\(?\s*(W[\w-]*)\s*\)?$", re.IGNORECASE)


def _check_deferral(ctx: GateContext, nid: str, wave: str) -> list[Finding]:
    """`Deferred (W2)` is valid only while an approved wave plan defers this NFR until W2 and W2 is not current yet."""
    plan = getattr(ctx.project, "wave_plan", None)
    if plan is None:
        return [Finding("error", f"{nid}: 'Deferred ({wave})' needs an approved wave plan (.ekit/waves.yaml); "
                                 "use Addressed, N/A, or Waived with an ADR")]
    from .waves import non_deferrable
    if nid in non_deferrable(ctx.project.kit):
        return [Finding("error", f"{nid} cannot be deferred to a later wave (non-deferrable in policy/waves.policy.yaml)")]
    d = plan.deferrals().get(nid)
    if not d:
        return [Finding("error", f"{nid}: marked Deferred ({wave}) but the approved wave plan does not defer it")]
    until = str(d.get("until"))
    if until.upper() != wave:
        return [Finding("error", f"{nid}: marked Deferred ({wave}) but the approved plan defers it until {until}")]
    if plan.order(plan.current) >= plan.order(until):
        return [Finding("error", f"{nid} was deferred until {until} and {plan.current} is now current: "
                                 "it is required now (Addressed, N/A, or Waived with an ADR)")]
    note = f" (re-deferred {d['redeferred']}x)" if d.get("redeferred") else ""
    return [Finding("info", f"{nid} deferred until {until}{note}: {d.get('reason')}")]


@check("wave.scope")
def wave_scope(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Waves on: every AC this feature specifies is planned for the current or an earlier wave."""
    plan = getattr(ctx.project, "wave_plan", None)
    if plan is None:
        return [Finding("info", "waves not in use: no scope restriction")]
    tp = ctx.path(w["trace"])
    if not tp.is_file():
        return []  # reported by trace.valid
    t = load_yaml(tp) or {}
    slug = Path(str(t.get("prd") or "")).name
    cur = plan.order(plan.current)
    out: list[Finding] = []
    for ac in t.get("acceptance_criteria") or []:
        wave = plan.wave_of(f"{slug}:{ac}")
        if wave is None:
            out.append(Finding("error", f"{slug}:{ac} is not in the approved wave plan; place it in a wave "
                                        "(proposal + `ekit wave approve`) before specifying it"))
        elif plan.order(wave) > cur:
            out.append(Finding("error", f"{slug}:{ac} is planned for {wave}; the current wave is {plan.current}. "
                                        "Leave it out of this feature (it becomes a later slice) or re-plan the waves"))
    if not out:
        out.append(Finding("info", f"all acceptance criteria are in scope for {plan.current}"))
    return out


@check("nfr.conformance")
def nfr_conformance(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    catalog = ctx.project.kit.nfr_catalog()
    allowed = set(catalog.get("statuses") or ["Addressed", "N/A", "Waived"])
    rows = parse_conformance(text)
    required = ctx.project.applicable_nfrs(scope=w.get("scope"))
    out: list[Finding] = []
    for n in required:
        nid = n["id"]
        level = "error" if n.get("level") == "mandatory" else "warn"
        row = rows.get(nid)
        if not row:
            out.append(Finding(level, f"{nid} ({n.get('title')}) has no row in the conformance table"))
            continue
        status = row["status"].strip("*` ")
        deferred = DEFERRED_STATUS_RE.match(status)
        if deferred:
            out += _check_deferral(ctx, nid, deferred.group(1).upper())
            continue
        if status not in allowed:
            out.append(Finding("error", f"{nid}: status '{row['status']}' not in {sorted(allowed)}"))
            continue
        if not row["evidence"] or row["evidence"].startswith("["):
            out.append(Finding("error", f"{nid}: '{status}' needs evidence or justification"))
        if status == "Waived" and not ADR_REF_RE.search(row["adr"] + " " + row["evidence"]):
            out.append(Finding("error", f"{nid}: Waived requires an ADR reference (e.g. ADR-0007)"))
    known = {n["id"] for n in catalog.get("nfrs", [])}
    for nid in rows:
        if nid not in known:
            out.append(Finding("warn", f"{nid}: not in the NFR catalogue (typo or overlay not installed?)"))
    return out


# ------------------------------------------------------------------------- profile
_MISSING_HINTS = {
    "uv.lock": " (run `uv lock` once — it needs network access — then `ekit run install`; the golden landing "
               "zone generates it on install when uv is on PATH)",
}


@check("profile.required_paths")
def required_paths(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    out = []
    for prof in _active(ctx):
        for rel in (prof.data.get("layout") or {}).get("required_paths", []) or []:
            if not (prof.root / rel).exists():
                hint = _MISSING_HINTS.get(Path(rel).name, "")
                out.append(Finding("error", f"[{prof.id}] missing {ctx.project.rel(prof.root / rel)}{hint}"))
    return out


@check("profile.command")
def profile_command(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    name = w["command"]
    ran, out = 0, []
    for prof in _active(ctx):
        res = run_profile_command(prof, name)
        if res is None:
            continue
        ran += 1
        ctx.outputs[f"{prof.id}:{name}"] = res.output
        if res.returncode != 0:
            tail = "\n".join(res.output.strip().splitlines()[-15:])
            out.append(Finding("error", f"[{prof.id}] `{name}` exited {res.returncode} in {ctx.project.rel(res.cwd)}\n{tail}"))
    if ran == 0:
        out.append(Finding("info", f"no profile defines command '{name}'"))
    return out


# ------------------------------------------------------------------------- gherkin
def _feature_scenarios(ctx: GateContext, d: str) -> tuple[list[gherkin.FeatureFile], list[gherkin.Scenario]]:
    files = gherkin.parse_dir(ctx.path(d))
    return files, [s for f in files for s in f.scenarios]


@check("gherkin.valid")
def gherkin_valid(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    d = ctx.path(w["dir"])
    if not d.is_dir():
        return [Finding("error", f"missing {ctx.project.rel(d)}/ (run /speckit.esdlc.gherkin)")]
    files, _ = _feature_scenarios(ctx, w["dir"])
    if not files:
        return [Finding("error", f"no .feature files in {ctx.project.rel(d)}")]
    return [Finding("error", e) for f in files for e in f.errors]


@check("gherkin.scn_unique")
def scn_unique(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    pattern = w.get("tag_pattern", r"SCN-\d{3}-\d{2}")
    owner: dict[str, str] = {}
    out = []
    fnum = ctx.feature_number
    for feat_dir in ctx.project.feature_dirs():
        for f in gherkin.parse_dir(feat_dir / "features"):
            for s in f.scenarios:
                ids = gherkin.scn_tags(s.tags, pattern)
                where = f"{ctx.project.rel(s.file)}:{s.line}"
                in_scope = ctx.feature_dir is not None and feat_dir.resolve() == ctx.feature_dir.resolve()
                if len(ids) != 1:
                    if in_scope:
                        out.append(Finding("error", f"{where}: scenario '{s.name}' needs exactly one @SCN-NNN-nn tag (has {ids or 'none'})"))
                    continue
                sid = ids[0]
                if sid in owner:
                    out.append(Finding("error", f"{where}: {sid} already used at {owner[sid]}"))
                owner[sid] = where
                if in_scope and fnum and not sid.startswith(f"SCN-{fnum}-"):
                    out.append(Finding("error", f"{where}: {sid} must start with SCN-{fnum}- for this feature"))
    return out


@check("gherkin.ac_covered")
def ac_covered(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    tp = ctx.path(w["trace"])
    if not tp.is_file():
        return [Finding("error", f"missing {ctx.project.rel(tp)}")]
    acs = (load_yaml(tp) or {}).get("acceptance_criteria") or []
    _, scenarios = _feature_scenarios(ctx, w["dir"])
    tagged: dict[str, list[str]] = {}
    for s in scenarios:
        for t in s.tags:
            if re.fullmatch(r"@AC-\d{3}", t):
                tagged.setdefault(t[1:], []).append(s.name)
    out = [Finding("error", f"{ac} has no scenario tagged @{ac}") for ac in acs if ac not in tagged]
    out += [Finding("warn", f"@{ac} is used in scenarios but not listed in trace.yaml") for ac in tagged if ac not in acs]
    return out


# ------------------------------------------------------------------------- BDD / ledger
def _model_fields(ctx: GateContext, command: str) -> dict[str, Any]:
    try:
        from . import models
        return models.ledger_fields(ctx.project.root, ctx.project.kit, command)
    except Exception:  # noqa: BLE001 - evidence never breaks a gate
        return {}


def _ekit_version() -> str:
    from . import __version__
    return __version__


def _ledger_path(ctx: GateContext) -> Path:
    assert ctx.feature_dir is not None
    return ctx.project.root / ".ekit" / "ledger" / f"{ctx.feature_dir.name}.yaml"


def _feature_scn_ids(ctx: GateContext, d: str) -> list[str]:
    _, scenarios = _feature_scenarios(ctx, d)
    ids: list[str] = []
    for s in scenarios:
        ids.extend(gherkin.scn_tags(s.tags))
    return sorted(set(ids))


# ---------------------------------------------------- frozen tests and empty-step scan
_TEST_SUFFIXES = {".py", ".java", ".kt", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"}


def _rel_posix(ctx: GateContext, p: Path) -> str:
    try:
        return p.resolve().relative_to(ctx.project.root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _bdd_dirs(prof: Any) -> list[Path]:
    rel = (prof.data.get("layout") or {}).get("acceptance_tests")
    if not rel:
        return []
    if any(c in rel for c in "*?["):
        return sorted(p for p in prof.root.glob(rel) if p.is_dir())
    p = prof.root / rel
    return [p] if p.is_dir() else []


def _test_files(prof: Any) -> list[Path]:
    out: list[Path] = []
    for d in _bdd_dirs(prof):
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix in _TEST_SUFFIXES and not {"__pycache__", "node_modules"} & set(f.parts):
                out.append(f)
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _feature_bound_tests(ctx: GateContext, d: str) -> list[Path]:
    """Acceptance test modules that bind this feature: they mention one of its .feature file names
    or one of its @SCN-<NNN>- ids. (Cucumber glue that binds nothing by name is not covered.)"""
    needles = {f.name for f in ctx.path(d).rglob("*.feature")}
    if ctx.feature_number:
        needles.add(f"SCN-{ctx.feature_number}-")
    found: set[Path] = set()
    for prof in ctx.project.profiles:
        if not prof.runs_bdd:
            continue
        for tf in _test_files(prof):
            text = tf.read_text(encoding="utf-8", errors="replace")
            if any(n in text for n in needles):
                found.add(tf)
    return sorted(found)


def _frozen_files(ctx: GateContext, d: str) -> list[Path]:
    return sorted(set(ctx.path(d).rglob("*.feature")) | set(_feature_bound_tests(ctx, d)))


@check("bdd.vacuous_steps")
def vacuous_steps(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Every step must set up or check something. Static scan, implemented for pytest-bdd."""
    out: list[Finding] = []
    for prof in _active(ctx):
        if not prof.runs_bdd:
            continue
        fw = prof.bdd.get("framework")
        if fw != "pytest-bdd":
            out.append(Finding("info", f"[{prof.id}] empty-step scan is not implemented for {fw}: review step definitions for empty bodies by hand"))
            continue
        files = set(_feature_bound_tests(ctx, w["dir"])) | {f for f in _test_files(prof) if f.name == "conftest.py"}
        for f in sorted(files):
            if f.suffix != ".py":
                continue
            rel = _rel_posix(ctx, f)
            res = stepscan.scan_source(f.read_text(encoding="utf-8", errors="replace"))
            if res.error:
                out.append(Finding("error", f"{rel}: {res.error}"))
            for i in res.steps:
                label = f"step {i.step!r} " if i.step else ""
                out.append(Finding("error", f"{rel}:{i.line} {label}({i.name}): {i.reason}. Make it set up state or assert behaviour through the public interface; a deliberate no-op needs `# ekit: allow-empty-step <reason>`"))
            for line, p in res.abs_paths:
                out.append(Finding("error", f"{rel}:{line} absolute feature path {p!r} breaks on every other machine and in CI: build it from Path(__file__)"))
    return out


@check("bdd.steps_bound")
def steps_bound(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Every step of every scenario has a step definition visible to the module that binds it.
    Static scan, implemented for pytest-bdd (a scenario failing at an early step hides a later
    undefined step from RED-RUN)."""
    from . import stepbind
    out: list[Finding] = []
    features = sorted(ctx.path(w["dir"]).rglob("*.feature"))
    cache: dict[Path, Any] = {}
    for prof in _active(ctx):
        if not prof.runs_bdd:
            continue
        fw = prof.bdd.get("framework")
        if fw != "pytest-bdd":
            out.append(Finding("info", f"[{prof.id}] step-binding scan is not implemented for {fw}: the runner's "
                                       "undefined-step report at red is the only check"))
            continue
        modules = [f for f in _test_files(prof) if f.suffix == ".py" and f.name != "conftest.py"]
        texts = {m: m.read_text(encoding="utf-8", errors="replace") for m in modules}
        for feat in features:
            binders = [m for m in modules if feat.name in texts[m]]
            if not binders:
                continue  # RED-RUN reports scenarios that no module runs
            steps = stepbind.feature_steps(feat.read_text(encoding="utf-8"))
            for mod in binders:
                defs, dynamic = stepbind.visible_definitions(mod, prof.root, cache)
                level = "warn" if dynamic else "error"
                seen: set[tuple[str, str]] = set()
                for st in stepbind.unbound(steps, defs):
                    if (st.kind, st.text) in seen:
                        continue
                    seen.add((st.kind, st.text))
                    hint = stepbind.near_miss(st, defs)
                    out.append(Finding(level, f"{_rel_posix(ctx, feat)}:{st.line} {st.keyword} \"{st.text}\" "
                                              f"(scenario '{st.scenario}') has no step definition visible to "
                                              f"{_rel_posix(ctx, mod)}" + (f"; {hint}" if hint else "")))
                if dynamic and seen:
                    out.append(Finding("info", f"{_rel_posix(ctx, mod)}: {dynamic} step pattern(s) are built at "
                                               "runtime and cannot be checked, so unbound steps are warnings"))
    for md_path, md in cache.items():
        if md.error:
            out.append(Finding("error", f"{_rel_posix(ctx, md_path)}: {md.error}"))
    return out


@check("ledger.tests_unchanged")
def tests_unchanged(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Red tests are frozen: the .feature files and bound test modules must be byte-identical
    (CRLF-normalised) to what the last red entry fingerprinted."""
    ledger = _ledger_path(ctx)
    if not ledger.is_file():
        return []  # ledger.red_first reports the missing ledger
    reds = [e for e in ((load_yaml(ledger) or {}).get("entries") or []) if e.get("phase") == "red"]
    if not reds:
        return []
    fp = reds[-1].get("fingerprints")
    if not fp:
        return [Finding("warn", "the red entry has no file fingerprints (recorded by an older ekit): re-run `ekit gate red` while the code is still red to freeze the tests")]
    out: list[Finding] = []
    for rel, sha in sorted(fp.items()):
        f = ctx.project.root / rel
        if not f.is_file():
            out.append(Finding("error", f"{rel}: deleted since red was recorded"))
        elif _sha(f) != sha:
            out.append(Finding("error", f"{rel}: changed since red was recorded. Red tests are frozen: restore the file from the commit that added {ctx.project.rel(ledger)}, or `ekit unfreeze {ctx.feature_dir.name} --reason ...` and go back to red. A reviewed exception needs an override for this check id"))
    for f in _frozen_files(ctx, w["dir"]):
        rel = _rel_posix(ctx, f)
        if rel not in fp:
            out.append(Finding("warn", f"{rel}: bound to this feature but added after red was recorded"))
    return out


@check("bdd.run")
def bdd_run(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    expect = w.get("expect", "red")
    want = _feature_scn_ids(ctx, w["dir"])
    if not want:
        return [Finding("error", "this feature has no @SCN-tagged scenarios (run gate scenarios first)")]
    runners = [p for p in _active(ctx) if p.runs_bdd]
    if not runners:
        return [Finding("error", "no profile in this stack runs BDD acceptance tests")]
    out: list[Finding] = []
    reports, exit_codes = [], {}
    for prof in runners:
        report = prof.root / prof.bdd["report"]
        if report.exists():
            report.unlink()  # never read a stale report
        report.parent.mkdir(parents=True, exist_ok=True)
        res = run_profile_command(prof, "acceptance")
        assert res is not None
        ctx.outputs[f"{prof.id}:acceptance"] = res.output
        exit_codes[prof.id] = res.returncode
        if not report.is_file():
            tail = "\n".join(res.output.strip().splitlines()[-20:])
            out.append(Finding("error", f"[{prof.id}] acceptance run produced no report at {ctx.project.rel(report)} (exit {res.returncode}). Harness broken or not wired.\n{tail}"))
        reports.append(report)
    results = gherkin.read_cucumber_reports(reports)
    status = {sid: gherkin.aggregate(results[sid]) for sid in want if sid in results}
    pytest_bdd = any(p.bdd.get("framework") == "pytest-bdd" for p in runners)
    for sid in want:
        if sid not in status:
            msg = f"{sid}: not executed by any runner (check feature path / tag filters in the BDD config)"
            if pytest_bdd:
                msg = (f"{sid}: not in the test report. Either no test module binds its feature file, or its first step has no "
                       "step definition (pytest-bdd leaves such a scenario out of its report; the pytest output shows "
                       "StepDefinitionNotFoundError), or the module fails before the first step")
            out.append(Finding("error", msg))
            continue
        st = status[sid]
        if expect == "red":
            if st == "passed":
                msg = f"{sid}: PASSES before implementation — the test does not test the new behaviour"
                if pytest_bdd:
                    msg += " (if pytest also shows StepDefinitionNotFoundError for it, a later step has no definition: pytest-bdd records such a scenario as passed)"
                out.append(Finding("error", msg))
            elif st in ("undefined", "pending", "ambiguous"):
                out.append(Finding("error", f"{sid}: {st} — bind every step before recording red"))
            elif st != "failed":
                # e.g. 'skipped' (a @skip tag, a skip marker, a tag filter): not evidence that the test can fail
                out.append(Finding("error", f"{sid}: {st} — red needs the scenario to run and FAIL; remove the skip or tag filter"))
        else:
            if st != "passed":
                out.append(Finding("error", f"{sid}: {st}"))
    if expect == "green":
        for pid, rc in exit_codes.items():
            if rc != 0:
                out.append(Finding("error", f"[{pid}] acceptance suite exited {rc} (another scenario or a regression is failing)"))
    if w.get("record") and not any(f.level == "error" for f in out):
        # Queue the ledger write rather than doing it here: this check (bdd.run/RED-RUN or
        # GREEN-RUN) only knows its own findings are clean, not whether a later check in the same
        # gate (RED-CLEAN-FAILURE, in particular) is about to reject the run. Writing eagerly let a
        # scenario that errored out of broken test glue — still reported "failed" by pytest-bdd,
        # so RED-RUN itself saw nothing wrong — get recorded as a real red entry (and re-frozen)
        # even though the gate's overall result was FAILED. `run_gate` calls flush_pending_records
        # once the whole gate's result is known, and only on a pass.
        fingerprints = {_rel_posix(ctx, f): _sha(f) for f in _frozen_files(ctx, w["dir"])}
        ctx.pending_records.append({
            "expect": expect, "want": want, "status": status, "fingerprints": fingerprints,
        })
    return out


def flush_pending_records(ctx: GateContext, results: list[Any]) -> None:
    """Write the ledger entries (and re-freeze, for red) queued by `bdd.run` checks during this
    gate run. Call only once the whole gate's result is known, and only when it passed — a run
    rejected by a later check (e.g. RED-CLEAN-FAILURE) must never reach the ledger; see the note
    in `bdd_run` above. Appends its notes as info findings on the originating CheckResult, same
    place they used to come from when this was done eagerly."""
    # Only one `bdd.run` check appears per gate (RED-RUN in `red`, GREEN-RUN in `green`), so the
    # type alone identifies which CheckResult a queued record's notes belong to.
    bdd_run_results = [r for r in results if r.type == "bdd.run"]
    for rec in ctx.pending_records:
        expect, want, status, fingerprints = rec["expect"], rec["want"], rec["status"], rec["fingerprints"]
        cr = bdd_run_results[0] if bdd_run_results else None
        ledger = _ledger_path(ctx)
        data = load_yaml(ledger) if ledger.is_file() else {"feature": ctx.feature_dir.name, "entries": []}
        data.setdefault("entries", []).append({
            "phase": expect,
            "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "git_head": git(ctx.project.root, "rev-parse", "HEAD"),
            "kit_version": ctx.project.kit.version,
            "ekit_version": _ekit_version(),   # the CLI holds the check logic that produced this verdict
            # model routing (optional): what was CONFIGURED for the command that produced this phase
            **_model_fields(ctx, "speckit.esdlc.red" if expect == "red" else "speckit.implement"),
            "scenarios": {sid: status[sid] for sid in want},
            # sha256 of the feature files and bound test modules at this moment; `ledger.tests_unchanged` compares
            "fingerprints": fingerprints,
        })
        dump_yaml(data, ledger)
        if cr is not None:
            cr.findings.append(Finding("info", f"recorded {expect} for {len(want)} scenario(s) in {ctx.project.rel(ledger)}"))
        if expect == "red":
            from . import freeze
            try:
                rules = freeze.freeze_feature(ctx.project.root, ctx.feature_dir.name, fingerprints)
                if cr is not None:
                    cr.findings.append(Finding("info", f"froze {len(fingerprints)} file(s) against agent edits in opencode.json ({len(rules)} deny rules); "
                                               f"restart OpenCode to apply; lift with `ekit unfreeze {ctx.feature_dir.name} --reason \"...\"`"))
            except EkitError as exc:
                if cr is not None:
                    cr.findings.append(Finding("warn", f"could not freeze the red tests in opencode.json: {exc}"))


_CLEAN_RED_DEFAULT = ("AssertionError",)


@check("bdd.clean_failure")
def clean_failure(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """A scenario recorded as red must fail on a genuine assertion about missing behaviour — not
    error out of broken test glue (a KeyError reading state no step set, an undefined step hidden
    behind an earlier failure, a typo'd fixture name). pytest-bdd reports both as plain 'failed',
    so RED-RUN alone accepts either; this reads the same report RED-RUN just wrote and rejects an
    exception type other than the allowed ones, so a broken test can't be frozen as if it were a
    legitimate TDD red. Static step-binding (RED-STEPS-BOUND) catches undefined steps that nothing
    ever reaches because an earlier step fails first; this catches what actually ran and errored."""
    allowed = set(w.get("allow") or _CLEAN_RED_DEFAULT)
    want = _feature_scn_ids(ctx, w["dir"])
    if not want:
        return []
    reports = [p.root / p.bdd["report"] for p in _active(ctx) if p.runs_bdd and p.bdd.get("report")]
    elements = gherkin.read_cucumber_elements([r for r in reports if r.is_file()])
    out: list[Finding] = []
    for sid in want:
        for el in elements.get(sid, []):
            if gherkin._scenario_status(el) != "failed":
                continue
            exc = gherkin.failure_exception(el)
            if exc == "MissingScenarioStateError" and exc not in allowed:
                out.append(Finding("error", f"{sid}: a step read scenario state that no earlier step of THIS scenario "
                                             "set (MissingScenarioStateError from ScenarioContext.recall / .http / "
                                             ".last_response). That is broken test glue, not a red: add the missing "
                                             "Given/When to this scenario or set the value in a step it already has, "
                                             "then rerun `ekit gate red`"))
                continue
            if exc and exc not in allowed:
                out.append(Finding("error", f"{sid}: failed with {exc}, not {'/'.join(sorted(allowed))} — this "
                                             "usually means broken test glue (a missing fixture value, an undefined "
                                             "step hidden behind an earlier failure, a typo), not a genuine gap in "
                                             "the implementation. Fix the test itself before freezing it as red; "
                                             "rerun `ekit gate red` once it fails cleanly on an assertion. If this "
                                             "really is a legitimate red failure in your style (e.g. a deliberate "
                                             "NotImplementedError stub), add it to this check's `allow` list or use "
                                             "an override"))
    return out


def _committed_with(root: Path, rel: str, sha: str) -> bool:
    """True if some commit reachable from HEAD has `rel` with this (CRLF-normalised) sha256."""
    revs = git(root, "rev-list", "HEAD", "--", rel)
    for rev in (revs or "").splitlines()[:50]:
        try:
            blob = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=root, capture_output=True, check=True).stdout
        except (subprocess.CalledProcessError, OSError):
            continue
        if hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest() == sha:
            return True
    return False


@check("ledger.red_committed")
def red_committed(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """The red evidence is in git: the frozen feature files and tests, exactly as fingerprinted at red,
    and the ledger itself. The ledger cites a commit as proof that tests came first; that proof only
    holds if what was recorded is committed."""
    ledger = _ledger_path(ctx)
    if not ledger.is_file():
        return []  # ledger.red_first reports it
    root = ctx.project.root
    if git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return [Finding("warn", "not a git repository: the red evidence (feature files, tests, ledger) cannot be "
                                "verified as committed; run `git init` and commit")]
    reds = [e for e in ((load_yaml(ledger) or {}).get("entries") or []) if e.get("phase") == "red"]
    fp = (reds[-1].get("fingerprints") if reds else None) or {}
    missing = [rel for rel, sha in sorted(fp.items()) if not _committed_with(root, rel, sha)]
    out = []
    if missing:
        out.append(Finding("error", f"{len(missing)} file(s) recorded at red are not committed as recorded "
                                    f"({', '.join(missing[:5])}{' …' if len(missing) > 5 else ''}). Commit the tests, "
                                    f"feature files and {ctx.project.rel(ledger)} right after `ekit gate red`, "
                                    "before implementing"))
    if not git(root, "ls-files", "--", ctx.project.rel(ledger)):
        out.append(Finding("error", f"{ctx.project.rel(ledger)} is not committed: the ledger is the evidence"))
    return out


@check("ledger.red_first")
def red_first(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    want = _feature_scn_ids(ctx, w["dir"])
    ledger = _ledger_path(ctx)
    if not ledger.is_file():
        return [Finding("error", f"no ledger {ctx.project.rel(ledger)}: run `ekit gate red` before implementing")]
    entries = (load_yaml(ledger) or {}).get("entries") or []
    red_ok: set[str] = set()
    heads = []
    for e in entries:
        if e.get("phase") != "red":
            continue
        heads.append(e.get("git_head"))
        for sid, st in (e.get("scenarios") or {}).items():
            if st == "failed":          # only an observed failure proves test-first (not skipped/pending)
                red_ok.add(sid)
    out = [Finding("error", f"{sid}: never recorded failing (red) before green") for sid in want if sid not in red_ok]
    head = git(ctx.project.root, "rev-parse", "HEAD")
    if head and heads and heads[-1] and heads[-1] != head:
        anc = git(ctx.project.root, "merge-base", "--is-ancestor", heads[-1], head)
        if anc is None:
            out.append(Finding("warn", "last red entry's commit is not an ancestor of HEAD (history rewritten?)"))
    return out


@check("tasks.all_done")
def tasks_done(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    text = _read(ctx, w["file"])
    if text is None:
        return _missing(ctx, w["file"])
    open_tasks = [ln.strip() for ln in text.splitlines() if re.match(r"^\s*-\s*\[ \]", ln)]
    return [Finding("error", f"{len(open_tasks)} unchecked task(s), e.g. {open_tasks[0][:100]}")] if open_tasks else []


# ------------------------------------------------------------------------- environment (ENV-01)
def venv_python_version(env_dir: Path) -> str | None:
    """Python version recorded in pyvenv.cfg (uv writes version_info, stdlib venv writes version)."""
    cfg = env_dir / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("version_info", "version"):
            return value.strip()
    return None


def version_matches(actual: str, pin: str) -> bool:
    """'3.12.4' matches pins '3.12', '3.12.4', 'cpython-3.12', '>=3.12' is not supported (pin exact)."""
    pin = pin.strip().split()[0] if pin.strip() else ""
    pin = re.sub(r"^[a-z]+-", "", pin.lower()).lstrip("v")
    pin_parts, act_parts = pin.split("."), actual.strip().lstrip("v").split(".")
    return bool(pin) and act_parts[: len(pin_parts)] == pin_parts


@check("profile.environment")
def profile_environment(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    root = ctx.project.root
    in_git = git(root, "rev-parse", "--is-inside-work-tree") == "true"
    if not in_git:
        out.append(Finding("warn", "not a git repository: cannot verify that environment folders are ignored/untracked"))
    checked = 0
    for prof in _active(ctx):
        env = prof.data.get("environment")
        if not env:
            continue
        checked += 1
        tag = f"[{prof.id}]"
        pin = prof.root / env["pin_file"] if env.get("pin_file") else None
        if pin is not None and not pin.is_file():
            out.append(Finding("error", f"{tag} runtime version not pinned: missing {ctx.project.rel(pin)}"))
        env_dir = prof.root / env["dir"] if env.get("dir") else None
        if env_dir is None:
            continue
        rel = ctx.project.rel(env_dir)
        if in_git:
            # --no-index: evaluate rules even for already-tracked files. The rule must come from a
            # .gitignore OUTSIDE the env folder (uv writes its own `*` inside .venv; stdlib venv doesn't).
            hit = git(root, "check-ignore", "--no-index", "-v", rel + "/")
            source = (hit or "").split(":", 1)[0].replace("\\", "/")
            if not hit or source.startswith(rel + "/"):
                out.append(Finding("error", f"{tag} {rel}/ is not ignored by the repository's .gitignore (add `{env['dir']}/`)"))
            tracked = git(root, "ls-files", "--", rel)
            if tracked:
                out.append(Finding("error", f"{tag} {rel}/ has files committed to git ({len(tracked.splitlines())}); remove with `git rm -r --cached {rel}`"))
        if not env_dir.is_dir():
            out.append(Finding("info", f"{tag} {rel}/ not created yet (run `ekit run install`)"))
            continue
        marker = env.get("marker")
        if marker and not (env_dir / marker).exists():
            out.append(Finding("error", f"{tag} {rel}/ exists but is not a valid {env.get('kind')} (no {marker}); delete it and run `ekit run install`"))
            continue
        if env.get("kind") == "python-venv" and pin is not None and pin.is_file():
            actual = venv_python_version(env_dir)
            wanted = pin.read_text(encoding="utf-8").strip()
            if actual and not version_matches(actual, wanted):
                out.append(Finding("error", f"{tag} {rel} uses Python {actual} but {ctx.project.rel(pin)} pins {wanted}; delete {rel} and run `ekit run install`"))
    if checked == 0:
        out.append(Finding("info", "no profile declares an environment"))
    return out


# ------------------------------------------------------------------------- 0.3.0: golden landing zone
def _golden(ctx: GateContext) -> Any:
    from . import golden
    return golden.for_project(ctx.project)


@check("constitution.intact")
def constitution_intact(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Principles I–VIII in the ratified constitution are word-for-word the kit template (whitespace aside).
    Before 0.3.0 only pull-request review protected them."""
    from . import constitution
    state, details = constitution.principles_drift(ctx.project)
    if state == "intact":
        return []
    if state == "changed":
        return [Finding("error", f"{constitution.MEMORY}: {d}. Restore I–VIII from "
                                 f"{ctx.project.rel(constitution.template_path(ctx.project))}; changing them needs an ADR "
                                 "and a new kit version. Project principles go in IX and above") for d in details]
    return [Finding("warn", f"{constitution.MEMORY}: {d}") for d in details]


@check("golden.intact")
def golden_intact(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Golden projects: every frozen core file is byte-identical (CRLF aside) to .ekit/golden.lock.yaml.
    This is also what covers shared test helpers and conftest.py, which `GREEN-TESTS-UNCHANGED` does not."""
    from . import golden
    if not golden.is_golden(ctx.project):
        return [Finding("info", "not a golden landing zone (baseline mode: generate)")]
    if golden.read_lock(ctx.project.root) is None:
        return [Finding("error", f"baseline mode is golden but {golden.LOCK} is missing: restore it from git")]
    out = []
    for d in golden.drift(ctx.project.root):
        hint = ("resolve the markers, review, then a person runs `ekit baseline accept --reason \"...\"`"
                if d.kind == "conflict" else
                "restore it (`git checkout -- <file>`), or, for a reviewed change to the core, a person runs "
                "`ekit baseline accept --reason \"...\"`. Feature code belongs in its feature package")
        out.append(Finding("error", f"{d.message()}: {hint}"))
    return out


# Names that, used as a dict shared between steps, produced the 0.2.2 KeyError class of broken red.
_UNTYPED_STATE = {"scenario_state", "state", "shared", "shared_state", "context", "scenario_context", "store"}


def _untyped_state_uses(source: str) -> list[tuple[int, str]]:
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in node.args.args + node.args.kwonlyargs}
        is_fixture = any("fixture" in ast.unparse(d) for d in node.decorator_list)
        if is_fixture and node.name in _UNTYPED_STATE:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, (ast.Dict, ast.Call)) and (
                        isinstance(sub.value, ast.Dict) or ast.unparse(sub.value.func) in ("dict", "defaultdict")):
                    found.append((node.lineno, f"fixture `{node.name}` returns a dict"))
                    break
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
                    and sub.value.id in _UNTYPED_STATE and sub.value.id in params):
                found.append((sub.lineno, f"`{sub.value.id}[...]` in step `{node.name}`"))
    return found


@check("bdd.typed_state")
def typed_state(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Golden projects: steps keep scenario state on `ctx: ScenarioContext`, not in a shared dict.
    A dict lets a step read a key another scenario's step set; pytest-bdd then reports the KeyError
    like a real failure (the 0.2.2 bug). `ctx.recall` raises MissingScenarioStateError instead."""
    from . import golden
    if not golden.is_golden(ctx.project):
        return [Finding("info", "typed scenario state is enforced in golden landing zones only")]
    out = []
    for f in _feature_bound_tests(ctx, w["dir"]):
        if f.suffix != ".py":
            continue
        for line, what in _untyped_state_uses(f.read_text(encoding="utf-8", errors="replace")):
            out.append(Finding("error", f"{_rel_posix(ctx, f)}:{line} {what}: keep scenario state on "
                                        "`ctx: ScenarioContext` (`ctx.remember(key, value)` / `ctx.recall(key)`), "
                                        "see tests/acceptance/test_000_reference_slice.py"))
    return out


@check("golden.no_exemplar")
def no_exemplar(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """A feature never *is* the reference slice and never depends on it (0.2.5: an agent took an
    illustrative example for the real feature). Copying its shape is the point; referencing it is not."""
    from . import golden
    g = _golden(ctx)
    if g is None:
        return [Finding("info", "no reference slice (not a golden landing zone)")]
    ex = g.exemplar
    spec_dir = str(ex.get("spec_dir") or "")
    pkg = str(ex.get("package") or "")
    out: list[Finding] = []
    if ctx.feature_dir is not None and spec_dir and _rel_posix(ctx, ctx.feature_dir) == spec_dir:
        return [Finding("error", f"{spec_dir} is the reference slice, not a feature: name the real feature "
                                 "(`ekit feature current`)")]
    needles = [n for n in (Path(spec_dir).name, pkg, pkg.rsplit(".", 1)[-1], "SCN-000-") if n]
    files = list(_feature_bound_tests(ctx, w["dir"]))
    pkg_rel = golden.feature_package(g, ctx.feature_dir.name) if ctx.feature_dir is not None else None
    if pkg_rel and (ctx.project.root / pkg_rel).is_dir():
        files += sorted((ctx.project.root / pkg_rel).rglob("*.py"))
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        hits = [n for n in needles if n in text]
        if hits:
            out.append(Finding("error", f"{_rel_posix(ctx, f)} refers to the reference slice ({', '.join(hits)}): "
                                        "copy its shape, never import it, bind its feature file or reuse its ids"))
    return out
