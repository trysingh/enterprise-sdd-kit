"""Check implementations. Each check is a pure function of repo files / test reports.

A check receives a GateContext and its `with:` params (placeholders already resolved) and
returns a list of Findings. Severity of a finding is "error", "warn" or "info"; the gate
engine downgrades "error" to "warn" when the policy (or an override) sets severity: warn.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
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
@check("profile.required_paths")
def required_paths(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    out = []
    for prof in _active(ctx):
        for rel in (prof.data.get("layout") or {}).get("required_paths", []) or []:
            if not (prof.root / rel).exists():
                out.append(Finding("error", f"[{prof.id}] missing {ctx.project.rel(prof.root / rel)}"))
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
        ledger = _ledger_path(ctx)
        fingerprints = {_rel_posix(ctx, f): _sha(f) for f in _frozen_files(ctx, w["dir"])}
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
        out.append(Finding("info", f"recorded {expect} for {len(want)} scenario(s) in {ctx.project.rel(ledger)}"))
        if expect == "red":
            from . import freeze
            try:
                rules = freeze.freeze_feature(ctx.project.root, ctx.feature_dir.name, fingerprints)
                out.append(Finding("info", f"froze {len(fingerprints)} file(s) against agent edits in opencode.json ({len(rules)} deny rules); "
                                           f"restart OpenCode to apply; lift with `ekit unfreeze {ctx.feature_dir.name} --reason \"...\"`"))
            except EkitError as exc:
                out.append(Finding("warn", f"could not freeze the red tests in opencode.json: {exc}"))
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
